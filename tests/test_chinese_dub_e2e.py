"""Source integrity and timing guards for Mandarin -> Edge-TTS CI."""
import hashlib
import pytest
from project.schema import Segment
from ci_chinese_dub_e2e import tempo_filter, verify_source
from translation.llm_e2e import (revise_flagged_lines, chinese_translation_flags)

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



def test_llm_repairs_specific_errors_not_all_lines():
    import json
    class FakeLLM:
        def _chat(self, system, user):
            item=json.loads(user)
            return json.dumps({"id":item["id"],
                "text_vi":"Bóng đá nữ Trung Quốc vô địch Asian Cup và vẫn phải bắt kịp đối thủ."}, ensure_ascii=False)
    lines=[Segment(index=0,start=0,end=5,speaker=0,
                   text_src="中国女足亚洲杯冠军追赶",
                   text_vi="Vô địch Đông Nam Á để追赶."),
           Segment(index=1,start=5,end=7,speaker=0,
                   text_src="继续努力",text_vi="Cần tiếp tục cố gắng.")]
    outcome=revise_flagged_lines(lines,FakeLLM())
    assert outcome["llm_revision_calls"]==1
    assert len(outcome["revised"])==1
    assert outcome["unresolved"]==[]
    assert lines[1].text_vi=="Cần tiếp tục cố gắng."


def test_invalid_llm_revision_does_not_overwrite_translation():
    class BadLLM:
        def _chat(self, system, user):
            return '{"id":99,"text_vi":"Bị sai ID"}'
    line=Segment(index=0,start=0,end=5,speaker=0,
                 text_src="亚洲杯冠军",text_vi="Vô địch Đông Nam Á.")
    outcome=revise_flagged_lines([line],BadLLM(),max_attempts=1)
    assert outcome["llm_revision_calls"]==1
    assert outcome["unresolved"]
    assert line.text_vi=="Vô địch Đông Nam Á."



def test_qa_revision_one_line_at_a_time_and_retry_diagnostics():
    import json
    class LLM:
        def __init__(self):
            self.calls = {}
        def _chat(self, system, user):
            req=json.loads(user)
            sid=req["id"]
            self.calls[sid]=self.calls.get(sid,0)+1
            if sid==8 and self.calls[sid]==1:
                return json.dumps({"id":sid,"text_vi":"Chúng tôi cố gắng."})
            answers={
                8:"Chúng tôi giành chức vô địch, nhưng điều đó không có nghĩa là đã ở đẳng cấp hàng đầu.",
                9:"Chúng tôi phải nỗ lực nhiều hơn để bắt kịp đối thủ.",
            }
            return json.dumps({"id":sid,"text_vi":answers[sid]},
                              ensure_ascii=False)
    segs=[
        Segment(index=8,start=65,end=75,speaker=0,
                text_src="我们拿了冠军但不一定是顶级",
                text_vi="Chúng tôi cố gắng."),
        Segment(index=9,start=75,end=84,speaker=0,
                text_src="我们要追赶强队",
                text_vi="Cần tiếp tục tiến lên."),
    ]
    provider=LLM()
    q=revise_flagged_lines(segs,provider)
    assert q["initial_flagged_count"]==2
    assert q["llm_revision_calls"]==3
    assert len(q["revised"])==2
    assert q["unresolved"]==[]
    assert len(q["diagnostics"])==3
    assert not q["diagnostics"][0]["accepted"]
    assert q["method"]=="individual_source_line_revision"



def test_cross_segment_chinese_womens_team_not_vietnamese():
    before=Segment(index=6,start=49,end=56.02,speaker=0,
                   text_src="体育精神那中国。",text_vi="Đó là tinh thần thể thao.")
    line=Segment(index=7,start=56.06,end=65.59,speaker=0,
                 text_src="女足拿了亚洲杯冠军",
                 text_vi="Đội bóng nữ Việt Nam vô địch Asian Cup.")
    flagged=chinese_translation_flags([before,line])["issues"]
    assert len(flagged)==1
    assert "COUNTRY_CONTRADICTION:中国女足" in flagged[0]["reasons"]
    assert "CHINA_TEAM_NAME_MISSING" in flagged[0]["reasons"]
    line.text_vi="Đội tuyển bóng đá nữ Trung Quốc vô địch Asian Cup."
    assert chinese_translation_flags([before,line])["flagged_line_count"]==0


def test_explicit_not_necessarily_cannot_be_rewritten_as_win():
    line=Segment(index=8,start=65.59,end=74.53,speaker=0,
                 text_src="不一定说我们拿了冠军我们就是亚洲包括世界的顶级水平",
                 text_vi="Chúng ta sẽ vượt qua tất cả và giành chức vô địch.")
    reasons=chinese_translation_flags([line])["issues"][0]["reasons"]
    assert "NEGATION_SCOPE_LOST:不一定" in reasons
    assert "TOP_LEVEL_RANKING_MISSING:顶级" in reasons
    line.text_vi=("Giành chức vô địch không có nghĩa là chúng ta "
                  "đã đạt đẳng cấp hàng đầu châu Á hay thế giới.")
    assert chinese_translation_flags([line])["flagged_line_count"]==0
