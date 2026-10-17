#!/usr/bin/env python3
"""Real 13-minute drama: voice consistency audit; never claim actor identity.

Inputs: saved genuine WhisperX/pyannote evidence and ORIGINAL drama video.
Outputs: anonymous speaker-cluster similarity and prioritized review points.
No video, raw audio, embeddings, or human approvals are exported.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from speaker.real_video_audit import build_review_plan, save_review_plan
from speaker.real_voice_scan import analyze_speaker_audio
from speaker.voice_anchors import extract_candidates
from speaker.voice_similarity import extract_embedding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconciled", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--draft", default="")
    parser.add_argument("--output", default="speaker_v2_real")
    parser.add_argument("--max-lines", type=int, default=18)
    parser.add_argument("--candidates-per-cluster", type=int, default=3)
    args = parser.parse_args()

    evidence = json.loads(Path(args.reconciled).read_text(encoding="utf-8"))
    draft = (json.loads(Path(args.draft).read_text(encoding="utf-8"))
             if args.draft else None)
    source_video = Path(args.video)
    if not source_video.is_file() or source_video.stat().st_size < 1_000_000:
        raise RuntimeError("Original drama video is missing or unexpectedly small")
    review_plan = build_review_plan(
        evidence, draft, max_candidates_per_cluster=args.candidates_per_cluster)

    with tempfile.TemporaryDirectory(prefix="vietdub-private-audio-") as directory:
        scratch = Path(directory)
        wav = scratch / "film_source_16k.wav"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source_video), "-vn", "-ac", "1",
            "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
            check=True)
        if not wav.is_file() or wav.stat().st_size < 100_000:
            raise RuntimeError("Real movie audio was not extracted")
        extract_candidates(
            review_plan["voice_anchor_manifest"], source_video, scratch)
        voice = analyze_speaker_audio(
            review_plan, wav, scratch, encoder=extract_embedding,
            max_lines=args.max_lines,
            diarization_regular=evidence.get("diarization_regular") or [])
    if voice["valid_reference_clips"] < 2:
        raise RuntimeError("Real video did not produce enough valid speaker references")
    if voice["measured_line_samples"] < 2:
        raise RuntimeError("Real drama did not produce usable independent voice comparisons")
    # Deliberately save ONLY text-based QA and model scores.
    out = save_review_plan(review_plan, args.output)
    (out / "speaker-ecapa-audit.json").write_text(
        json.dumps(voice, ensure_ascii=False, indent=2), encoding="utf-8")
    assert review_plan["human_identity_approvals"] == 0
    assert voice["human_character_identity_verified"] is False
    assert voice["embedding_vectors_persisted"] is False
    assert voice["original_audio_exported"] is False
    print(json.dumps({
        "status": voice["status"],
        "source_asr_lines": review_plan["source_asr_lines"],
        "review_lines": review_plan["review_lines"],
        "pyannote_clusters": review_plan["distinct_pyannote_clusters"],
        "voice_refs": voice["valid_reference_clips"],
        "test_lines": voice["measured_line_samples"],
        "identity_approved": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
