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
from pathlib import Path

_FFMPEG = "ffmpeg"


def configure(ffmpeg_path: str | None) -> None:
    """Set the ffmpeg binary (path or bare name). Call once at startup."""
    global _FFMPEG
    _FFMPEG = (ffmpeg_path or "ffmpeg").strip() or "ffmpeg"


def ffmpeg_cmd() -> str:
    """ffmpeg executable to invoke (respects settings, falls back to PATH)."""
    p = _FFMPEG
    if Path(p).is_file():
        return p
    found = shutil.which(p)
    return found or p


def ffprobe_cmd() -> str:
    """ffprobe executable: sibling of a configured ffmpeg path when present,
    otherwise PATH lookup."""
    f = Path(ffmpeg_cmd())
    if f.parent != Path("."):
        exe = "ffprobe.exe" if f.suffix.lower() == ".exe" else "ffprobe"
        cand = f.parent / exe
        if cand.is_file():
            return str(cand)
    return shutil.which("ffprobe") or "ffprobe"
