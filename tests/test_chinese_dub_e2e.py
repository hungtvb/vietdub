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



def test_regroup_preserves_every_source_id_and_speaker_boundary():
    from asr.dub_grouping import group_for_vietnamese_dub
    pieces = [
        Segment(index=0, start=0, end=1.5, speaker=0, text_src="你好，"),
        Segment(index=1, start=1.5, end=2.0, speaker=0, text_src="这，"),
        Segment(index=2, start=2.0, end=3.0, speaker=0, text_src="是采访。"),
        Segment(index=3, start=3.1, end=6.0, speaker=1, text_src="是的。"),
        Segment(index=4, start=6.1, end=7.0, speaker=1, text_src="谢谢。"),
    ]
    merged, manifest = group_for_vietnamese_dub(pieces)
    assert [x["original_asr_ids"] for x in manifest] == [[0, 1, 2], [3, 4]]
    assert merged[0].speaker == 0 and merged[1].speaker == 1
    assert merged[0].text_src == "你好，这，是采访。"
    assert all(x.needs_review and x.source_lang == "zh" for x in merged)


def test_regroup_refuses_twelve_second_overflow():
    from asr.dub_grouping import group_for_vietnamese_dub
    pieces = [
        Segment(index=i, start=i * 4., end=(i + 1) * 4.,
                speaker=0, text_src="中国足球，") for i in range(5)
    ]
    merged, manifest = group_for_vietnamese_dub(pieces)
    assert len(merged) >= 2
    assert max(x.end-x.start for x in merged) <= 12
    assert [id for x in manifest for id in x["original_asr_ids"]] == list(range(5))



def test_existing_base_translator_executes_analyze_then_translate_and_records_llm_calls():
    import json
    from translation.base import BaseTranslator
    from translation.llm_e2e import analyze_and_translate
    from translation import prompts
    class StubExistingLLM(BaseTranslator):
        name = "existing_llm_interface"
        model = "test_stub_only"
        def _chat(self, system, user):
            if system == prompts.ANALYZE_SYSTEM:
                return json.dumps({
                    "speakers": [{"id": 0, "role": "interviewee",
                                  "relations": [{"audience": "audience",
                                                 "pronoun_i": "tôi",
                                                 "pronoun_you": "quý vị",
                                                 "is_default": True}]}],
                    "lines": [{"id": 0, "audience": "audience"}]})
            if system == prompts.VIDEO_META_SYSTEM:
                return json.dumps({"genre": "interview", "style": "formal",
                                   "setting": "modern", "tone_notes": "sports"})
            if system.startswith(prompts.TRANSLATE_SYSTEM):
                assert "tôi/quý vị" in user, "Locked speaker relation missing"
                return json.dumps({"translations": [
                    {"id": 0, "text_vi": "Bóng đá nữ Trung Quốc còn phải nỗ lực."}]})
            raise AssertionError("Unexpected prompt")
    segments=[Segment(index=0,start=0,end=4,speaker=0,source_lang="zh",
                      text_src="中国女足还要努力")]
    evidence=analyze_and_translate(segments, StubExistingLLM())
    assert evidence["llm_call_counts"]["analyze"] == 1
    assert evidence["llm_call_counts"]["translate"] == 1
    assert evidence["video_context"]["genre"] == "interview"
    assert segments[0].text_vi == "Bóng đá nữ Trung Quốc còn phải nỗ lực."
    assert evidence["human_approved"] is False


def test_existing_llm_fallback_to_chinese_source_is_rejected():
    import json
    from translation.base import BaseTranslator
    from translation.llm_e2e import analyze_and_translate
    from translation import prompts
    class SourceEchoLLM(BaseTranslator):
        name = "source_echo"
        model = "stub"
        def _chat(self, system, user):
            if system == prompts.ANALYZE_SYSTEM:
                return json.dumps({"speakers": [
                    {"id": 0, "role": "speaker",
                     "relations": [{"audience": "audience",
                                    "pronoun_i": "tôi",
                                    "pronoun_you": "quý vị",
                                    "is_default": True}]}],
                                    "lines":[{"id":0,"audience":"audience"}]})
            if system == prompts.VIDEO_META_SYSTEM:
                return json.dumps({"genre":"interview"})
            return json.dumps({"translations": [
                {"id":0,"text_vi":"中国女足"}]})
    with pytest.raises(RuntimeError, match="untranslated"):
        analyze_and_translate([
            Segment(index=0, start=0, end=4, speaker=0,
                    source_lang="zh", text_src="中国女足")], SourceEchoLLM())
