"""Whisper transcription with FunASR/CAM++ speaker labels.

Whisper large-v3-turbo provides clearer text and sentence timestamps on the
tested Chinese news clip. FunASR remains the source of VAD and speaker turns;
Whisper segments inherit the speaker with the largest time overlap.
"""
from __future__ import annotations

import gc
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, List

from asr.funasr_adapter import ASRError, FunASRAdapter, _models_dir, _wav_duration_sec
from project.schema import Segment

log = logging.getLogger("vietdub.asr.whisper")


def _speaker_for_interval(start: float, end: float,
                          diarization: List[Segment]) -> int:
    """Select the CAM++ speaker with the most overlap; nearest turn if none."""
    overlaps: dict[int, float] = defaultdict(float)
    for seg in diarization:
        overlap = max(0.0, min(end, seg.end) - max(start, seg.start))
        if overlap:
            overlaps[seg.speaker] += overlap
    if overlaps:
        return max(overlaps, key=overlaps.get)
    if not diarization:
        return 0
    mid = (start + end) / 2

    def distance(seg: Segment) -> float:
        if mid < seg.start:
            return seg.start - mid
        if mid > seg.end:
            return mid - seg.end
        return 0.0

    return min(diarization, key=distance).speaker


def merge_whisper_segments(whisper_segments: Iterable,
                           diarization: List[Segment],
                           duration_sec: float) -> List[Segment]:
    """Convert faster-whisper results to VietDub segments with CAM++ speakers."""
    out: List[Segment] = []
    for raw in whisper_segments:
        text = str(getattr(raw, "text", "") or "").strip()
        if not text:
            continue
        start = max(0.0, float(getattr(raw, "start", 0.0) or 0.0))
        end = min(duration_sec, float(getattr(raw, "end", start) or start))
        if end <= start:
            continue
        no_speech = float(getattr(raw, "no_speech_prob", 0.0) or 0.0)
        avg_logprob = float(getattr(raw, "avg_logprob", 0.0) or 0.0)
        out.append(Segment(
            index=len(out), start=start, end=end,
            speaker=_speaker_for_interval(start, end, diarization),
            text_src=text,
            confidence=max(0.0, min(1.0, 1.0 - no_speech)),
            needs_review=no_speech >= 0.5 or avg_logprob < -1.0,
        ))
    return FunASRAdapter.post_fix(out)


class WhisperDiarizationAdapter:
    """Use Whisper for text/timestamps and FunASR/CAM++ for speaker turns."""

    def __init__(self, asr_model: str, vad_model: str, punc_model: str,
                 spk_model: str, whisper_model: str = "large-v3-turbo",
                 compute_type: str = "int8", cpu_threads: int = 4,
                 source_language: str | None = "zh",
                 proper_nouns: List[str] | None = None,
                 model_factory: Callable | None = None,
                 diarizer: FunASRAdapter | None = None):
        self.whisper_model = whisper_model
        self.compute_type = compute_type
        self.cpu_threads = max(1, int(cpu_threads))
        self.source_language = self._normalize_language(source_language)
        self.proper_nouns = [str(x).strip() for x in (proper_nouns or [])
                             if str(x).strip()]
        self._factory = model_factory
        self._pipe = None
        self._diarizer = diarizer or FunASRAdapter(
            asr_model=asr_model, vad_model=vad_model,
            punc_model=punc_model, spk_model=spk_model)

    @staticmethod
    def _prepare_hf_cache() -> Path:
        # Set before FunASR imports ModelScope/Hugging Face during diarization;
        # those libraries read HF_HOME at import time.
        models = _models_dir()
        if not os.environ.get("HF_HOME"):
            os.environ["HF_HOME"] = str(models / "huggingface")
        return models

    @staticmethod
    def _normalize_language(language: str | None) -> str | None:
        value = (language or "").strip().lower()
        if not value or value == "auto":
            return None
        if value in {"chinese", "中文", "cn"}:
            return "zh"
        if value == "english":
            return "en"
        return value

    def load(self) -> None:
        if self._pipe is not None:
            return

        # Keep the Whisper weights beside the other app models on first launch.
        self._prepare_hf_cache()
        factory = self._factory
        if factory is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise ASRError(
                    "Chưa cài faster-whisper. Cách khắc phục: pip install "
                    "-r requirements.txt.") from e
            factory = WhisperModel
        try:
            log.info("loading Whisper %s (%s, CPU)", self.whisper_model,
                     self.compute_type)
            self._pipe = factory(self.whisper_model, device="cpu",
                                 compute_type=self.compute_type,
                                 cpu_threads=self.cpu_threads)
        except Exception as e:  # noqa: BLE001
            raise ASRError(
                "Không tải được Whisper ASR (lần đầu cần mạng để tải model). "
                f"Chi tiết: {e}") from e

    def transcribe(self, wav_path: str | Path) -> List[Segment]:
        wav_path = Path(wav_path)
        self._prepare_hf_cache()
        # Retain a safe transcript if Whisper is unavailable or returns nothing.
        # If a caller explicitly preloaded Whisper, release it before loading
        # FunASR so this adapter never intentionally keeps both stacks live.
        if self._pipe is not None:
            self._pipe = None
            gc.collect()
        diarization = self._diarizer.transcribe(wav_path)
        # The speaker turns are saved in `diarization`; release the heavier
        # FunASR stack before loading Whisper to keep peak RAM conservative.
        if getattr(self._diarizer, "_pipe", None) is not None:
            self._diarizer._pipe = None
            gc.collect()
        try:
            self.load()
            terms = self.proper_nouns[:40]
            initial_prompt = "常见专名：" + "、".join(terms) if terms else None
            raw, info = self._pipe.transcribe(
                str(wav_path), language=self.source_language, beam_size=5,
                condition_on_previous_text=False, vad_filter=False,
                initial_prompt=initial_prompt)
            raw = list(raw)
        except Exception as e:  # noqa: BLE001
            self._pipe = None
            gc.collect()
            log.warning("Whisper lỗi, dùng transcript FunASR dự phòng: %s", e)
            for seg in diarization:
                seg.needs_review = True
            return diarization
        # These models are large. Keep them sequential in memory, including
        # across repeated jobs in the same desktop session.
        self._pipe = None
        gc.collect()

        if not raw:
            log.warning("Whisper không trả câu nào, dùng transcript FunASR")
            for seg in diarization:
                seg.needs_review = True
            return diarization
        segments = merge_whisper_segments(
            raw, diarization, _wav_duration_sec(wav_path))
        if not segments:
            log.warning("Whisper trả timestamp lỗi, dùng transcript FunASR")
            for seg in diarization:
                seg.needs_review = True
            return diarization

        language = getattr(info, "language", "unknown")
        probability = float(getattr(info, "language_probability", 0.0) or 0.0)
        log.info("Whisper nhận dạng %s (%.2f), %d câu; ghép nhãn CAM++ cho %d loa",
                 language, probability, len(segments),
                 len({s.speaker for s in segments}))
        return segments
