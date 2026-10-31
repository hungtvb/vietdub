# Duration fit: edge case 1 (too long -> TooLongError -> split),
# edge case 2 (short slot -> max squeeze + overflow allowed, warning),
# edge case 3 (gaps preserved in built track).
import numpy as np
import soundfile as sf

import pytest

from project.schema import Segment
from tts import duration_fit as mfit


def _wav(path, sec, sr=44100):
    n = int(sec * sr)
    sf.write(str(path), np.zeros(n, dtype=np.float32), sr, subtype="PCM_16")
    return path


def test_keep_when_shorter(tmp_path):
    w = _wav(tmp_path / "a.wav", 2.0)
    seg = Segment(index=0, start=0.0, end=5.0, speaker=0, text_vi="x",
                  audio_vi=str(w))
    dec = mfit.plan([seg])
    assert dec[0][1] == "keep"


def test_atempo_when_slightly_long(tmp_path):
    w = _wav(tmp_path / "a.wav", 6.0)  # ratio 1.2 -> atempo 1/1.2
    seg = Segment(index=0, start=0.0, end=5.0, speaker=0, text_vi="x",
                  audio_vi=str(w))
    dec = mfit.plan([seg])
    assert dec[0][1] == "atempo"
    assert abs(dec[0][2] - 1.2) < 0.01  # speedup factor = dubb/slot
    mfit.apply_plan(dec)
    assert abs(mfit.wav_duration_sec(w) - 5.0) < 0.15


def test_too_long_raises_and_splits(tmp_path):
    # edge case 1
    w = _wav(tmp_path / "a.wav", 10.0)  # ratio 2.0 > 1.25
    seg = Segment(index=0, start=0.0, end=5.0, speaker=0,
                  text_vi="câu này rất dài, cần phải tách ra, để vừa khung giờ",
                  audio_vi=str(w))
    with pytest.raises(mfit.TooLongError):
        mfit.plan([seg])
    a, b = mfit.split_segment(seg)
    assert a.end == pytest.approx(b.start)
    assert b.end == pytest.approx(5.0)
    assert a.text_vi and b.text_vi  # both halves non-empty
    assert (a.text_vi + b.text_vi).replace(" ", "") == \
        seg.text_vi.replace(" ", "")  # nothing lost in the split


def test_short_slot_overflow_allowed(tmp_path, caplog):
    # edge case 2: 0.3s slot, small ratio -> squeeze + light overflow
    w = _wav(tmp_path / "a.wav", 0.42)
    seg = Segment(index=0, start=0.0, end=0.3, speaker=0, text_vi="ừ",
                  audio_vi=str(w))
    import logging
    with caplog.at_level(logging.WARNING, logger="vietdub.duration_fit"):
        dec = mfit.plan([seg])
    assert dec[0][1] == "overflow"
    assert any("quá ngắn" in r.message for r in caplog.records)


def test_missing_tts_becomes_silence(tmp_path):
    seg = Segment(index=0, start=1.0, end=3.0, speaker=0, text_vi="x",
                  audio_vi=str(tmp_path / "missing.wav"))
    dec = mfit.plan([seg])
    assert dec[0][1] == "keep"
    assert mfit.wav_duration_sec(seg.audio_vi) == pytest.approx(2.0, abs=0.05)


def test_build_track_preserves_gaps(tmp_path):
    # edge case 3: sentence at 0-1s and 5-6s -> 1-5s must stay silent
    w1 = _wav(tmp_path / "s1.wav", 1.0)
    w2 = _wav(tmp_path / "s2.wav", 1.0)
    # put a loud tone in w2 so silence is detectable
    sr = 44100
    tone = (0.5 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)).astype(np.float32)
    sf.write(str(w2), tone, sr, subtype="PCM_16")
    segs = [Segment(index=0, start=0.0, end=1.0, speaker=0, audio_vi=str(w1)),
            Segment(index=1, start=5.0, end=6.0, speaker=0, audio_vi=str(w2))]
    out = mfit.build_track(segs, tmp_path / "track.wav", 6.0)
    data, _ = sf.read(str(out), dtype="float32")
    gap = data[int(2 * sr):int(4 * sr)]
    assert np.abs(gap).max() < 1e-6  # silence preserved
    tail = data[int(5.2 * sr):int(5.8 * sr)]
    assert np.abs(tail).max() > 0.1  # sentence 2 placed at 5s


def test_segment_crossing_track_chunk_boundary_is_not_replayed(tmp_path):
    sr = 44100
    wav = tmp_path / "crossing.wav"
    # The second half differs so replaying the start at t=60 is observable.
    samples = np.r_[np.full(2 * sr, 0.1), np.full(2 * sr, 0.3)]
    sf.write(str(wav), samples, sr, subtype="PCM_16")
    seg = Segment(index=0, start=58.0, end=62.0, speaker=0,
                  audio_vi=str(wav))

    out = mfit.build_track([seg], tmp_path / "track.wav", 64.0)
    data, _ = sf.read(str(out), dtype="float32")

    assert data[int(59.0 * sr)] == pytest.approx(0.1, abs=0.02)
    assert data[int(60.5 * sr)] == pytest.approx(0.3, abs=0.02)
    assert np.abs(data[int(62.5 * sr)]).max() < 0.02


def test_severe_short_slot_overflow_is_blocked(tmp_path):
    # 4x slowdown would either overlap next dialogue or be truncated.
    w = _wav(tmp_path / "too_long.wav", 1.2)
    seg = Segment(index=8, start=0.0, end=0.3, speaker=0,
                  text_vi="Một câu quá dài.", audio_vi=str(w))
    with pytest.raises(mfit.SevereOverflowError, match="1"):
        mfit.plan([seg])


def test_severe_forced_overflow_is_blocked(tmp_path):
    w = _wav(tmp_path / "long.wav", 5.0)
    seg = Segment(index=9, start=0.0, end=2.0, speaker=0,
                  text_vi="không thể chia", audio_vi=str(w))
    with pytest.raises(mfit.SevereOverflowError):
        mfit.plan([seg], force_overflow={id(seg)})
