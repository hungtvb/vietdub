"""Qwen transcription with forced alignment and CAM++ speaker labels.

Qwen3-ASR returns transcript text without timestamps. This adapter runs the
ASR, forced aligner, and FunASR/CAM++ diarizer sequentially so their model
weights do not all need to remain resident at once. Aligned character spans
are grouped back into sentence-sized VietDub segments.
"""
from __future__ import annotations

import gc
import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List

from asr.funasr_adapter import (
    ASRError,
    FunASRAdapter,
    _models_dir,
    _wav_duration_sec,
)
from asr.whisper_adapter import _speaker_for_interval
from media import _bin
from project.schema import Segment

log = logging.getLogger("vietdub.asr.qwen")

QWEN_MODEL = "Qwen/Qwen3-ASR-1.7B"
QWEN_ALIGNER_MODEL = "Qwen/Qwen3-ForcedAligner-0.6B"
# Qwen's forced aligner is designed for <=180s. Keep a little margin and
# transcribe/align longer inputs in matching audio chunks.
QWEN_ALIGN_CHUNK_SEC = 170.0

_LANGUAGE_ALIASES = {
    "zh": "Chinese", "zh-cn": "Chinese", "zh-tw": "Chinese",
    "中文": "Chinese", "chinese": "Chinese",
    "en": "English", "english": "English",
    "yue": "Cantonese", "cantonese": "Cantonese",
    "vi": "Vietnamese", "vietnamese": "Vietnamese",
    "ja": "Japanese", "japanese": "Japanese",
    "ko": "Korean", "korean": "Korean",
}


def _language_name(language: str | None) -> str | None:
    value = (language or "").strip()
    if not value or value.lower() in {"auto", "detect"}:
        return None
    if value.lower() in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[value.lower()]
    # Accept any canonical language name supported by qwen-asr.
    canonical = {
        "arabic": "Arabic", "german": "German", "french": "French",
        "spanish": "Spanish", "portuguese": "Portuguese",
        "indonesian": "Indonesian", "italian": "Italian",
        "russian": "Russian", "thai": "Thai", "turkish": "Turkish",
        "hindi": "Hindi", "malay": "Malay", "dutch": "Dutch",
        "swedish": "Swedish", "danish": "Danish", "finnish": "Finnish",
        "polish": "Polish", "czech": "Czech", "filipino": "Filipino",
        "persian": "Persian", "greek": "Greek", "romanian": "Romanian",
        "hungarian": "Hungarian", "macedonian": "Macedonian",
    }
    return canonical.get(value.lower())


def merge_qwen_alignment(text: str, aligned, aligner_processor,
                         diarization: List[Segment], duration_sec: float,
                         offset_sec: float = 0.0,
                         language: str = "Chinese") -> List[Segment]:
    """Reinsert punctuation, group aligned tokens, and attach CAM++ speakers."""
    tokens, _ = aligner_processor.encode_timestamp(text, language)
    items = list(getattr(aligned, "items", aligned))
    if not tokens or len(tokens) != len(items):
        raise ASRError("Qwen ForcedAligner không căn được transcript đầy đủ.")

    out: List[Segment] = []
    chunk_items = []
    chunk_text = ""
    cursor = 0
    sentence_ends = set("。？！!?…")
    clause_marks = set("，,；;")

    def emit() -> None:
        nonlocal chunk_items, chunk_text
        if not chunk_items:
            return
        start = min(float(item.start_time) for item in chunk_items) + offset_sec
        end = max(float(item.end_time) for item in chunk_items) + offset_sec
        start = max(0.0, start)
        end = min(duration_sec, end)
        source = chunk_text.strip()
        if source and end > start:
            out.append(Segment(
                index=len(out), start=start, end=end,
                speaker=_speaker_for_interval(start, end, diarization),
                text_src=source,
            ))
        chunk_items = []
        chunk_text = ""

    for token, item in zip(tokens, items):
        pos = text.find(token, cursor)
        if pos < 0:
            raise ASRError("Token Qwen không khớp văn bản đưa vào aligner.")
        skipped = text[cursor:pos]
        gap = (float(item.start_time) - float(chunk_items[-1].end_time)
               if chunk_items else 0.0)
        span = (float(item.end_time) - float(chunk_items[0].start_time)
                if chunk_items else 0.0)
        should_split = (
            bool(set(skipped) & sentence_ends)
            or (bool(chunk_items) and gap > 1.2)
            or (bool(chunk_items) and span > 9.0
                and bool(set(skipped) & clause_marks))
            or (bool(chunk_items) and span > 15.0)
        )
        chunk_text += skipped
        if should_split:
            emit()
        chunk_items.append(item)
        chunk_text += token
        cursor = pos + len(token)

    chunk_text += text[cursor:]
    emit()
    return FunASRAdapter.post_fix(out)


