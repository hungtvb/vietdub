"""Offline Chinese ASR backend/profile tests. Never download actual models."""
import sys
from types import SimpleNamespace
import pytest

from asr import funasr_adapter as fa


def _realistic_sentence():
    return [{
        "sentence_info": [{
            "start": 100, "end": 1800,
            "text": "你好，世界！", "spk": "spk0",
        }]
    }]


def test_auto_model_backend_records_measured_latency(monkeypatch, tmp_path):
    observed = {}
    class FakeAutoModel:
        def __init__(self, **kwargs):
            observed.update(kwargs)
        def generate(self, **kwargs):
            observed["generate"] = kwargs
            return _realistic_sentence()
    monkeypatch.setitem(sys.modules, "funasr",
                        SimpleNamespace(AutoModel=FakeAutoModel))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    monkeypatch.setattr(fa, "_wav_duration_sec", lambda _: 2.)
    adapter = fa.FunASRAdapter("seaco", "vad", "punc", "spk",
                              backend="automodel", ncpu=2,
                              batch_size_s=30, max_vad_segment_ms=12000)
    segments = adapter.transcribe(tmp_path / "sample.wav")
    assert observed["model"] == "paraformer-zh"
    assert observed["vad_kwargs"] == {"max_single_segment_time": 12000}
    assert observed["ncpu"] == 2
    assert observed["generate"]["batch_size_s"] == 30
    assert len(segments) == 1
    assert segments[0].source_lang == "zh"
    assert segments[0].needs_review  # no model confidence -> never pretend 1.0
    assert adapter.metrics["backend"] == "automodel"
    assert adapter.metrics["model_load_seconds"] >= 0
    assert adapter.metrics["inference_seconds"] >= 0
    assert adapter.metrics["audio_seconds"] == 2.
    assert adapter.metrics["total_seconds"] >= 0
    assert adapter.metrics["segment_count"] == 1

    segments_again = adapter.transcribe(tmp_path / "sample.wav")
    assert segments_again
    assert adapter.metrics["reused_loaded_model"] is True


def test_model_without_sentence_info_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    adapter = fa.FunASRAdapter("asr", "vad", "punc", "spk",
                              backend="automodel")
    adapter._pipe = SimpleNamespace(generate=lambda **kwargs: [{"text": "你好"}])
    monkeypatch.setattr(fa, "_wav_duration_sec", lambda _: 2.)
    with pytest.raises(fa.ASRError, match="sentence_info"):
        adapter.transcribe(tmp_path / "sample.wav")


@pytest.mark.parametrize("backend", ["unknown", "cloud", ""])
def test_unknown_chinese_backend_rejected(backend):
    with pytest.raises(ValueError, match="backend"):
        fa.FunASRAdapter("asr", "vad", "punc", "spk", backend=backend)


def test_inference_time_excludes_model_initialization(monkeypatch, tmp_path):
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    monkeypatch.setattr(fa, "_wav_duration_sec", lambda _: 6.)
    model = SimpleNamespace(generate=lambda **kw: _realistic_sentence())
    adapter = fa.FunASRAdapter("asr", "vad", "punc", "spk",
                              backend="automodel")
    adapter._pipe = model
    segments = adapter.transcribe(tmp_path / "sample.wav")
    assert len(segments) == 1
    assert adapter.metrics["model_load_seconds"] is None
    assert adapter.metrics["inference_seconds"] <= adapter.metrics["total_seconds"]
    assert adapter.metrics["real_time_factor"] >= 0
