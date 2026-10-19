"""Prioritize real-video speaker evidence WITHOUT assigning actor identities.

Inputs: genuine pyannote/WhisperX QA and optional provisional Vietnamese draft.
The numeric ASR cluster and draft role identifiers are independent spaces;
their numeric equality is not proof that the speaker is the named character.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path

from speaker.voice_anchors import make_manifest


HIGH_RISK = frozenset({
    "SPEAKER_DISAGREEMENT", "MULTIPLE_SPEAKERS",
    "NO_DIARIZED_SPEECH", "NO_WORD_EVIDENCE",
})
MEDIUM_RISK = frozenset({
    "SPEAKER_LOW_COVERAGE", "SHORT_UTTERANCE", "WHISPER_PRIOR_REVIEW",
})


def _interval(item):
    start, end = float(item["start"]), float(item["end"])
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Nonfinite, negative or inverted original speech timestamp")
    return start, end


def _overlap(a, b, x, y):
    return max(0., min(b, y) - max(a, x))


def _source_ids(item, mapping, original):
    if mapping is None:
        return [int(item["index"])]
    raw = mapping.get(str(item["index"]))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Draft line has no auditable original ASR IDs")
    ids = [int(i) for i in raw]
    if len(set(ids)) != len(ids) or min(ids) < 0 or max(ids) >= len(original):
        raise ValueError("Invalid source ASR line references")
    return ids


def build_review_plan(reconciled: dict, draft: dict | None = None, *,
                      max_candidates_per_cluster: int = 3) -> dict:
    """Return time-ordered and risk-ranked *unapproved* scene review queue."""
    if reconciled.get("video_metadata", {}).get("diarization_executed") is not True:
        raise ValueError("Real pyannote diarization is required")
    source = reconciled.get("segments") or []
    qa_rows = reconciled.get("qa") or []
    if not source or not qa_rows:
        raise ValueError("Real ASR and evidence-based speaker QA are required")
    if [int(s["index"]) for s in source] != list(range(len(source))):
        raise ValueError("Source ASR indexing must be contiguous")
    qa = {int(item["index"]): item for item in qa_rows}
    if len(qa) != len(source) or set(qa) != set(range(len(source))):
        raise ValueError("Speaker QA must cover every ASR utterance exactly once")
    if any(q.get("qa_status") not in ("NEEDS_REVIEW", "CANDIDATE_NOT_HUMAN_VERIFIED")
           for q in qa.values()):
        raise ValueError("Unexpected speaker QA state")
    for seg in source:
        _interval(seg)
    evidence = {
        "diarization_exclusive": reconciled.get("diarization_exclusive") or [],
        "diarization_regular": reconciled.get("diarization_regular") or [],
        "word_evidence": reconciled.get("word_evidence") or [],
        "segments": source,
    }
    manifest = make_manifest(
        evidence, per_cluster=max_candidates_per_cluster)
    if not manifest["candidates"]:
        raise ValueError("No usable source voice anchors for visual review")
    # Bind scores to the exact ASR, QA, diarization and selected anchors.
    # A segment count alone cannot distinguish two source films.
    evidence_sha256 = hashlib.sha256(json.dumps({
        "fingerprint_schema": 1,
        "segments": source,
        "qa": qa_rows,
        "diarization_exclusive": evidence["diarization_exclusive"],
        "diarization_regular": evidence["diarization_regular"],
        "word_evidence": evidence["word_evidence"],
        "voice_anchor_manifest": manifest,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8")).hexdigest()
    if draft is not None:
        meta = draft.get("video_metadata") or {}
        if meta.get("qa_status") not in ("REVIEW_REQUIRED", "UNAPPROVED",
                                         "DRAFT_CI1B_EVIDENCE_REVIEW"):
            raise ValueError("Draft must be unapproved")
        mapping = meta.get("original_ids_per_segment")
        if not isinstance(mapping, dict):
            raise ValueError("V5 requires an auditable original-ASR-ID mapping")
        lines = draft.get("segments") or []
        roles = {int(c["id"]): c.get("role", "") for c in draft.get("speakers", [])}
    else:
        mapping = None
        lines = source
        roles = {}
    ordered = []
    qa_flags = Counter()
    source_ids_covered = set()
    for item in lines:
        start, end = _interval(item)
        ids = _source_ids(item, mapping, source)
        source_ids_covered.update(ids)
        issues = sorted({reason for i in ids for reason in qa[i].get("reasons", [])})
        qa_flags.update(issues)
        clusters = sorted({str(qa[i].get("speaker_label")) for i in ids
                           if qa[i].get("speaker_label")})
        voice_ids = sorted({int(qa[i]["suggested_speaker"]) for i in ids
                            if qa[i].get("suggested_speaker") is not None})
        role_id = int(item.get("speaker", -1))
        alerts = set(issues)
        if len(clusters) > 1 or len(voice_ids) > 1:
            alerts.add("MERGE_CROSSES_SOURCE_VOICES")
        if draft is not None and any(i in {int(s["index"]) for s in source}
                                     and _overlap(start, end, *_interval(source[i])) == 0
                                     for i in ids):
            alerts.add("SOURCE_TIME_MAPPING_CONFLICT")
        if end-start < .65:
            alerts.add("SHORT_REVIEW_AUDIO")
        if draft is not None and role_id not in roles:
            alerts.add("MISSING_PROVISIONAL_ROLE")
        if item.get("identity_status") == "VERIFIED" or item.get("character_id"):
            raise ValueError("Speaker review report refuses preapproved identities")
        # 'provisional_role' is NOT inferred from diarization. A numeric ID
        # match is not accepted as an identity match.
        base = 15
        base += 38 if alerts & HIGH_RISK else 0
        base += 18 if alerts & MEDIUM_RISK else 0
        base += 23 if "MERGE_CROSSES_SOURCE_VOICES" in alerts else 0
        base += 18 if "SOURCE_TIME_MAPPING_CONFLICT" in alerts else 0
        base += 8 if "SHORT_REVIEW_AUDIO" in alerts else 0
        if role_id >= 10 and draft is not None:
            alerts.add("PROVISIONAL_SECONDARY_ROLE_NEEDS_SCENE")
            base += 12
        ordered.append({
            "review_id": int(item["index"]),
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end-start, 3),
            "original_asr_ids": ids,
            "source_pyannote_clusters": clusters,
            "source_candidate_speakers": voice_ids,
            "provisional_role_id": role_id if draft is not None else None,
            "provisional_role_name": roles.get(role_id, "") if draft is not None else "",
            "provisional_role_is_verified": False,
            "source_text_unverified": str(item.get("text_src") or "")[:240],
            "provisional_translation_unapproved": (
                str(item.get("text_vi") or "")[:240] if draft is not None else ""),
            "priority": min(base, 100),
            "review_alerts": sorted(alerts),
            "state": "PENDING_AUDIO_AND_VIDEO_REVIEW",
            "proposed_character": None,
            "human_verified": False,
        })
    if source_ids_covered != set(range(len(source))):
        raise ValueError("Draft drops original ASR evidence")
    ordered.sort(key=lambda row: (-row["priority"], row["start"], row["review_id"]))
    counts = Counter("HIGH" if row["priority"] >= 50 else
                     "MEDIUM" if row["priority"] >= 30 else "LOW"
                     for row in ordered)
    return {
        "schema_version": 1,
        "status": "UNAPPROVED",
        "source": "REAL_WHISPERX_PYANNOTE_UNVERIFIED",
        "source_evidence_sha256": evidence_sha256,
        "human_identity_approvals": 0,
        "source_asr_lines": len(source),
        "review_lines": len(ordered),
        "distinct_pyannote_clusters": len(manifest["clusters"]),
        "anchor_candidate_clips": len(manifest["candidates"]),
        "risk_counts": dict(counts),
        "qa_reason_occurrences": dict(qa_flags),
        "warning": "Cosine matching and cluster numeric IDs are not identities. "
                   "Listen to ORIGINAL audio and inspect VIDEO before verifying each line.",
        "rows": ordered,
        "voice_anchor_manifest": manifest,
    }



def attach_ecapa_suggestions(review_plan: dict, ecapa_report: dict) -> dict:
    """Join *unapproved* original-ASR acoustic hints into V5 split/merge rows.

    The two timelines differ: V5 can split or merge Whisper utterances, so
    joining on V5 row number is WRONG. Match only via original ASR IDs.
    Existing manual identity decisions are never produced or modified here.
    """
    if review_plan.get("status") != "UNAPPROVED":
        raise ValueError("Only unapproved review plans are supported")
    if ecapa_report.get("status") != "REAL_ECAPA_CLUSTER_AUDIT_UNAPPROVED":
        raise ValueError("Expected real unapproved ECAPA evidence")
    if (ecapa_report.get("human_character_identity_verified") or
            ecapa_report.get("embedding_vectors_persisted")):
        raise ValueError("Reject apparently approved or exported voice biometrics")
    digest = review_plan.get("source_evidence_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or ecapa_report.get("source_evidence_sha256") != digest):
        raise ValueError("Source evidence fingerprint mismatch; refuse cross-film ECAPA join")
    if review_plan.get("source_asr_lines") != ecapa_report.get("review_plan_source_lines"):
        raise ValueError("ASR count mismatch; do not mix unrelated films")
    from copy import deepcopy
    out = deepcopy(review_plan)
    hints = {}
    for hint in ecapa_report.get("review_lines", []):
        source_id = int(hint["review_id"])
        if source_id in hints or not 0 <= source_id < review_plan["source_asr_lines"]:
            raise ValueError("Duplicate or out-of-range original ASR hint ID")
        if hint.get("human_verified") is not False:
            raise ValueError("ECAPA cannot supply human-approved identities")
        if hint.get("status") not in (
                "UNVERIFIED_CLUSTER_SIMILARITY_ONLY",
                "MULTIPLE_PYANNOTE_VOICES_SKIP_SCORING",
                "EMBEDDING_UNUSABLE"):
            raise ValueError("Unexpected ECAPA status")
        if any(score.get("score_is_probability") is not False
               for score in hint.get("ranked_clusters", [])):
            raise ValueError("Cosine scores are not identity probabilities")
        hints[source_id] = hint
    for row in out["rows"]:
        matches = [hints[i] for i in row["original_asr_ids"] if i in hints]
        row["ecapa_source_line_ids"] = [
            x["review_id"] for x in matches]
        row["ecapa_top_cluster_unverified"] = ";".join(
            sorted({str(x["nearest_cluster"]) for x in matches
                    if x.get("nearest_cluster") is not None}))
        row["ecapa_status"] = ";".join(sorted(
            {str(x["status"]) for x in matches}))
        row["ecapa_review_required"] = bool(matches)
        row["human_verified"] = False
        if matches and any(
            x.get("status") == "UNVERIFIED_CLUSTER_SIMILARITY_ONLY" and
            x.get("nearest_cluster") not in x.get("source_clusters", [])
            for x in matches
        ):
            row["review_alerts"] = sorted(set(row["review_alerts"]) |
                                         {"ECAPA_PYANNOTE_CLUSTER_DISAGREEMENT"})
    out["attached_ecapa_evidence"] = {
        "source_asr_hints": len(hints),
        "review_rows_with_hints": sum(bool(row["ecapa_source_line_ids"])
                                     for row in out["rows"]),
        "human_verified": False,
        "note": "Acoustic cluster hints are NOT actor names or identity probabilities.",
    }
    return out


def save_review_plan(report: dict, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out/"speaker-review-plan.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out/"voice-anchor-candidates.json").write_text(
        json.dumps(report["voice_anchor_manifest"], ensure_ascii=False, indent=2),
        encoding="utf-8")
    columns = ["review_id", "start", "end", "duration", "priority",
               "original_asr_ids", "source_pyannote_clusters",
               "source_candidate_speakers", "provisional_role_name",
               "source_text_unverified", "provisional_translation_unapproved",
               "review_alerts", "state",
               "ecapa_source_line_ids", "ecapa_top_cluster_unverified",
               "ecapa_status"]
    with (out/"speaker-review-queue.csv").open("w", encoding="utf-8-sig",
                                                newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in report["rows"]:
            data = {k: row.get(k, "") for k in columns}
            for key in ("original_asr_ids", "source_pyannote_clusters",
                        "source_candidate_speakers", "review_alerts",
                        "ecapa_source_line_ids"):
                data[key] = ";".join(str(v) for v in (data[key] or []))
            writer.writerow(data)
    return out
