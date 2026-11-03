# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Edge case 17: estimate peak RAM before the heavy steps and warn when the
machine may not have enough (overnight mode must never die silently).

Components of the estimate (conservative until profiled on Windows):
- Largest ASR model stack resident in RAM; hybrid and Qwen adapters load
  their model stacks sequentially so they do not intentionally overlap.
- gender step loads the whole 16kHz mono wav as float32.
- build_track works in 60s chunks, so only one chunk buffer is held.
- headroom for the ffmpeg subprocesses.
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("vietdub.resources")

# Conservative estimate based on the older FunASR/SeacoParaformer profile
# (3433MB process peak for a 55s clip). Retain this budget until the hybrid
# Whisper + FunASR peak is profiled on the target Windows setup.
ASR_MODEL_MB = 3100.0
# Measured Qwen 1.7B and the 0.6B aligner are loaded sequentially. The ASR
# pass peaked around 6.5GB in the benchmark environment; keep headroom for the
# Python/runtime allocations and the full audio buffer.
QWEN_ASR_MODEL_MB = 7000.0
FFMPEG_HEADROOM_MB = 300.0
TRACK_CHUNK_SEC = 60.0   # build_track chunk size
TRACK_CHUNK_MB = TRACK_CHUNK_SEC * 44100 * 4 / 1048576.0  # float32 buffer
WARN_FRACTION = 0.85     # warn when estimate exceeds 85% of machine RAM


def total_ram_mb() -> float | None:
    """Total physical RAM in MB, or None when it cannot be determined."""
    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / 1048576.0
        except Exception:  # noqa: BLE001 - best effort only
            return None
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
        return pages * page / 1048576.0
    except (ValueError, OSError, AttributeError):
        return None


def estimate_peak_ram_mb(total_sec: float,
                         asr_backend: str = "whisper") -> float:
    """Peak RAM estimate (MB) for a video of total_sec seconds."""
    model_mb = QWEN_ASR_MODEL_MB if asr_backend == "qwen" else ASR_MODEL_MB
    wav_full_mb = total_sec * 16000 * 4 / 1048576.0  # gender step, 16k float32
    return model_mb + wav_full_mb + TRACK_CHUNK_MB + FFMPEG_HEADROOM_MB


def check_ram(total_sec: float, asr_backend: str = "whisper") -> float:
    """Log the peak-RAM estimate; warn when it may exceed machine RAM.

    Returns the estimate (MB) so tests/reporting can use it.
    """
    est = estimate_peak_ram_mb(total_sec, asr_backend)
    total = total_ram_mb()
    log.info("ước lượng RAM đỉnh cho video %.0fs với backend %s: ~%.0fMB%s",
             total_sec, asr_backend, est,
             f" (máy có ~{total:.0f}MB)" if total else " (không đo được RAM máy)")
    if total and est > total * WARN_FRACTION:
        log.warning(
            "CẢNH BÁO: RAM máy (~%.0fMB) có thể không đủ cho video này "
            "(cần ~%.0fMB). Cách khắc phục: đóng bớt app khác, hoặc chia "
            "video thành các phần < 30 phút rồi lồng tiếng từng phần.",
            total, est)
    return est
