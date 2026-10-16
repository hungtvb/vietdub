"""Speaker Verification V2: human-reviewed per-job, per-line character IDs.

Pyannote clusters and speaker embeddings can propose, never approve, a
character. Both audio and source video must be explicitly reviewed for any
verified anchor or utterance. This module has no external paid dependencies.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import re

from core import checkpoint as cp
from project.schema import Segment

STEP = "speaker_verification"
SCHEMA_VERSION = 2


def line_key(seg: Segment) -> str:
    """Fingerprint reviewed content/times; changed/split text invalidates it."""
    base_speaker = (seg.detected_speaker if seg.detected_speaker is not None
                    else seg.speaker)
    payload = [int(seg.index), round(float(seg.start), 3),
               round(float(seg.end), 3), seg.text_src or "", int(base_speaker)]
    return sha256(json.dumps(payload, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def audio_fingerprint(path: str | Path) -> str:
    """Stream the FULL original audio SHA256; never reuse decisions on a changed source."""
    h = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _name(name: str) -> str:
    value = re.sub(r"\s+", " ", (name or "").strip())
    if not value or len(value) > 100 or any(ord(c) < 32 for c in value):
        raise ValueError("Tên nhân vật phải dài 1–100 ký tự, không có ký tự điều khiển")
    return value


def clear_identity(seg: Segment) -> None:
    """Undo canonical voice remap when source evidence is edited or revoked."""
    if seg.identity_status == "VERIFIED" and seg.detected_speaker is not None:
        seg.speaker = seg.detected_speaker
    seg.character_id = ""
    seg.character_name = ""
    seg.identity_status = "UNVERIFIED"
    seg.needs_review = True


class SpeakerVerification:
    """Independent per-job review state; *never* auto-approves a whole cluster."""

    def __init__(self, job_dir, segments, wav_path, manifest=None):
        self.job_dir = Path(job_dir)
        self.segments = list(segments)
        self.audio_identity = audio_fingerprint(wav_path)
        self.manifest = manifest or {"candidates": [], "clusters": []}
        self.candidates = {
            str(c["candidate_id"]): c for c in self.manifest.get("candidates", [])
            if isinstance(c, dict) and c.get("candidate_id")
        }
        prior = cp.load_step(self.job_dir, STEP)
        if prior is not None:
            if prior.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("Speaker Verification checkpoint khác version")
            if prior.get("audio_fingerprint") != self.audio_identity:
                raise ValueError("Audio nguồn đã thay đổi; không dùng lại xác minh cũ")
            self.state = prior
        else:
            self.state = {
                "schema_version": SCHEMA_VERSION,
                "audio_fingerprint": self.audio_identity,
                "status": "PARTIAL_REVIEW", "characters": {},
                "anchor_decisions": {}, "line_decisions": {},
                "review_events": [], "translation_approved": False,
            }
        IDs = [c.get("speaker_id") for c in self.characters.values()]
        if any(not isinstance(i, int) or i < 0 for i in IDs) or len(IDs) != len(set(IDs)):
            raise ValueError("Dữ liệu speaker ID đã duyệt không hợp lệ")

    @property
    def characters(self):
        return self.state["characters"]

    @property
    def anchor_decisions(self):
        return self.state["anchor_decisions"]

    @property
    def line_decisions(self):
        return self.state["line_decisions"]

    def _event(self, kind, target, char_id=""):
        actions = self.state["review_events"]
        actions.append({"sequence": len(actions) + 1, "kind": kind,
                        "target": target, "character_id": char_id,
                        "actor": "human_review_in_app"})

    def ensure_character(self, name: str) -> str:
        name = _name(name)
        for key, char in self.characters.items():
            if char["name"].casefold() == name.casefold():
                return key
        counter = 1
        while f"CHAR_{counter:03d}" in self.characters:
            counter += 1
        occupied = {s.speaker for s in self.segments}
        occupied.update(s.detected_speaker for s in self.segments
                        if s.detected_speaker is not None)
        occupied.update(c["speaker_id"] for c in self.characters.values())
        key = f"CHAR_{counter:03d}"
        self.characters[key] = {"name": name, "speaker_id": max(occupied | {-1}) + 1}
        self._event("CREATE_CHARACTER", key, key)
        return key

    @staticmethod
    def _require_confirmed(heard_audio, checked_video):
        if not heard_audio or not checked_video:
            raise ValueError("Cần xác nhận đã nghe audio GỐC và đối chiếu cảnh phim")

    def verify_anchor(self, candidate_id, character_name, *,
                      heard_audio, checked_video, note=""):
        self._require_confirmed(heard_audio, checked_video)
        item = self.candidates.get(candidate_id)
        if item is None:
            raise KeyError(f"Mẫu giọng không thuộc video này: {candidate_id}")
        char_id = self.ensure_character(character_name)
        self.anchor_decisions[candidate_id] = {
            "status": "VERIFIED_CLIP_ONLY",
            "character_id": char_id,
            "cluster": item.get("cluster", ""),
            "start": item.get("start"), "end": item.get("end"),
            "note": str(note or "").strip()[:500],
            "evidence": "HUMAN_AUDIO_AND_VIDEO_REVIEW",
            "cluster_wide_approval": False,
        }
        self._event("VERIFY_ANCHOR", candidate_id, char_id)
        return char_id

    def revoke_anchor(self, candidate_id):
        if candidate_id in self.anchor_decisions:
            del self.anchor_decisions[candidate_id]
            self._event("REVOKE_ANCHOR", candidate_id)

    def _line(self, index):
        for seg in self.segments:
            if seg.index == index:
                return seg
        raise KeyError(f"Không có câu {index} trong video này")

    def verify_line(self, index, character_name, *,
                    heard_audio, checked_video, note=""):
        self._require_confirmed(heard_audio, checked_video)
        seg = self._line(index)
        key = line_key(seg)
        char_id = self.ensure_character(character_name)
        self.line_decisions[key] = {
            "status": "VERIFIED_LINE_ONLY",
            "character_id": char_id,
            "index_at_review": seg.index,
            "original_speaker": (
                seg.detected_speaker if seg.detected_speaker is not None else seg.speaker),
            "start": round(seg.start, 3), "end": round(seg.end, 3),
            "note": str(note or "").strip()[:500],
            "evidence": "HUMAN_AUDIO_AND_VIDEO_REVIEW",
        }
        self._event("VERIFY_LINE", key, char_id)
        self.apply_verified_lines()
        return char_id

    def revoke_line(self, index):
        seg = self._line(index)
        key = line_key(seg)
        if key in self.line_decisions:
            del self.line_decisions[key]
            self._event("REVOKE_LINE", key)
        clear_identity(seg)

    def apply_verified_lines(self):
        confirmed = 0
        for seg in self.segments:
            decision = self.line_decisions.get(line_key(seg))
            if not decision or decision.get("status") != "VERIFIED_LINE_ONLY":
                if seg.identity_status == "VERIFIED":
                    clear_identity(seg)
                continue
            char = self.characters.get(decision.get("character_id"))
            if char is None:
                clear_identity(seg)
                continue
            if seg.detected_speaker is None:
                seg.detected_speaker = int(decision["original_speaker"])
            seg.speaker = int(char["speaker_id"])
            seg.character_id = decision["character_id"]
            seg.character_name = char["name"]
            seg.identity_status = "VERIFIED"
            # Do not clear independent ASR/translation QA flags.
            confirmed += 1
        return {"verified_lines": confirmed,
                "remaining_lines": len(self.segments) - confirmed,
                "verified_anchors": len(self.anchor_decisions),
                "all_lines_verified": confirmed == len(self.segments)}

    def suggest(self, index):
        """Candidates verified at the SAME time; no global cluster inference."""
        seg = self._line(index)
        refs = []
        for candidate_id, item in self.candidates.items():
            dec = self.anchor_decisions.get(candidate_id)
            if not dec or dec.get("status") != "VERIFIED_CLIP_ONLY":
                continue
            referenced = seg.index in (item.get("source_asr_ids") or [])
            overlap = max(0., min(seg.end, float(item["end"])) -
                          max(seg.start, float(item["start"])))
            if referenced or overlap >= .2:
                refs.append((candidate_id, dec["character_id"]))
        character_ids = {char for _, char in refs}
        if len(character_ids) > 1:
            return {"status": "CONFLICT", "character_name": "",
                    "evidence_clips": [r[0] for r in refs],
                    "requires_explicit_line_confirmation": True}
        if len(character_ids) == 1:
            char_id = next(iter(character_ids))
            return {"status": "SUGGESTION_ONLY",
                    "character_id": char_id,
                    "character_name": self.characters[char_id]["name"],
                    "evidence_clips": [r[0] for r in refs],
                    "requires_explicit_line_confirmation": True}
        return {"status": "NO_DIRECT_REFERENCE", "character_name": "",
                "evidence_clips": [],
                "requires_explicit_line_confirmation": True}

    def summary(self):
        report = self.apply_verified_lines()
        report.update(characters=len(self.characters),
                      project_scoped=True,
                      translation_approved=False)
        return report

    def save(self):
        self.apply_verified_lines()
        self.state["status"] = "PARTIAL_REVIEW"
        self.state["translation_approved"] = False
        return cp.save_step(self.job_dir, STEP, self.state)
