#!/usr/bin/env python3
"""Evidence-based speaker diarization and alignment QA for real Whisper transcripts.

QA-only must never claim that a diarization model or aligner was executed.
Neither this script nor its workflow writes translations/approved.json.
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import subprocess

from project.schema import Segment


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def overlap(a, b, x, y):
    return max(0., min(b, y) - max(a, x))


def annotation_windows(annotation):
    """Community-1's Annotation supports itertracks(yield_label=True)."""
    if hasattr(annotation, "itertracks"):
        it = ((turn, label) for turn, _, label in annotation.itertracks(yield_label=True))
    else:
        it = annotation
    out = [{"start": float(turn.start), "end": float(turn.end), "label": str(label)}
           for turn, label in it]
    if any(t["start"] < 0 or t["end"] <= t["start"] for t in out):
        raise ValueError("Invalid diarization timestamps")
    return sorted(out, key=lambda x: (x["start"], x["end"]))


def pyannote_diarize(video, out, token):
    if not token:
        raise RuntimeError("HF_TOKEN is missing: accept pyannote Community-1 conditions on Hugging Face, then configure GitHub Actions secret HF_TOKEN")
    from pyannote.audio import Pipeline
    wav = Path(out) / "source-16k.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                    "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token=token)
    result = pipe(str(wav))
    exclusive = annotation_windows(result.exclusive_speaker_diarization)
    regular = annotation_windows(result.speaker_diarization)
    if not exclusive:
        raise RuntimeError("Real pyannote Community-1 returned no diarization turns")
    return wav, exclusive, regular


from asr.whisper_align import forced_align


def map_speakers(segments, turns):
    """Optimal overlap matching only; never assert source IDs are human-verified."""
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    labels = sorted({x["label"] for x in turns})
    old_ids = sorted({s.speaker for s in segments})
    weights = np.zeros((len(labels), len(old_ids)))
    lengths = {lab: 0. for lab in labels}
    for i, label in enumerate(labels):
        for turn in turns:
            if turn["label"] != label:
                continue
            lengths[label] += turn["end"] - turn["start"]
            for seg in segments:
                if seg.speaker in old_ids:
                    weights[i, old_ids.index(seg.speaker)] += overlap(turn["start"], turn["end"], seg.start, seg.end)
    rows, cols = linear_sum_assignment(-weights)
    proposed = {labels[i]: old_ids[j] for i, j in zip(rows, cols)}
    next_id = max(old_ids, default=-1) + 1
    mapping, details = {}, {}
    for i, label in enumerate(labels):
        old = proposed.get(label)
        matched = weights[i, old_ids.index(old)] if old in old_ids else 0.
        competing = max((weights[i, k] for k, sid in enumerate(old_ids) if sid != old), default=0.)
        share = matched / max(lengths[label], .001)
        supported = old is not None and matched >= 1.5 and share >= .55 and matched >= competing * 1.3
        mapping[label] = int(old) if supported else next_id
        if not supported:
            next_id += 1
        details[label] = {"proposed_legacy_id": old,
                          "matched_seconds": round(float(matched), 3),
                          "overlap_share": round(float(share), 3),
                          "reliable_legacy_mapping": bool(supported),
                          "assigned_id": mapping[label]}
    return mapping, details


