# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Edge case 17: estimate peak RAM before the heavy steps and warn when the
machine may not have enough (overnight mode must never die silently).

Components of the estimate (measured/profiled, conservative):
- FunASR model combo resident in RAM (ĐO THẬT, không ước lượng).
- gender step loads the whole 16kHz mono wav as float32.
- build_track works in 60s chunks, so only one chunk buffer is held.
- headroom for the ffmpeg subprocesses.
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("vietdub.resources")

# HIỆU CHỈNH 2026-10-09 (Wave 3): số cũ 1800MB underestimate nặng.
# Đo thật trong hidden_files/wave1_integration.log (run 2026-10-08 16:58:15):
#   [2.asr] OK time=87.3s ram_start=15MB ram_peak=3433MB (clip 55s)
# Trừ các thành phần đã tính riêng: ffmpeg headroom 300MB + track chunk
# ~10MB + wav 55s ~3MB + process base ~15MB -> model combo resident ≈ 3105MB.
# (combo: SeacoParaformer + fsmn-vad + ct-punc 290M + cam++, torch CPU)
ASR_MODEL_MB = 3100.0
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


def estimate_peak_ram_mb(total_sec: float) -> float:
    """Peak RAM estimate (MB) for a video of total_sec seconds."""
    wav_full_mb = total_sec * 16000 * 4 / 1048576.0  # gender step, 16k float32
    return ASR_MODEL_MB + wav_full_mb + TRACK_CHUNK_MB + FFMPEG_HEADROOM_MB


def check_ram(total_sec: float) -> float:
    """Log the peak-RAM estimate; warn when it may exceed machine RAM.

    Returns the estimate (MB) so tests/reporting can use it.
    """
    est = estimate_peak_ram_mb(total_sec)
    total = total_ram_mb()
    log.info("ước lượng RAM đỉnh cho video %.0fs: ~%.0fMB%s",
             total_sec, est,
             f" (máy có ~{total:.0f}MB)" if total else " (không đo được RAM máy)")
    if total and est > total * WARN_FRACTION:
        log.warning(
            "CẢNH BÁO: RAM máy (~%.0fMB) có thể không đủ cho video này "
            "(cần ~%.0fMB). Cách khắc phục: đóng bớt app khác, hoặc chia "
            "video thành các phần < 30 phút rồi lồng tiếng từng phần.",
            total, est)
    return est
