# Mix: dub 100% + original attenuated. Real ffmpeg on synthetic wavs.
import numpy as np
import soundfile as sf
import subprocess

import pytest

from media import mix as mmix


def _wav(path, sec, freq, sr=44100, amp=0.5):
    n = int(sec * sr)
    tone = (amp * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float32)
    sf.write(str(path), tone, sr, subtype="PCM_16")


def test_mix_real_ffmpeg(tmp_path):
    dub = tmp_path / "dub.wav"
    orig = tmp_path / "orig.wav"
    _wav(dub, 2.0, 440, amp=0.5)
    _wav(orig, 2.0, 880, amp=0.5)
    out = mmix.mix(dub, orig, tmp_path / "mixed.wav",
                   dub_volume=1.0, orig_volume=0.15)
    assert out.exists()
    data, sr = sf.read(str(out), dtype="float32")
    assert len(data) > 0
    # dub must dominate: energy near 440Hz >> energy near 880Hz
    spec = np.abs(np.fft.rfft(data.mean(axis=1) if data.ndim > 1 else data))
    freqs = np.fft.rfftfreq(len(data), 1 / sr)
    e440 = spec[(freqs > 400) & (freqs < 480)].sum()
    e880 = spec[(freqs > 840) & (freqs < 920)].sum()
    assert e440 > e880 * 2


def test_mix_missing_input(tmp_path):
    with pytest.raises(mmix.MixError):
        mmix.mix(tmp_path / "nope.wav", tmp_path / "nope2.wav",
                 tmp_path / "o.wav")
