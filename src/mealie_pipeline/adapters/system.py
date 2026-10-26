"""The SystemProbe port: what `mp doctor` needs to know about the machine."""

import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol


class SystemProbe(Protocol):
    def python_version(self) -> tuple[int, int, int]: ...

    def which(self, name: str) -> str | None: ...

    def claude_auth_status(self) -> str | None:
        """Raw stdout of `claude auth status`, or None if it could not be run."""
        ...

    def yt_dlp_version(self) -> str | None: ...

    def chrome_available(self) -> bool:
        """Whether Playwright's `chrome` channel (the installed Google Chrome) can be launched."""
        ...

    def gpu_name(self) -> str | None:
        """`<name>, <memory>` of the first NVIDIA GPU, or None."""
        ...


def _run(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(
            argv, capture_output=True, encoding="utf-8", errors="replace", timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


class RealSystemProbe:
    def python_version(self) -> tuple[int, int, int]:
        info = sys.version_info
        return info.major, info.minor, info.micro

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def claude_auth_status(self) -> str | None:
        exe = shutil.which("claude")
        return _run([exe, "auth", "status"]) if exe else None

    def yt_dlp_version(self) -> str | None:
        try:
            return importlib.metadata.version("yt-dlp")
        except importlib.metadata.PackageNotFoundError:
            return None

    def chrome_available(self) -> bool:
        candidates: list[str | None] = [
            shutil.which(n) for n in ("chrome", "google-chrome", "google-chrome-stable")
        ]
        if platform.system() == "Windows":
            for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                root = os.environ.get(var)
                if root:
                    candidates.append(str(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"))
        elif platform.system() == "Darwin":
            candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return any(c and Path(c).is_file() for c in candidates)

    def gpu_name(self) -> str | None:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None
        out = _run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader"])
        return out.splitlines()[0].strip() if out and out.strip() else None
