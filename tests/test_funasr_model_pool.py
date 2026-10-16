"""In-memory ASR cache tests: one model only, no concurrent unsafe inference."""
import sys
from types import SimpleNamespace

from asr import funasr_adapter as fa
from asr import model_pool


def test_model_pool_does_not_reload_identical_configuration():
    model_pool.clear_model()
    calls = []
    def load():
        instance = object()
        calls.append(instance)
        return instance
    a, lock_a, reused_a = model_pool.acquire_model(("zh", "cpu"), load)
    b, lock_b, reused_b = model_pool.acquire_model(("zh", "cpu"), load)
    assert a is b and lock_a is lock_b
    assert not reused_a and reused_b
    assert len(calls) == 1
    c, lock_c, reused_c = model_pool.acquire_model(("zh", "cuda"), load)
    assert c is not a and lock_c is not lock_a and not reused_c
    assert len(calls) == 2
    model_pool.clear_model()
    assert model_pool.cache_info()["occupied"] is False


def test_funasr_adapter_reuses_loaded_model_between_video_jobs(monkeypatch, tmp_path):
    model_pool.clear_model()
    calls = []
    class FakeAutoModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def generate(self, **kwargs):
            return [{"sentence_info": [{
                "start": 0, "end": 1200, "text": "你好", "spk": "spk0"}]}]
    monkeypatch.setitem(sys.modules, "funasr",
                        SimpleNamespace(AutoModel=FakeAutoModel))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    monkeypatch.setattr(fa, "_wav_duration_sec", lambda _: 1.5)
    def adapter():
        return fa.FunASRAdapter("asr", "vad", "punc", "spk",
                                backend="automodel", keep_loaded=True)
    first = adapter()
    second = adapter()
    assert len(first.transcribe(tmp_path / "video1.wav")) == 1
    assert len(second.transcribe(tmp_path / "video2.wav")) == 1
    assert len(calls) == 1
    assert first._pipe is second._pipe
    assert first._inference_lock is second._inference_lock
    assert first.metrics["reused_loaded_model"] is False
    assert second.metrics["reused_loaded_model"] is True
    assert second.metrics["model_load_seconds"] < .1
    model_pool.clear_model()


def test_disabling_ram_cache_actually_evicts_prior_resident_model(monkeypatch, tmp_path):
    # Switching the UI toggle off must remove the previous model, not just
    # construct an uncached second instance while the first remains in RAM.
    from asr import model_pool
    model_pool.clear_model()
    calls = []
    class LightweightModel:
        def __init__(self, **kw):
            calls.append(kw)
        def generate(self, **kw):
            return [{"sentence_info": [{"start": 0, "end": 1200,
                                         "text": "你好", "spk": "spk0"}]}]
    monkeypatch.setitem(sys.modules, "funasr",
                        SimpleNamespace(AutoModel=LightweightModel))
    monkeypatch.setenv("MODELSCOPE_CACHE", str(tmp_path))
    monkeypatch.setattr(fa, "_wav_duration_sec", lambda _: 2.)
    with_cache = fa.FunASRAdapter("a", "v", "p", "s", backend="automodel",
                                  keep_loaded=True)
    assert with_cache.transcribe(tmp_path / "first.wav")
    assert model_pool.cache_info()["occupied"]
    without_cache = fa.FunASRAdapter("a", "v", "p", "s", backend="automodel",
                                     keep_loaded=False)
    assert without_cache.transcribe(tmp_path / "second.wav")
    assert not model_pool.cache_info()["occupied"]
    assert len(calls) == 2
