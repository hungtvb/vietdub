# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Select the TTS adapter without importing optional model dependencies."""
from __future__ import annotations


def create_tts(settings, *, provider=None, voice_male=None, voice_female=None):
    selected = provider or settings.get("tts_provider", "edge")
    if selected == "vieneu":
        from tts.vieneu_tts import VieNeuTTS
        return VieNeuTTS(
            voice_male=voice_male or settings.get("vieneu_voice_male", "Hải Đăng"),
            voice_female=voice_female or settings.get("vieneu_voice_female", "Mai Anh"),
            backend=settings.get("vieneu_backend", "auto"),
            precision=settings.get("vieneu_precision", "fp32"))
    if selected == "edge":
        from tts.edge_tts import EdgeTTS
        return EdgeTTS(
            voice_male=voice_male or settings.get("voice_male", "vi-VN-NamMinhNeural"),
            voice_female=voice_female or settings.get("voice_female", "vi-VN-HoaiMyNeural"),
            rate=settings.get("tts_rate", "+0%"),
            pitch=settings.get("tts_pitch", "+0Hz"),
            concurrency=int(settings.get("tts_concurrency", 10)))
    raise ValueError(f"Không hỗ trợ TTS provider: {selected}")
