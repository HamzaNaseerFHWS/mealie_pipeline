"""Ticket 31: the compose project's files stay consistent with the code (no Docker needed)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
DEPLOY = ROOT / "deploy"


def compose() -> dict:
    return yaml.safe_load((DEPLOY / "compose.yml").read_text(encoding="utf-8"))


def test_the_project_has_the_inbox_and_the_pipeline_and_leaves_mealie_alone():
    services = compose()["services"]
    assert set(services) == {"inbox", "pipeline"}
    assert set(compose()["volumes"]) == {"inbox-data", "pipeline-data", "claude-login"}


def test_the_pipeline_reaches_the_bot_by_service_name_and_mealie_through_a_setting():
    pipeline = compose()["services"]["pipeline"]
    assert pipeline["environment"]["INBOX_URL"] == "http://inbox:8765"
    assert "host.docker.internal:9000" in pipeline["environment"]["MEALIE_URL"]
    assert "host.docker.internal:host-gateway" in pipeline["extra_hosts"]
    assert pipeline["environment"]["WEB__BROWSER_HEADLESS"] == "true"


def test_the_bots_port_is_not_published():
    assert "ports" not in compose()["services"]["inbox"]


def test_the_volumes_hold_the_data_the_login_and_the_exports():
    mounts = compose()["services"]["pipeline"]["volumes"]
    assert "pipeline-data:/workspace" in mounts
    assert "claude-login:/home/mp/.claude" in mounts
    assert "./imports:/workspace/imports" in mounts
    assert "inbox-data:/data" in compose()["services"]["inbox"]["volumes"]


def test_the_env_example_has_every_secret_and_no_values():
    lines = (DEPLOY / ".env.example").read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    for name in ("TELEGRAM_BOT_TOKEN", "INBOX_API_TOKEN", "TELEGRAM_CHAT_ID", "MEALIE_TOKEN"):
        assert values[name] == ""


def test_deploy_env_and_secrets_are_git_and_docker_ignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "deploy/.env" in gitignore and "secrets/" in gitignore
    assert "**/.env" in dockerignore and "secrets" in dockerignore and "cookies*.txt" in dockerignore


def test_the_image_never_uses_bare_or_an_api_key():
    dockerfile = (DEPLOY / "Dockerfile.pipeline").read_text(encoding="utf-8")
    assert "--bare" not in dockerfile and "ANTHROPIC_API_KEY" not in dockerfile
    assert 'CMD ["mp", "inbox-worker"]' in dockerfile
