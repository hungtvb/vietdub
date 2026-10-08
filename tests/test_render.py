# Edge case 11: burn subtitles via intermediate .srt FILE (never inline text
# in filter args) - even with quotes/% in text. Real ffmpeg burn on a tiny
# video. Edge case 13: unicode output path.
import subprocess

import pytest

from media import render as mrender
from media import subs as msubs
from project.schema import Segment


def _tiny_video(path):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=3:size=160x120:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)], check=True)


def _tiny_wav(path):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=880:duration=3",
         "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(path)],
        check=True)


def test_burn_special_chars(tmp_path):
    # edge case 11
    tricky = "Cô ấy nói: 'giảm 50%' rồi đi."
    segs = [Segment(index=0, start=0.5, end=2.5, speaker=0, text_vi=tricky)]
    srt = msubs.write_srt(segs, tmp_path / "t.srt")
    v, a = tmp_path / "v.mp4", tmp_path / "a.wav"
    _tiny_video(v)
    _tiny_wav(a)
    out = mrender.render(v, a, srt, tmp_path / "out.mp4", sub_mode="burn")
    assert out.exists() and out.stat().st_size > 1000


def test_srt_sidecar_mode(tmp_path):
    segs = [Segment(index=0, start=0.5, end=2.5, speaker=0, text_vi="Xin chào")]
    srt = msubs.write_srt(segs, tmp_path / "t.srt")
    v, a = tmp_path / "v.mp4", tmp_path / "a.wav"
    _tiny_video(v)
    _tiny_wav(a)
    out = mrender.render(v, a, srt, tmp_path / "out.mp4", sub_mode="srt")
    assert out.exists()
    sidecar = tmp_path / "out.srt"
    assert sidecar.exists()
    assert "Xin chào" in sidecar.read_text(encoding="utf-8")


def test_unicode_output_path(tmp_path):
    # edge case 13
    segs = [Segment(index=0, start=0.5, end=2.5, speaker=0, text_vi="Chào")]
    srt = msubs.write_srt(segs, tmp_path / "t.srt")
    v, a = tmp_path / "v.mp4", tmp_path / "a.wav"
    _tiny_video(v)
    _tiny_wav(a)
    out = mrender.render(v, a, srt, tmp_path / "video đã lồng tiếng.mp4",
                         sub_mode="srt")
    assert out.exists()


def test_escape_sub_path_windows():
    # review fix: backslash->slash FIRST, then escape : and '.
    # D:\jobs\a\subs.vi.srt must become D\:/jobs/a/subs.vi.srt
    from pathlib import PureWindowsPath
    p = PureWindowsPath(r"D:\jobs\a\subs.vi.srt")
    assert mrender._escape_sub_path(p) == r"D\:/jobs/a/subs.vi.srt"


def test_escape_sub_path_posix():
    # no backslashes: only : and ' get escaped
    assert mrender._escape_sub_path("/tmp/a b/c's.srt") == "/tmp/a b/c\\'s.srt"
    assert mrender._escape_sub_path("/tmp/x:y/z.srt") == "/tmp/x\\:y/z.srt"


def test_bad_sub_mode(tmp_path):
    segs = [Segment(index=0, start=0.5, end=2.5, speaker=0, text_vi="Chào")]
    srt = msubs.write_srt(segs, tmp_path / "t.srt")
    v, a = tmp_path / "v.mp4", tmp_path / "a.wav"
    _tiny_video(v)
    _tiny_wav(a)
    with pytest.raises(mrender.RenderError) as e:
        mrender.render(v, a, srt, tmp_path / "o.mp4", sub_mode="bogus")
    assert "sub_mode" in str(e.value)
