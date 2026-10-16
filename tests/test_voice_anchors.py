"""Offline tests: voice candidate selection never invents approved identity."""
import pytest
from speaker.voice_anchors import make_manifest


def test_no_diarization_cannot_generate_anchors():
    with pytest.raises(ValueError, match="pyannote"):
        make_manifest({"segments": []})


def test_pending_candidates_even_with_good_word_evidence():
    evidence = {
        "diarization_exclusive": [
            {"start": 0., "end": 3., "label": "SPEAKER_00"},
            {"start": 30., "end": 33., "label": "SPEAKER_01"},
        ],
        "diarization_regular": [
            {"start": 0., "end": 3., "label": "SPEAKER_00"},
            {"start": 30., "end": 33., "label": "SPEAKER_01"},
        ],
        "word_evidence": [
            {"start": .3, "end": 2.2, "word": "Hello"},
            {"start": 30.5, "end": 32.6, "word": "Hi"},
        ],
        "segments": [
            {"index": 0, "start": 0., "end": 3., "text_src": "Hello"},
            {"index": 1, "start": 30., "end": 33., "text_src": "Hi"},
        ],
    }
    manifest = make_manifest(evidence)
    assert manifest["qa_status"] == "UNAPPROVED"
    assert not manifest["cluster_character_mapping_approved"]
    assert len(manifest["candidates"]) == 2
    assert all(c["verified_character"] is None for c in manifest["candidates"])
    assert all(c["review_status"] == "PENDING_AUDIO_VISUAL_REVIEW"
               for c in manifest["candidates"])


def test_short_turn_is_not_faked_into_anchor():
    m = make_manifest({"diarization_exclusive": [
        {"start": 0., "end": .3, "label": "SPEAKER_00"}]})
    assert not m["candidates"]
    assert m["clusters"] == ["SPEAKER_00"]


def test_nonadjacent_selection_avoids_repetitive_clips():
    e = {"diarization_exclusive": [
        {"start": x, "end": x+3., "label": "SPEAKER_00"}
        for x in [0., 6., 24., 30., 50.]]}
    manifest = make_manifest(e, per_cluster=3, min_separation=18.)
    starts = [c["start"] for c in manifest["candidates"]]
    assert len(starts) == 3
    assert all(abs(x-y) >= 18. for i, x in enumerate(starts)
               for y in starts[i+1:])
