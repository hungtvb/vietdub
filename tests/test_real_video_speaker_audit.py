"""Real-data review plan + optional ECAPA scores remain unapproved."""
import pytest

from speaker.real_video_audit import (build_review_plan, save_review_plan,
                                      attach_ecapa_suggestions)
from speaker.real_voice_scan import analyze_speaker_audio


def evidence():
    asr = [
        {"index": 0, "start": 0, "end": 2,
         "speaker": 0, "text_src": "Where are you?"},
        {"index": 1, "start": 3, "end": 5,
         "speaker": 1, "text_src": "I'm in the shower."},
        {"index": 2, "start": 27, "end": 29,
         "speaker": 0, "text_src": "Don't go yet."},
    ]
    qa = [
        {"index": 0, "speaker_label": "S0", "suggested_speaker": 0,
         "reasons": [], "qa_status": "CANDIDATE_NOT_HUMAN_VERIFIED"},
        {"index": 1, "speaker_label": "S1", "suggested_speaker": 1,
         "reasons": ["SPEAKER_DISAGREEMENT", "SPEAKER_LOW_COVERAGE"],
         "qa_status": "NEEDS_REVIEW"},
        {"index": 2, "speaker_label": "S0", "suggested_speaker": 0,
         "reasons": [], "qa_status": "CANDIDATE_NOT_HUMAN_VERIFIED"},
    ]
    turns = [
        {"start": 0, "end": 2, "label": "S0"},
        {"start": 3, "end": 5, "label": "S1"},
        {"start": 27, "end": 29, "label": "S0"},
    ]
    words = [{"start": t["start"], "end": t["end"]}
             for t in turns]
    return {
        "segments": asr, "qa": qa,
        "diarization_exclusive": turns,
        "diarization_regular": turns,
        "word_evidence": words,
        "video_metadata": {"diarization_executed": True, "human_verified": False},
    }


def draft():
    return {
        "segments": [
            {"index": 0, "start": 0, "end": 2, "speaker": 0,
             "text_src": "Where are you?", "text_vi": "Cậu đâu rồi?"},
            {"index": 1, "start": 3, "end": 5, "speaker": 1,
             "text_src": "I'm in the shower.", "text_vi": "Đang tắm."},
            {"index": 2, "start": 27, "end": 29, "speaker": 0,
             "text_src": "Don't go yet.", "text_vi": "Đừng đi."},
        ],
        "speakers": [{"id": 0, "role": "Maddie"},
                     {"id": 1, "role": "Ethan"}],
        "video_metadata": {
            "qa_status": "DRAFT_CI1B_EVIDENCE_REVIEW",
            "original_ids_per_segment": {
                "0": [0], "1": [1], "2": [2]
            },
        },
    }


def test_rank_real_evidence_without_approving_a_character(tmp_path):
    report = build_review_plan(evidence(), draft())
    assert report["status"] == "UNAPPROVED"
    assert report["source_asr_lines"] == 3
    assert report["review_lines"] == 3
    assert report["distinct_pyannote_clusters"] == 2
    assert len(report["voice_anchor_manifest"]["candidates"]) == 3
    assert report["rows"][0]["review_id"] == 1
    assert report["rows"][0]["priority"] >= 50
    assert report["rows"][0]["provisional_role_name"] == "Ethan"
    assert not report["rows"][0]["provisional_role_is_verified"]
    assert not any(row["human_verified"] for row in report["rows"])
    out = save_review_plan(report, tmp_path)
    assert (out / "speaker-review-queue.csv").exists()
    assert (out / "speaker-review-plan.json").exists()


def test_rejects_approved_or_missing_original_ids():
    d = draft()
    d["video_metadata"]["qa_status"] = "APPROVED"
    with pytest.raises(ValueError, match="unapproved"):
        build_review_plan(evidence(), d)
    d["video_metadata"]["qa_status"] = "REVIEW_REQUIRED"
    del d["video_metadata"]["original_ids_per_segment"]["2"]
    with pytest.raises(ValueError, match="original ASR IDs"):
        build_review_plan(evidence(), d)


def test_rejects_preapproved_character_and_incomplete_source():
    d = draft()
    d["segments"][0]["character_id"] = "CHAR_001"
    with pytest.raises(ValueError, match="preapproved"):
        build_review_plan(evidence(), d)
    d = draft()
    d["segments"] = d["segments"][:2]
    with pytest.raises(ValueError, match="drops original"):
        build_review_plan(evidence(), d)


def test_diarization_must_be_real():
    e = evidence()
    e["video_metadata"]["diarization_executed"] = False
    with pytest.raises(ValueError, match="Real pyannote"):
        build_review_plan(e)