class QwenDiarizationAdapter:
    """Qwen3-ASR text + Qwen ForcedAligner timestamps + CAM++ speakers."""

    def __init__(self, asr_model: str, vad_model: str, punc_model: str,
                 spk_model: str, qwen_model: str = QWEN_MODEL,
                 aligner_model: str = QWEN_ALIGNER_MODEL,
                 source_language: str | None = "zh",
                 proper_nouns: List[str] | None = None,
                 diarizer: FunASRAdapter | None = None):
        self.qwen_model = qwen_model
        self.aligner_model = aligner_model
        self.language = _language_name(source_language)
        self.proper_nouns = [str(x).strip() for x in (proper_nouns or [])
                             if str(x).strip()]
        self._diarizer = diarizer or FunASRAdapter(
            asr_model=asr_model, vad_model=vad_model,
            punc_model=punc_model, spk_model=spk_model)

    @staticmethod
    def _prepare_hf_cache() -> None:
        if not os.environ.get("HF_HOME"):
            os.environ["HF_HOME"] = str(_models_dir() / "huggingface")

    @staticmethod
    def _mark_for_review(segments: List[Segment]) -> List[Segment]:
        for segment in segments:
            segment.needs_review = True
        return segments

    def _audio_chunks(self, wav_path: Path, duration_sec: float,
                      temp_dir: Path) -> list[tuple[Path, float, float]]:
        if duration_sec <= QWEN_ALIGN_CHUNK_SEC:
            return [(wav_path, 0.0, duration_sec)]
        n = max(1, int(math.ceil(
            (duration_sec - 0.005) / QWEN_ALIGN_CHUNK_SEC)))
        chunks = []
        for i in range(n):
            offset = i * QWEN_ALIGN_CHUNK_SEC
            length = min(QWEN_ALIGN_CHUNK_SEC, duration_sec - offset)
            if length <= 0.01:
                break
            path = temp_dir / f"chunk_{i:03d}.wav"
            proc = subprocess.run(
                [_bin.ffmpeg_cmd(), "-y", "-v", "error",
                 "-ss", f"{offset:.3f}", "-t", f"{length:.3f}",
                 "-i", str(wav_path), "-map", "0:a:0", "-ac", "1",
                 "-ar", "16000", "-c:a", "pcm_s16le", str(path)],
                capture_output=True, text=True)
            if proc.returncode or not path.exists():
                raise ASRError(
                    f"Không chia được audio cho Qwen ({i + 1}/{n}): "
                    f"{proc.stderr[:200]}")
            chunks.append((path, offset, length))
        return chunks

    def transcribe(self, wav_path: str | Path) -> List[Segment]:
        wav_path = Path(wav_path)
        duration_sec = _wav_duration_sec(wav_path)
        self._prepare_hf_cache()
        # Fail before loading/downloading the supporting FunASR stack if the
        # optional Qwen runtime was not installed. This happens only when a
        # Qwen job is actually started, never while opening the app.
        try:
            import torch
            from qwen_asr import Qwen3ASRModel
        except ImportError as e:
            raise ASRError(
                "Chưa cài backend Qwen. Cài bằng: "
                "pip install -r requirements-qwen.txt") from e

        try:
            diarization = self._diarizer.transcribe(wav_path)
        except Exception as e:  # noqa: BLE001
            log.warning("CAM++/FunASR lỗi trước Qwen: %s", e)
            diarization = []
        finally:
            if getattr(self._diarizer, "_pipe", None) is not None:
                self._diarizer._pipe = None
                gc.collect()

        with tempfile.TemporaryDirectory(prefix="vietdub_qwen_") as td:
            try:
                chunks = self._audio_chunks(wav_path, duration_sec, Path(td))
            except Exception as e:  # noqa: BLE001
                log.warning("Không chuẩn bị được audio cho Qwen: %s", e)
                return self._mark_for_review(diarization)

            # Run Qwen ASR first, then release it before loading the aligner.
            context = ""
            if self.proper_nouns:
                terms = self.proper_nouns[:40]
                context = ("只在音频确实说到时使用这些专名，"
                           "不要根据上下文补写：" + "、".join(terms))
            transcripts: list[tuple[Path, float, str, str]] = []
            model = None
            try:
                log.info("Đang tải Qwen %s (bfloat16, CPU)", self.qwen_model)
                model = Qwen3ASRModel.from_pretrained(
                    self.qwen_model, dtype=torch.bfloat16,
                    device_map="cpu")
                for path, offset, _length in chunks:
                    answers = model.transcribe(
                        str(path), language=self.language, context=context,
                        return_time_stamps=False)
                    answer = answers[0] if answers else None
                    text = str(getattr(answer, "text", "") or "").strip()
                    if not text:
                        continue
                    language = str(getattr(answer, "language", "") or "")
                    language = _language_name(language) or self.language or "Chinese"
                    transcripts.append((path, offset, text, language))
            except Exception as e:  # noqa: BLE001
                log.warning("Qwen ASR lỗi, dùng transcript FunASR dự phòng: %s", e)
                return self._mark_for_review(diarization)
            finally:
                model = None
                gc.collect()

            if not transcripts:
                log.warning("Qwen không trả transcript, dùng FunASR dự phòng")
                return self._mark_for_review(diarization)

            try:
                from qwen_asr import Qwen3ForcedAligner
                log.info("Đang tải Qwen ForcedAligner %s (bfloat16, CPU)",
                         self.aligner_model)
                aligner = Qwen3ForcedAligner.from_pretrained(
                    self.aligner_model, dtype=torch.bfloat16,
                    device_map="cpu")
                segments: List[Segment] = []
                for path, offset, text, language in transcripts:
                    aligned = aligner.align(
                        str(path), text, language=language)[0]
                    segments.extend(merge_qwen_alignment(
                        text, aligned, aligner.aligner_processor,
                        diarization, duration_sec, offset, language))
                del aligner
                gc.collect()
                if not segments:
                    raise ASRError("Qwen ForcedAligner không tạo segment nào.")
                segments = FunASRAdapter.post_fix(segments)
                log.info("Qwen trả %d câu có timestamp; ghép CAM++ cho %d loa",
                         len(segments), len({s.speaker for s in segments}))
                return segments
            except Exception as e:  # noqa: BLE001
                log.warning("Qwen ForcedAligner lỗi, dùng transcript FunASR dự phòng: %s", e)
                return self._mark_for_review(diarization)
