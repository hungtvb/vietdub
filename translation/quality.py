"""Reusable translation QA for ANY source language, genre, or video.

Never hardcode source-video entities, names, topics, or translations.
Model judgments are advisory and not independent human verification.
"""
from __future__ import annotations
import json
from project.schema import Segment

def structural_issues(segments):
    """Deterministic source/translation integrity checks, no glossary."""
    result = {}
    from collections import Counter
    # Alert only, never silently rewrite real repeated lines. Requires three
    # different source utterances yielding the same consecutive target.
    collapse_ids = set()
    cursor = 0
    while cursor < len(segments):
        nxt=cursor+1
        same=(segments[cursor].text_vi or "").strip().casefold()
        while (same and nxt<len(segments) and
               (segments[nxt].text_vi or "").strip().casefold()==same):
            nxt+=1
        if nxt-cursor>=3 and len({
                (s.text_src or "").strip().casefold()
                for s in segments[cursor:nxt]})>=3:
            collapse_ids.update(s.index for s in segments[cursor:nxt])
        cursor=nxt
    for s in segments:
        issues = []
        source = (s.text_src or "").strip()
        target = (s.text_vi or "").strip()
        if not target or target == source:
            issues.append("EMPTY_OR_SOURCE_ECHO")
        if s.index in collapse_ids:
            issues.append("REPEATED_TRANSLATION_DISTINCT_SOURCES")
        # ASR punctuation is probabilistic. This is only a REVIEW WARNING:
        # a direct / rhetorical question can legitimately be indirect speech.
        if ("?" in source or "？" in source) and "?" not in target:
            issues.append("QUESTION_FORM_LOST")
        # Only a warning: proper nouns may legitimately retain source script.
        if s.source_lang == "zh" and any("\u3400" <= c <= "\u9fff" for c in target):
            issues.append("SOURCE_SCRIPT_REMAINS")
        if issues:
            result[s.index] = issues
    return result

REVIEW_SYSTEM = (
    "You are a meticulous bilingual translation QA reviewer. "
    "Compare EACH source utterance against its Vietnamese dubbing draft. "
    "Use ONLY the provided original-language dialogue and neighboring context. "
    "For every line assess factual entities and proper names, pronouns, numbers, "
    "negation/polarity, conditionals, time, causal relations, tone, omissions, "
    "hallucinations, mistranslated terminology, and missing or inverted "
    "questions, answers, speech acts and rhetorical intent. These checks apply to ANY "
    "language, genre, or topic. Do not inject outside facts or a sports glossary. "
    "If the source audio transcript is ambiguous, mark as needs_review instead "
    "of guessing. Return ONLY JSON: "
    '{"reviews":[{"id":0,"issues":[{"category":"omission","detail":"..."}]}]}. '
    "Include EVERY requested id exactly once. Use an empty issues list when "
    "you find no specific error. This is a preliminary machine review, not "
    "proof that a translation is correct."
)

