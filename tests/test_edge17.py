# Edge case 17: 90-minute films.
# - build_track works in 60s chunks (never holds the whole track in RAM)
# - peak RAM estimate + warning logic
# - ASR transcribes long wavs in 10-minute chunks with offset re-join
import logging

import numpy as np
import soundfile as sf

import asr.funasr_adapter as asr_mod
from asr.funasr_adapter import FunASRAdapter
from core import resources as mres
from project.schema import Segment
from tts import duration_fit as mfit


def _wav(path, sec, sr=44100, tone=False):
    n = int(sec * sr)
    if tone:
        data = (0.5 * np.sin(2 * np.pi * 440 * np.arange(n) / sr)).astype(np.float32)
    else:
        data = np.zeros(n, dtype=np.float32)
    sf.write(str(path), data, sr, subtype="PCM_16")
    return path


def test_build_track_chunks_join_correctly(tmp_path):
    # 5s total, 2s chunks -> 3 chunks; tone at 3.2-4.2s must survive the join
    w1 = _wav(tmp_path / "s1.wav", 1.0)
    w2 = _wav(tmp_path / "s2.wav", 1.0, tone=True)
    segs = [Segment(index=0, start=0.0, end=1.0, speaker=0, audio_vi=str(w1)),
            Segment(index=1, start=3.2, end=4.2, speaker=0, audio_vi=str(w2))]
    out = mfit.build_track(segs, tmp_path / "track.wav", 5.0, chunk_sec=2.0)
    data, sr = sf.read(str(out), dtype="float32")
    assert abs(len(data) / sr - 5.0) < 0.05
    gap = data[int(1.5 * sr):int(2.5 * sr)]
    assert np.abs(gap).max() < 1e-6  # silence preserved across chunk boundary
    tone = data[int(3.4 * sr):int(4.0 * sr)]
    assert np.abs(tone).max() > 0.1  # tone survived chunking


def test_build_track_single_chunk_still_works(tmp_path):
    w = _wav(tmp_path / "s.wav", 1.0, tone=True)
    segs = [Segment(index=0, start=0.5, end=1.5, speaker=0, audio_vi=str(w))]
    out = mfit.build_track(segs, tmp_path / "t.wav", 3.0)  # default 60s chunks
    data, sr = sf.read(str(out), dtype="float32")
    assert abs(len(data) / sr - 3.0) < 0.05
    assert np.abs(data[int(0.7 * sr):int(1.3 * sr)]).max() > 0.1


def test_ram_estimate_90min():
    est = mres.estimate_peak_ram_mb(5400.0)
    # ASR models 1800 + full 16k wav 329MB + chunk 10.6 + ffmpeg 300
    assert 2400 < est < 2600
    assert mres.estimate_peak_ram_mb(60.0) < est  # grows with duration


def test_check_ram_warns_when_tight(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr(mres, "total_ram_mb", lambda: 2000.0)
    with caplog.at_level(logging.WARNING, logger="vietdub.resources"):
        est = mres.check_ram(5400.0)
    assert est > 2000 * 0.85
    assert any("CẢNH BÁO" in r.message for r in caplog.records)


def test_check_ram_quiet_when_enough(monkeypatch, caplog):
    monkeypatch.setattr(mres, "total_ram_mb", lambda: 16000.0)
    with caplog.at_level(logging.WARNING, logger="vietdub.resources"):
        mres.check_ram(5400.0)
    assert not [r for r in caplog.records if "CẢNH BÁO" in r.message]


def _long_wav(path, sec):
    return _wav(path, sec, sr=16000)


def test_asr_short_wav_single_call(tmp_path, monkeypatch):
    ad = FunASRAdapter("a", "v", "p", "s")
    ad.load = lambda: None
    calls = []
    monkeypatch.setattr(
        ad, "_transcribe_one",
        lambda p: calls.append(p) or
        [Segment(index=0, start=0.0, end=1.0, speaker=0,
                 text_src="你好", confidence=1.0)])
    monkeypatch.setattr(asr_mod, "ASR_CHUNK_SEC", 60.0)
    segs = ad.transcribe(_long_wav(tmp_path / "short.wav", 30.0))
    assert len(calls) == 1
    assert len(segs) == 1 and segs[0].start == 0.0


def test_asr_long_wav_chunked_with_offset(tmp_path, monkeypatch):
    ad = FunASRAdapter("a", "v", "p", "s")
    ad.load = lambda: None
    seen = []

    def fake_one(path):
        seen.append(path)
        # each chunk pretends to hold one sentence at its own 0-1s
        return [Segment(index=0, start=0.0, end=1.0, speaker=0,
                        text_src="你好", confidence=1.0)]

    monkeypatch.setattr(ad, "_transcribe_one", fake_one)
    monkeypatch.setattr(asr_mod, "ASR_CHUNK_SEC", 5.0)  # 5s chunks for the test
    segs = ad.transcribe(_long_wav(tmp_path / "long.wav", 12.0))
    assert len(seen) == 3  # 0-5, 5-10, 10-12
    assert [s.start for s in segs] == [0.0, 5.0, 10.0]
    assert [s.end for s in segs] == [1.0, 6.0, 11.0]
    assert [s.index for s in segs] == [0, 1, 2]  # post_fix renumbered