def test_ecapa_scores_use_independent_audio_and_never_verify(tmp_path):
    plan = build_review_plan(evidence())
    for clip in plan["voice_anchor_manifest"]["candidates"]:
        path = tmp_path / clip["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test fixture")

    def fake_embedding(path, start=0., end=None):
        if end is None:
            return [1., .1, 0.] if "S0" in str(path) else [0., .1, 1.]
        return [1., .05, 0.] if start < 3 or start >= 7 else [0., .05, 1.]

    report = analyze_speaker_audio(
        plan, "test_source.wav", tmp_path, encoder=fake_embedding,
        max_lines=3, diarization_regular=evidence()["diarization_regular"])
    assert report["status"] == "REAL_ECAPA_CLUSTER_AUDIT_UNAPPROVED"
    assert report["valid_reference_clips"] == 3
    assert len(report["review_lines"]) == 3
    assert all(not line["human_verified"] for line in report["review_lines"])
    assert all(line["status"] == "UNVERIFIED_CLUSTER_SIMILARITY_ONLY"
               for line in report["review_lines"])
    assert report["embedding_vectors_persisted"] is False
    assert report["original_audio_exported"] is False
    assert all(r["score_is_probability"] is False
               for line in report["review_lines"] for r in line["ranked_clusters"])


def test_path_traversal_in_voice_manifest_cannot_escape(tmp_path):
    plan = build_review_plan(evidence())
    for clip in plan["voice_anchor_manifest"]["candidates"]:
        clip["file"] = "../../private-person.wav"
    (tmp_path.parent / "private-person.wav").write_bytes(b"not a speaker clip")
    with pytest.raises(RuntimeError, match="No valid"):
        analyze_speaker_audio(plan, "unused.wav", tmp_path,
                              encoder=lambda *a, **k: [1., 0.], max_lines=2)


def test_untranscribed_reference_is_excluded_from_voice_ranking(tmp_path):
    plan = build_review_plan(evidence())
    samples = plan["voice_anchor_manifest"]["candidates"]
    samples[0]["word_density"] = 0.0
    for clip in samples:
        path = tmp_path / clip["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"valid dummy")
    def fake_embedding(path, start=0., end=None):
        if end is None:
            return [1., .1, 0.] if "S0" in str(path) else [0., 1., .1]
        return [1., .1, 0.]
    report = analyze_speaker_audio(plan, "source.wav", tmp_path,
                                   encoder=fake_embedding, max_lines=2)
    assert report["valid_reference_clips"] == len(samples) - 1
    assert any("LOW_WORD_DENSITY" in entry["reason"]
               for entry in report["invalid_reference_clips"])
    assert report["scored_line_samples"] >= 1
    assert report["embedding_vectors_persisted"] is False
    assert report["human_character_identity_verified"] is False


def test_join_acoustic_hints_by_original_asr_ids_not_v5_row_number(tmp_path):
    base = draft()
    # Turn ASR 1 into two Vietnamese dub sentences (same original ID).
    base["segments"] = [
        base["segments"][0],
        {**base["segments"][1], "index": 1, "start": 3, "end": 4},
        {**base["segments"][1], "index": 2, "start": 4, "end": 5},
        {**base["segments"][2], "index": 3},
    ]
    base["video_metadata"]["original_ids_per_segment"] = {
        "0": [0], "1": [1], "2": [1], "3": [2],
    }
    report = build_review_plan(evidence(), base)
    acoustic = {
        "status": "REAL_ECAPA_CLUSTER_AUDIT_UNAPPROVED",
        "human_character_identity_verified": False,
        "embedding_vectors_persisted": False,
        "review_plan_source_lines": 3,
        "review_lines": [{
            "review_id": 1,
            "status": "UNVERIFIED_CLUSTER_SIMILARITY_ONLY",
            "nearest_cluster": "S0",
            "source_clusters": ["S1"],
        }],
    }
    merged = attach_ecapa_suggestions(report, acoustic)
    matched = [row for row in merged["rows"] if row["ecapa_source_line_ids"]]
    assert sorted(x["review_id"] for x in matched) == [1, 2]
    assert all(x["ecapa_top_cluster_unverified"] == "S0" for x in matched)
    assert all("ECAPA_PYANNOTE_CLUSTER_DISAGREEMENT" in x["review_alerts"]
               for x in matched)
    assert all(not row["human_verified"] for row in merged["rows"])
    assert merged["attached_ecapa_evidence"]["review_rows_with_hints"] == 2
    save_review_plan(merged, tmp_path)
    assert "ECAPA_PYANNOTE_CLUSTER_DISAGREEMENT" in (
        tmp_path / "speaker-review-queue.csv").read_text(encoding="utf-8-sig")
    # Never mutate the original V5 draft in place or approve translation.
    assert report["rows"][0].get("ecapa_source_line_ids") is None


def test_rejects_faked_approved_acoustic_hints():
    review = build_review_plan(evidence(), draft())
    acoustic = {
        "status": "REAL_ECAPA_CLUSTER_AUDIT_UNAPPROVED",
        "human_character_identity_verified": True,
        "review_plan_source_lines": 3,
    }
    with pytest.raises(ValueError, match="approved"):
        attach_ecapa_suggestions(review, acoustic)
