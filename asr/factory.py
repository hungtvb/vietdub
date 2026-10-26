"""Build the configured ASR backend."""
from __future__ import annotations

import os


def build_adapter(settings, source_language: str | None = "zh",
                  proper_nouns: list[str] | None = None):
    """Create the selected transcript/timestamp/speaker adapter."""
    args = {
        "asr_model": settings.get("asr_model"),
        "vad_model": settings.get("vad_model"),
        "punc_model": settings.get("punc_model"),
        "spk_model": settings.get("spk_model"),
    }
    if settings.get("asr_backend", "whisper") == "vietdub_stt":
        from asr.vietdub_stt_adapter import VietDubSTTAdapter
        from asr.funasr_adapter import FunASRAdapter
        return VietDubSTTAdapter(
            stt_url=settings.get("stt_url", "http://127.0.0.1:8768"),
            quality=settings.get("stt_quality", "fast"),
            source_language=source_language,
            proper_nouns=proper_nouns,
            diarizer=FunASRAdapter(**args))
    if settings.get("asr_backend", "whisper") == "whisper":
        from asr.whisper_adapter import WhisperDiarizationAdapter
        return WhisperDiarizationAdapter(
            **args,
            whisper_model=settings.get("whisper_model", "large-v3-turbo"),
            compute_type=settings.get("whisper_compute_type", "int8"),
            cpu_threads=max(1, min(os.cpu_count() or 1, 4)),
            source_language=source_language,
            proper_nouns=proper_nouns)
    if settings.get("asr_backend") == "qwen":
        from asr.qwen_adapter import QwenDiarizationAdapter
        return QwenDiarizationAdapter(
            **args,
            qwen_model=settings.get("qwen_model", "Qwen/Qwen3-ASR-1.7B"),
            aligner_model=settings.get(
                "qwen_aligner_model", "Qwen/Qwen3-ForcedAligner-0.6B"),
            source_language=source_language,
            proper_nouns=proper_nouns)
    from asr.funasr_adapter import FunASRAdapter
    return FunASRAdapter(**args)
