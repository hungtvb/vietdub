# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Resolve ffmpeg/ffprobe binaries from settings (ffmpeg_path).

`ffmpeg_path` used to be a dead config: media/tts hardcoded "ffmpeg".
Now every module calls ffmpeg_cmd()/ffprobe_cmd() here instead.
The orchestrator calls configure() once at startup; default is PATH lookup.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_FFMPEG = "ffmpeg"


def configure(ffmpeg_path: str | None) -> None:
    """Set the ffmpeg binary (path or bare name). Call once at startup."""
    global _FFMPEG
    _FFMPEG = (ffmpeg_path or "ffmpeg").strip() or "ffmpeg"


def _bundled_binary(name: str) -> str | None:
    """Find FFmpeg in a PyInstaller onedir bundle (6.x uses _internal).

    Always prefer the bundled binary to the runner/user PATH for frozen apps,
    unless the user explicitly configured a different executable.
    """
    if not getattr(sys, "frozen", False):
        return None
    roots = []
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    exe_dir = Path(sys.executable).resolve().parent
    roots.extend((exe_dir, exe_dir / "_internal"))
    binary = name + (".exe" if sys.platform == "win32" else "")
    for root in roots:
        candidate = root / binary
        if candidate.is_file():
            return str(candidate)
    return None


def ffmpeg_cmd() -> str:
    """Return explicit configured FFmpeg, bundled FFmpeg, or PATH fallback."""
    configured = _FFMPEG
    if configured != "ffmpeg":
        if Path(configured).is_file():
            return str(Path(configured))
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        return configured  # preserve invalid explicit path for useful errors
    return _bundled_binary("ffmpeg") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_cmd() -> str:
    """Resolve ffprobe next to selected ffmpeg before bundle/PATH fallback."""
    ffmpeg = Path(ffmpeg_cmd())
    if ffmpeg.parent != Path("."):
        candidate = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe"
                                     else "ffprobe")
        if candidate.is_file():
            return str(candidate)
    return _bundled_binary("ffprobe") or shutil.which("ffprobe") or "ffprobe"
