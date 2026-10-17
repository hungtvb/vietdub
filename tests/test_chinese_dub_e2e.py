"""Source integrity and timing guards for Mandarin -> Edge-TTS CI."""
import hashlib
import pytest
from project.schema import Segment
from ci_chinese_dub_e2e import tempo_filter, verify_source

def test_speed_filter_includes_safe_multi_step_factors():
    assert tempo_filter(1.25) == "atempo=1.250000"
    assert tempo_filter(4.5) == "atempo=2.0,atempo=2.0,atempo=1.125000"
    with pytest.raises(ValueError):
        tempo_filter(-1)

def test_source_fingerprint_not_confused_by_equal_segment_counts(tmp_path):
    video = tmp_path / "video.webm"
    video.write_bytes(b"this is the source")
    asr = {
        "status": "CHINESE_FUNASR_REAL_ASR_COMPLETE",
        "model_backend": "automodel",
        "qa": {"qa_status": "UNAPPROVED"},
        "source_video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "segment_count": 1,
        "real_transcript": [Segment(index=0, start=0, end=2, speaker=0,
                                    text_src="大家好").to_dict()]}
    assert verify_source(asr, video, 3)[0].needs_review
    video.write_bytes(b"other video, same number of lines")
    with pytest.raises(ValueError, match="SHA256"):
        verify_source(asr, video, 3)

def test_rejects_impossible_timing_and_fake_approval(tmp_path):
    video = tmp_path / "video.webm"
    video.write_bytes(b"source")
    asr = {
        "status": "CHINESE_FUNASR_REAL_ASR_COMPLETE", "model_backend": "automodel",
        "qa": {"qa_status": "UNAPPROVED"},
        "source_video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "segment_count": 1,
        "real_transcript": [Segment(index=0, start=1, end=2, speaker=0,
                                    text_src="你好").to_dict()]}
    asr["qa"]["qa_status"] = "APPROVED"
    with pytest.raises(ValueError, match="unapproved"):
        verify_source(asr, video, 3)
    asr["qa"]["qa_status"] = "UNAPPROVED"
    asr["real_transcript"][0]["end"] = 15
    with pytest.raises(ValueError, match="timing"):
        verify_source(asr, video, 3)