def reconcile(legacy, evidence, turns=None, regular=None, aligned_raw=None, align_stats=None):
    segments = [Segment.from_dict(s) for s in legacy["segments"]]
    raw = aligned_raw if aligned_raw is not None else evidence["raw"]
    if not segments or not raw:
        raise ValueError("Expected real ASR and Whisper word evidence")
    turns = sorted(turns or [], key=lambda t: t["start"])
    mapping, mapping_details = map_speakers(segments, turns) if turns else ({}, {})
    word_evidence = []
    for part in raw:
        words = part.get("words") or [{"start": part["start"], "end": part["end"], "word": part["text"]}]
        for word in words:
            if word.get("start") is None or word.get("end") is None:
                continue
            a, b = float(word["start"]), float(word["end"])
            if b <= a:
                continue
            votes = defaultdict(float)
            for turn in turns:
                if turn["start"] >= b:
                    break
                if turn["end"] > a:
                    votes[turn["label"]] += overlap(a, b, turn["start"], turn["end"])
            label = max(votes, key=votes.get) if votes else None
            word_evidence.append({"start": a, "end": b, "word": word.get("word", ""),
                                  "raw_id": part.get("id"), "speaker_label": label,
                                  "mapped_speaker": mapping.get(label),
                                  "alignment_status": part.get("alignment_status", "whisper_words_unaligned")})
    qa, output = [], []
    for seg in segments:
        relevant = [w for w in word_evidence if overlap(seg.start, seg.end, w["start"], w["end"]) >= min(.04, (w["end"] - w["start"]) * .45)]
        votes = defaultdict(float)
        for word in relevant:
            if word["speaker_label"] is not None:
                votes[word["speaker_label"]] += overlap(seg.start, seg.end, word["start"], word["end"])
        label = max(votes, key=votes.get) if votes else None
        mapped = mapping.get(label)
        coverage = votes[label] / max(seg.end - seg.start, .001) if label else 0.
        share = votes[label] / max(sum(votes.values()), .001) if label else 0.
        reasons = []
        if not turns:
            reasons.append("DIARIZATION_NOT_RUN")
        else:
            if label is None: reasons.append("NO_DIARIZED_SPEECH")
            if label is not None and coverage < .55: reasons.append("SPEAKER_LOW_COVERAGE")
            if label is not None and share < .75: reasons.append("MULTIPLE_SPEAKERS")
            if mapped is not None and mapped != seg.speaker: reasons.append("SPEAKER_DISAGREEMENT")
            if label is not None and not mapping_details[label]["reliable_legacy_mapping"]:
                reasons.append("UNMATCHED_SPEAKER_LABEL")
        if seg.end - seg.start < .5: reasons.append("SHORT_UTTERANCE")
        if seg.needs_review: reasons.append("WHISPER_PRIOR_REVIEW")
        if not relevant: reasons.append("NO_WORD_EVIDENCE")
        if any(w["alignment_status"] != "whisperx_aligned" for w in relevant):
            reasons.append("FORCED_ALIGNMENT_UNVERIFIED")
        sources = [p for p in raw if overlap(seg.start, seg.end, p["start"], p["end"]) > 0]
        if any(float(p.get("avg_logprob", 0)) < -.85 or float(p.get("no_speech_prob", 0)) > .6 for p in sources):
            reasons.append("WHISPER_LOW_EVIDENCE")
        output.append({**seg.to_dict(), "needs_review": bool(reasons)})
        qa.append({"index": seg.index, "start": seg.start, "end": seg.end,
                   "text_src": seg.text_src, "prior_speaker": seg.speaker,
                   "suggested_speaker": mapped, "speaker_label": label,
                   "speaker_time_coverage": round(coverage, 3),
                   "speaker_vote_share": round(share, 3), "reasons": reasons,
                   "qa_status": "NEEDS_REVIEW" if reasons else "CANDIDATE_NOT_HUMAN_VERIFIED"})
    reason_counts = dict(Counter(reason for row in qa for reason in row["reasons"]))
    return {"schema_version": 1,
            "source": "real_whisper_plus_pyannote" if turns else "real_whisper_qa_only",
            "video_metadata": {"qa_status": "UNAPPROVED",
                               "diarization_executed": bool(turns),
                               "forced_alignment_executed": bool(align_stats and align_stats.get("aligned")),
                               "human_verified": False, "calibrated_asr_confidence": False},
            "segments": output, "speakers": legacy["speakers"],
            "speaker_mapping": mapping_details, "qa": qa,
            "diarization_exclusive": turns, "diarization_regular": regular or [],
            "word_evidence": word_evidence,
            "summary": {"segments": len(segments),
                        "flagged_segments": sum(bool(x["reasons"]) for x in qa),
                        "reason_counts": reason_counts,
                        "diarized_turns": len(turns),
                        "word_evidence_count": len(word_evidence),
                        "alignment": align_stats or {"method": "not_executed"}}}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--asr", default="prior_asr/asr-handoff.json")
    cli.add_argument("--raw", default="prior_asr/whisper-raw-and-qa.json")
    cli.add_argument("--video", default="private_input/input.mp4")
    cli.add_argument("--out", default="output")
    cli.add_argument("--mode", choices=("qa_only", "diarize"), default="qa_only")
    cli.add_argument("--forced-align", action="store_true")
    args = cli.parse_args()
    data, raw = load(args.asr), load(args.raw)
    turns, regular, aligned, stats = None, None, None, None
    if args.mode == "diarize":
        video = Path(args.video)
        if not video.is_file():
            raise FileNotFoundError(video)
        wav, turns, regular = pyannote_diarize(video, args.out, os.environ.get("HF_TOKEN", ""))
        save(Path(args.out) / "diarization-evidence.json",
             {"source": "pyannote_community_1_real", "exclusive": turns, "regular": regular})
        if args.forced_align:
            aligned, stats = forced_align(raw["raw"], wav)
    elif args.forced_align:
        raise ValueError("Forced alignment cannot run in QA-only mode")
    result = reconcile(data, raw, turns, regular, aligned, stats)
    target = Path(args.out)
    save(target / "asr-reconciled-UNAPPROVED.json", result)
    save(target / "reconciliation-qa.json", result["qa"])
    save(target / "reconciliation-summary.json", result["summary"])
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
