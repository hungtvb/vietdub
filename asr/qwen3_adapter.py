"""Qwen3-ASR local inference with mandatory real forced-alignment timestamps.

Uses the official qwen-asr Transformers interface, not Ollama text models.
Requires Qwen3-ForcedAligner; rejects missing or inconsistent timestamps.
Speaker IDs are NEVER claimed verified (Qwen3-ASR is not diarization).
"""
from __future__ import annotations

import logging
import math
import time
import unicodedata
from types import SimpleNamespace
from pathlib import Path

from project.schema import Segment

log = logging.getLogger("vietdub.asr.qwen3")

QWEN_LANGUAGES = {
    "zh": "Chinese", "en": "English", "ja": "Japanese",
    "ko": "Korean", "fr": "French", "de": "German",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese",
    "ru": "Russian",
}
LANGUAGE_CODES = {value.casefold(): key for key, value in QWEN_LANGUAGES.items()}


class QwenASRError(RuntimeError):
    pass


def restore_asr_punctuation(items, recognized_text):
    """Map Qwen transcription punctuation onto its genuine timed tokens.

    No word insertion or deletion: restore only if the source and aligned
    Unicode alphanumeric sequences match exactly. This preserves speech-act
    punctuation (?/？), clauses, and commas for all source languages.
    """
    def lexical_chars(value):
        return "".join(ch for ch in value if
                       not ch.isspace() and
                       not unicodedata.category(ch).startswith("P"))

    source=str(recognized_text or "")
    span_list=list(items)
    tokens=[str(getattr(it,"text","") or "") for it in span_list]
    original=lexical_chars(source)
    from_aligner="".join(lexical_chars(t) for t in tokens)
    if not original or original != from_aligner:
        return span_list, False
    positions=[i for i,ch in enumerate(source)
               if not ch.isspace() and
               not unicodedata.category(ch).startswith("P")]
    cursor=0
    fixed=[]
    for i,token in enumerate(tokens):
        count=len(lexical_chars(token))
        if count<=0:
            return span_list,False
        start=0 if i==0 else positions[cursor]
        cursor+=count
        end=positions[cursor] if cursor<len(positions) else len(source)
        own_text=source[start:end].strip()
        fixed.append(SimpleNamespace(
            text=own_text,
            start_time=getattr(span_list[i],"start_time"),
            end_time=getattr(span_list[i],"end_time")))
    return fixed,True


def aligned_to_segments(items, *, duration, language="und", max_window=9.0):
    """Turn Qwen3-ForcedAligner word/character spans into timed dub lines."""
    if not math.isfinite(float(duration)) or duration <= 0:
        raise QwenASRError("Qwen WAV duration is invalid")
    lines, group = [], []
    previous_end = 0.0

    def flush():
        if not group:
            return
        # A few Qwen aligned Hanzi are point-aligned (start == end).
        # Keep those words attached to their surrounding TIMED utterance;
        # never fabricate durations for individual characters.
        if group[-1][1] <= group[0][0]:
            raise QwenASRError(
                "Qwen aligned tokens have zero total utterance duration")
        phrase = ("".join(w[2] for w in group)
                  if language in ("zh", "ja")
                  else " ".join(w[2] for w in group))
        phrase = " ".join(phrase.split()).strip()
        if not phrase:
            raise QwenASRError("Qwen alignment contains empty text")
        lines.append(Segment(
            index=len(lines), start=group[0][0], end=group[-1][1],
            speaker=0, text_src=phrase, source_lang=language,
            confidence=0.0, needs_review=True,
            identity_status="UNVERIFIED"))
        group.clear()

    for item in items:
        try:
            token = str(item.text or "").strip()
            start = float(item.start_time)
            end = float(item.end_time)
        except (AttributeError, ValueError, TypeError) as exc:
            raise QwenASRError("Qwen forced aligner emitted invalid item") from exc
        if not token:
            raise QwenASRError("Qwen forced aligner emitted empty word")
        if not all(math.isfinite(x) for x in (start, end)):
            raise QwenASRError("Qwen timestamps are nonfinite")
        if start < -0.05 or start > end or end > duration + .2:
            raise QwenASRError(
                f"Qwen word timestamps escaped audio duration: "
                f"word={token[:30]!r} start={start:.3f} "
                f"end={end:.3f} audio_duration={duration:.3f}")
        if start < previous_end - .15:
            raise QwenASRError("Qwen word timestamps overlap/out of order")
        start = max(0.0, start)
        end = min(float(duration), end)
        if end < start:
            raise QwenASRError("Qwen word interval runs backward")
        if group and (start - group[-1][1] > 1.0
                      or end - group[0][0] > max_window):
            flush()
        group.append((start, end, token))
        if (token.endswith(("。", "！", "？", ".", "!", "?"))
                and group[-1][1] > group[0][0]):
            flush()
        previous_end = end
    flush()
    if not lines:
        raise QwenASRError("Qwen returned no aligned spoken words")
    return lines


