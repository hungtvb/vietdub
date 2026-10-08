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

    # -- to be implemented by providers ------------------------------------
    def _chat(self, system: str, user: str) -> str:
        raise NotImplementedError

    # -- step [4]: relationship analysis -----------------------------------
    def analyze(self, segments: List[Segment],
                speakers: Dict[int, Speaker]) -> Dict[int, Speaker]:
        lines = []
        for s in segments:
            spk = speakers.get(s.speaker)
            g = spk.gender if spk else "unknown"
            lines.append(f"[{s.index}] SPEAKER_{s.speaker} ({g}) "
                         f"{s.start:.1f}s: {s.text_src}")
        user = prompts.build_analyze_user(lines)
        last_err = ""
        for attempt in range(ANALYZE_RETRIES):
            try:
                raw = self._chat(prompts.ANALYZE_SYSTEM, user)
                data = _parse_json(raw)
                return self._apply_analysis(speakers, data)
            except (ValueError, KeyError, TypeError) as e:
                last_err = str(e)
                log.warning("analyze attempt %d/%d bad JSON: %s",
                            attempt + 1, ANALYZE_RETRIES, last_err[:200])
        # edge case 7 fallback: keep default pronouns (toi/ban)
        log.warning("phân tích quan hệ thất bại sau %d lần, dùng đại từ mặc định "
                    "tôi/bạn (%s)", ANALYZE_RETRIES, last_err[:120])
        return speakers

    def _apply_analysis(self, speakers: Dict[int, Speaker], data: dict) -> Dict[int, Speaker]:
        items = data.get("speakers")
        if not isinstance(items, list) or not items:
            raise ValueError("thiếu mảng 'speakers'")
        for it in items:
            sid = int(it["id"])
            spk = speakers.get(sid)
            if spk is None:
                continue
            spk.role = str(it.get("role", ""))
            spk.speaking_to = str(it.get("speaking_to", ""))
            spk.pronoun_i = str(it.get("pronoun_i", "tôi") or "tôi")
            spk.pronoun_you = str(it.get("pronoun_you", "bạn") or "bạn")
            spk.tone = str(it.get("tone", "neutral"))
        return speakers

    # -- step [5]: translation ----------------------------------------------
    def translate(self, segments: List[Segment],
                  speakers: Dict[int, Speaker]) -> List[Segment]:
        rel_table = []
        for sid in sorted(speakers):
            spk = speakers[sid]
            rel_table.append(
                f"SPEAKER_{sid}: gender={spk.gender}, role={spk.role}, "
                f"speaking_to={spk.speaking_to}, "
                f"pronoun_i={spk.pronoun_i}, pronoun_you={spk.pronoun_you}")
        system = prompts.translate_system_with_names(self.proper_nouns)

        # batch with 2-line overlap context so pronouns stay consistent
        out: Dict[int, str] = {}
        n = len(segments)
        step = self.batch_size
        for b0 in range(0, n, step):
            chunk = segments[b0:b0 + step]
            ctx0 = max(0, b0 - 2)
            ctx_lines = [f"[{s.index}] SPEAKER_{s.speaker}: {s.text_src}"
                         for s in segments[ctx0:b0]]
            lines = [f"[{s.index}] SPEAKER_{s.speaker} "
                     f"{s.start:.1f}-{s.end:.1f}s: {s.text_src}" for s in chunk]
            if ctx_lines:
                lines = ["(context) " + l for l in ctx_lines] + lines
            user = prompts.build_translate_user(rel_table, lines, self.proper_nouns)
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
        return segments

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
            [f"[{seg.index}] SPEAKER_{seg.speaker}: {seg.text_src}"],
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
                            use_google_free: bool = True
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
            else:
                log.info("dùng kết quả phân tích đã lưu, bỏ qua analyze (%s)",
                         prov.name)
            segments = prov.translate(segments, speakers)
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
