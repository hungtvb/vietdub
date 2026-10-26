# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Offline integration tests for the optional VieNeu provider (no model download)."""
from __future__ import annotations

import hashlib
import shutil

import numpy as np
import pytest
import soundfile as sf

from core.settings import Settings
from project.schema import Project, Segment
from tts.provider import create_tts
from tts.vieneu_tts import VieNeuTTS, VieNeuTTSError, _cache_key


class FakeVieNeu:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def infer(self, text, voice):
        self.calls.append((text, voice))
        if self.fail:
            raise RuntimeError("inference failed")
        return np.zeros(48000, dtype=np.float32)

    def save(self, audio, path):
        sf.write(path, audio, 48000)


def sample(index=1, text="Xin chào", gender="male"):
    return Segment(index=index, start=0.0, end=2.0, speaker=0,
                   gender=gender, text_vi=text)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_generates_compatible_wav_and_reuses_cache(tmp_path):
    fake = FakeVieNeu()
    tts = VieNeuTTS(engine_factory=lambda *args: fake)
    male = sample(1)
    female = sample(2, "Cảm ơn", "female")
    result = tts.synthesize([male, female], tmp_path)
    assert result == [male, female]
    assert fake.calls == [("Xin chào", "Hải Đăng"), ("Cảm ơn", "Mai Anh")]
    for seg in result:
        info = sf.info(seg.audio_vi)
        assert info.samplerate == 44100
        assert info.channels == 1
        assert info.frames > 0
    again = [sample(1), sample(2, "Cảm ơn", "female")]
    tts.synthesize(again, tmp_path)
    assert len(fake.calls) == 2
    assert all(s.audio_vi for s in again)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_text_voice_provider_cache_invalidation(tmp_path):
    fake = FakeVieNeu()
    tts = VieNeuTTS(engine_factory=lambda *args: fake)
    tts.synthesize([sample()], tmp_path)
    tts.synthesize([sample(1, "Nội dung khác")], tmp_path)
    tts2 = VieNeuTTS(voice_male="Thiện Minh", engine_factory=lambda *args: fake)
    tts2.synthesize([sample(1, "Nội dung khác")], tmp_path)
    assert len(fake.calls) == 3
    # A cached Edge-TTS digest must never validate a VieNeu-rendered WAV.
    edge_digest = hashlib.md5(
        "vi-VN-NamMinhNeural|+0%|+0Hz|Nội dung khác".encode()).hexdigest()
    assert (tmp_path / "seg_0001.md5").read_text() != edge_digest
    assert _cache_key("Nội dung khác", "Thiện Minh", "auto", "fp32")


def test_fail_loudly_instead_of_silent_placeholder(tmp_path):
    dest = tmp_path / "seg_0001.wav"
    sf.write(dest, np.zeros(44100, dtype=np.float32), 44100)
    (tmp_path / "seg_0001.md5").write_text("stale")
    tts = VieNeuTTS(engine_factory=lambda *args: FakeVieNeu(fail=True))
    seg = sample()
    with pytest.raises(VieNeuTTSError, match="câu 1"):
        tts.synthesize([seg], tmp_path)
    assert not dest.exists()
    assert not (tmp_path / "seg_0001.md5").exists()
    assert seg.audio_vi == ""


def test_factory_defaults_and_project_compatibility(tmp_path):
    settings = Settings(path=tmp_path / "settings.json")
    assert create_tts(settings).__class__.__name__ == "EdgeTTS"
    assert Project.from_dict({"name": "old"}).tts_provider == "edge"
    settings.set("tts_provider", "vieneu")
    settings.set("vieneu_voice_male", "Thiện Minh")
    tts = create_tts(settings)
    assert isinstance(tts, VieNeuTTS)
    assert tts.voice_male == "Thiện Minh"
    assert tts.voice_female == "Mai Anh"
    assert create_tts(settings, provider="edge").__class__.__name__ == "EdgeTTS"
    with pytest.raises(ValueError, match="provider"):
        create_tts(settings, provider="unsupported")


def test_invalid_engine_config_rejected():
    with pytest.raises(ValueError, match="backend"):
        VieNeuTTS(backend="banana")
    with pytest.raises(ValueError, match="precision"):
        VieNeuTTS(precision="fp16")
