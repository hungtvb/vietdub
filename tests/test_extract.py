# Edge case 6: no audio track -> clear Vietnamese error, clean stop.
# Edge case 12: multi audio tracks -> list, default track 0.
# Edge case 13: unicode path (dấu + cách) via list args, no shell=True.
import subprocess

import pytest

from media import extract as mextract
from project.schema import Segment


def _make_video(path, with_audio=True, audio_tracks=1):
    """Tiny 2s test video with/without audio track(s)."""
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", "testsrc=duration=2:size=128x128:rate=10"]
    n_aud = audio_tracks if with_audio else 0
    for _ in range(n_aud):
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    cmd += ["-map", "0:v"]
    for i in range(n_aud):
        cmd += ["-map", f"{i + 1}:a"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, check=True)


def test_no_audio_track_raises_clear_error(tmp_path):
    # edge case 6
    v = tmp_path / "silent.mp4"
    _make_video(v, with_audio=False)
    with pytest.raises(mextract.ExtractError) as e:
        mextract.extract_audio(v, tmp_path / "a.wav")
    assert "không có track audio" in str(e.value)


def test_extract_ok_and_format(tmp_path):
    v = tmp_path / "clip.mp4"
    _make_video(v, with_audio=True)
    out = mextract.extract_audio(v, tmp_path / "a.wav")
    info = mextract.probe(out)
    st = info["streams"][0]
    assert st["sample_rate"] == "16000"
    assert st["channels"] == 1


def test_multi_audio_tracks_default_zero(tmp_path):
    # edge case 12
    v = tmp_path / "multi.mp4"
    _make_video(v, with_audio=True, audio_tracks=2)
    streams = mextract.audio_streams(v)
    assert len(streams) == 2
    out = mextract.extract_audio(v, tmp_path / "a.wav", audio_track=0)
    assert out.exists()
    with pytest.raises(mextract.ExtractError):
        mextract.extract_audio(v, tmp_path / "b.wav", audio_track=5)


def test_unicode_path(tmp_path):
    # edge case 13: dấu + cách, no shell=True anywhere
    v = tmp_path / "video thử nghiệm có dấu.mp4"
    _make_video(v, with_audio=True)
    out = tmp_path / "âm thanh trích ra.wav"
    got = mextract.extract_audio(v, out)
    assert got.exists()
