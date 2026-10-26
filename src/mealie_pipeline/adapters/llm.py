"""The LLMBackend port and its `claude -p` implementation (ADR 0002).

The pipeline never calls an API for Claude: it runs the Claude Code CLI on the user's subscription.
`--bare` is never passed, because it ignores the subscription login.
"""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

Tier = Literal["fast", "strong", "strongest"]

DEFAULT_MODELS: dict[str, str] = {"fast": "haiku", "strong": "sonnet", "strongest": "opus"}
USAGE_LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "rate_limit")


class LLMError(Exception):
    """The backend failed or returned something unusable."""


class UsageLimited(LLMError):  # noqa: N818  (named by the spec)
    """The subscription's usage window is spent. `reset_at` is None when the CLI did not say."""

    def __init__(self, message: str, reset_at: datetime | None = None):
        super().__init__(message)
        self.reset_at = reset_at


class LLMBackend(Protocol):
    def complete(
        self, task: str, prompt: str, schema: dict[str, Any], tier: Tier, images: tuple[Path, ...] = ()
    ) -> dict[str, Any]:
        """One structured completion. `task` names the system prompt file (`prompts/<task>.md`)."""
        ...


class ClaudeCliBackend:
    def __init__(
        self,
        prompts_dir: Path,
        *,
        models: dict[str, str] | None = None,
        timeout_seconds: float = 600,
        executable: str | None = None,
    ):
        self.prompts_dir = prompts_dir
        self.models = {**DEFAULT_MODELS, **(models or {})}
        self.timeout_seconds = timeout_seconds
        self.executable = executable

    def build_args(self, exe: str, task: str, schema: dict[str, Any], tier: Tier) -> list[str]:
        return [
            exe,
            "-p",
            "--model",
            self.models[tier],
            "--safe-mode",
            "--tools",
            "",
            "--system-prompt-file",
            str(self.prompts_dir / f"{task}.md"),
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--no-session-persistence",
        ]

    def complete(
        self, task: str, prompt: str, schema: dict[str, Any], tier: Tier, images: tuple[Path, ...] = ()
    ) -> dict[str, Any]:
        if images:
            raise LLMError("image input is not built yet (it arrives with the OCR phase)")
        exe = self.executable or shutil.which("claude")
        if not exe:
            raise LLMError("the `claude` CLI was not found on PATH: run `mp doctor`")
        try:
            done = subprocess.run(
                self.build_args(exe, task, schema, tier),
                input=prompt,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as err:
            raise LLMError(f"claude timed out after {self.timeout_seconds:.0f}s") from err
        except OSError as err:
            raise LLMError(f"could not run claude: {err}") from err
        return self._parse(done.returncode, done.stdout, done.stderr)

    @staticmethod
    def _parse(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
        text = ""
        if isinstance(payload, dict):
            text = str(payload.get("result") or "")
        if returncode != 0 or not isinstance(payload, dict) or payload.get("is_error"):
            detail = (text or stderr or stdout).strip()[:500] or f"exit code {returncode}"
            if any(marker in detail.lower() for marker in USAGE_LIMIT_MARKERS):
                raise UsageLimited(detail)
            raise LLMError(f"claude failed: {detail}")
        structured = payload.get("structured_output") if isinstance(payload, dict) else None
        if not isinstance(structured, dict):
            raise LLMError("claude returned no structured_output (is --json-schema supported?)")
        return structured
