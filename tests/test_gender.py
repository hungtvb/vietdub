# Gender estimation on synthetic tones (real librosa/pyin).
import numpy as np
import soundfile as sf

from project.schema import Segment
from speaker import gender as mgender


def _tone_wav(path, freqs, sr=16000, each_sec=2.0):
    """freqs: list of (freq_hz, speaker_id) -> wav + segments."""
    parts, segs = [], []
    t = 0.0
    for i, (f, spk) in enumerate(freqs):
        n = int(each_sec * sr)
        tone = 0.5 * np.sin(2 * np.pi * f * np.arange(n) / sr)
        parts.append(tone.astype(np.float32))
        segs.append(Segment(index=i, start=t, end=t + each_sec,
                            speaker=spk, text_src=f"câu {i}"))
        t += each_sec
    sf.write(str(path), np.concatenate(parts), sr)
    return segs


def test_male_low_pitch(tmp_path):
    wav = tmp_path / "m.wav"
    segs = _tone_wav(wav, [(120.0, 0)])
    spk = mgender.estimate_genders(wav, segs)
    assert spk[0].gender == "male"
    assert abs(spk[0].median_hz - 120.0) < 15


def test_female_high_pitch(tmp_path):
    wav = tmp_path / "f.wav"
    segs = _tone_wav(wav, [(220.0, 1)])
    spk = mgender.estimate_genders(wav, segs)
    assert spk[1].gender == "female"
    assert abs(spk[1].median_hz - 220.0) < 20


def test_two_speakers_mixed(tmp_path):
    wav = tmp_path / "mix.wav"
    segs = _tone_wav(wav, [(110.0, 0), (240.0, 1), (115.0, 0)])
    spk = mgender.estimate_genders(wav, segs)
    assert spk[0].gender == "male"
    assert spk[1].gender == "female"
    assert 0.0 < spk[0].confidence <= 1.0


def test_ambiguous_pitch_low_confidence(tmp_path):
    wav = tmp_path / "amb.wav"
    segs = _tone_wav(wav, [(162.0, 2)])  # between 160 and 165
    spk = mgender.estimate_genders(wav, segs)
    assert spk[2].confidence < 0.6