class Qwen3ASRAdapter:
    """Native Qwen3-ASR adapter with auditable performance/QA evidence."""

    def __init__(self, model="Qwen/Qwen3-ASR-0.6B",
                 aligner="Qwen/Qwen3-ForcedAligner-0.6B",
                 device="auto", language="auto"):
        if device not in ("auto", "cpu", "cuda"):
            raise ValueError("Qwen ASR device must be auto, cpu, or cuda")
        if not model or not aligner:
            raise ValueError("Qwen3-ASR and Qwen3-ForcedAligner are required")
        self.model = model
        self.aligner = aligner
        self.device = device
        self.language = language
        self.last_evidence = {}

    def transcribe(self, wav_path):
        try:
            import torch
            import soundfile as sf
            from qwen_asr import Qwen3ASRModel
        except ImportError as exc:
            raise QwenASRError(
                "Thiếu Qwen3-ASR. Cài bằng lệnh: "
                "pip install -r requirements-asr-qwen.txt") from exc

        path = Path(wav_path)
        if not path.is_file():
            raise QwenASRError(f"WAV file not found: {path}")
        duration = float(sf.info(str(path)).duration)
        if not math.isfinite(duration) or duration <= 0:
            raise QwenASRError("Invalid WAV duration")
        use_device = self.device
        if use_device == "auto":
            use_device = "cuda" if torch.cuda.is_available() else "cpu"
        if use_device == "cuda" and not torch.cuda.is_available():
            raise QwenASRError("Không tìm thấy CUDA. Chọn Qwen device=cpu/auto.")
        dtype = torch.float16 if use_device == "cuda" else torch.float32
        device_map = "cuda:0" if use_device == "cuda" else "cpu"

        forced_language = QWEN_LANGUAGES.get(self.language)
        if self.language not in ("auto", "und", "", "mixed") and forced_language is None:
            log.warning("Qwen language %s not recognized; auto-detect", self.language)
        started = time.perf_counter()
        try:
            provider = Qwen3ASRModel.from_pretrained(
                self.model, dtype=dtype, device_map=device_map,
                max_inference_batch_size=1, max_new_tokens=512,
                forced_aligner=self.aligner,
                forced_aligner_kwargs={
                    "dtype": dtype, "device_map": device_map})
            result = provider.transcribe(
                audio=str(path), language=forced_language,
                return_time_stamps=True)
        except Exception as exc:
            raise QwenASRError("Qwen3-ASR inference/aligner failed: "
                               + str(exc)[:400]) from exc
        if not isinstance(result, (list, tuple)) or len(result) != 1:
            raise QwenASRError("Qwen ASR expected one result per input WAV")
        entry = result[0]
        self.last_evidence = {
            "status": "ALIGNMENT_REVIEW_IN_PROGRESS",
            "raw_transcript": str(getattr(entry,"text","") or "")[:2500],
            "detected_language": str(getattr(entry,"language","") or ""),
            "source_duration": round(duration,3)}
        spans = getattr(entry.time_stamps, "items", None) if entry.time_stamps else None
        if isinstance(spans,(list,tuple)):
            self.last_evidence["raw_aligned_count"]=len(spans)
            self.last_evidence["raw_aligned_preview"]=[
                {"word":str(getattr(w,"text",""))[:60],
                 "start":getattr(w,"start_time",None),
                 "end":getattr(w,"end_time",None)}
                for w in (list(spans[:8])+list(spans[-8:]))]
        if not isinstance(spans, (list, tuple)) or not spans:
            raise QwenASRError(
                "Qwen returned text without real aligned timestamps; "
                "cannot create trustworthy dubbed timeline")
        raw_lang = str(getattr(entry, "language", "") or "").casefold().strip()
        detected = LANGUAGE_CODES.get(raw_lang)
        if detected is None:
            detected = self.language if self.language in QWEN_LANGUAGES else "und"
        restored, matched=restore_asr_punctuation(
            spans,str(getattr(entry,"text","") or ""))
        self.last_evidence["punctuation_restored"]=matched
        if not matched:
            log.warning("Qwen transcript characters differ from forced aligner; "
                        "cannot restore punctuation. Requires manual review.")
        segments = aligned_to_segments(restored, duration=duration,
                                       language=detected)
        # This is always a single unknown speaker unless independent
        # diarization is applied and manually verified.
        self.last_evidence = {
            "source": "qwen3_asr", "engine": "qwen3_asr",
            "model": self.model, "aligner": self.aligner,
            "device": use_device, "language_detected": detected,
            "language_review_required": True,
            "audio_seconds": round(duration, 3),
            "inference_seconds": round(time.perf_counter()-started, 2),
            "timed_segment_count": len(segments),
            "punctuation_restored": matched,
            "human_verified": False, "qa_status": "UNAPPROVED",
            "speaker_diarization_executed": False,
            "speaker_validation_warning": (
                "Qwen ASR does not diarize; all segments temporarily "
                "belong to unverified speaker 0."),
            "forced_alignment_executed": True,
            "segments": [s.to_dict() for s in segments],
        }
        return segments
