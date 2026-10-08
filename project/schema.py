# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""Data model: Segment, Speaker, Project. Plain dataclasses, JSON-serializable."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Segment:
    """Smallest unit: one spoken sentence."""
    index: int
    start: float          # seconds
    end: float            # seconds
    speaker: int          # speaker id
    gender: str = ""      # "male" | "female" | ""
    text_src: str = ""
    text_vi: str = ""
    audio_vi: str = ""    # path to dubbed wav for this segment
    confidence: float = 1.0
    needs_review: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Speaker:
    id: int
    gender: str = ""          # "male" | "female"
    confidence: float = 0.0
    median_hz: float = 0.0
    role: str = ""
    speaking_to: str = ""
    pronoun_i: str = "tôi"    # default safe pronouns (edge case 7/8)
    pronoun_you: str = "bạn"
    tone: str = "neutral"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Speaker":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Project:
    """Per-job project settings + state. Saved as jobs/<job_id>/project.json."""
    name: str = "untitled"
    video_source: str = "file"   # "file" | "url"
    video_url: str = ""          # set when video_source == "url"
    video_in: str = ""           # local input path (or resolved path after fetch)
    video_out: str = ""
    src_lang: str = "zh"
    dst_lang: str = "vi"
    audio_track: int = 0       # edge 12: which audio track to extract (Wave 2: dropdown)
    voice_male: str = "vi-VN-NamMinhNeural"
    voice_female: str = "vi-VN-HoaiMyNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"
    dub_volume: float = 1.0
    orig_volume: float = 0.15
    sub_mode: str = "burn"       # "burn" | "srt"
    translate_provider: str = "9router"  # "9router" | "ollama"
    review_stops: bool = True
    overnight: bool = False
    stages_done: List[str] = field(default_factory=list)
    proper_nouns: List[str] = field(default_factory=list)  # custom proper names (edge 9)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def effective_review_stops(self) -> bool:
        """Overnight mode MUST disable review stops (enforced in code, not UI)."""
        if self.overnight:
            return False
        return self.review_stops
