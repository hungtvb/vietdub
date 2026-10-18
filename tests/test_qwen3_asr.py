"""Optional Qwen3-ASR plugin tests (no model download required).

The real Qwen model uses much more hardware; these tests only verify
routing, API shape, exact aligned timestamps and fail-closed behavior.
"""
from types import SimpleNamespace
import sys
import types
import pytest
from asr.source_language import choose_language
from asr.engine_router import select_asr_engine
from asr.qwen3_adapter import Qwen3ASRAdapter,QwenASRError,aligned_to_segments
from core.settings import DEFAULTS


def test_qwen_is_explicit_choice_not_new_default():
    for language in ("zh", "en", "ja"):
        decision=choose_language([],requested=language)
        result=select_asr_engine(decision,requested_engine="qwen3_asr")
        assert result.engine=="qwen3_asr"
        assert result.manual_override is True
        assert result.language_review_required is True
    assert select_asr_engine(choose_language([],requested="zh")).engine=="funasr"
    assert select_asr_engine(choose_language([],requested="en")).engine=="whisper_pyannote"
    assert DEFAULTS["qwen_asr_model"]=="Qwen/Qwen3-ASR-0.6B"


def test_qwen_aligner_preserves_real_chinese_word_timestamps():
    items=[
        SimpleNamespace(text="你",start_time=1.1,end_time=1.5),
        SimpleNamespace(text="好？",start_time=1.5,end_time=2.1),
        SimpleNamespace(text="谢谢。",start_time=3.1,end_time=4.0),
    ]
    result=aligned_to_segments(items,duration=5.,language="zh")
    assert [(s.start,s.end) for s in result]==[(1.1,2.1),(3.1,4.0)]
    assert [s.text_src for s in result]==["你好？","谢谢。"]
    assert all(s.needs_review for s in result)
    assert all(s.identity_status=="UNVERIFIED" for s in result)


def test_qwen_segments_group_english_word_alignment_without_fake_timing():
    items=[
        SimpleNamespace(text="Can",start_time=0.1,end_time=0.4),
        SimpleNamespace(text="you",start_time=0.5,end_time=0.8),
        SimpleNamespace(text="help?",start_time=0.9,end_time=1.3),
    ]
    data=aligned_to_segments(items,duration=2.0,language="en")
    assert len(data)==1
    assert data[0].text_src=="Can you help?"
    assert (data[0].start,data[0].end)==(0.1,1.3)


def test_qwen_rejects_invalid_timestamps_and_silent_output():
    items=[SimpleNamespace(text="hi",start_time=5,end_time=7)]
    with pytest.raises(QwenASRError,match="escaped"):
        aligned_to_segments(items,duration=6)
    with pytest.raises(QwenASRError,match="no aligned"):
        aligned_to_segments([],duration=3)
    with pytest.raises(ValueError,match="aligner"):
        Qwen3ASRAdapter(aligner="")


def fake_provider(monkeypatch, sentences):
    # CLI CI does not install heavyweight torch or qwen-asr.
    fake_torch=types.ModuleType("torch")
    fake_torch.float16="float16"
    fake_torch.float32="float32"
    fake_torch.cuda=SimpleNamespace(is_available=lambda:False)
    monkeypatch.setitem(sys.modules,"torch",fake_torch)
    class FakeQwen:
        @classmethod
        def from_pretrained(cls,model,**kwargs):
            assert kwargs["forced_aligner"]=="Qwen/Qwen3-ForcedAligner-0.6B"
            assert kwargs["device_map"]=="cpu"
            return cls()
        def transcribe(self,audio,language,return_time_stamps):
            assert return_time_stamps is True
            assert language=="Chinese"
            return sentences
    plugin=types.ModuleType("qwen_asr")
    plugin.Qwen3ASRModel=FakeQwen
    monkeypatch.setitem(sys.modules,"qwen_asr",plugin)


def test_qwen_adapter_uses_official_api_and_persists_uncertainty(tmp_path,monkeypatch):
    import soundfile as sf
    import numpy as np
    audio=tmp_path/"sample.wav"
    sf.write(str(audio),np.zeros(16000*4,dtype="float32"),16000)
    word=SimpleNamespace(text="你好？",start_time=.9,end_time=1.5)
    entry=SimpleNamespace(text="你好？",language="Chinese",
                          time_stamps=SimpleNamespace(items=[word]))
    fake_provider(monkeypatch,[entry])
    adapter=Qwen3ASRAdapter(device="cpu",language="zh")
    result=adapter.transcribe(audio)
    assert len(result)==1
    assert result[0].text_src=="你好？"
    assert (result[0].start,result[0].end)==(.9,1.5)
    assert adapter.last_evidence["source"]=="qwen3_asr"
    assert adapter.last_evidence["forced_alignment_executed"] is True
    assert adapter.last_evidence["speaker_diarization_executed"] is False
    assert adapter.last_evidence["human_verified"] is False


def test_qwen_adapter_fails_closed_without_aligner_spans(tmp_path,monkeypatch):
    import soundfile as sf
    import numpy as np
    audio=tmp_path/"sample.wav"
    sf.write(str(audio),np.zeros(16000*2,dtype="float32"),16000)
    entry=SimpleNamespace(text="hello",language="English",time_stamps=None)
    fake_provider(monkeypatch,[entry])
    with pytest.raises(QwenASRError,match="aligned timestamps"):
        Qwen3ASRAdapter(device="cpu",language="zh").transcribe(audio)
