"""`mp doctor` at the pipeline seam: the CLI, fake adapters, a temporary workspace."""

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.fake_system import FakeSystemProbe
from mealie_pipeline.cli import app
from tests.helpers import fake_adapters

TOKEN = "test-token-1234567890"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "OPENAI_API_KEY", "OPENAI_MAX_USD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / ".env").write_text(
        f"MEALIE_URL=http://fake-mealie:9000\nMEALIE_TOKEN={TOKEN}\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def mealie():
    return FakeMealie(token=TOKEN, tags=["Dinner", "Vegan", "Quick"], foods=["onion", "salt"], units=["cup"])


@pytest.fixture
def system():
    return FakeSystemProbe()


def doctor(workspace, mealie, system):
    adapters = fake_adapters(mealie=mealie, system=system)
    return CliRunner().invoke(app, ["--workspace", str(workspace), "doctor"], obj=adapters)


def test_all_green_lists_every_check_and_exits_zero(workspace, mealie, system):
    result = doctor(workspace, mealie, system)

    assert result.exit_code == 0, result.output
    for expected in (
        "[ OK ] Python 3.12.4",
        "[ OK ] ffmpeg",
        "[ OK ] claude CLI: logged in with a subscription (claude.ai)",
        "[ OK ] Playwright Chrome",
        "[ OK ] yt-dlp 2025.01.01",
        "[ OK ] NVIDIA GPU: NVIDIA GeForce GTX 1650, 4096 MiB",
        "[ OK ] Mealie reachable at http://fake-mealie:9000: v3.22.0",
        "[ OK ] Mealie token: tester",
        "[ OK ] Mealie catalog: 3 tags, 2 foods, 1 units",
    ):
        assert expected in result.output
    assert "FAIL" not in result.output


def test_unreachable_mealie_fails_with_a_tailscale_hint_and_skips_dependent_checks(workspace, mealie, system):
    mealie.reachable = False

    result = doctor(workspace, mealie, system)

    assert result.exit_code == 1
    assert "[FAIL] Mealie reachable at http://fake-mealie:9000" in result.output
    assert "Tailscale connected?" in result.output
    assert "[SKIP] Mealie token" in result.output
    assert "[SKIP] Mealie catalog" in result.output
    assert "[ OK ] ffmpeg" in result.output  # local checks still run


def test_bad_token_fails_with_a_fix_hint_and_never_prints_the_token(workspace, mealie, system):
    mealie.valid_token = "some-other-token"

    result = doctor(workspace, mealie, system)

    assert result.exit_code == 1
    assert "[ OK ] Mealie reachable" in result.output
    assert "[FAIL] Mealie token" in result.output
    assert "Profile -> API Tokens" in result.output
    assert "[SKIP] Mealie catalog" in result.output
    assert TOKEN not in result.output


def test_missing_claude_cli_fails_with_a_login_hint(workspace, mealie, system):
    system.executables.pop("claude")

    result = doctor(workspace, mealie, system)

    assert result.exit_code == 1
    assert "[FAIL] claude CLI: not found on PATH" in result.output
    assert "run `claude` once and log in" in result.output


def test_claude_logged_in_with_an_api_key_is_rejected(workspace, mealie, system):
    system.claude_status = '{"loggedIn": true, "authMethod": "api_key"}'

    result = doctor(workspace, mealie, system)

    assert result.exit_code == 1
    assert "[FAIL] claude CLI" in result.output
    assert "subscription" in result.output


def test_no_gpu_is_informational_and_does_not_fail(workspace, mealie, system):
    system.gpu = None

    result = doctor(workspace, mealie, system)

    assert result.exit_code == 0
    assert "[WARN] NVIDIA GPU: not detected" in result.output


def test_missing_ffmpeg_fails_with_the_winget_hint(workspace, mealie, system):
    system.executables.pop("ffmpeg")

    result = doctor(workspace, mealie, system)

    assert result.exit_code == 1
    assert "winget install Gyan.FFmpeg" in result.output


def test_old_python_fails(workspace, mealie, system):
    system.python = (3, 11, 9)

    result = doctor(workspace, mealie, system)

    assert result.exit_code == 1
    assert "[FAIL] Python 3.11.9" in result.output


def test_missing_mealie_settings_fail_with_an_env_hint(tmp_path, mealie, system):
    result = doctor(tmp_path, mealie, system)  # no .env at all

    assert result.exit_code == 1
    assert "MEALIE_URL" in result.output
    assert ".env" in result.output


def test_doctor_lists_tag_rules_whose_tag_is_missing_from_mealie(workspace, mealie, system):
    (workspace / "config").mkdir()
    (workspace / "config" / "tag_rules.yaml").write_text(
        "rules:\n  - {tag: Quick, when: {max_total_minutes: 30}}\n  - {tag: Ghost, when: {drink: true}}\n",
        encoding="utf-8",
    )

    result = doctor(workspace, mealie, system)

    assert "[WARN] Tag rules: 1 rule names a tag missing from Mealie: Ghost" in result.output
    assert result.exit_code == 0
