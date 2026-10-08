# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Step [7] - mix: dubbed track at 100%, original at ~15% underneath.

Port note: filter pattern adapted from pyVideoTrans
(https://github.com/jianchang512/pyvideotrans) task/_stage_audio.py:
`amix=...:normalize=0` is the critical detail - without normalize=0, amix
halves the dub volume. Followed by alimiter to avoid clipping.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from media import _bin

log = logging.getLogger("vietdub.mix")


class MixError(Exception):
    pass


def mix(dub_wav: str | Path, orig_wav: str | Path, out_wav: str | Path,
        dub_volume: float = 1.0, orig_volume: float = 0.15) -> Path:
    """Overlay dub (full) over attenuated original. Returns out_wav.

    dub_wav is built to full video length by duration_fit.build_track, so
    amix duration=first keeps the timeline exact.
    """
    dub_wav, orig_wav, out_wav = Path(dub_wav), Path(orig_wav), Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if not dub_wav.exists():
        raise MixError(f"Không tìm thấy track lồng tiếng: {dub_wav}")
    if not orig_wav.exists():
        raise MixError(f"Không tìm thấy track gốc: {orig_wav}")

    fc = (f"[0:a]volume={dub_volume}[dub];"
          f"[1:a]volume={orig_volume}[bg];"
          f"[dub][bg]amix=inputs=2:duration=first:"
          f"dropout_transition=0:normalize=0,"
          f"alimiter=limit=0.95[mix]")
    cmd = [_bin.ffmpeg_cmd(), "-y", "-i", str(dub_wav), "-i", str(orig_wav),
           "-filter_complex", fc, "-map", "[mix]",
           "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out_wav)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not out_wav.exists():
        raise MixError(f"Trộn audio thất bại:\n{p.stderr[-500:]}")
    log.info("mixed -> %s (dub=%.2f, orig=%.2f)", out_wav, dub_volume, orig_volume)
    return out_wav
