# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
#
# Algorithm adapted from pyVideoTrans (https://github.com/jianchang512/pyvideotrans)
# by jianchang512, GPL-3.0: task/_rate.py::TtsSpeedRate -
#   _prepare_data (silent placeholder for missing TTS),
#   _calculate_adjustments (force long dubs into their slot),
#   _precise_speed_up_audio (atempo chain), _concat_audio_aligned
#   (pad short dubs with tail silence, keep timeline).
# DESIGN.md differences: atempo factor capped to [0.8, 1.25]; beyond that
# raise TooLongError so the caller splits the sentence (edge case 1)
# instead of distorting the voice.
"""Step [6b] - fit each dubbed wav into its timestamp slot, then build one
continuous dub track placed exactly on the timeline (gaps preserved)."""
from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Set, Tuple

import numpy as np

from media import _bin
from project.schema import Segment

log = logging.getLogger("vietdub.duration_fit")

ATEMPO_MIN = 0.8
ATEMPO_MAX = 1.25
SHORT_SLOT_SEC = 0.5  # edge case 2: slots shorter than this can't be split

SAMPLE_RATE = 44100


class TooLongError(Exception):
    """TTS much longer than its slot (ratio > 1.25): caller must split the
    sentence at a comma/period and re-run TTS on the halves (edge case 1)."""

    def __init__(self, segment: Segment, ratio: float):
        self.segment = segment
        self.ratio = ratio
        super().__init__(
            f"Câu {segment.index} dài gấp {ratio:.2f} lần khung giờ "
            f"({segment.start:.1f}-{segment.end:.1f}s): cần tách câu.")


def wav_duration_sec(path: str | Path) -> float:
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / float(info.samplerate)


def make_silence_wav(path: str | Path, duration_sec: float,
                     sr: int = SAMPLE_RATE) -> Path:
    import soundfile as sf
    path = Path(path)
    n = max(1, int(duration_sec * sr))
    sf.write(str(path), np.zeros(n, dtype=np.float32), sr, subtype="PCM_16")
    return path


def _atempo_filter(factor: float) -> str:
    # factor >1 speeds up (shortens); <1 slows down (lengthens).
    # Our cap [0.8, 1.25] always fits a single atempo ([0.5, 2.0]).
    assert 0.5 <= factor <= 2.0, f"atempo factor out of range: {factor}"
    return f"atempo={factor:.4f}"


def apply_atempo(wav_path: str | Path, factor: float) -> Path:
    """Speed-change wav in place via ffmpeg atempo. factor<1 slows down."""
    wav_path = Path(wav_path)
    tmp = wav_path.with_suffix(".atempo.wav")
    cmd = [_bin.ffmpeg_cmd(), "-y", "-v", "error", "-i", str(wav_path),
           "-filter:a", _atempo_filter(factor),
           "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le",
           str(tmp)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"atempo lỗi: {p.stderr[:200]}")
    tmp.replace(wav_path)
    return wav_path


def plan(segments: List[Segment],
         atempo_min: float = ATEMPO_MIN,
         atempo_max: float = ATEMPO_MAX,
         out_dir: Optional[str | Path] = None,
         force_overflow: Optional[Set[int]] = None) -> List[Tuple[Segment, str, float]]:
    """Decide per-segment action. Returns [(seg, action, factor)].

    action: "keep" | "atempo" | "overflow". Raises TooLongError (edge 1)
    when the dub is >atempo_max x the slot and the slot is splittable.

    out_dir: where to write silent placeholders for missing TTS audio.
        Must be inside the job dir (jobs/<id>/stages/tts) - never the CWD.
    force_overflow: ids (id(seg)) of segments that must NOT raise
        TooLongError because they cannot be split - they get max squeeze
        + overflow instead (edge 2 treatment).
    """
    force = force_overflow or set()
    decisions = []
    for seg in segments:
        slot = seg.end - seg.start
        if slot <= 0:
            log.warning("câu %d slot không hợp lệ, bỏ qua", seg.index)
            continue
        if not seg.audio_vi or not Path(seg.audio_vi).exists():
            # port policy: silent placeholder (pyVideoTrans _prepare_data)
            if seg.audio_vi:
                ph = Path(seg.audio_vi)
            elif out_dir is not None:
                ph = Path(out_dir) / f"silent_{seg.index:04d}.wav"
            else:
                ph = Path(f"stages/tts/silent_{seg.index:04d}.wav")
            ph.parent.mkdir(parents=True, exist_ok=True)
            make_silence_wav(ph, slot)
            seg.audio_vi = str(ph)
            decisions.append((seg, "keep", 1.0))
            continue
        dur = wav_duration_sec(seg.audio_vi)
        ratio = dur / slot  # >1 means TTS longer than slot -> speed up
        if ratio <= 1.0:
            decisions.append((seg, "keep", 1.0))
        elif ratio <= atempo_max:
            # atempo factor = ratio (e.g. 1.2x faster); within [0.8, 1.25]
            decisions.append((seg, "atempo", ratio))
        elif slot < SHORT_SLOT_SEC or id(seg) in force:
            # edge case 2: too short to split - or not splittable at all:
            # max squeeze, allow light overflow, warn
            log.warning("câu %d (%.1fs) quá ngắn/không tách được, nén tối đa "
                        "%.2fx và cho tràn nhẹ quá slot", seg.index, slot,
                        atempo_max)
            decisions.append((seg, "overflow", atempo_max))
        else:
            raise TooLongError(seg, ratio)
    return decisions


