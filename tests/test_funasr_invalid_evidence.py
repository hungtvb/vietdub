"""FunASR never invents timestamp evidence or speaker identity."""
from types import SimpleNamespace
import pytest
from asr.funasr_adapter import ASRError, FunASRAdapter


def adapter_with_rows(rows):
    adapter = FunASRAdapter("asr", "vad", "punc", "spk", backend="modelscope")
    adapter._pipe = lambda wav: [{"sentence_info": rows}]
    return adapter


@pytest.mark.parametrize("row", [
    {"text": "不要走", "end": 2000, "spk": "spk0"},
    {"text": "不要走", "start": 1000, "spk": "spk0"},
    {"text": "不要走", "start": float("nan"), "end": 2000, "spk": "spk0"},
    {"text": "不要走", "start": 2000, "end": 1000, "spk": "spk0"},
    {"text": "不要走", "start": -3, "end": 1000, "spk": "spk0"},
])
def test_timestamp_gaps_fail_instead_of_dropping_real_dialogue(row):
    adapter = adapter_with_rows([row])
    with pytest.raises(ASRError, match="timestamp"):
        adapter._transcribe_one("unused.wav")


@pytest.mark.parametrize("spk", [None, "unknown", "spk-1"])
def test_unknown_model_speaker_is_flagged_not_assumed_verified(spk):
    adapter = adapter_with_rows([
        {"start": 100, "end": 900, "text": "你是谁？",
         "spk": spk, "confidence": .95}
    ])
    segments = adapter._transcribe_one("unused.wav")
    assert len(segments) == 1
    assert segments[0].text_src == "你是谁？"
    assert segments[0].needs_review
    assert segments[0].confidence == .95
    assert segments[0].source_lang == "zh"


def test_valid_timestamp_and_speaker_id_are_retained():
    adapter = adapter_with_rows([
        {"start": 500, "end": 1100, "text": "大家好",
         "spk": "spk2", "confidence": .88}
    ])
    (seg,) = adapter._transcribe_one("unused.wav")
    assert seg.start == .5
    assert seg.end == 1.1
    assert seg.speaker == 2
    assert seg.confidence == .88
    assert not seg.needs_review
