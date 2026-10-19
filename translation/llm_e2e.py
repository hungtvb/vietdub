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
        languages={s.source_lang for s in segments if s.source_lang}
        meta.update(source_language=(next(iter(languages)) if len(languages)==1 else "mixed"),
                    language_review_required=True)
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
            "batch_translation_collapse": getattr(
                provider, "last_translation_collapse", {}),
            "untranslated_line_ids": [],
            "quality_human_verified": False
        }
    finally:
        provider._chat = original_chat


def translation_quality_flags(segments):
    """Video-agnostic structural issues; not an accuracy score."""
    from translation.quality import structural_issues
    issues=structural_issues(segments)
    return {"review_required":True,"flagged_line_count":len(issues),
            "issues":[{"id":s.index,"reasons":issues[s.index],
                       "source":s.text_src,"draft_vi":s.text_vi}
                      for s in segments if s.index in issues],
            "is_ground_truth_score":False}


def revise_flagged_lines(segments,provider,max_attempts=3,flagged=None):
    """Revise QA-flagged utterances using SAME configured LLM.

    Unlike the previous implementation, no video-specific words or facts are
    embedded in the prompt. Review issues are derived from this video's
    source/draft pair and surrounding context by the QA model.
    """
    from translation.base import _parse_json
    from translation.quality import structural_issues
    from translation import prompts
    if not 1 <= max_attempts <= 5:
        raise ValueError("Invalid revision count")
    original=flagged if flagged is not None else translation_quality_flags(segments)["issues"]
    original=[item for item in original
              if not any(e.get("category") in ("REVIEW_UNRELIABLE_REPEAT",
                  "REVIEW_UNAVAILABLE") for e in item.get("issues",[]))]
    revised,diagnostics,calls=[],[],0
    ids={s.index for s in segments}
    for item in original:
        idx=item["id"]
        if idx not in ids:
            raise ValueError("Unknown review issue source ID")
        pos=next(i for i,s in enumerate(segments) if s.index==idx)
        seg=segments[pos]
        problems=item.get("issues") or item.get("reasons") or []
        problem_names={
            p.get("category","") if isinstance(p,dict) else str(p)
            for p in problems
        }
        needs_full_translation="SOURCE_SCRIPT_REMAINS" in problem_names
        rejections=[]
        for attempt in range(1,max_attempts+1):
            context=[
                {"id":s.index,"source":s.text_src}
                for s in segments[max(0,pos-2):min(len(segments),pos+3)]
                if s.index != idx]
            # The source is the authority; drafts are supplied only to help
            # diagnose errors, never as a translation template. On foreign-
            # script leakage the request explicitly demands FULL retranslation.
            leftover_script = [
                ch for ch in (seg.text_vi or "")
                if "\u3400" <= ch <= "\u9fff"
                or "\u3040" <= ch <= "\u30ff"
                or "\uac00" <= ch <= "\ud7af"
            ]
            user=json.dumps({
                "requested_id":idx,
                "source_language":seg.source_lang,
                "ORIGINAL_SOURCE_TO_TRANSLATE":seg.text_src,
                "wrong_draft_for_diagnosis_only":(seg.text_vi if attempt==1 else ""),
                "source_script_leaks_in_wrong_draft":"".join(leftover_script)[:120],
                "full_retranslation_required":needs_full_translation,
                "errors_to_correct":problems,
                "neighboring_source_CONTEXT_ONLY":(context if attempt==1 else []),
                "last_rejected_attempt_reasons":rejections[-2:],
                "suggested_max_spoken_words":max(6,int((seg.end-seg.start)*4.2)),
                "source_may_be_interrogative":("?" in seg.text_src or "？" in seg.text_src),
            },ensure_ascii=False)
            system=prompts.repair_system_prompt(
                idx,source_script_remains=needs_full_translation,
                concise_retry=attempt>1)
            calls+=1
            try:
                data=_parse_json(provider._chat(system,user))
                if "translations" in data:
                    arr=data["translations"]
                    if not isinstance(arr,list) or len(arr)!=1:
                        raise ValueError("Exactly one revised line required")
                    data=arr[0]
                if not isinstance(data,dict) or type(data.get("id")) is not int or data["id"] != idx:
                    raise ValueError("Mismatched ID")
                val=data.get("text_vi")
                if not isinstance(val,str) or not val.strip():
                    raise ValueError("Empty revision")
                proposed=" ".join(val.split())
                if not any(c.isalnum() for c in proposed):
                    raise ValueError("Unspeakable placeholder / punctuation-only output")
                old=seg.text_vi
                if proposed==seg.text_src or proposed==old:
                    raise ValueError("Unchanged or untranslated")
                # Never lengthen a line until Edge-TTS needs severe time warp.
                word_limit=max(6,int((seg.end-seg.start)*4.2))
                if len(proposed.split())>word_limit:
                    raise ValueError(f"Dubbing sentence too long: {len(proposed.split())} > {word_limit} words")
                seg.text_vi=proposed
                structural=structural_issues([seg])
                if structural:
                    seg.text_vi=old
                    raise ValueError("Structural QA: "+str(structural[idx]))
                revised.append({"id":idx,"before":old,"after":proposed,
                                "human_verified":False})
                diagnostics.append({"id":idx,"attempt":attempt,
                                    "accepted":True,
                                    "reason":"STRUCTURAL_QA_ONLY"})
                break
            except Exception as exc:
                reason=type(exc).__name__+": "+str(exc)[:200]
                rejections.append(reason)
                diagnostics.append({"id":idx,"attempt":attempt,
                                    "accepted":False,"reason":reason})
        # Some small models cannot translate a long, ASR-fragmented Chinese
        # utterance in one response and keep leaking Hanzi after retries.
        # One final bounded rescue translates its actual sentence clauses
        # independently and rejoins them under the ORIGINAL ID and timing.
        # Abort atomically if even one clause is missing or unspeakable.
        if (needs_full_translation and seg.source_lang=="zh" and
                "SOURCE_SCRIPT_REMAINS" in structural_issues([seg]).get(idx, [])):
            clauses=_source_clauses_for_recovery(seg.text_src)
            if clauses:
                fragments=[]
                errors=[]
                for piece_idx,clause in enumerate(clauses):
                    calls+=1
                    question=("？" in clause or "?" in clause)
                    repair_prompt=(
                        "Translate ONLY the following Chinese speech clause "
                        "into natural, concise Vietnamese for video dubbing. "
                        "Translate every meaningful word; NO Hanzi, no source "
                        "script, no explanations. Do not translate neighboring "
                        "clauses. Keep question intent, negation, names, numbers. "
                        "Never output ellipses, an empty string, or placeholder. "
                        f'Return ONLY JSON {{"id":{idx},"text_vi":"Vietnamese words"}} '
                        f"with id={idx} exactly."
                    )
                    payload=json.dumps({
                        "source_clause_to_translate":clause,
                        "source_language":"zh",
                        "clause_number":piece_idx+1,
                        "clause_count":len(clauses),
                        "question":question,
                        "response_id":idx,
                    },ensure_ascii=False)
                    try:
                        data=_parse_json(provider._chat(repair_prompt,payload))
                        if ("translations" in data and
                                isinstance(data["translations"],list) and
                                len(data["translations"])==1):
                            data=data["translations"][0]
                        translated=data.get("text_vi")
                        if (type(data.get("id")) is not int or data["id"] != idx
                                or not isinstance(translated,str) or
                                not any(c.isalnum() for c in translated)):
                            raise ValueError("Clause rescue missing ID or spoken translation")
                        cleaned=" ".join(translated.split())
                        if any("\u3400"<=c<="\u9fff" for c in cleaned):
                            raise ValueError("Clause rescue left source-script Hanzi")
                        fragments.append(cleaned)
                    except Exception as exc:
                        errors.append(str(exc)[:170])
                        break
                if not errors and len(fragments)==len(clauses):
                    combined=" ".join(fragments)
                    # QA conservatively requires interrogative form preserved.
                    if ("?" in seg.text_src or "？" in seg.text_src) and "?" not in combined:
                        combined=combined.rstrip(".。! ")+"?"
                    word_limit=max(6,int((seg.end-seg.start)*4.2))
                    if len(combined.split()) <= word_limit:
                        before=seg.text_vi
                        seg.text_vi=combined
                        problems_after=structural_issues([seg]).get(idx,[])
                        if not problems_after:
                            revised.append({"id":idx,"before":before,"after":combined,
                                            "method":"source_clause_rescue",
                                            "human_verified":False})
                            diagnostics.append({"id":idx,"attempt":"source_clause_rescue",
                                                "accepted":True,"clauses":len(clauses),
                                                "reason":"STRUCTURAL_QA_ONLY"})
                        else:
                            seg.text_vi=before
                            errors.append("Post-rescue QA: "+repr(problems_after))
                    else:
                        errors.append("Clause rescue exceeds dubbing word budget")
                if errors:
                    diagnostics.append({"id":idx,"attempt":"source_clause_rescue",
                                        "accepted":False,
                                        "reason":"; ".join(errors)[:220]})
    return {"llm_revision_calls":calls,"initial_flagged_count":len(original),
            "revised":revised,"diagnostics":diagnostics,
            "unresolved":translation_quality_flags(segments)["issues"],
            "method":"contextual_per_line_revision",
            "human_approved":False}



def _source_clauses_for_recovery(source):
    """Only split a long Chinese source on REAL ASR sentence boundaries.

    Keeps the same utterance ID; not a new segmentation of the audio timeline.
    Very short or punctuation-free text should NOT be split on guessed chars.
    """
    import re
    if sum("\u3400" <= c <= "\u9fff" for c in source) < 25:
        return []
    clauses=[s.strip() for s in re.split(r"(?<=[。！？])",source) if s.strip()]
    return clauses if 2 <= len(clauses) <= 4 else []
