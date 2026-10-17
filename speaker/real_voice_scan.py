"""Real ECAPA clustering audit on the *original video*.

All scores remain uncalibrated similarity suggestions, not character
identities. Never persist raw biometric embeddings, clips or source audio.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import math
import statistics
import time

from speaker.voice_similarity import cosine_similarity, rank_voice_vectors


def _overlap(a, b, x, y):
    return max(0., min(b, y) - max(a, x))


def _verified_clip_path(root, filename):
    root = Path(root).resolve()
    clip = (root / filename).resolve()
    if not clip.is_relative_to(root):
        raise ValueError("Speaker clip path escapes review directory")
    return clip


def _independent_voice_references(samples, start, end):
    """Exclude own acoustic windows: same-audio matches have misleading scores."""
    return {
        cluster: [x["vector"] for x in clips
                  if _overlap(start, end, x["start"], x["end"]) < .2]
        for cluster, clips in samples.items()
    }


def analyze_speaker_audio(review_plan: dict, source_wav, clips_dir, *,
                          encoder, max_lines=18, diarization_regular=None):
    """Compute independent ECAPA voice suggestions for risky ASR lines.

    A sample's pyannote cluster is a weak source hypothesis. The algorithm
    never writes a named character, 'verified' field, or modifies segments.
    Only numerical cosine similarities and provenance are output.
    """
    if review_plan.get("status") != "UNAPPROVED":
        raise ValueError("Cannot analyze an already-approved review")
    if max_lines < 1 or max_lines > 100:
        raise ValueError("max_lines must be 1..100")
    started = time.perf_counter()
    candidates = review_plan["voice_anchor_manifest"]["candidates"]
    vectors = defaultdict(list)
    skipped = []
    for item in candidates:
        try:
            path = _verified_clip_path(clips_dir, item["file"])
            if not path.is_file():
                raise OSError("MISSING_VOICE_CLIP")
            vec = encoder(path, 0., None)
            # Protect against injected or broken embeddings without storing
            # their raw values: cosine(v, v) performs dimensionality checks.
            if abs(cosine_similarity(vec, vec) - 1.) > 1e-5:
                raise ValueError("INVALID_VOICE_VECTOR")
            vectors[str(item["cluster"])].append({
                "candidate_id": str(item["candidate_id"]),
                "start": float(item["start"]),
                "end": float(item["end"]),
                "vector": vec,
            })
        except (ValueError, OSError, RuntimeError) as exc:
            skipped.append({"candidate_id": str(item["candidate_id"]),
                            "reason": type(exc).__name__ + ": " + str(exc)[:120]})
    if not vectors:
        raise RuntimeError("No valid real ECAPA speaker embeddings were produced")

    # No scores are identity probabilities. Low intra-cluster similarity or
    # large cross-cluster similarity merits HUMAN cluster review, not merging.
    pairwise = []
    all_examples = [dict(row, cluster=cluster)
                    for cluster, group in vectors.items() for row in group]
    for i, first in enumerate(all_examples):
        for second in all_examples[i + 1:]:
            pairwise.append({
                "candidate_1": first["candidate_id"],
                "candidate_2": second["candidate_id"],
                "cluster_1": first["cluster"],
                "cluster_2": second["cluster"],
                "same_pyannote_cluster": first["cluster"] == second["cluster"],
                "uncalibrated_cosine": round(
                    cosine_similarity(first["vector"], second["vector"]), 4),
                "identity_approved": False,
            })

    # Select high-risk lines distributed across the film, not 18 consecutive
    # one-second lines from one ambiguous scene.
    selected = []
    scene_quota = defaultdict(int)
    for row in review_plan["rows"]:
        if len(selected) >= max_lines:
            break
        if float(row["duration"]) < 1.25:
            continue
        bucket = int(float(row["start"]) // 60)
        if scene_quota[bucket] >= 3:
            continue
        if not any(_independent_voice_references(
                vectors, float(row["start"]), float(row["end"])).values()):
            continue
        selected.append(row)
        scene_quota[bucket] += 1

    results = []
    for row in selected:
        start, end = float(row["start"]), float(row["end"])
        independent = _independent_voice_references(vectors, start, end)
        regular = diarization_regular or []
        involved = sorted({
            str(t["label"]) for t in regular
            if _overlap(start, end, float(t["start"]),
                        float(t["end"])) >= min(.25, .3 * (end-start))
        })
        if len(involved) > 1:
            results.append({
                "review_id": row["review_id"], "start": start, "end": end,
                "status": "MULTIPLE_PYANNOTE_VOICES_SKIP_SCORING",
                "source_clusters": involved, "ranked_clusters": [],
                "human_verified": False,
            })
            continue
        try:
            target = encoder(source_wav, start, end)
            ranked = rank_voice_vectors(target, independent)
        except (ValueError, OSError, RuntimeError) as exc:
            results.append({
                "review_id": row["review_id"], "start": start, "end": end,
                "status": "EMBEDDING_UNUSABLE", "error": str(exc)[:120],
                "ranked_clusters": [], "human_verified": False,
            })
            continue
        lead = ranked[0] if ranked else None
        margin = (round(lead["cosine_similarity"]-ranked[1]["cosine_similarity"], 4)
                  if len(ranked) > 1 else None)
        results.append({
            "review_id": row["review_id"], "start": start, "end": end,
            "source_clusters": row["source_pyannote_clusters"],
            "status": "UNVERIFIED_CLUSTER_SIMILARITY_ONLY",
            "nearest_cluster": lead["character_id"] if lead else None,
            "nearest_score": lead["cosine_similarity"] if lead else None,
            "top_two_margin": margin,
            "ranked_clusters": [{
                "cluster": r["character_id"],
                "cosine_similarity": r["cosine_similarity"],
                "independent_reference_clips": r["reference_samples"],
                "score_is_probability": False,
            } for r in ranked],
            "human_verified": False,
            "requires_video_and_audio_review": True,
        })

    within = [r["uncalibrated_cosine"] for r in pairwise
              if r["same_pyannote_cluster"]]
    between = [r["uncalibrated_cosine"] for r in pairwise
               if not r["same_pyannote_cluster"]]
    return {
        "status": "REAL_ECAPA_CLUSTER_AUDIT_UNAPPROVED",
        "model": "speechbrain/spkrec-ecapa-voxceleb",
        "human_character_identity_verified": False,
        "automatic_cluster_merging": False,
        "embedding_vectors_persisted": False,
        "original_audio_exported": False,
        "review_plan_source_lines": review_plan["source_asr_lines"],
        "distinct_clusters_with_embeddings": len(vectors),
        "valid_reference_clips": sum(len(v) for v in vectors.values()),
        "invalid_reference_clips": skipped,
        "measured_line_samples": len(results),
        "cross_model_accuracy_measured": False,
        "median_within_cluster_cosine": (
            round(statistics.median(within), 4) if within else None),
        "median_cross_cluster_cosine": (
            round(statistics.median(between), 4) if between else None),
        "sample_pairs": pairwise,
        "review_lines": results,
        "elapsed_seconds": round(time.perf_counter()-started, 3),
        "limitations": [
            "ECAPA cosine scores are NOT calibrated identity probabilities.",
            "Pyannote voice clusters may include more than one character.",
            "All reference clips are UNVERIFIED until original audio and "
            "video scene review.",
            "The same source recording is not independent ground truth; "
            "acoustic similarity can reflect channel and background sounds.",
        ],
    }
