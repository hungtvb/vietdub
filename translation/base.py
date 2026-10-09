# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
#
# Batching/JSON-validate ideas adapted from pyVideoTrans
# (https://github.com/jianchang512/pyvideotrans) by jianchang512, GPL-3.0:
#   - translator/_base.py (chunked calls, per-batch cache)
"""Common translator interface: analyze() + translate().

Edge cases handled here:
  7 - LLM returns bad JSON -> validate, retry 3x -> fallback: skip analysis,
      translate with default pronouns (toi/ban).
  8 - LLM merges/splits/drops lines -> validate count+ids, retry 3x ->
      fallback to plain translation.
 15 - provider 503/quota -> retry w/ backoff -> caller falls back to the
      next provider in the chain (Ollama, then Google free).
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Dict, List, Tuple

from project.schema import Segment, Speaker
from translation import prompts

log = logging.getLogger("vietdub.translate")

ANALYZE_RETRIES = 3
TRANSLATE_RETRIES = 3


class TranslateError(Exception):
    pass


class BaseTranslator:
    """Subclasses implement _chat(system, user) -> raw LLM text."""

    name = "base"

    def __init__(self, temperature: float = 0.2, batch_size: int = 20,
                 proper_nouns: List[str] | None = None):
        self.temperature = temperature
        self.batch_size = batch_size
        self.proper_nouns = proper_nouns or []
        # filled by analyze(): video-level metadata, also an arbiter input
        self.last_video_metadata: dict | None = None

    # -- to be implemented by providers ------------------------------------
    def _chat(self, system: str, user: str) -> str:
        raise NotImplementedError

    # -- step [4]: relationship analysis (3 layers, Tony) ---------------------
    def analyze(self, segments: List[Segment],
                speakers: Dict[int, Speaker]) -> Dict[int, Speaker]:
        """Analyze speaker relationships and LOCK one table.

        (a) BATCH: ~batch_size lines per LLM call. Each batch returns its own
            relationship table (per-line audience + per-speaker relations).
        (b) SUMMARY: all batch tables are merged into one summary (one row
            per speaker: which batches, what each assigned, line count,
            highlighted conflicts).
        (d) VIDEO METADATA: 1 LLM pass on evenly-spaced samples + a
            preliminary majority-merged table -> {genre, style, setting,
            tone_notes}. Stored on self.last_video_metadata for the caller.
        (c) ARBITER: summary + metadata + controversial sample lines go to 1
            final LLM pass -> the single LOCKED table: each speaker has a
            relations LIST [{audience, pronoun_i, pronoun_you}], one marked
            default. Falls back to deterministic majority merge.

        Sending a long film's whole transcript in one LLM prompt is
        error-prone, so step [5] receives the SAME locked table for every
        translate batch -> consistent pronouns across the whole film.
        """
        batch_data: List[tuple] = []  # (table, line_aud, counts)
        step = self.batch_size
        for b0 in range(0, len(segments), step):
            chunk = segments[b0:b0 + step]
            table, line_aud = self._analyze_batch(chunk, speakers)
            if table:
                batch_data.append((table, line_aud,
                                   Counter(s.speaker for s in chunk)))
        if not batch_data:
            # edge case 7 fallback: keep default pronouns (toi/ban)
            log.warning("phân tích quan hệ thất bại ở mọi batch, dùng đại từ "
                        "mặc định tôi/bạn")
            return speakers
        # per-line audience from the batch LLM (respect manual review edits:
        # review stop #1 may have set audience by hand -> only fill empties)
        for _, line_aud, _ in batch_data:
            for seg in segments:
                if not (seg.audience or "").strip() and seg.index in line_aud:
                    seg.audience = line_aud[seg.index]
        # (d) metadata pass needs a relationship table -> preliminary
        # deterministic merge (the arbiter may still override it below)
        prelim_table = self._merge_majority(speakers, batch_data)
        prelim = {sid: self._speaker_view(sid, speakers[sid], fields)
                  for sid, fields in prelim_table.items()}
        try:
            self.last_video_metadata = self.analyze_video_metadata(
                segments, prelim)
        except Exception as e:  # noqa: BLE001 - metadata must never break [4]
            log.warning("bỏ qua metadata video: %s", e)
            self.last_video_metadata = {"genre": "other", "style": "other",
                                        "setting": "other", "tone_notes": ""}
        if len(batch_data) == 1:
            locked = prelim_table  # nothing to arbitrate: lock directly
        else:
            log.info("trọng tài: gộp %d bảng batch thành 1 bảng khóa",
                     len(batch_data))
            locked = self._arbitrate(speakers, segments, batch_data,
                                     self.last_video_metadata)
            if not locked:
                log.warning("trọng tài thất bại, dùng gộp đa số dự phòng")
                locked = prelim_table
        self._apply_analysis(speakers, locked)
        self._post_rule_interviewee(speakers)
        return speakers

    @staticmethod
    def _speaker_view(sid: int, template: Speaker, fields: dict) -> Speaker:
        """A shallow Speaker copy with merged fields applied.

        Used for the metadata pass, which runs before the arbiter locks the
        final table (metadata needs role/pronoun info as input).
        """
        spk = Speaker(id=sid, gender=template.gender)
        spk.role = fields.get("role", "")
        spk.tone = fields.get("tone", "neutral")
        spk.relations = fields.get("relations") or []
        spk.sync_default_pronouns()
        return spk

    def _analyze_batch(self, chunk: List[Segment],
                       speakers: Dict[int, Speaker]) -> Tuple[dict, dict]:
        """One analyze LLM call for a chunk.

        Returns (table, line_aud): table = {sid: {"role", "relations", "tone"}},
        line_aud = {seg_index: audience}. ({}, {}) on persistent failure.
        """
        lines = []
        for s in chunk:
            spk = speakers.get(s.speaker)
            g = spk.gender if spk else "unknown"
            lines.append(f"[{s.index}] SPEAKER_{s.speaker} ({g}): {s.text_src}")
        user = prompts.build_analyze_user(lines)
        for attempt in range(ANALYZE_RETRIES):
            try:
                raw = self._chat(prompts.ANALYZE_SYSTEM, user)
                data = _parse_json(raw)
                # per-line audiences: prompt names the key "lines"
                # (accept "segments" too, in case the model renames it)
                seg_items = data.get("segments")
                if not isinstance(seg_items, list):
                    seg_items = data.get("lines")
                spk_items = data.get("speakers")
                if (not isinstance(seg_items, list)
                        or not isinstance(spk_items, list)):
                    raise ValueError("thiếu mảng 'segments'/'lines'/'speakers'")
                line_aud: Dict[int, str] = {}
                for it in seg_items:
                    idx = int(it["id"])
                    aud = self._norm_audience(it.get("audience"), speakers)
                    if aud:
                        line_aud[idx] = aud
                table: Dict[int, dict] = {}
                for it in spk_items:
                    sid = int(it["id"])
                    if sid not in speakers:
                        continue
                    table[sid] = self._norm_locked_fields(sid, it, speakers)
                return table, line_aud
            except (ValueError, KeyError, TypeError) as e:
                log.warning("analyze batch attempt %d/%d bad JSON: %s",
                            attempt + 1, ANALYZE_RETRIES, str(e)[:200])
        log.warning("bỏ qua 1 batch phân tích sau %d lần lỗi JSON",
                    ANALYZE_RETRIES)
        return {}, {}

    @staticmethod
    def _norm_audience(aud, speakers: Dict[int, Speaker]) -> str:
        """Normalize an audience value: 'audience' | 'all' | '<sid>' | ''."""
        a = str(aud or "").strip().lower()
        if a in ("audience", "all"):
            return a
        if a.isdigit() and int(a) in speakers:
            return a
        return ""

    @staticmethod
    def _norm_locked_fields(sid: int, it: dict,
                            speakers: Dict[int, Speaker]) -> dict:
        """Normalize one speaker entry into the locked-table format:
        {"role", "relations": [{audience, pronoun_i, pronoun_you, is_default}],
        "tone"}. Exactly one relation is marked default."""
        rels = []
        for r in it.get("relations") or []:
            if not isinstance(r, dict):
                continue
            aud = BaseTranslator._norm_audience(r.get("audience"), speakers)
            if not aud:
                continue
            rels.append({
                "audience": aud,
                "pronoun_i": str(r.get("pronoun_i", "tôi") or "tôi"),
                "pronoun_you": str(r.get("pronoun_you", "bạn") or "bạn"),
                "is_default": bool(r.get("is_default", False)),
            })
        if not rels:
            rels = [{"audience": "audience", "pronoun_i": "tôi",
                     "pronoun_you": "bạn", "is_default": True}]
        if not any(r["is_default"] for r in rels):
            rels[0]["is_default"] = True
        return {"role": str(it.get("role", "") or ""),
                "relations": rels,
                "tone": str(it.get("tone", "neutral") or "neutral")}

    def _arbitrate(self, speakers: Dict[int, Speaker],
                   segments: List[Segment],
                   batch_data: List[tuple],
                   metadata: dict | None) -> Dict[int, dict]:
        """1 final LLM pass (Tony): the arbiter reads the summary table +
        video metadata + controversial sample lines, then locks ONE
        relationship table. Returns {} on persistent failure."""
        summary = self._build_summary(speakers, segments, batch_data)
        controversial = self._controversial_lines(segments, batch_data)
        user = prompts.build_arbiter_user(summary, metadata, controversial)
        for attempt in range(ANALYZE_RETRIES):
            try:
                raw = self._chat(prompts.ARBITER_SYSTEM, user)
                data = _parse_json(raw)
                items = data.get("speakers")
                if not isinstance(items, list) or not items:
                    raise ValueError("thiếu mảng 'speakers'")
                locked: Dict[int, dict] = {}
                for it in items:
                    sid = int(it["id"])
                    if sid not in speakers:
                        continue
                    if it.get("note"):
                        log.info("trọng tài speaker %d: %s",
                                 sid, str(it["note"])[:200])
                    locked[sid] = self._norm_locked_fields(sid, it, speakers)
                # fill any speaker the arbiter dropped via majority merge
                missing = [sid for sid in speakers if sid not in locked]
                if missing:
                    fb = self._merge_majority(speakers, batch_data)
                    for sid in missing:
                        locked[sid] = fb[sid]
                return locked
            except (ValueError, KeyError, TypeError) as e:
                log.warning("arbiter attempt %d/%d bad JSON: %s",
                            attempt + 1, ANALYZE_RETRIES, str(e)[:200])
        return {}

    @staticmethod
    def _build_summary(speakers: Dict[int, Speaker],
                       segments: List[Segment],
                       batch_data: List[tuple]) -> List[str]:
        """Summary table (Tony): one row per speaker listing which batches
        it appeared in, what each batch assigned, line counts, and
        highlighted conflicts."""
        total = Counter(s.speaker for s in segments)
        out: List[str] = []
        for sid in sorted(speakers):
            batches = [i for i, (t, _, _) in enumerate(batch_data) if sid in t]
            out.append(f"SPEAKER_{sid}: appears in batches {batches} "
                       f"({total.get(sid, 0)} lines total)")
            for i, (t, _, counts) in enumerate(batch_data):
                f = t.get(sid)
                if not f:
                    continue
                rels = "; ".join(
                    f"to '{r['audience']}': {r['pronoun_i']}/{r['pronoun_you']}"
                    + (" (default)" if r["is_default"] else "")
                    for r in f.get("relations") or [])
                out.append(
                    f"  batch {i} ({counts.get(sid, 0)} lines): "
                    f"role=\"{f.get('role')}\", {rels or 'no relations'}, "
                    f"tone={f.get('tone')}")
            pairs = {(r["audience"], r["pronoun_i"], r["pronoun_you"])
                     for t, _, _ in batch_data
                     for r in (t.get(sid) or {}).get("relations") or []}
            if len(pairs) > 1:
                out.append(f"  !! CONFLICT: {sorted(pairs)}")
        return out

    @staticmethod
    def _controversial_lines(segments: List[Segment],
                             batch_data: List[tuple],
                             limit: int = 8) -> List[str]:
        """Sample original lines from speakers whose batches disagreed -
        evidence for the arbiter. Falls back to one line per speaker."""
        sids = set()
        for t, _, _ in batch_data:
            sids |= set(t)
        conflicting = set()
        for sid in sorted(sids):
            pairs = {(r["audience"], r["pronoun_i"], r["pronoun_you"])
                     for t, _, _ in batch_data
                     for r in (t.get(sid) or {}).get("relations") or []}
            if len(pairs) > 1:
                conflicting.add(sid)
        lines: List[str] = []
        for s in segments:
            if s.speaker in conflicting and len(lines) < limit:
                lines.append(f"[{s.index}] SPEAKER_{s.speaker}: {s.text_src}")
        if not lines:
            seen = set()
            for s in segments:
                if s.speaker not in seen and len(lines) < 4:
                    seen.add(s.speaker)
                    lines.append(
                        f"[{s.index}] SPEAKER_{s.speaker}: {s.text_src}")
        return lines

    @staticmethod
    def _merge_majority(speakers: Dict[int, Speaker],
                        batch_data: List[tuple]) -> Dict[int, dict]:
        """Deterministic fallback: per speaker, per-audience majority vote
        on the pronoun pair; role/tone by majority; the default relation is
        the audience that won the most is_default votes."""
        merged: Dict[int, dict] = {}
        for sid in speakers:
            votes = [t[sid] for t, _, _ in batch_data if sid in t]
            if not votes:
                merged[sid] = {"role": "", "tone": "neutral", "relations": [
                    {"audience": "audience", "pronoun_i": "tôi",
                     "pronoun_you": "bạn", "is_default": True}]}
                continue
            aud_votes: Dict[str, List[dict]] = {}
            def_aud_votes: List[str] = []
            for v in votes:
                for r in v.get("relations") or []:
                    aud_votes.setdefault(r["audience"], []).append(r)
                    if r.get("is_default"):
                        def_aud_votes.append(r["audience"])
            default_aud = (Counter(def_aud_votes).most_common(1)[0][0]
                           if def_aud_votes else "audience")
            relations = []
            for aud, rs in aud_votes.items():
                (pi, py) = Counter(
                    (r["pronoun_i"], r["pronoun_you"])
                    for r in rs).most_common(1)[0][0]
                relations.append({"audience": aud, "pronoun_i": pi,
                                  "pronoun_you": py,
                                  "is_default": aud == default_aud})
            if not any(r["is_default"] for r in relations):
                relations[0]["is_default"] = True
            role = Counter(v["role"] for v in votes if v.get("role"))
            tone = Counter(v["tone"] for v in votes if v.get("tone"))
            merged[sid] = {
                "role": role.most_common(1)[0][0] if role else "",
                "tone": tone.most_common(1)[0][0] if tone else "neutral",
                "relations": relations,
            }
        return merged

    def _apply_analysis(self, speakers: Dict[int, Speaker],
                        locked: Dict[int, dict]) -> Dict[int, Speaker]:
        """Write the locked table into Speaker objects (relations model).

        Accepts the relations format; tolerates the legacy flat format
        (pronoun_i/pronoun_you/speaking_to fields) from older checkpoints.
        """
        for sid, fields in locked.items():
            spk = speakers.get(sid)
            if spk is None:
                continue
            spk.role = str(fields.get("role", "") or "")
            spk.tone = str(fields.get("tone", "neutral") or "neutral")
            rels = fields.get("relations")
            if isinstance(rels, list) and rels:
                clean = [dict(r) for r in rels if isinstance(r, dict)]
                if not any(r.get("is_default") for r in clean):
                    clean[0]["is_default"] = True
            else:  # legacy flat table -> single default relation
                pi = str(fields.get("pronoun_i", "tôi") or "tôi")
                py = str(fields.get("pronoun_you", "bạn") or "bạn")
                aud = fields.get("speaking_to") or "audience"
                clean = [{"audience": aud, "pronoun_i": pi,
                          "pronoun_you": py, "is_default": True}]
            spk.relations = clean
            spk.sync_default_pronouns()
        return speakers

    # Matches roles that present news to an audience.
    _REPORTER_RE = re.compile(
        r"reporter|anchor|\bhost\b|journalist|phóng viên|người dẫn|"
        r"biên tập|narrator|người đọc", re.I)

    def _post_rule_interviewee(self, speakers: Dict[int, Speaker]) -> None:
        """Deterministic post-rule (always logged when it fires).

        In a news program (signature: a reporter/anchor/narrator whose
        *audience* relation is tôi/quý vị), a non-presenter speaker stuck on
        the generic fallback pair tôi/bạn gets the conventional Vietnamese
        dubbing address "anh" on the default relation. Guards against the
        LLM taking the lazy "safe default" exit (seen 3/3 runs on video 01:
        interviewee -> tôi/bạn instead of tôi/anh). The reviewer can still
        correct it at review stop #1.
        """
        def audience_pair(spk: Speaker, aud: str):
            for r in spk.relations or []:
                if r.get("audience") == aud:
                    return (r.get("pronoun_i"), r.get("pronoun_you"))
            return (None, None)

        reporter = None
        for sid, s in speakers.items():
            pi, py = audience_pair(s, "audience")
            if (pi, py) == ("tôi", "quý vị") and self._REPORTER_RE.search(
                    s.role or ""):
                reporter = sid
                break
        if reporter is None:
            return
        for sid, s in speakers.items():
            if sid == reporter or self._REPORTER_RE.search(s.role or ""):
                continue
            d = next((r for r in s.relations or [] if r.get("is_default")),
                     None)
            if d and (d.get("pronoun_i"), d.get("pronoun_you")) == (
                    "tôi", "bạn"):
                log.warning(
                    "quy tắc hậu kiểm: speaker %d (%s) trong chương trình tin "
                    "tức rớt về 'bạn' mặc định -> sửa default pronoun_you="
                    "'anh' (quy ước lồng tiếng; sửa tay ở màn duyệt nếu cần)",
                    sid, (s.role or "")[:40])
                d["pronoun_you"] = "anh"
                s.sync_default_pronouns()

    # -- step [4b]: video-level metadata (1 LLM pass, Tony) ------------------
    @staticmethod
    def _sample_for_metadata(segments: List[Segment]) -> List[Segment]:
        """Even sampling across the whole video (Tony): short video
        (<5 minutes or <=100 lines) -> all lines; otherwise 10
        evenly-spaced chunks x 10 lines, capped ~8000 chars."""
        n = len(segments)
        dur = max((s.end or 0.0) for s in segments) if segments else 0.0
        if n <= 100 or dur < 300:
            sample = list(segments)
        else:
            chunks, per = 10, 10
            starts = [round(i * (n - per) / (chunks - 1))
                      for i in range(chunks)]
            sample = [s for st in starts for s in segments[st:st + per]]
        chars = sum(len(s.text_src or "") for s in sample)
        if chars > 8000:
            step = max(2, chars // 8000)
            sample = sample[::step]
        return sample

    def analyze_video_metadata(self, segments: List[Segment],
                               speakers: Dict[int, Speaker]) -> dict:
        """Infer overall video metadata from evenly-spaced samples + the
        (preliminary) relationship table. Called inside analyze() BEFORE the
        arbiter pass, because the metadata is an arbiter input. Returns
        {genre, style, setting, tone_notes}; defaults (all 'other') on
        persistent failure - never raises."""
        sample = self._sample_for_metadata(segments)
        sample_lines = [f"[{s.index}] SPEAKER_{s.speaker}: {s.text_src}"
                        for s in sample]
        rel_lines = [
            f"SPEAKER_{sid}: gender={spk.gender}, role={spk.role}, "
            f"speaking_to={spk.speaking_to}, "
            f"pronoun_i={spk.pronoun_i}, pronoun_you={spk.pronoun_you}"
            for sid, spk in sorted(speakers.items())]
        cnt = Counter(s.speaker for s in segments)
        dist = ", ".join(f"SPEAKER_{sid} ({speakers[sid].role or 'unknown'}): "
                         f"{c} lines" for sid, c in sorted(cnt.items())
                         if sid in speakers)
        user = prompts.build_video_meta_user(sample_lines, rel_lines, dist)
        for attempt in range(ANALYZE_RETRIES):
            try:
                data = _parse_json(self._chat(prompts.VIDEO_META_SYSTEM,
                                              user))
                meta = {"genre": str(data.get("genre", "other") or "other"),
                        "style": str(data.get("style", "other") or "other"),
                        "setting": str(data.get("setting", "other")
                                       or "other"),
                        "tone_notes": str(data.get("tone_notes", "") or "")}
                log.info("metadata video: %s/%s/%s", meta["genre"],
                         meta["style"], meta["setting"])
                return meta
            except (ValueError, KeyError, TypeError) as e:
                log.warning("video metadata attempt %d/%d bad JSON: %s",
                            attempt + 1, ANALYZE_RETRIES, str(e)[:200])
        log.warning("không suy được metadata video, dùng mặc định 'other'")
        return {"genre": "other", "style": "other", "setting": "other",
                "tone_notes": ""}

    # -- step [5]: translation ----------------------------------------------
    def translate(self, segments: List[Segment],
                  speakers: Dict[int, Speaker],
                  video_metadata: dict | None = None) -> List[Segment]:
        rel_table = []
        for sid in sorted(speakers):
            spk = speakers[sid]
            rels = "; ".join(
                f"to '{r.get('audience')}': "
                f"{r.get('pronoun_i')}/{r.get('pronoun_you')}"
                + (" (default)" if r.get("is_default") else "")
                for r in spk.relations or [])
            rel_table.append(
                f"SPEAKER_{sid}: gender={spk.gender}, role={spk.role}, "
                f"{rels or 'toi/ban (default)'}, tone={spk.tone}")
        system = prompts.translate_system_with_names(self.proper_nouns,
                                                      video_metadata)

        # batch with 2-line overlap context so pronouns stay consistent;
        # context goes in its own clearly-marked section (never translated)
        out: Dict[int, str] = {}
        n = len(segments)
        step = self.batch_size
        for b0 in range(0, n, step):
            chunk = segments[b0:b0 + step]
            ctx0 = max(0, b0 - 2)
            ctx_lines = [f"[{s.index}] {self._line_header(s)}: {s.text_src}"
                         for s in segments[ctx0:b0]]
            lines = [f"[{s.index}] {self._line_header(s)} "
                     f"{s.start:.1f}-{s.end:.1f}s: {s.text_src}" for s in chunk]
            user = prompts.build_translate_user(rel_table, lines,
                                                self.proper_nouns,
                                                ctx_lines or None)
            got = self._translate_batch(system, user, chunk)
            out.update(got)

        missing = [s.index for s in segments if s.index not in out]
        if missing:
            # edge case 8 fallback: translate missing lines one-by-one, plain
            log.warning("%d câu bị thiếu sau dịch batch, dịch lẻ bù: %s",
                        len(missing), missing[:10])
            for s in segments:
                if s.index in out:
                    continue
                out[s.index] = self._translate_single(system, rel_table, s)

        for s in segments:
            s.text_vi = out.get(s.index, s.text_src)
        # validate: số câu ra phải == số câu vào; câu nào rớt đại từ so với
        # bảng khóa thì đánh dấu để Tony duyệt tay ở điểm dừng #2
        empty = [s.index for s in segments if not (s.text_vi or "").strip()]
        if empty:
            log.warning("dịch xong vẫn có %d câu text_vi rỗng: %s",
                        len(empty), empty[:10])
        self._flag_missing_pronouns(segments, speakers)
        return segments

    @staticmethod
    def _line_header(seg: Segment) -> str:
        """'SPEAKER_0 (to SPEAKER_1)' / 'SPEAKER_0 (to AUDIENCE)' / ..."""
        h = f"SPEAKER_{seg.speaker}"
        aud = (seg.audience or "").strip()
        if aud == "audience":
            h += " (to AUDIENCE)"
        elif aud == "all":
            h += " (to ALL)"
        elif aud.isdigit():
            h += f" (to SPEAKER_{aud})"
        return h

    @staticmethod
    def _pronoun_hit(text: str, pronoun: str) -> bool:
        """Word-boundary match (tránh 'anh' khớp nhầm trong 'thành phố';
        không phân biệt hoa/thường vì đầu câu thường viết hoa)."""
        if not pronoun:
            return False
        return re.search(r"(?<!\w)" + re.escape(pronoun) + r"(?!\w)",
                         text or "", re.IGNORECASE) is not None

    # Chinese first/second-person markers: if the source has one, the
    # translation is expected to carry the locked pronouns.
    _SRC_PERSON_RE = re.compile(r"[我你您咱]|大家|各位|观众|朋友们")

    def _flag_missing_pronouns(self, segments: List[Segment],
                               speakers: Dict[int, Speaker]) -> None:
        """Flag lines that lost pronouns in translation.

        Per line: if the SOURCE contains a person marker (我/你/您/咱/
        大家/各位...) but the translation has neither locked pronoun for
        that (speaker, audience) pair -> mark needs_review=True (hiện vàng
        ở màn duyệt #2). Narration lines without person markers are never
        flagged (avoids noise on news scripts). The generic fallback pair
        (tôi/bạn) is skipped: too uncertain to flag.
        """
        for s in segments:
            spk = speakers.get(s.speaker)
            if spk is None:
                continue
            if not self._SRC_PERSON_RE.search(s.text_src or ""):
                continue
            pi, py = spk.get_pronouns((s.audience or "").strip())
            if (pi, py) == ("tôi", "bạn"):
                continue  # cặp fallback chung: không chắc nên không đánh dấu
            if self._pronoun_hit(s.text_vi, pi) or \
                    self._pronoun_hit(s.text_vi, py):
                continue
            log.warning("câu %d (spk%d->'%s'): nguồn có đại từ nhân xưng "
                        "nhưng bản dịch thiếu cặp đã khóa (%s/%s) -> đánh "
                        "dấu needs_review",
                        s.index, s.speaker, s.audience or "?", pi, py)
            s.needs_review = True

    def _translate_batch(self, system: str, user: str,
                         chunk: List[Segment]) -> Dict[int, str]:
        want_ids = [s.index for s in chunk]
        last_err = ""
        for attempt in range(TRANSLATE_RETRIES):
            try:
                raw = self._chat(system, user)
                data = _parse_json(raw)
                items = data.get("translations")
                if not isinstance(items, list):
                    raise ValueError("thiếu mảng 'translations'")
                got = {int(it["id"]): str(it["text_vi"]) for it in items}
                if sorted(got.keys()) != sorted(want_ids):
                    raise ValueError(
                        f"số câu/id không khớp (muốn {want_ids}, được "
                        f"{sorted(got.keys())})")
                return got
            except (ValueError, KeyError, TypeError) as e:
                last_err = str(e)
                log.warning("translate batch attempt %d/%d lỗi: %s",
                            attempt + 1, TRANSLATE_RETRIES, last_err[:200])
        log.warning("batch dịch thất bại sau %d lần (%s), dịch lẻ từng câu",
                    TRANSLATE_RETRIES, last_err[:120])
        return {}

    def _translate_single(self, system: str, rel_table: List[str],
                          seg: Segment) -> str:
        user = prompts.build_translate_user(
            rel_table,
            [f"[{seg.index}] {self._line_header(seg)}: {seg.text_src}"],
            self.proper_nouns)
        for _ in range(2):
            try:
                data = _parse_json(self._chat(system, user))
                items = data.get("translations") or []
                if items:
                    return str(items[0].get("text_vi", seg.text_src))
            except (ValueError, KeyError, TypeError):
                continue
        return seg.text_src  # last resort: keep source text


def _parse_json(raw: str) -> dict:
    """Extract JSON from LLM output (tolerates code fences / prose)."""
    text = (raw or "").strip()
    if text.startswith("```"):
        # strip ```json ... ```
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("không tìm thấy JSON trong output LLM")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON sai format: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON root không phải object")
    return data


def google_translate_free(texts: List[str], src: str = "zh-CN",
                          dst: str = "vi") -> List[str]:
    """Last-resort fallback (edge case 15): free Google endpoint, no key.

    Warns about quality: pronoun handling is worse than the LLM providers.
    Per-sentence errors keep the source text - a line is never dropped.
    """
    import requests
    log.warning("dùng Google Translate free (dự phòng) - chất lượng đại từ "
                "có thể kém hơn bản LLM")
    out: List[str] = []
    url = "https://translate.googleapis.com/translate_a/single"
    for t in texts:
        try:
            r = requests.get(url, params={"client": "gtx", "sl": src, "tl": dst,
                                          "dt": "t", "q": t}, timeout=20)
            r.raise_for_status()
            data = r.json()
            out.append("".join(s[0] for s in data[0] if s[0]))
        except Exception as e:  # noqa: BLE001
            log.warning("Google free lỗi cho câu %r: %s", t[:40], e)
            out.append(t)  # keep source rather than dropping the line
    return out


def translate_with_fallback(providers: List[BaseTranslator],
                            segments: List[Segment],
                            speakers: Dict[int, Speaker],
                            skip_analyze: bool = False,
                            use_google_free: bool = True,
                            video_metadata: dict | None = None
                            ) -> Tuple[List[Segment], str]:
    """Try providers in order (edge case 15 chain). Returns (segments, used_name).

    skip_analyze: speakers were already analyzed in step [4] (checkpoint
        exists) - do NOT call analyze() a second time, translate directly.
    use_google_free: when every LLM provider fails, last resort is Google
        Translate free (direct per-sentence, pronoun quality may be worse).
    """
    last_err: Exception | None = None
    for prov in providers:
        try:
            log.info("dịch bằng provider: %s", prov.name)
            if not skip_analyze:
                speakers = prov.analyze(segments, speakers)
                # analyze() also ran the video-metadata pass (arbiter input);
                # reuse it instead of calling the LLM a second time
                video_metadata = (
                    getattr(prov, "last_video_metadata", None)
                    or video_metadata)
            else:
                log.info("dùng kết quả phân tích đã lưu, bỏ qua analyze (%s)",
                         prov.name)
            segments = prov.translate(segments, speakers,
                                      video_metadata=video_metadata)
            return segments, prov.name
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("provider %s lỗi, thử provider tiếp: %s", prov.name, e)
    if use_google_free and segments:
        log.warning("tất cả nguồn LLM đều lỗi, dùng Google Translate free "
                    "(dự phòng cuối): chất lượng đại từ có thể kém, nên "
                    "duyệt lại bản dịch ở bước [5]")
        vi = google_translate_free([s.text_src for s in segments])
        for s, t in zip(segments, vi):
            s.text_vi = (t or "").strip() or s.text_src
        return segments, "google_free"
    raise TranslateError(
        "Tất cả nguồn dịch đều lỗi (kể cả Google Translate free).\n"
        "Cách khắc phục: kiểm tra mạng / API key 9Router / Ollama đang chạy, "
        "rồi chạy lại.") from last_err
