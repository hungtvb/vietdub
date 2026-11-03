"""Routing/Chinese QA regressions. No model files needed for deterministic tests."""
import pytest
from asr.engine_router import select_asr_engine
from asr.source_language import choose_language
from asr.chinese_quality import qa_chinese_segments, reconcile_pyannote_speakers
from project.schema import Segment

def observations(lang, prob=.96):
    return [{"language": lang, "probability": prob, "has_speech": True}
            for _ in range(3)]

def test_chinese_uses_funasr():
    decision = choose_language(observations("zh"))
    assert select_asr_engine(decision).engine == "funasr"

def test_english_uses_whisper():
    assert select_asr_engine(
        choose_language(observations("en"))).engine == "whisper_pyannote"

@pytest.mark.parametrize("lang", ["ja", "ko", "fr", "es", "de", "th"])
def test_other_languages_use_whisper(lang):
    assert select_asr_engine(
        choose_language(observations(lang))).engine == "whisper_pyannote"

def test_mixed_languages_need_review_and_whisper():
    decision = choose_language([
        {"language": "zh", "probability": .96},
        {"language": "en", "probability": .93},
        {"language": "zh", "probability": .98}])
    route = select_asr_engine(decision)
    assert route.engine == "whisper_pyannote"
    assert route.language_review_required

def test_uncertain_audio_never_assumed_chinese():
    decision = choose_language([{"language": "und", "has_speech": False}])
    route = select_asr_engine(decision)
    assert route.engine == "whisper_pyannote"
    assert route.language_review_required

def test_manual_zh_uses_funasr_and_manual_en_uses_whisper():
    assert select_asr_engine(choose_language([], requested="zh")).engine == "funasr"
    assert select_asr_engine(choose_language([], requested="en")).engine == "whisper_pyannote"

def test_manual_engine_override_keeps_control():
    decision = choose_language([], requested="zh")
    assert select_asr_engine(decision, "whisper_pyannote").engine == "whisper_pyannote"
    assert select_asr_engine(decision, "funasr").engine == "funasr"
    with pytest.raises(ValueError, match="FunASR"):
        select_asr_engine(choose_language(observations("zh")), "funasr")

def test_same_voice_is_reconciled_across_video_chunks():
    segs = [
        Segment(index=0, start=0, end=2, speaker=0, text_src="你好", confidence=.5),
        Segment(index=1, start=605, end=607, speaker=1, text_src="大家好", confidence=.5)]
    quality = qa_chinese_segments(segs)
    diar = reconcile_pyannote_speakers(segs, [
        {"start": 0, "end": 2, "label": "S00"},
        {"start": 605, "end": 607, "label": "S00"}])
    assert segs[0].speaker == segs[1].speaker
    assert quality["review_required"] == 2
    assert diar["review_required"] == 0
    assert all(s.source_lang == "zh" for s in segs)

def test_overlapping_chinese_speakers_not_auto_verified():
    seg = Segment(index=0, start=0, end=4, speaker=0, text_src="你好你好")
    quality = reconcile_pyannote_speakers([seg], [
        {"start": 0, "end": 2, "label": "A"},
        {"start": 2, "end": 4, "label": "B"}])
    assert quality["review_required"] == 1
    assert seg.needs_review

def test_chinese_short_long_segments_flagged_without_changing_content():
    a = Segment(index=0, start=0, end=.2, speaker=0, text_src="好")
    b = Segment(index=1, start=2, end=14, speaker=0, text_src="你好" * 30)
    before = [a.text_src, b.text_src]
    quality = qa_chinese_segments([a, b])
    assert quality["review_required"] == 2
    assert [a.text_src, b.text_src] == before
