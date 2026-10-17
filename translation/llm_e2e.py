"""Strict real-LLM analysis + translation bridge for Chinese E2E tests.

Reuses the EXISTING BaseTranslator analyze/translate pipeline and provider.
No MarianMT, Google fallback, invented role approval, or synthetic responses.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from project.schema import Speaker
from translation.chinese_semantic_guard import source_semantic_issues

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
    # Add cross-line entity facts and explicit polarity checks from source.
    semantic = source_semantic_issues(segments)
    by_id = {row["id"]: row for row in flags}
    for seg in segments:
        reasons = semantic.get(seg.index, [])
        if not reasons:
            continue
        row = by_id.get(seg.index)
        if row is None:
            row = {"id": seg.index, "reasons": [],
                   "source_zh": seg.text_src, "draft_vi": seg.text_vi}
            by_id[seg.index] = row
            flags.append(row)
        row["reasons"] += [r for r in reasons if r not in row["reasons"]]
    return {"review_required": True, "flagged_line_count": len(flags),
            "issues": flags, "is_ground_truth_score": False}


def revise_flagged_lines(segments, provider, max_attempts=4):
    """Targeted, auditable same-LLM corrections, one source line per request.

    Small LLMs often fail batched JSON rewrites. Keep original source IDs and
    reject malformed, untranslated, or glossary-incomplete revisions. These
    checks are heuristics, not independent semantic or human approval.
    """
    from translation.base import _parse_json

    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")
    initial = chinese_translation_flags(segments)["issues"]
    revised, attempts_log, calls = [], [], 0
    guidance = {
        "亚洲杯": "Asian Cup / Cúp châu Á, not a Southeast Asia tournament",
        "中国女足": "đội tuyển bóng đá nữ Trung Quốc",
        "冠军": "giành chức vô địch, chức vô địch",
        "追赶": "bắt kịp, đuổi kịp, theo kịp đối thủ",
        "中国女足": "đội tuyển nữ Trung Quốc, không phải Việt Nam",
        "不一定": "không có nghĩa là / không nhất thiết / không đồng nghĩa",
        "顶级": "đẳng cấp hàng đầu châu Á hoặc thế giới",
    }
    for issue in initial:
        sid = issue["id"]
        pos = next(i for i, seg in enumerate(segments) if seg.index == sid)
        seg = segments[pos]
        # Lock ALL key source meanings on EVERY repair, even those already
        # translated correctly. Otherwise repairing a missing negation can
        # silently drop the championship fact or the top-level comparison.
        required = {zh: hint for zh, hint in guidance.items()
                    if zh in (seg.text_src or "")}
        if ("CHINA_TEAM_NAME_MISSING" in issue["reasons"] or
                "COUNTRY_CONTRADICTION:中国女足" in issue["reasons"]):
            required["中国女足"] = guidance["中国女足"]
        conditional_claim = (
            "Dù giành chức vô địch, điều đó không có nghĩa là đã đạt đẳng cấp hàng đầu."
            if all(term in seg.text_src for term in ("冠军", "不一定", "顶级"))
            else "")
        rejection_reasons = []
        for attempt in range(1, max_attempts + 1):
            source = {
                "id": sid,
                "chinese_to_translate": seg.text_src,
                "current_vietnamese_draft": seg.text_vi,
                "errors_to_fix": issue["reasons"],
                "required_meanings": required,
                "preserve_all_of_these_meanings": True,
                "source_grounded_conditional_example": conditional_claim,
                "previous_rejection_reasons": rejection_reasons[-2:],
                "translation_constraints": ["Keep the team nationality across neighboring lines.",
                                            "Do NOT reverse 不一定 (not necessarily): champion does not imply world class."],
                "neighboring_context_not_to_translate": [
                    {"id": x.index, "zh": x.text_src, "vi_draft": x.text_vi}
                    for x in segments[max(0, pos-2): min(len(segments), pos+3)]
                    if x.index != sid
                ],
            }
            system = (
                "Bạn là biên dịch viên lồng tiếng Trung sang Việt. "
                "Hãy sửa đúng MỘT câu bị lỗi. Nguồn tiếng Trung và nghĩa bắt "
                "buộc nằm trong dữ liệu JSON; không bỏ sót thông tin, "
                "đổi tên giải đấu hay chế thêm tình tiết. "
                "Giữ đúng quốc tịch đội bóng giữa các câu liên tiếp: Trung Quốc không phải Việt Nam. "
                "Nếu nguyên tác nói giành chức vô địch KHÔNG đồng nghĩa đẳng cấp hàng đầu, "
                "phải giữ nghĩa phủ định; KHÔNG biến thành mục tiêu giành chức vô địch. "
                "Phải viết toàn bộ bằng tiếng Việt, ngắn gọn và tự nhiên. "
                "KHÔNG dịch riêng các câu neighboring_context. "
                "Trả về đúng JSON object gồm id là số và text_vi là chuỗi, "
                "ví dụ: {\"id\":7,\"text_vi\":\"Đội vẫn cần cố gắng hơn.\"}. "
                "Hãy giữ TẤT CẢ các ý đã có trong required_meanings, "
                "kể cả ý đã đúng ở bản dịch cũ; không được sửa được ý này "
                "nhưng làm rơi ý khác. "
                "Không dùng markdown hay trả thêm trường giải thích."
            )
            if attempt > 1:
                system += " Lần trước không hợp lệ, phải sửa đầy đủ các lỗi được chỉ ra."
            calls += 1
            try:
                raw = provider._chat(system, json.dumps(source, ensure_ascii=False))
                obj = _parse_json(raw)
                # Accept BaseTranslator envelope with EXACTLY one translation,
                # but do not allow missing IDs, extras, or unexpected returns.
                if "translations" in obj:
                    items = obj["translations"]
                    if not isinstance(items, list) or len(items) != 1:
                        raise ValueError("Need exactly one translated line")
                    obj = items[0]
                if (not isinstance(obj, dict)
                        or type(obj.get("id")) is not int or obj["id"] != sid):
                    raise ValueError("Invalid/mismatched source ID")
                if not isinstance(obj.get("text_vi"), str):
                    raise ValueError("Vietnamese string text_vi required")
                proposal = " ".join(obj["text_vi"].split()).strip()
                if not proposal or proposal == seg.text_src:
                    raise ValueError("Empty or original Chinese text")
                old = seg.text_vi
                if proposal == old:
                    raise ValueError("The LLM returned the unchanged draft")
                seg.text_vi = proposal
                flagged = [item for item in chinese_translation_flags(segments)["issues"]
                           if item["id"] == sid]
                if flagged:
                    seg.text_vi = old
                    raise ValueError("Still flagged: " + ",".join(flagged[0]["reasons"]))
                revised.append({"id":sid, "before":old, "after":proposal,
                                "human_verified":False})
                attempts_log.append({"id":sid, "attempt":attempt,
                                     "accepted":True, "reason":"HEURISTIC_QA_CLEAR"})
                break
            except Exception as err:
                message = type(err).__name__+": "+str(err)[:200]
                rejection_reasons.append(message)
                attempts_log.append({"id":sid, "attempt":attempt,
                                     "accepted":False, "reason":message})
    remaining = chinese_translation_flags(segments)["issues"]
    return {
        "llm_revision_calls": calls,
        "initial_flagged_count": len(initial),
        "revised": revised,
        "diagnostics": attempts_log,
        "unresolved": remaining,
        "method": "individual_source_line_revision",
        "human_approved": False,
    }
