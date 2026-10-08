# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Step [3] - guess each speaker's gender from pitch (librosa/pyin).

Median F0 per speaker across all their segments:
  median < male_max_hz   -> male
  median > female_min_hz -> female
  in between             -> lower confidence, closer side wins, flagged
Confidence = normalized distance from the decision boundary.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

import numpy as np

from project.schema import Segment, Speaker

log = logging.getLogger("vietdub.gender")


class GenderError(Exception):
    pass


def _median_f0(audio: np.ndarray, sr: int, start: float, end: float) -> float:
    try:
        import librosa
    except ImportError as e:
        raise GenderError(
            "Chưa cài thư viện librosa.\n"
            "Cách khắc phục: pip install librosa") from e
    s0, s1 = int(start * sr), int(end * sr)
    clip = audio[s0:s1]
    if clip.size < sr // 2:  # < 0.5s of audio: not reliable
        return 0.0
    f0, voiced_flag, _ = librosa.pyin(
        clip, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
        sr=sr)
    voiced = f0[voiced_flag]
    voiced = voiced[np.isfinite(voiced)]
    if voiced.size == 0:
        return 0.0
    return float(np.median(voiced))


def estimate_genders(wav_path: str | Path, segments: List[Segment],
                     male_max_hz: float = 160.0,
                     female_min_hz: float = 165.0) -> Dict[int, Speaker]:
    """Return {speaker_id: Speaker(gender, confidence, median_hz)}."""
    try:
        import librosa
        import soundfile as sf
    except ImportError as e:
        raise GenderError(
            "Chưa cài thư viện librosa/soundfile.\n"
            "Cách khắc phục: pip install librosa soundfile") from e

    wav_path = Path(wav_path)
    if not wav_path.exists():
        raise GenderError(f"Không tìm thấy file audio: {wav_path}")
    audio, sr = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    by_speaker: Dict[int, List[float]] = {}
    for seg in segments:
        if seg.speaker < 0:
            continue
        hz = _median_f0(audio, sr, seg.start, seg.end)
        if hz > 0:
            by_speaker.setdefault(seg.speaker, []).append(hz)

    speakers: Dict[int, Speaker] = {}
    for spk_id, hzs in by_speaker.items():
        median = float(np.median(hzs))
        mid = (male_max_hz + female_min_hz) / 2.0
        half_gap = max((female_min_hz - male_max_hz) / 2.0, 1.0)
        if median <= male_max_hz:
            gender = "male"
            conf = min(1.0, (mid - median) / (mid - 50.0) + 0.5)
        elif median >= female_min_hz:
            gender = "female"
            conf = min(1.0, (median - mid) / (400.0 - mid) + 0.5)
        else:
            gender = "male" if median < mid else "female"
            conf = 0.5 * (1.0 - abs(median - mid) / half_gap)
        conf = float(max(0.05, min(1.0, conf)))
        speakers[spk_id] = Speaker(id=spk_id, gender=gender,
                                   confidence=round(conf, 2),
                                   median_hz=round(median, 1))
        log.info("speaker %d: %s (median %.1f Hz, conf %.2f)",
                 spk_id, gender, median, conf)
    return speakers