def review_with_llm(segments, provider, video_metadata=None, batch_size=10):
    """LLM source-to-translation comparison with contextual, auditable output.

    Fail closed: invalid model response -> REVIEW_UNAVAILABLE for the affected
    chunk; never silently report an unreliable model verdict as QA passed.
    """
    from translation.base import _parse_json
    if not 1 <= batch_size <= 30:
        raise ValueError("Batch size out of range")
    if not segments:
        raise ValueError("No dialogue to review")
    records, calls = [], 0
    for start in range(0, len(segments), batch_size):
        chunk = segments[start:start+batch_size]
        expected = [s.index for s in chunk]
        around = segments[max(0,start-2):min(len(segments),start+batch_size+2)]
        request = {
            "video_metadata": video_metadata or {},
            "translate_language": "Vietnamese",
            "context_only": [
                {"id":s.index,"speaker":s.speaker,"source":s.text_src,
                 "draft_vi":s.text_vi}
                for s in around if s.index not in expected],
            "review_these": [
                {"id":s.index,"speaker":s.speaker,"audience":s.audience,
                 "start":s.start,"end":s.end,"source_lang":s.source_lang,
                 "source":s.text_src,"draft_vi":s.text_vi}
                for s in chunk],
        }
        calls += 1
        try:
            raw = provider._chat(REVIEW_SYSTEM, json.dumps(request,ensure_ascii=False))
            payload = _parse_json(raw)
            items = payload.get("reviews")
            if not isinstance(items,list) or len(items)!=len(expected):
                raise ValueError("Missing/extra review line")
            seen={}
            for item in items:
                if not isinstance(item,dict) or type(item.get("id")) is not int:
                    raise ValueError("Review ID invalid")
                sid=item["id"]
                if sid in seen or sid not in expected:
                    raise ValueError("Review IDs not a permutation of source IDs")
                issues=item.get("issues")
                if not isinstance(issues,list):
                    raise ValueError("Review issues must be a list")
                clean=[]
                for issue in issues:
                    if not isinstance(issue,dict):
                        raise ValueError("Review issue must be structured")
                    category=issue.get("category")
                    detail=issue.get("detail")
                    if not isinstance(category,str) or not isinstance(detail,str):
                        raise ValueError("Review issue missing category or detail")
                    if not category.strip() or not detail.strip():
                        raise ValueError("Empty review issue")
                    clean.append({"category":category.strip()[:60],
                                  "detail":detail.strip()[:450]})
                seen[sid]=clean
            for s in chunk:
                records.append({"id":s.index,"issues":seen[s.index],
                                "source":s.text_src,"draft_vi":s.text_vi})
                if seen[s.index]:
                    s.needs_review=True
        except Exception as exc:
            for s in chunk:
                s.needs_review=True
                records.append({"id":s.index,"issues":[{
                    "category":"REVIEW_UNAVAILABLE",
                    "detail":type(exc).__name__+": "+str(exc)[:200]
                }],"source":s.text_src,"draft_vi":s.text_vi})
    # Guard against a collapsed small-model reviewer which copies the same
    # "error" verbatim across unrelated source sentences. Its verdicts
    # MUST NOT be used to rewrite the video automatically.
    from collections import Counter
    frequencies = Counter(
        (err["category"].casefold(),err["detail"].casefold().strip())
        for row in records for err in row["issues"])
    bad = {item for item,num in frequencies.items()
           if num >= 3 and num >= len(segments) / 2}
    # Batch-review collapse is also unsafe if the small reviewer claims
    # essentially EVERY unrelated utterance is wrong. In that case it is
    # still valid as a manual-review alert, but NEVER as an automatic rewrite
    # instruction: this previously corrupted an English 15-line interview.
    high_flag_rate = (len(segments) >= 8 and
                      sum(bool(row["issues"]) for row in records)
                      >= len(segments)*.85)
    unreliable_ids = []
    if bad or high_flag_rate:
        for row in records:
            matches=[e for e in row["issues"]
                     if (e["category"].casefold(),
                         e["detail"].casefold().strip()) in bad]
            if matches or high_flag_rate:
                # Retain original issues in the exported report for auditing,
                # while barring an unreliable model from mass auto-rewriting.
                row["issues"].append({
                    "category":"REVIEW_UNRELIABLE_REPEAT",
                    "detail":("Reviewer flagged nearly every unrelated turn"
                              if high_flag_rate else
                              "Repeated the same alleged error across unrelated "
                              "source lines: "+matches[0]["detail"][:160])
                })
                unreliable_ids.append(row["id"])
                next(s for s in segments if s.index == row["id"]).needs_review=True
    issues = [r for r in records if r["issues"]]
    basics=structural_issues(segments)
    for s in segments:
        if s.index in basics:
            s.needs_review=True
    return {
        "reviewer_model":getattr(provider,"model","unknown"),
        "reviewer_provider":getattr(provider,"name","unknown"),
        "llm_calls":calls,"reviewed_lines":len(records),
        "flagged_lines":len(set(r["id"] for r in issues)|set(basics)),
        "issues":issues,
        "unreliable_reviewer_ids":unreliable_ids,
        "auto_repair_eligible_ids":[r["id"] for r in issues
            if all(e["category"] not in ("REVIEW_UNRELIABLE_REPEAT",
                      "REVIEW_UNAVAILABLE") for e in r["issues"])],
        "structural_flags":[{"id":k,"reasons":v} for k,v in basics.items()],
        "status":("LLM_REVIEWER_UNRELIABLE" if unreliable_ids
                  else "LLM_ADVISORY_REVIEW_ONLY"),
        "independent_quality_verified":False,
        "human_approved":False,
    }
