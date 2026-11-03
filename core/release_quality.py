"""Deterministic release gates for Vietnamese dubbed audio.

This is not semantic translation QA. Only objectively unusable text is
blocked; uncertain translation meaning remains for bilingual human review.
"""
from __future__ import annotations

from translation.base import BaseTranslator


def assert_dub_ready(segments) -> None:
    """Refuse to synthesize missing or visibly untranslated dialogue."""
    if not segments:
        raise RuntimeError("Không có câu thoại để tạo TTS; hãy kiểm tra ASR.")
    bad = [
        seg.index for seg in segments
        if BaseTranslator._looks_untranslated(
            seg.text_src, seg.text_vi
        )
    ]
    if bad:
        raise RuntimeError(
            "Bản dịch còn câu rỗng hoặc ký tự nguồn chưa dịch "
            f"(ID: {bad[:12]}). Hãy sửa ở màn review bản dịch "
            "trước khi tạo giọng; không xuất MP4 thiếu nội dung."
        )
