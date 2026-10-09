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
    # who this line is addressed to: speaker id as str, "audience"
    # (viewers in general), "all" (everyone present), or "" (unknown)
    audience: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


def audience_label(aud: str) -> str:
    """Human/prompt label for an audience value."""
    a = (aud or "").strip()
    if a == "audience":
        return "the audience"
    if a == "all":
        return "everyone"
    if a.isdigit():
        return f"SPEAKER_{a}"
    return a or "the audience"


def audience_label_vi(aud: str) -> str:
    """Nhãn tiếng Việt cho cột 'Nói với ai' ở màn duyệt."""
    a = (aud or "").strip()
    if a == "audience":
        return "Khán giả"
    if a == "all":
        return "Tất cả"
    if a.isdigit():
        return f"Loa {a}"
    return "Chưa rõ"


def audience_value_vi(label: str) -> str | None:
    """Nhãn tiếng Việt -> giá trị audience; None = nhãn không hợp lệ."""
    t = (label or "").strip()
    if t in ("", "Chưa rõ"):
        return ""
    if t == "Khán giả":
        return "audience"
    if t == "Tất cả":
        return "all"
    if t.startswith("Loa "):
        try:
            return str(int(t[4:].strip()))
        except ValueError:
            return None
    return None


@dataclass
class Speaker:
    id: int
    gender: str = ""          # "male" | "female"
    confidence: float = 0.0
    median_hz: float = 0.0
    role: str = ""
    speaking_to: str = ""     # legacy: default relation's audience
    pronoun_i: str = "tôi"    # default pair (kept in sync with relations)
    pronoun_you: str = "bạn"  # default pair (kept in sync with relations)
    tone: str = "neutral"
    # per-audience pronoun tables: [{"audience": "audience"|"all"|"<sid>",
    #   "pronoun_i": str, "pronoun_you": str, "is_default": bool}]
    relations: List[dict] = field(default_factory=list)

    def get_pronouns(self, audience: str = "") -> tuple:
        """(pronoun_i, pronoun_you) for the given audience; default first."""
        rels = self.relations or []
        if audience:
            for r in rels:
                if r.get("audience") == audience:
                    return (r.get("pronoun_i") or "tôi",
                            r.get("pronoun_you") or "bạn")
        for r in rels:
            if r.get("is_default"):
                return (r.get("pronoun_i") or "tôi",
                        r.get("pronoun_you") or "bạn")
        if rels:
            r = rels[0]
            return (r.get("pronoun_i") or "tôi",
                    r.get("pronoun_you") or "bạn")
        return (self.pronoun_i or "tôi", self.pronoun_you or "bạn")

    def sync_default_pronouns(self) -> None:
        """Keep pronoun_i/pronoun_you = the default relation (back-compat)."""
        for r in self.relations or []:
            if r.get("is_default"):
                self.pronoun_i = r.get("pronoun_i") or "tôi"
                self.pronoun_you = r.get("pronoun_you") or "bạn"
                self.speaking_to = r.get("audience") or ""
                return

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
