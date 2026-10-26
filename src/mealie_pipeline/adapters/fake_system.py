"""Scriptable SystemProbe: every check is green until a test breaks one."""


class FakeSystemProbe:
    def __init__(self) -> None:
        self.python = (3, 12, 4)
        self.executables: dict[str, str] = {"ffmpeg": "/usr/bin/ffmpeg", "claude": "/usr/bin/claude"}
        self.claude_status: str | None = '{"loggedIn": true, "authMethod": "claude.ai"}'
        self.yt_dlp: str | None = "2025.01.01"
        self.chrome = True
        self.gpu: str | None = "NVIDIA GeForce GTX 1650, 4096 MiB"

    def python_version(self) -> tuple[int, int, int]:
        return self.python

    def which(self, name: str) -> str | None:
        return self.executables.get(name)

    def claude_auth_status(self) -> str | None:
        return self.claude_status if "claude" in self.executables else None

    def yt_dlp_version(self) -> str | None:
        return self.yt_dlp

    def chrome_available(self) -> bool:
        return self.chrome

    def gpu_name(self) -> str | None:
        return self.gpu
