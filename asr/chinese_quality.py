"""Conservative Chinese ASR quality checks and full-video speaker reconciliation.

No invented confidence, speaker identity, or human approval.
"""
from collections import defaultdict
from project.schema import Segment


def overlap(a, b, x, y):
    return max(0., min(b, y) - max(a, x))


def qa_chinese_segments(segments: list[Segment]) -> dict:
    diagnostics = []
    prev = None
    for seg in segments:
        reasons = []
        if seg.end <= seg.start:
            reasons.append("NONPOSITIVE_DURATION")
        if seg.end - seg.start < .35:
            reasons.append("VERY_SHORT_UTTERANCE")
        if seg.end - seg.start > 9.:
            reasons.append("LONG_UNALIGNED_UTTERANCE")
        if sum("\u3400" <= ch <= "\u9fff" for ch in seg.text_src) > 55:
            reasons.append("LONG_CHINESE_SENTENCE")
        if prev and seg.start < prev.start:
            reasons.append("OUT_OF_ORDER")
        if prev and seg.start < prev.end - .05:
            reasons.append("OVERLAPPING_UTTERANCES")
        if seg.confidence <= .5:
            reasons.append("UNVERIFIED_ASR_CONFIDENCE")
        if seg.needs_review and not reasons:
            reasons.append("PRIOR_REVIEW")
        if reasons:
            seg.needs_review = True
        seg.source_lang = "zh"
        diagnostics.append({"index": seg.index, "source_lang": "zh",
                            "reasons": reasons})
        prev = seg
    return {"qa_status": "UNAPPROVED", "source_language": "zh",
            "segments": diagnostics,
            "review_required": sum(bool(x["reasons"]) for x in diagnostics)}


def reconcile_pyannote_speakers(segments: list[Segment], exclusive: list[dict],
                                *, min_coverage=.55, min_share=.75) -> dict:
    """Diarize across entire film; don't assume same spk0 between ASR chunks."""
    exclusive = sorted(exclusive, key=lambda x: x["start"])
    labels = sorted({window["label"] for window in exclusive})
    mapping = {label: idx for idx, label in enumerate(labels)}
    unknown_id = len(mapping)
    diagnostics = []
    for seg in segments:
        votes = defaultdict(float)
        for win in exclusive:
            if float(win["start"]) >= seg.end:
                break
            duration = overlap(seg.start, seg.end,
                               float(win["start"]), float(win["end"]))
            if duration:
                votes[win["label"]] += duration
        best = max(votes, key=votes.get) if votes else None
        coverage = votes[best] / max(seg.end-seg.start, .001) if best else 0.
        share = votes[best] / max(sum(votes.values()), .001) if best else 0.
        chunk_id = seg.speaker
        seg.speaker = mapping[best] if best else unknown_id
        issue = best is None or coverage < min_coverage or share < min_share
        if issue:
            seg.needs_review = True
        diagnostics.append({
            "index": seg.index, "cluster": best,
            "source_chunk_speaker": chunk_id, "speaker": seg.speaker,
            "coverage": round(coverage, 3), "share": round(share, 3),
            "multiple_speakers_possible": share < min_share,
            "review_required": bool(issue)})
    return {"qa_status": "UNAPPROVED", "speaker_clusters": labels,
            "speaker_mapping": mapping, "segments": diagnostics,
            "review_required": sum(row["review_required"] for row in diagnostics)}
