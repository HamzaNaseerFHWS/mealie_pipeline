"""`mp login <platform>`: the user logs in by hand in the pipeline's Chrome window; then the
profile's cookies are exported to `secrets/cookies.txt` for yt-dlp.

The wait ends when the platform's session cookies appear, when the user presses Enter, or after
`timeout_s`. Nothing here ever prints a cookie value.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mealie_pipeline.adapters.browser import Browser
from mealie_pipeline.sessions import PlatformProfile, cookies_file, has_session, logins_file, to_netscape


@dataclass(frozen=True)
class LoginResult:
    platform: str
    logged_in: bool
    cookie_count: int  # every cookie of the profile, all platforms
    cookies_path: Path


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def run_login(
    profile: PlatformProfile,
    browser: Browser,
    workspace: Path,
    *,
    pressed_enter: Callable[[], bool],
    sleep: Callable[[float], object] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    poll_s: float = 2.0,
    timeout_s: float = 15 * 60,
) -> LoginResult:
    try:
        browser.show(profile.login_url)
        waited = 0.0
        cookies = browser.cookies()
        while not has_session(cookies, profile, now=now().timestamp()):
            if pressed_enter() or waited >= timeout_s:
                break
            sleep(poll_s)
            waited += poll_s
            cookies = browser.cookies()
        logged_in = has_session(cookies, profile, now=now().timestamp())
        target = cookies_file(workspace)
        _write_private(target, to_netscape(cookies))
        if logged_in:
            path = logins_file(workspace)
            logins = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            logins[profile.name] = now().isoformat(timespec="seconds")
            _write_private(path, json.dumps(logins, indent=2))
        return LoginResult(profile.name, logged_in, len(cookies), target)
    finally:
        browser.close()
