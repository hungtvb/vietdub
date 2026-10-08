# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""SRT read/write. Subtitle text always goes through an intermediate .srt
file - never inlined into ffmpeg filter args (edge case 11: quotes, %, etc.
are handled by ffmpeg's own escaping when reading the file)."""
from __future__ import annotations

from pathlib import Path
from typing import List

from project.schema import Segment


def ms_to_srt_time(ms: float) -> str:
    ms = int(round(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def sec_to_srt_time(sec: float) -> str:
    return ms_to_srt_time(sec * 1000.0)


def write_srt(segments: List[Segment], path: str | Path,
              field: str = "text_vi") -> Path:
    """Write segments to .srt. Uses text_vi, falls back to text_src."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    n = 0
    for seg in segments:
        text = getattr(seg, field, "") or seg.text_src or ""
        text = text.strip()
        if not text:
            continue
        n += 1
        out.append(f"{n}\n{sec_to_srt_time(seg.start)} --> "
                   f"{sec_to_srt_time(seg.end)}\n{text}\n")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def parse_srt_time(t: str) -> float:
    t = t.strip().replace(".", ",")
    hms, ms = t.split(",")
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def read_srt(path: str | Path) -> List[Segment]:
    """Minimal SRT reader -> Segments (speaker=-1, unknown)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    segs: List[Segment] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0])
            start_s, end_s = lines[1].split("-->")
            body = "\n".join(lines[2:])
        except (ValueError, IndexError):
            continue
        segs.append(Segment(index=idx - 1, start=parse_srt_time(start_s),
                            end=parse_srt_time(end_s), speaker=-1,
                            text_vi=body))
    return segs
