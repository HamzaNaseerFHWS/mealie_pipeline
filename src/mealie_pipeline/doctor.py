"""`mp doctor`: check by check, is the setup in place? Pure logic over the adapters."""

import json
from dataclasses import dataclass
from typing import Literal

from mealie_pipeline.adapters import Adapters
from mealie_pipeline.errors import MealieAuthError, MealieError, MealieUnreachableError
from mealie_pipeline.settings import Settings

Status = Literal["ok", "fail", "warn", "skip"]
MIN_PYTHON = (3, 12)


@dataclass
class Check:
    status: Status
    name: str
    detail: str = ""
    hint: str = ""


def run_doctor(adapters: Adapters, settings: Settings) -> list[Check]:
    system = adapters.system
    checks = [
        _python(system),
        _ffmpeg(system),
        _claude(system),
        _chrome(system),
        _yt_dlp(system),
        _gpu(system),
    ]
    checks += _mealie(adapters, settings)
    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == "fail" for c in checks) else 0


def _python(system) -> Check:
    major, minor, micro = system.python_version()
    name = f"Python {major}.{minor}.{micro}"
    if (major, minor) >= MIN_PYTHON:
        return Check("ok", name)
    return Check("fail", name, "needs 3.12 or newer", "install Python 3.12 and run `uv sync`")


def _ffmpeg(system) -> Check:
    path = system.which("ffmpeg")
    if path:
        return Check("ok", "ffmpeg", path)
    return Check(
        "fail", "ffmpeg", "not found on PATH", "run `winget install Gyan.FFmpeg`, then open a new terminal"
    )


def _claude(system) -> Check:
    login_hint = "run `claude` once and log in with your Claude Pro account (not an API key)"
    if not system.which("claude"):
        return Check("fail", "claude CLI", "not found on PATH", f"install Claude Code, then {login_hint}")
    raw = system.claude_auth_status()
    try:
        method = json.loads(raw or "").get("authMethod")
    except (ValueError, AttributeError):
        return Check("fail", "claude CLI", "could not read `claude auth status`", login_hint)
    if method == "claude.ai":
        return Check("ok", "claude CLI", "logged in with a subscription (claude.ai)")
    return Check("fail", "claude CLI", f"not using a subscription login (authMethod: {method})", login_hint)


def _chrome(system) -> Check:
    if system.chrome_available():
        return Check("ok", "Playwright Chrome", "Google Chrome found")
    return Check("fail", "Playwright Chrome", "Google Chrome not found", "install Google Chrome")


def _yt_dlp(system) -> Check:
    version = system.yt_dlp_version()
    if version:
        return Check("ok", f"yt-dlp {version}")
    return Check("fail", "yt-dlp", "not installed", "run `uv sync`")


def _gpu(system) -> Check:
    name = system.gpu_name()
    if name:
        return Check("ok", "NVIDIA GPU", name)
    return Check("warn", "NVIDIA GPU", "not detected (only needed for transcription from ticket 07)")


def _mealie(adapters: Adapters, settings: Settings) -> list[Check]:
    mealie = adapters.mealie
    if not settings.mealie_url or not settings.mealie_token:
        missing = [
            n
            for n, v in (("MEALIE_URL", settings.mealie_url), ("MEALIE_TOKEN", settings.mealie_token))
            if not v
        ]
        return [
            Check(
                "fail",
                "Mealie settings",
                f"{' and '.join(missing)} not set",
                "copy .env.example to .env and fill them in",
            )
        ]

    reach = f"Mealie reachable at {settings.mealie_url}"
    try:
        version = mealie.about().version
    except MealieUnreachableError as err:
        return [
            Check("fail", reach, str(err), "Tailscale connected? Is the Mealie PC on?"),
            Check("skip", "Mealie token", "needs Mealie to be reachable"),
            Check("skip", "Mealie catalog", "needs Mealie to be reachable"),
        ]
    except MealieError as err:
        return [
            Check("fail", reach, str(err), "check MEALIE_URL points at Mealie"),
            Check("skip", "Mealie token", "needs Mealie to be reachable"),
            Check("skip", "Mealie catalog", "needs Mealie to be reachable"),
        ]
    checks = [Check("ok", reach, version)]

    try:
        me = mealie.whoami()
    except MealieAuthError:
        return checks + [
            Check(
                "fail",
                "Mealie token",
                "rejected (401)",
                "create a new token in Mealie under Profile -> API Tokens and put it in .env as MEALIE_TOKEN",
            ),
            Check("skip", "Mealie catalog", "needs a valid token"),
        ]
    except MealieError as err:
        return checks + [
            Check("fail", "Mealie token", str(err), "check MEALIE_URL and MEALIE_TOKEN"),
            Check("skip", "Mealie catalog", "needs a valid token"),
        ]
    checks.append(Check("ok", "Mealie token", me.username))

    try:
        catalog = mealie.catalog()
    except MealieError as err:
        return checks + [Check("fail", "Mealie catalog", str(err), "check the token's permissions")]
    counts = f"{len(catalog.tags)} tags, {len(catalog.foods)} foods, {len(catalog.units)} units"
    return checks + [Check("ok", "Mealie catalog", counts)]


def render(checks: list[Check]) -> str:
    labels = {"ok": " OK ", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}
    lines = []
    for c in checks:
        line = f"[{labels[c.status]}] {c.name}"
        if c.detail:
            line += f": {c.detail}"
        lines.append(line)
        if c.hint and c.status == "fail":
            lines.append(f"       fix: {c.hint}")
    return "\n".join(lines)
