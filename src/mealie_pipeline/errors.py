"""Typed errors shared across adapters."""

MAX_BODY_CHARS = 2000


def redact(text: str, secret: str | None) -> str:
    """Removes a secret from text before it reaches an error message or a log."""
    if secret:
        text = text.replace(secret, "***")
    return text


class MealieError(Exception):
    """Base class for everything the Mealie gateway raises."""


class MealieHttpError(MealieError):
    """A non-2xx response. Carries the request line, status and a truncated, redacted body."""

    def __init__(self, method: str, path: str, status: int, body: str, token: str | None = None):
        self.method = method
        self.path = path
        self.status = status
        self.body = redact(body, token)[:MAX_BODY_CHARS]
        super().__init__(f"{method} {path} -> {status}: {self.body}")


class MealieAuthError(MealieHttpError):
    """401: the token is missing, expired or revoked."""

    def __init__(self, method: str, path: str, status: int, body: str, token: str | None = None):
        super().__init__(method, path, status, body, token)
        self.args = (
            f"token invalid ({method} {path} -> {status}): create a new token in Mealie under "
            "Profile -> API Tokens and put it in .env as MEALIE_TOKEN",
        )


class MealieUnreachableError(MealieError):
    """DNS or connection failure after the retries were used up."""

    def __init__(self, base_url: str, detail: str = ""):
        self.base_url = base_url
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"cannot reach Mealie at {base_url}: is Tailscale connected?{suffix}")


class NeedsHumanLogin(Exception):
    """A platform showed a login wall, checkpoint or rate-limit page: only the user can go on.

    The pipeline stops that platform and asks for `mp login <platform>`; it never works around it."""

    def __init__(self, platform: str, kind: str, detail: str = ""):
        super().__init__(f"{platform}: {kind}" + (f" ({detail})" if detail else ""))
        self.platform = platform
        self.kind = kind
        self.detail = detail
