"""Strict real-LLM analysis + translation bridge for Chinese E2E tests.

Reuses the EXISTING BaseTranslator analyze/translate pipeline and provider.
No MarianMT, Google fallback, invented role approval, or synthetic responses.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from project.schema import Speaker

def _fingerprint(segments):
    payload = [{"id": s.index, "speaker": s.speaker, "start": s.start,
                "end": s.end, "zh": s.text_src} for s in segments]
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

def analyze_and_translate(segments, provider):
    """Execute both existing LLM steps, failing closed on silent fallbacks.

    Works with an authenticated NineRouterTranslator or locally configured
    OllamaTranslator. Markers count REAL calls to provider._chat, even when its
    high-level methods retry JSON parsing. No provider is silently substituted.
    """
    if not segments or [s.index for s in segments] != list(range(len(segments))):
        raise ValueError("Nonempty consecutively indexed Chinese dialogue required")
    from translation import prompts
    speakers = {}
    for s in segments:
        speakers.setdefault(s.speaker, Speaker(
            id=s.speaker, gender=(s.gender if s.gender in ("male","female") else ""),
            identity_verified=False))
    counters = Counter()
    original_chat = provider._chat
    def monitored_chat(system, user):
        if system == prompts.ANALYZE_SYSTEM:
            phase = "analyze"
        elif system == prompts.VIDEO_META_SYSTEM:
            phase = "video_metadata"
        elif system == prompts.ARBITER_SYSTEM:
            phase = "arbiter"
        elif system.startswith(prompts.TRANSLATE_SYSTEM):
            phase = "translate"
        else:
            phase = "other"
        response = original_chat(system, user)
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError("LLM returned an empty response")
        counters[phase] += 1
        return response
    provider._chat = monitored_chat
    try:
        provider.analyze(segments, speakers)
        if not counters["analyze"]:
            raise RuntimeError("LLM speaker/relationship analyze was not executed")
        if not any(sp.role.strip() and sp.relations for sp in speakers.values()):
            raise RuntimeError("LLM analyze returned no usable speaker relationship")
        meta = provider.last_video_metadata or {}
        meta.update(source_language="zh", language_review_required=True)
        # The translated dialogue shares the EXACT analyzed segments:
        # line audiences and locked speaker relationship table are preserved.
        translated = provider.translate(segments, speakers, video_metadata=meta)
        if translated is not segments:
            raise RuntimeError("Translator replaced analyzed source segment objects")
        if not counters["translate"]:
            raise RuntimeError("LLM translation never executed")
        invalid = [s.index for s in segments
                   if not isinstance(s.text_vi, str) or not s.text_vi.strip()
                   or s.text_vi.strip() == s.text_src.strip()]
        if invalid:
            raise RuntimeError(f"LLM untranslated/missing lines: {invalid}")
        for seg in segments:
            seg.needs_review = True
        return {
            "provider": provider.name,
            "model": str(getattr(provider, "model", "unknown")),
            "method": "existing_BaseTranslator_analyze_then_translate",
            "human_approved": False,
            "source_transcript_sha256": _fingerprint(segments),
            "llm_call_counts": dict(counters),
            "video_context": meta,
            "speakers": [s.to_dict() for s in speakers.values()],
            "analyzed_audience_count": sum(bool(s.audience) for s in segments),
            "translated_line_count": len(segments),
            "untranslated_line_ids": [],
            "quality_human_verified": False
        }
    finally:
        provider._chat = original_chat


def chinese_translation_flags(segments):
    """Cheap review warnings, not an independent semantic-accuracy score."""
    terminology = (
        ("亚洲杯", ("asian cup", "cúp châu á")),
        ("中国女足", ("đội tuyển nữ trung quốc", "bóng đá nữ trung quốc",
                  "đội tuyển bóng đá nữ trung quốc")),
        ("冠军", ("vô địch", "quán quân")),
        ("追赶", ("bắt kịp", "đuổi kịp", "theo kịp")),
    )
    flags = []
    for seg in segments:
        issues = []
        lower = seg.text_vi.casefold()
        if any("\u3400" <= ch <= "\u9fff" for ch in seg.text_vi):
            issues.append("CJK_REMAINS_IN_VI")
        for src, choices in terminology:
            if src in seg.text_src and not any(t in lower for t in choices):
                issues.append("MISSING_TRANSLATION_TERM:" + src)
        if issues:
            flags.append({"id": seg.index, "reasons": issues,
                          "source_zh": seg.text_src,
                          "draft_vi": seg.text_vi})
    return {"review_required": True, "flagged_line_count": len(flags),
            "issues": flags, "is_ground_truth_score": False}


def revise_flagged_lines(segments, provider, max_attempts=2):
    """Ask the SAME authorized LLM provider to correct concrete QA failures.

    A revision is not human verification or an independent translation score.
    Preserve source IDs and source text; reject invalid JSON, introduced Hanzi,
    missing glossary equivalents and unrequested outputs.
    """
    from translation.base import _parse_json
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    changes = []
    attempts = 0
    for _ in range(max_attempts):
        pending = chinese_translation_flags(segments)["issues"]
        if not pending:
            break
        requested = [item["id"] for item in pending]
        context = []
        for item in pending:
            i = next(i for i, s in enumerate(segments) if s.index == item["id"])
            context.append({
                "id": item["id"], "errors": item["reasons"],
                "surrounding_dialogue": [
                    {"id": s.index, "zh": s.text_src, "vi_draft": s.text_vi}
                    for s in segments[max(0,i-2):min(len(segments),i+3)]
                ]})
        prompt = json.dumps({"requested_ids": requested,
                             "review_items": context}, ensure_ascii=False)
        system = (
            "You are repairing Chinese-to-Vietnamese video dubbing translations. "
            "Use the Chinese source and neighboring dialogue to correct ONLY the "
            "requested Vietnamese lines. Translate EVERY Chinese character and "
            "preserve ALL meaning, factual team/tournament names and fluency. "
            "Asian Cup 亚洲杯 is Cúp châu Á, NOT a Southeast Asian tournament; "
            "中国女足 is the Chinese women's football team; "
            "追赶 is bắt kịp/theo kịp. Do not invent film plots. "
            "Keep speech concise and natural. Output ONLY JSON: "
            '{"translations":[{"id":0,"text_vi":"..."}]}. '
            "Return each requested ID once, and NO other IDs."
        )
        attempts += 1
        try:
            items = _parse_json(provider._chat(system, prompt)).get("translations")
            if not isinstance(items, list) or len(items) != len(requested):
                continue
            mapping = {}
            for item in items:
                if not isinstance(item, dict) or type(item.get("id")) is not int:
                    raise ValueError("Invalid revision ID")
                if item["id"] in mapping:
                    raise ValueError("Duplicate revision ID")
                if not isinstance(item.get("text_vi"), str):
                    raise ValueError("Non-string Vietnamese revision")
                mapping[item["id"]] = " ".join(item["text_vi"].split())
            if set(mapping) != set(requested):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        for item in pending:
            seg = next(s for s in segments if s.index == item["id"])
            proposal = mapping[seg.index]
            old = seg.text_vi
            if not proposal or proposal == seg.text_src:
                continue
            seg.text_vi = proposal
            if any(x["id"] == seg.index
                   for x in chinese_translation_flags([seg])["issues"]):
                seg.text_vi = old
                continue
            changes.append({"id":seg.index, "before":old, "after":proposal,
                            "human_verified":False})
    remaining = chinese_translation_flags(segments)["issues"]
    return {"llm_revision_calls":attempts, "revised":changes,
            "unresolved":remaining, "human_approved":False}
