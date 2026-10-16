"""Optional open-source ECAPA voice matching. Uncalibrated suggestions ONLY.

No raw speaker vectors are persisted or shared; similarities never approve a
character or alter the transcript. Models run locally after free download.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import math
import os
import statistics

MODEL = "speechbrain/spkrec-ecapa-voxceleb"
MIN_AUDIO_SECONDS = 1.0


def cosine_similarity(a, b):
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("Invalid voice embedding dimensions")
    va, vb = [float(v) for v in a], [float(v) for v in b]
    if not all(math.isfinite(v) for v in va + vb):
        raise ValueError("Non-finite voice embedding")
    aa = math.sqrt(sum(v * v for v in va))
    bb = math.sqrt(sum(v * v for v in vb))
    if aa <= 1e-12 or bb <= 1e-12:
        raise ValueError("Silent/zero voice embedding")
    return max(-1., min(1., sum(x * y for x, y in zip(va, vb)) / (aa * bb)))


def rank_voice_vectors(target, references):
    """References: {character_id: [verified anchor embedding, ...]}."""
    ranked = []
    for char_id, vectors in references.items():
        if not vectors:
            continue
        distances = [cosine_similarity(target, v) for v in vectors]
        ranked.append({
            "character_id": char_id,
            "cosine_similarity": round(statistics.median(distances), 4),
            "reference_samples": len(distances),
            "score_is_probability": False,
        })
    ranked.sort(key=lambda row: -row["cosine_similarity"])
    return ranked


@lru_cache(maxsize=1)
def _get_encoder():
    try:
        from speechbrain.inference.speaker import EncoderClassifier
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu SpeechBrain. Cài: pip install -r requirements-speaker-v2.txt") from exc
    custom = os.getenv("VIETDUB_SPEAKER_MODEL_CACHE")
    saved = Path(custom) if custom else Path.home() / ".cache" / "vietdub" / "speaker-ecapa"
    saved.mkdir(parents=True, exist_ok=True)
    return EncoderClassifier.from_hparams(
        source=MODEL, savedir=str(saved), run_opts={"device": "cpu"})


def extract_embedding(wav, start=0., end=None):
    """Extract a real one-person 16k WAV crop, never the whole film."""
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("Thiếu numpy/soundfile để đọc audio giọng") from exc
    with sf.SoundFile(str(wav)) as f:
        if f.samplerate != 16000:
            raise ValueError("Mẫu giọng phải là audio 16kHz")
        a = float(start)
        b = f.frames / 16000 if end is None else float(end)
        if a < 0 or b <= a or b > f.frames / 16000 + .02:
            raise ValueError("Khoảng giọng nói không hợp lệ")
        if b - a < MIN_AUDIO_SECONDS:
            raise ValueError("Mẫu giọng quá ngắn để so khớp")
        f.seek(round(a * 16000))
        data = f.read(round((b - a) * 16000), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if (len(mono) < 16000 or not np.isfinite(mono).all()
            or np.max(np.abs(mono)) < 1e-4):
        raise ValueError("Audio mẫu giọng trống hoặc không hợp lệ")
    # Validate source audio BEFORE importing heavyweight optional torch.
    # A corrupt or too-short clip should fail with its real validation cause.
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "Thiếu PyTorch cho embedding. Cài requirements-speaker-v2.txt") from exc
    wave = torch.from_numpy(mono).unsqueeze(0)
    with torch.inference_mode():
        vector = _get_encoder().encode_batch(wave).squeeze().detach().cpu().numpy()
    if vector.ndim != 1 or len(vector) < 2:
        raise ValueError("Model không tạo được embedding hợp lệ")
    return vector.astype(float).tolist()


def compare_line_to_verified_anchors(store, line_index, wav_path, anchor_dir,
                                     *, encoder=extract_embedding):
    """Exclude overlapping self-audio to avoid meaningless perfect scores."""
    line = store._line(line_index)
    start, end = float(line.start), float(line.end)
    if end - start < MIN_AUDIO_SECONDS:
        return {"status": "INSUFFICIENT_AUDIO", "ranked": [],
                "requires_human_review": True}
    grouped = defaultdict(list)
    skipped = []
    for candidate_id, decision in store.anchor_decisions.items():
        if decision.get("status") != "VERIFIED_CLIP_ONLY":
            continue
        clip = store.candidates.get(candidate_id)
        if not clip:
            continue
        a, b = float(clip["start"]), float(clip["end"])
        if max(0., min(end, b) - max(start, a)) >= .2:
            skipped.append({"candidate_id": candidate_id,
                            "reason": "OVERLAPS_TARGET_AUDIO"})
            continue
        file = Path(anchor_dir) / clip["file"]
        if not file.is_file():
            skipped.append({"candidate_id": candidate_id, "reason": "MISSING_AUDIO_CLIP"})
            continue
        grouped[decision["character_id"]].append((candidate_id, file))
    if not grouped:
        return {"status": "NO_INDEPENDENT_REFERENCES", "ranked": [],
                "skipped": skipped, "requires_human_review": True}
    target = encoder(wav_path, start, end)
    reference_vectors = defaultdict(list)
    for char_id, clips in grouped.items():
        for candidate_id, file in clips:
            try:
                reference_vectors[char_id].append(encoder(file, 0., None))
            except (ValueError, OSError) as exc:
                skipped.append({"candidate_id": candidate_id,
                                "reason": f"INVALID_REFERENCE: {str(exc)[:100]}"})
    ranked = rank_voice_vectors(target, reference_vectors)
    for row in ranked:
        row["character_name"] = store.characters[row["character_id"]]["name"]
    return {
        "status": "SUGGESTION_ONLY" if ranked else "NO_USABLE_EMBEDDINGS",
        "model": MODEL,
        "score_type": "uncalibrated_cosine_similarity",
        "ranked": ranked,
        "skipped": skipped,
        "requires_human_review": True,
        "line_verified_by_model": False,
    }
