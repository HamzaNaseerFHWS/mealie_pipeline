"""Settings come from config/settings.yaml, overridden by .env, overridden by the environment."""

from pathlib import Path

from mealie_pipeline.settings import load_settings


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_defaults_come_from_the_yaml_file(tmp_path):
    write(tmp_path / "config" / "settings.yaml", "mealie:\n  timeout_seconds: 7\n  max_retries: 2\n")
    settings = load_settings(tmp_path, environ={})
    assert settings.mealie.timeout_seconds == 7
    assert settings.mealie.max_retries == 2


def test_missing_yaml_falls_back_to_built_in_defaults(tmp_path):
    settings = load_settings(tmp_path, environ={})
    assert settings.mealie.timeout_seconds == 20
    assert settings.mealie.max_retries == 3
    assert settings.mealie_token is None


def test_dotenv_provides_secrets_and_beats_yaml(tmp_path):
    write(tmp_path / "config" / "settings.yaml", "mealie:\n  timeout_seconds: 7\n")
    write(tmp_path / ".env", "MEALIE_URL=http://mealie:9000\nMEALIE_TOKEN=abc\nMEALIE__TIMEOUT_SECONDS=9\n")
    settings = load_settings(tmp_path, environ={})
    assert settings.mealie_url == "http://mealie:9000"
    assert settings.mealie_token is not None and settings.mealie_token.get_secret_value() == "abc"
    assert settings.mealie.timeout_seconds == 9


def test_environment_beats_dotenv(tmp_path):
    write(tmp_path / ".env", "MEALIE_URL=http://from-dotenv:9000\n")
    settings = load_settings(tmp_path, environ={"MEALIE_URL": "http://from-env:9000"})
    assert settings.mealie_url == "http://from-env:9000"


def test_url_trailing_slash_is_dropped(tmp_path):
    settings = load_settings(tmp_path, environ={"MEALIE_URL": "http://mealie:9000/"})
    assert settings.mealie_url == "http://mealie:9000"


def test_the_token_is_never_shown_in_repr_or_str(tmp_path):
    settings = load_settings(tmp_path, environ={"MEALIE_TOKEN": "super-secret-token"})
    assert "super-secret-token" not in repr(settings)
    assert "super-secret-token" not in str(settings)
