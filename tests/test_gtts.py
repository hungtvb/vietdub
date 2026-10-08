# gTTS fallback (step [6]): single Vietnamese voice, per-sentence resume,
# all-fail raises. The real gtts library is faked (network is not needed).
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from project.schema import Segment
from tts import gtts as mgtts


def _segs(n):
    return [Segment(index=i, start=float(i), end=float(i + 1), speaker=i % 2,
                    gender="female" if i % 2 == 0 else "male",
                    text_src=f"câu {i}", text_vi=f"câu việt {i}")
            for i in range(n)]


def _fake_gtts_module(fail_texts=()):
    mod = types.ModuleType("gtts")

    class FakeLib:
        def __init__(self, text, lang):
            assert lang == "vi"  # single Vietnamese voice
            self.text = text

        def save(self, path):
            if self.text in fail_texts:
                raise RuntimeError("gtts network down")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "sine=frequency=440:duration=0.5",
                 "-c:a", "libmp3lame", path], check=True)

    mod.gTTS = FakeLib
    return mod


def test_gtts_synthesize_ok(tmp_path):
    g = mgtts.GTTS(retries=0)
    with mock.patch.dict(sys.modules, {"gtts": _fake_gtts_module()}):
        out = g.synthesize(_segs(2), tmp_path)
    assert all(s.audio_vi and Path(s.audio_vi).exists() for s in out)


def test_gtts_single_failure_leaves_silence_slot(tmp_path):
    g = mgtts.GTTS(retries=0)
    with mock.patch.dict(sys.modules,
                          {"gtts": _fake_gtts_module(fail_texts={"câu việt 1"})}):
        out = g.synthesize(_segs(2), tmp_path)
    assert out[0].audio_vi  # ok
    assert not out[1].audio_vi  # failed -> silence inserted at duration fit


def test_gtts_all_fail_raises(tmp_path):
    g = mgtts.GTTS(retries=0)
    with mock.patch.dict(sys.modules, {"gtts": _fake_gtts_module(
            fail_texts={"câu việt 0", "câu việt 1"})}):
        with pytest.raises(mgtts.GTTSError) as e:
            g.synthesize(_segs(2), tmp_path)
    assert "thất bại toàn bộ" in str(e.value)


def test_gtts_resume_skips_done(tmp_path):
    g = mgtts.GTTS(retries=0)
    segs = _segs(1)
    with mock.patch.dict(sys.modules, {"gtts": _fake_gtts_module()}):
        g.synthesize(segs, tmp_path)
    # second run with a broken lib: md5 cache hit -> no network call, no raise
    with mock.patch.dict(sys.modules, {"gtts": _fake_gtts_module(
            fail_texts={"câu việt 0"})}):
        out = g.synthesize(segs, tmp_path)
    assert out[0].audio_vi and Path(out[0].audio_vi).exists()


def test_gtts_missing_library_clear_message(tmp_path):
    g = mgtts.GTTS(retries=0)
    with mock.patch.dict(sys.modules, {"gtts": None}):
        with pytest.raises(mgtts.GTTSError) as e:
            g.synthesize(_segs(1), tmp_path)
    assert "pip install gtts" in str(e.value)
