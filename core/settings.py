# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""App settings: real JSON load/save in the user directory.

- Windows: %APPDATA%/VietDub/settings.json
- Linux/macOS: ~/.config/VietDub/settings.json

Nothing is hardcoded: every tunable (API keys, models, voices, thresholds,
volumes, ffmpeg path) lives here and is editable from the Settings dialog
(Wave 2) or by editing the JSON file.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List

log = logging.getLogger("vietdub.settings")

DEFAULTS = {
    # --- translation ---
    "nine_router_key": "",
    "nine_router_model": "mimo-v2.6-flash-free",
    "nine_router_url": "https://opencode.ai/zen/v1",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "",
    "translate_provider": "9router",      # "9router" | "ollama"
    "llm_temperature": 0.2,
    "translate_batch": 20,
    # --- ASR ---
    "asr_model": "damo/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "vad_model": "damo/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "punc_model": "damo/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",  # 290M, light
    "spk_model": "damo/speech_campplus_sv_zh-cn_16k-common",
    # --- ASR quality ---
    "asr_confidence_low": 0.5,   # below this -> needs_review (edge case 5)
    # --- speaker gender ---
    "pitch_male_max_hz": 160.0,
    "pitch_female_min_hz": 165.0,
    "pitch_confidence_low": 0.55,
    # --- TTS ---
    "voice_male": "vi-VN-NamMinhNeural",
    "voice_female": "vi-VN-HoaiMyNeural",
    "tts_rate": "+0%",
    "tts_pitch": "+0Hz",
    "tts_concurrency": 10,
    "atempo_min": 0.8,
    "atempo_max": 1.25,
    # --- mix / render ---
    "dub_volume": 1.0,
    "orig_volume": 0.15,
    "sub_mode": "burn",                  # "burn" | "srt"
    "crf": 20,
    "ffmpeg_path": "ffmpeg",
    # --- behaviour ---
    "review_stops": True,
    "overnight": False,
    "proper_nouns": [],
}


def settings_path() -> Path:
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "VietDub"
    else:
        base = Path.home() / ".config" / "VietDub"
    base.mkdir(parents=True, exist_ok=True)
    return base / "settings.json"


class Settings:
    """dict-like settings with JSON persistence."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings_path()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    self._data.update(saved)
                log.debug("settings loaded from %s", self.path)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("settings file hỏng (%s), dùng mặc định: %s", self.path, e)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)
        log.debug("settings saved to %s", self.path)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, values: dict) -> None:
        self._data.update(values)

    def to_dict(self) -> dict:
        return dict(self._data)
