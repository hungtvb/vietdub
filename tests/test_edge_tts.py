# Edge case 10: TTS disconnect mid-run -> per-sentence checkpoint, resume
# continues from the missing sentence. All-fail -> raise. Existing -> skip.
import asyncio
from pathlib import Path
from unittest import mock

import pytest

from project.schema import Segment
from tts import edge_tts as metts


def _segs(n):
    return [Segment(index=i, start=float(i), end=float(i + 1), speaker=i % 2,
                    gender="female" if i % 2 == 0 else "male",
                    text_src=f"câu {i}", text_vi=f"câu việt {i}")
            for i in range(n)]


class FakeComm:
    """Mimics edge_tts.Communicate.save(). fail_at: raise on that call #."""
    calls = 0
    fail_at = None

    def __init__(self, text, voice, rate, pitch):
        self.text = text

    async def save(self, mp3_path):
        FakeComm.calls += 1
        if FakeComm.fail_at is not None and FakeComm.calls >= FakeComm.fail_at:
            raise ConnectionError("websocket disconnect")
        # write a tiny valid mp3-ish file (mp3->wav uses ffmpeg; write real mp3)
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=0.5",
             "-c:a", "libmp3lame", mp3_path], check=True)


@pytest.fixture(autouse=True)
def _reset():
    FakeComm.calls = 0
    FakeComm.fail_at = None
    yield


def _factory(text, voice, rate, pitch):
    return FakeComm(text, voice, rate, pitch)


def test_disconnect_then_resume(tmp_path):
    # edge case 10
    tts = metts.EdgeTTS(communicate_factory=_factory, retries=0,
                        concurrency=1)
    out = tmp_path / "tts"
    FakeComm.fail_at = 6  # dies on the 6th sentence
    segs = _segs(8)
    got = tts.synthesize(segs, out)
    done = [s for s in got if s.audio_vi]
    assert len(done) == 5  # 0..4 ok, 5..7 failed -> silence later

    # resume: new instance, no failures -> completes the rest
    FakeComm.fail_at = None
    tts2 = metts.EdgeTTS(communicate_factory=_factory, retries=0,
                         concurrency=1)
    got2 = tts2.synthesize(segs, out)
    assert all(s.audio_vi for s in got2)
    assert all(Path(s.audio_vi).exists() for s in got2)


def test_all_fail_raises(tmp_path):
    tts = metts.EdgeTTS(communicate_factory=_factory, retries=0,
                        concurrency=1)
    FakeComm.fail_at = 1  # every call fails
    with pytest.raises(metts.TTSError) as e:
        tts.synthesize(_segs(3), tmp_path / "vd_tts_allfail")
    assert "thất bại toàn bộ" in str(e.value)


def test_voice_mapping():
    tts = metts.EdgeTTS()
    assert tts.voice_for("female") == "vi-VN-HoaiMyNeural"
    assert tts.voice_for("male") == "vi-VN-NamMinhNeural"


def test_rate_pitch_cleaned():
    tts = metts.EdgeTTS(rate="10%", pitch="5Hz")
    assert tts.rate == "+10%"
    assert tts.pitch == "+5Hz"
    tts2 = metts.EdgeTTS(rate="bogus", pitch="bogus")
    assert tts2.rate == "+0%"
    assert tts2.pitch == "+0Hz"
