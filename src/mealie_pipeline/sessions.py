"""Platform logins (pure): where the secrets live, cookie export, session detection, stop signals.

The pipeline Chrome profile lives in `secrets/browser_profile/`, its cookies are exported to
`secrets/cookies.txt` (Netscape format, for yt-dlp) and `secrets/logins.json` remembers when each
platform was last logged in. Cookie values are never printed or logged; only names and dates are.
Platform settings and stop-signal markers come from `config/platforms.yaml`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PLATFORMS = ("youtube", "instagram", "facebook")
STOP_KINDS = ("checkpoint", "rate_limit", "login_wall")  # checked in this order: most specific first
NETSCAPE_HEADER = "# Netscape HTTP Cookie File"
HTTPONLY_PREFIX = "#HttpOnly_"
_REPO_CONFIG = Path(__file__).parents[2] / "config" / "platforms.yaml"


def secrets_dir(workspace: Path) -> Path:
    return workspace / "secrets"


def profile_dir(workspace: Path) -> Path:
    return secrets_dir(workspace) / "browser_profile"


def cookies_file(workspace: Path) -> Path:
    return secrets_dir(workspace) / "cookies.txt"


def logins_file(workspace: Path) -> Path:
    return secrets_dir(workspace) / "logins.json"


@dataclass(frozen=True)
class Markers:
    url: tuple[str, ...] = ()
    title: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    login_url: str
    cookie_domain: str
    session_cookies: tuple[str, ...]
    stop_signals: dict[str, Markers] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return {"youtube": "YouTube"}.get(self.name, self.name.capitalize())


def load_platforms(workspace: Path) -> dict[str, PlatformProfile]:
    """`config/platforms.yaml` of the workspace, else the repository's copy."""
    path = workspace / "config" / "platforms.yaml"
    raw: dict[str, Any] = yaml.safe_load(
        (path if path.is_file() else _REPO_CONFIG).read_text(encoding="utf-8")
    )
    profiles = {}
    for name, entry in raw.items():
        signals = {
            kind: Markers(
                **{part: tuple(m.lower() for m in markers) for part, markers in (spec or {}).items()}
            )
            for kind, spec in (entry.get("stop_signals") or {}).items()
        }
        profiles[name] = PlatformProfile(
            name, entry["login_url"], entry["cookie_domain"], tuple(entry["session_cookies"]), signals
        )
    return profiles


# -- cookies ------------------------------------------------------------------------------


def to_netscape(cookies: list[dict[str, Any]]) -> str:
    """Playwright cookie dicts -> a `cookies.txt` yt-dlp reads. Session cookies get expiry 0."""
    lines = [NETSCAPE_HEADER, "# Exported by mealie_pipeline `mp login`. Do not share this file.", ""]
    for c in cookies:
        domain = str(c["domain"])
        expires = float(c.get("expires", -1) or -1)
        lines.append(
            "\t".join(
                [
                    (HTTPONLY_PREFIX if c.get("httpOnly") else "") + domain,
                    "TRUE" if domain.startswith(".") else "FALSE",
                    str(c.get("path") or "/"),
                    "TRUE" if c.get("secure") else "FALSE",
                    str(int(expires)) if expires > 0 else "0",
                    str(c["name"]),
                    str(c["value"]),
                ]
            )
        )
    return "\n".join(lines) + "\n"


def parse_netscape(text: str) -> list[dict[str, Any]]:
    """`cookies.txt` -> cookie dicts shaped like Playwright's (expiry 0 reads back as -1)."""
    cookies = []
    for line in text.splitlines():
        http_only = line.startswith(HTTPONLY_PREFIX)
        if http_only:
            line = line.removeprefix(HTTPONLY_PREFIX)
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, _subdomains, path, secure, expires, name, value = fields
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                "expires": int(expires) if expires.isdigit() and int(expires) > 0 else -1,
                "httpOnly": http_only,
                "secure": secure == "TRUE",
            }
        )
    return cookies


def _on_domain(cookie: dict[str, Any], domain: str) -> bool:
    host = str(cookie.get("domain", "")).lstrip(".").lower()
    return host == domain or host.endswith("." + domain)


def _live(cookie: dict[str, Any], now: float) -> bool:
    expires = float(cookie.get("expires", -1) or -1)
    return expires <= 0 or expires > now


def has_session(cookies: list[dict[str, Any]], profile: PlatformProfile, *, now: float) -> bool:
    """All of the platform's session cookies are present on its domain and not expired."""
    names = {c["name"] for c in cookies if _on_domain(c, profile.cookie_domain) and _live(c, now)}
    return all(name in names for name in profile.session_cookies)


@dataclass(frozen=True)
class SessionStatus:
    platform: str
    logged_in: bool
    age_days: int | None  # since `mp login` last found the session
    expires_in_days: int | None  # earliest expiry of the session cookies; None for session cookies


def session_statuses(
    cookies_text: str | None,
    logins: dict[str, str],
    profiles: dict[str, PlatformProfile],
    now: datetime,
) -> list[SessionStatus]:
    cookies = parse_netscape(cookies_text or "")
    statuses = []
    for name, profile in profiles.items():
        logged_in = has_session(cookies, profile, now=now.timestamp())
        when = logins.get(name)
        age = (now - datetime.fromisoformat(when)).days if when else None
        expiries = [
            c["expires"]
            for c in cookies
            if _on_domain(c, profile.cookie_domain)
            and c["name"] in profile.session_cookies
            and c["expires"] > 0
        ]
        expires_in = int((min(expiries) - now.timestamp()) // 86400) if logged_in and expiries else None
        statuses.append(SessionStatus(name, logged_in, age, expires_in))
    return statuses


# -- stop signals -------------------------------------------------------------------------


def stop_signal(profile: PlatformProfile, url: str, title: str, html: str) -> str | None:
    """`checkpoint`, `rate_limit` or `login_wall` when the page shows one, else None."""
    url, title, html = url.lower(), title.lower(), html.lower()
    for kind in STOP_KINDS:
        markers = profile.stop_signals.get(kind)
        if markers is None:
            continue
        if (
            any(m in url for m in markers.url)
            or any(m in title for m in markers.title)
            or any(m in html for m in markers.body)
        ):
            return kind
    return None
