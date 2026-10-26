"""ClaudeCliBackend against a stub `claude` that replays recorded `--output-format json` results."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from mealie_pipeline.adapters.llm import ClaudeCliBackend, LLMError, UsageLimited

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

STUB = """\
import json, os, sys
record = {"argv": sys.argv[1:], "stdin": sys.stdin.buffer.read().decode("utf-8")}
open(os.environ["STUB_RECORD"], "w", encoding="utf-8").write(json.dumps(record))
sys.stdout.buffer.write(open(os.environ["STUB_REPLY"], "rb").read())
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


@pytest.fixture
def stub(tmp_path, monkeypatch):
    """A `claude` executable first on PATH; `reply(...)` sets what it prints."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "stub_claude.py"
    script.write_text(STUB, encoding="utf-8")
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = bin_dir / "claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_RECORD", str(tmp_path / "record.json"))
    reply_file = tmp_path / "reply.json"
    monkeypatch.setenv("STUB_REPLY", str(reply_file))

    class Stub:
        def reply(self, payload, exit_code=0):
            reply_file.write_text(json.dumps(payload), encoding="utf-8")
            monkeypatch.setenv("STUB_EXIT", str(exit_code))

        def recorded(self):
            return json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))

    return Stub()


def backend(tmp_path):
    return ClaudeCliBackend(tmp_path / "prompts")


def test_success_returns_structured_output_and_builds_the_exact_command(stub, tmp_path):
    stub.reply({"type": "result", "is_error": False, "result": "", "structured_output": {"ok": True}})

    result = backend(tmp_path).complete("extract", "Zutaten: Möhren – 2 Stück\n", SCHEMA, "strong")

    assert result == {"ok": True}
    recorded = stub.recorded()
    assert recorded["stdin"] == "Zutaten: Möhren – 2 Stück\n"  # UTF-8 on stdin, intact
    assert recorded["argv"] == [
        "-p",
        "--model",
        "sonnet",
        "--safe-mode",
        "--tools",
        "",
        "--system-prompt-file",
        str(tmp_path / "prompts" / "extract.md"),
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(SCHEMA),
        "--no-session-persistence",
    ]
    assert "--bare" not in recorded["argv"]


@pytest.mark.parametrize(("tier", "model"), [("fast", "haiku"), ("strong", "sonnet"), ("strongest", "opus")])
def test_tier_picks_the_model_alias(stub, tmp_path, tier, model):
    stub.reply({"is_error": False, "structured_output": {}})

    backend(tmp_path).complete("extract", "x", SCHEMA, tier)

    argv = stub.recorded()["argv"]
    assert argv[argv.index("--model") + 1] == model


def test_is_error_raises_llm_error_with_the_message(stub, tmp_path):
    stub.reply({"is_error": True, "result": "Invalid API key"})

    with pytest.raises(LLMError, match="Invalid API key"):
        backend(tmp_path).complete("extract", "x", SCHEMA, "strong")


def test_non_zero_exit_raises_llm_error(stub, tmp_path):
    stub.reply({"is_error": False, "result": "crashed"}, exit_code=2)

    with pytest.raises(LLMError):
        backend(tmp_path).complete("extract", "x", SCHEMA, "strong")


def test_a_usage_limit_result_raises_usage_limited(stub, tmp_path):
    stub.reply({"is_error": True, "result": "Claude usage limit reached. Your limit will reset at 5pm."})

    with pytest.raises(UsageLimited):
        backend(tmp_path).complete("extract", "x", SCHEMA, "strong")


def test_missing_structured_output_is_an_error(stub, tmp_path):
    stub.reply({"is_error": False, "result": "just prose"})

    with pytest.raises(LLMError, match="structured_output"):
        backend(tmp_path).complete("extract", "x", SCHEMA, "strong")


def test_a_missing_claude_executable_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(LLMError, match="not found on PATH"):
        backend(tmp_path).complete("extract", "x", SCHEMA, "strong")


def test_the_extract_prompt_exists_and_states_the_rules():
    path = Path(__file__).parents[1] / "prompts" / "extract.md"
    prompt = path.read_text(encoding="utf-8")

    for rule in (
        "Never invent quantities",
        "quantity_stated",
        "verbatim",
        "original_line",
        "Never invent a tag",
    ):
        assert rule in prompt
