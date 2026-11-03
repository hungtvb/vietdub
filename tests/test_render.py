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


def test_no_subtitle_mode_has_no_text_track(tmp_path):
    """No subtitle track or new burned-in text (old burned-in pixels are separate)."""
    segs = [Segment(index=0, start=.3, end=1.5, speaker=0, text_vi="Xin chào")]
    srt = msubs.write_srt(segs, tmp_path / "t.srt")
    v, a = tmp_path / "v.mp4", tmp_path / "a.wav"
    _tiny_video(v)
    _tiny_wav(a)
    out = mrender.render(v, a, srt, tmp_path / "no_subs.mp4", sub_mode="none")
    assert out.is_file()
    assert not out.with_suffix(".srt").exists()
    import shutil
    if shutil.which("ffprobe"):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
             "stream=index", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True)
        assert probe.stdout.strip() == ""
    else:
        # Portable imageio-ffmpeg smoke runners may not ship ffprobe.
        probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out)],
                               capture_output=True, text=True)
        assert "Stream #" in probe.stderr
        assert "Subtitle:" not in probe.stderr


@pytest.mark.parametrize("sub_mode", ["none", "burn"])
def test_short_dub_audio_must_not_drop_end_frames(tmp_path, sub_mode):
    """Regression from real 91.8s output: -shortest clipped two source frames."""
    cv2 = pytest.importorskip("cv2")
    v, a = tmp_path/"v.mp4", tmp_path/"short.wav"
    _tiny_video(v)  # 30 frames at 10 fps
    subprocess.run(
        ["ffmpeg","-v","error","-y","-f","lavfi",
         "-i","sine=frequency=770:duration=0.5",
         "-ac","1","-ar","44100",str(a)],
        check=True)
    srt = msubs.write_srt(
        [Segment(index=0,start=0.5,end=2,speaker=0,text_vi="Chào")],
        tmp_path/"text.srt")
    result=mrender.render(v,a,srt,tmp_path/"retained.mp4",sub_mode=sub_mode)
    cap=cv2.VideoCapture(str(result))
    assert cap.isOpened()
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 30
    # Actually decode the final frames, not just trust container metadata.
    cap.set(cv2.CAP_PROP_POS_FRAMES,29)
    ok,last=cap.read()
    cap.release()
    assert ok and last is not None
