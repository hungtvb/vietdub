"""QA must never report unverified ASR or speaker assignments as approved."""
import copy

from ci_stage1_reconcile import reconcile, map_speakers


def fixtures():
    asr = {
        "segments": [
            dict(index=0, start=0.0, end=2.0, speaker=0, gender="female", text_src="Hi."),
            dict(index=1, start=2.0, end=4.0, speaker=1, gender="male", text_src="Hello."),
        ],
        "speakers": [dict(id=0, gender="female"), dict(id=1, gender="male")]
    }
    raw = {"raw": [
        dict(id=0, start=0., end=2., text="Hi.", avg_logprob=-.1,
             words=[dict(start=0., end=2., word="Hi.")]),
        dict(id=1, start=2., end=4., text="Hello.", avg_logprob=-.2,
             words=[dict(start=2., end=4., word="Hello.")])
    ]}
    turns = [
        dict(start=0., end=2., label="S0"),
        dict(start=2., end=4., label="S1")
    ]
    return asr, raw, turns


def test_qa_only_does_not_claim_real_diarization_or_approval():
    legacy, raw, _ = fixtures()
    result = reconcile(legacy, raw)
    assert result["source"] == "real_whisper_qa_only"
    assert result["video_metadata"]["diarization_executed"] is False
    assert result["video_metadata"]["qa_status"] == "UNAPPROVED"
    assert all("DIARIZATION_NOT_RUN" in item["reasons"] for item in result["qa"])


def test_pyannote_evidence_can_reconcile_ids_without_auto_approval():
    legacy, raw, turns = fixtures()
    result = reconcile(legacy, raw, turns, turns)
    assert [row["suggested_speaker"] for row in result["qa"]] == [0, 1]
    assert result["speaker_mapping"]["S0"]["reliable_legacy_mapping"]
    assert result["video_metadata"]["qa_status"] == "UNAPPROVED"


def test_full_alignment_is_still_only_candidate_not_human_verified():
    legacy, raw, turns = fixtures()
    aligned = copy.deepcopy(raw["raw"])
    for part in aligned:
        part["alignment_status"] = "whisperx_aligned"
    result = reconcile(legacy, raw, turns, turns, aligned,
                       {"method": "whisperx_forced_alignment", "aligned": 2})
    assert result["summary"]["flagged_segments"] == 0
    assert all(q["qa_status"] == "CANDIDATE_NOT_HUMAN_VERIFIED" for q in result["qa"])
    assert result["video_metadata"]["qa_status"] == "UNAPPROVED"


def test_short_turn_always_flagged():
    legacy, raw, turns = fixtures()
    legacy["segments"][0]["end"] = .3
    result = reconcile(legacy, raw, turns, turns)
    assert "SHORT_UTTERANCE" in result["qa"][0]["reasons"]


def test_no_fake_100_percent_asr_confidence():
    legacy, raw, turns = fixtures()
    result = reconcile(legacy, raw, turns, turns)
    assert result["video_metadata"]["calibrated_asr_confidence"] is False


def test_low_overlap_speaker_keeps_unmatched_reason():
    legacy, raw, turns = fixtures()
    legacy["segments"][0]["speaker"] = 1
    result = reconcile(legacy, raw, turns, turns)
    assert any("SPEAKER_DISAGREEMENT" in q["reasons"] or
               "UNMATCHED_SPEAKER_LABEL" in q["reasons"] for q in result["qa"])
