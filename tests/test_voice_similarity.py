"""Speaker embedding scores are uncalibrated suggestions, never approvals."""
import numpy as np
import pytest
import soundfile as sf

from project.schema import Segment
from speaker.verification import SpeakerVerification
from speaker.voice_similarity import (
    cosine_similarity, rank_voice_vectors, compare_line_to_verified_anchors,
    extract_embedding,
)


def test_cosine_vectors_are_not_probabilities():
    assert cosine_similarity([1, 0], [1, 0]) == 1.
    assert cosine_similarity([1, 0], [0, 1]) == 0.
    ranked = rank_voice_vectors([1, 0], {"A": [[1, 0], [.9, .1]],
                                         "B": [[0, 1]]})
    assert ranked[0]["character_id"] == "A"
    assert all(row["score_is_probability"] is False for row in ranked)


@pytest.mark.parametrize("vectors", [
    ([0, 0], [1, 0]), ([float("nan"), 1], [1, 1]),
    ([1, 0], [1]),
])
def test_invalid_voice_embedding_rejected(vectors):
    with pytest.raises(ValueError):
        cosine_similarity(*vectors)


def test_comparison_excludes_same_audio_to_avoid_fake_perfect_similarity(tmp_path):
    audio = tmp_path / "source.wav"
    sf.write(audio, np.ones(12 * 16000) * .1, 16000)
    clip_dir = tmp_path / "clips"
    clip_dir.mkdir()
    sf.write(clip_dir / "one.wav", np.ones(2 * 16000) * .1, 16000)
    segments = [
        Segment(index=0, start=1, end=3, speaker=0, text_src="Hello"),
        Segment(index=1, start=8, end=10, speaker=0, text_src="Again"),
    ]
    manifest = {"candidates": [{
        "candidate_id": "one", "start": 1., "end": 3.,
        "cluster": "SPEAKER_00", "source_asr_ids": [0],
        "file": "clips/one.wav",
    }]}
    store = SpeakerVerification(tmp_path, segments, audio, manifest)
    store.verify_anchor("one", "Maddie", heard_audio=True, checked_video=True)
    encoder = lambda *args: [1., 0., .2]
    same = compare_line_to_verified_anchors(
        store, 0, audio, tmp_path, encoder=encoder)
    other = compare_line_to_verified_anchors(
        store, 1, audio, tmp_path, encoder=encoder)
    assert same["status"] == "NO_INDEPENDENT_REFERENCES"
    assert other["status"] == "SUGGESTION_ONLY"
    assert other["ranked"][0]["character_name"] == "Maddie"
    assert other["line_verified_by_model"] is False
    assert other["requires_human_review"]
    assert store.line_decisions == {}
    assert segments[1].identity_status == "UNVERIFIED"


def test_short_speech_skips_embedding_model(tmp_path):
    wav = tmp_path / "speech.wav"
    wav.write_bytes(b"audio-content-for-fingerprint")
    segments = [Segment(index=0, start=1., end=1.2,
                        speaker=0, text_src="Hi")]
    store = SpeakerVerification(tmp_path, segments, wav)
    report = compare_line_to_verified_anchors(store, 0, wav, tmp_path)
    assert report["status"] == "INSUFFICIENT_AUDIO"


def test_short_clip_validated_before_model_load(tmp_path):
    wav = tmp_path / "short.wav"
    sf.write(wav, np.ones(1000) * .1, 16000)
    with pytest.raises(ValueError, match="quá ngắn"):
        extract_embedding(wav)
