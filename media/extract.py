# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Step [1] - extract audio: ffmpeg -> wav 16kHz mono (what FunASR needs).

Edge case 6: video without an audio track (or broken track) -> clear error,
clean stop, no crash.
Edge case 12: multiple audio tracks -> list them, default to track 0.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import List

from media import _bin

log = logging.getLogger("vietdub.extract")


class ExtractError(Exception):
    pass


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    # list args, no shell=True -> safe with unicode paths (edge case 13)
    log.debug("run: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path: str | Path) -> dict:
    p = _run([_bin.ffprobe_cmd(), "-v", "quiet", "-print_format", "json",
              "-show_streams", "-show_format", str(path)])
    if p.returncode != 0:
        raise ExtractError(f"Không đọc được file video: {path}\n{p.stderr[:300]}")
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError as e:
        raise ExtractError(f"ffprobe trả dữ liệu lỗi: {e}") from e


def audio_streams(path: str | Path) -> List[dict]:
    return [s for s in probe(path).get("streams", []) if s.get("codec_type") == "audio"]


def duration_sec(path: str | Path) -> float:
    info = probe(path)
    try:
        return float(info.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def extract_audio(video_path: str | Path, out_wav: str | Path,
                  audio_track: int = 0) -> Path:
    """Extract track `audio_track` -> 16kHz mono wav. Returns out_wav path."""
    video_path = Path(video_path)
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    streams = audio_streams(video_path)
    if not streams:
        # edge case 6: no audio track at all
        raise ExtractError(
            "Video không có track audio (video câm hoặc track âm thanh bị lỗi).\n"
            "VietDub cần video có tiếng nói để lồng tiếng.")
    if audio_track >= len(streams):
        raise ExtractError(
            f"Video chỉ có {len(streams)} track audio, không có track {audio_track}.")
    if len(streams) > 1:
        log.info("video has %d audio tracks, using track %d (edge case 12)",
                 len(streams), audio_track)

    if out_wav.exists() and out_wav.stat().st_size > 0:
        log.info("reuse extracted audio %s", out_wav)
        return out_wav

    cmd = [_bin.ffmpeg_cmd(), "-y", "-i", str(video_path),
           "-map", f"0:a:{audio_track}",
           "-vn", "-ar", "16000", "-ac", "1",
           "-c:a", "pcm_s16le", str(out_wav)]
    p = _run(cmd)
    if p.returncode != 0 or not out_wav.exists():
        raise ExtractError(f"Tách audio thất bại:\n{p.stderr[-500:]}")
    log.info("extracted audio -> %s", out_wav)
    return out_wav