def apply_plan(decisions: List[Tuple[Segment, str, float]]) -> None:
    for seg, action, factor in decisions:
        if action == "atempo" or (action == "overflow" and factor != 1.0):
            apply_atempo(seg.audio_vi, factor)
            log.debug("câu %d: atempo=%.3f (%s)", seg.index, factor, action)


_SPLIT_PUNC = re.compile(r"[,，.。!！?？;；:：]")


def split_segment(seg: Segment) -> Tuple[Segment, Segment]:
    """Edge case 1: split a too-long sentence at the comma/period nearest
    the middle; split the timestamp proportionally by character count."""
    text = seg.text_vi or seg.text_src
    matches = list(_SPLIT_PUNC.finditer(text))
    if matches:
        mid = len(text) / 2
        cut = min(matches, key=lambda m: abs(m.start() - mid))
        cut_at = cut.end()
    else:
        cut_at = len(text) // 2
    t1, t2 = text[:cut_at].strip(), text[cut_at:].strip()
    if not t1 or not t2:
        raise ValueError(f"câu {seg.index} không tách được (không có dấu câu)")
    total = len(t1) + len(t2)
    mid_time = seg.start + (seg.end - seg.start) * (len(t1) / total)
    a = Segment(index=seg.index, start=seg.start, end=mid_time,
                speaker=seg.speaker, gender=seg.gender,
                text_src=seg.text_src, text_vi=t1)
    b = Segment(index=seg.index, start=mid_time, end=seg.end,
                speaker=seg.speaker, gender=seg.gender,
                text_src=seg.text_src, text_vi=t2)
    log.info("tách câu %d thành 2 câu con tại %.1fs", seg.index, mid_time)
    return a, b


CHUNK_SEC = 60.0  # edge 17: build the dub track one chunk at a time


def _place_segment(buf: np.ndarray, chunk_start: float, seg: Segment,
                   sr: int, chunk_len: int) -> None:
    """Add seg's wav into buf at (seg.start - chunk_start); clips to bounds."""
    import soundfile as sf
    data, file_sr = sf.read(seg.audio_vi, dtype="float32")
    if file_sr != sr:
        raise RuntimeError(
            f"câu {seg.index}: sample rate {file_sr} != {sr}, không khớp track")
    if data.ndim > 1:
        data = data.mean(axis=1)
    s0 = int((seg.start - chunk_start) * sr)
    if s0 >= chunk_len:
        return
    s0 = max(0, s0)
    s1 = min(chunk_len, s0 + len(data))
    if s1 > s0:
        buf[s0:s1] += data[:s1 - s0]


def build_track(segments: List[Segment], out_wav: str | Path,
                total_sec: float, sr: int = SAMPLE_RATE,
                chunk_sec: float = CHUNK_SEC) -> Path:
    """Place each segment wav at its exact start; silence elsewhere.

    Gaps between sentences stay silent (edge case 3).
    Edge case 17: never holds the whole 90-minute track in RAM - each
    chunk_sec-long chunk is written to a temp wav, then all chunks are
    concatenated with ffmpeg. Peak extra RAM ~= one chunk (~10MB).
    """
    import soundfile as sf
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if total_sec <= 0:
        raise ValueError("total_sec phải > 0")
    segs = sorted(segments, key=lambda s: s.start)
    n_chunks = max(1, int(math.ceil(total_sec / chunk_sec)))
    tmpdir = Path(tempfile.mkdtemp(prefix="vd_track_"))
    try:
        chunk_files = []
        for ci in range(n_chunks):
            c0 = ci * chunk_sec
            c1 = min((ci + 1) * chunk_sec, total_sec)
            chunk_len = int((c1 - c0) * sr)
            if chunk_len <= 0:
                continue
            buf = np.zeros(chunk_len, dtype=np.float32)
            for seg in segs:
                if not seg.audio_vi or not Path(seg.audio_vi).exists():
                    continue
                if seg.end <= c0 or seg.start >= c1:
                    continue
                if seg.start * sr >= total_sec * sr:
                    log.warning("câu %d bắt đầu sau cuối video, bỏ qua",
                                seg.index)
                    continue
                _place_segment(buf, c0, seg, sr, chunk_len)
            np.clip(buf, -1.0, 1.0, out=buf)
            cp = tmpdir / f"chunk_{ci:04d}.wav"
            sf.write(str(cp), buf, sr, subtype="PCM_16")
            chunk_files.append(cp)
        # concat with ffmpeg (same codec, lossless join)
        lst = tmpdir / "list.txt"
        lst.write_text(
            "".join("file '" + c.as_posix().replace("'", "'\\''") + "'\n"
                    for c in chunk_files),
            encoding="utf-8")
        cmd = [_bin.ffmpeg_cmd(), "-y", "-v", "error",
               "-f", "concat", "-safe", "0", "-i", str(lst),
               "-c:a", "pcm_s16le", str(out_wav)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0 or not out_wav.exists():
            raise RuntimeError(f"nối chunk dub track lỗi: {p.stderr[:300]}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    log.info("dub track -> %s (%.1fs, %d chunk)", out_wav, total_sec,
             n_chunks)
    return out_wav
