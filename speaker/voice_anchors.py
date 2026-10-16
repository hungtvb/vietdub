"""Conservative, auditable pyannote voice-anchor audition workflow.

A diarization cluster is NOT a character identity. Every proposed reference
stays PENDING until a reviewer confirms it using source audio and video.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess


def overlap(a, b, x, y):
    return max(0.0, min(b, y) - max(a, x))


def _candidate(turn, words, regular, sources, max_length):
    label = turn["label"]
    start = float(turn["start"])
    end = min(float(turn["end"]), start + max_length)
    duration = end - start
    if duration < 1.5:
        return None
    active = [w for w in words if overlap(start, end, float(w["start"]), float(w["end"])) > .03]
    related = [s for s in sources if overlap(start, end, float(s["start"]), float(s["end"])) > .1]
    voiced = sum(overlap(start, end, float(w["start"]), float(w["end"])) for w in active)
    concurrent = sum(overlap(start, end, float(t["start"]), float(t["end"]))
                     for t in regular if t["label"] != label)
    density = min(1., voiced / duration)
    cshare = min(1., concurrent / duration)
    return dict(
        cluster=label, start=round(start, 3), end=round(end, 3),
        duration=round(duration, 3), word_density=round(density, 3),
        other_speaker_overlap=round(cshare, 3),
        candidate_priority=round(.7 * density + .3 * max(0., 1. - cshare), 3),
        source_asr_ids=[int(s["index"]) for s in related],
        transcript_context_unverified=re.sub(
            r"\s+", " ", " ".join(s.get("text_src", "") for s in related)
        ).strip()[:300],
        review_status="PENDING_AUDIO_VISUAL_REVIEW",
        verified_character=None,
        evidence_level="DIARIZATION_CLUSTER_ONLY",
    )


def make_manifest(evidence, *, per_cluster=3, max_length=6., min_separation=18.):
    if per_cluster < 1 or not 1.5 <= max_length <= 15.:
        raise ValueError("Invalid anchor settings")
    turns = evidence.get("diarization_exclusive", [])
    if not turns:
        raise ValueError("Actual pyannote diarization evidence is required")
    groups = defaultdict(list)
    for turn in turns:
        candidate = _candidate(turn, evidence.get("word_evidence", []),
                               evidence.get("diarization_regular", []),
                               evidence.get("segments", []), max_length)
        if candidate:
            groups[turn["label"]].append(candidate)
    clips = []
    for label in sorted({turn["label"] for turn in turns}):
        options = sorted(groups[label],
                         key=lambda item: (-item["candidate_priority"], -item["duration"]))
        chosen = []
        for item in options:
            if len(chosen) >= per_cluster:
                break
            if any(abs(item["start"] - prior["start"]) < min_separation for prior in chosen):
                continue
            item["candidate_id"] = f"{label}_sample_{len(chosen)+1:02d}"
            item["file"] = f"clips/{item['candidate_id']}.wav"
            chosen.append(item)
        clips.extend(chosen)
    return {
        "schema_version": 1,
        "source": "pyannote_exclusive_diarization_and_real_audio",
        "qa_status": "UNAPPROVED",
        "cluster_character_mapping_approved": False,
        "warning": "A diarization cluster can contain multiple film characters; "
                   "these are listening candidates, not verified identities.",
        "clusters": sorted({t["label"] for t in turns}),
        "candidates": clips,
        "verified_anchors": [],
    }


def extract_candidates(manifest, media, out_dir, *, ffmpeg="ffmpeg"):
    media, out_dir = Path(media), Path(out_dir)
    if not media.is_file():
        raise FileNotFoundError(media)
    for item in manifest["candidates"]:
        path = out_dir / item["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(item["start"]), "-i", str(media),
            "-t", str(round(item["end"]-item["start"], 3)),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(path)
        ], check=True, capture_output=True, text=True)
        if not path.is_file() or path.stat().st_size < 1000:
            raise RuntimeError(f"Voice anchor clip missing: {path}")


def export_review(evidence, media, out_dir, *, per_cluster=3):
    out_dir = Path(out_dir)
    manifest = make_manifest(evidence, per_cluster=per_cluster)
    extract_candidates(manifest, media, out_dir)
    path = out_dir / "voice_anchor_candidates.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--media", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--per-cluster", type=int, default=3)
    args = parser.parse_args()
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    path = export_review(evidence, args.media, args.out, per_cluster=args.per_cluster)
    print(f"Voice review: {path}")


if __name__ == "__main__":
    main()
