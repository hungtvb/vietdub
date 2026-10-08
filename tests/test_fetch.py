# Edge case 18: bad link / login / 403 / IP-blocked -> Vietnamese message,
# 2 retries, no crash. Local file -> pass through.
from unittest import mock

import pytest

from media import fetch as mfetch


def _boom(msg):
    import yt_dlp
    return yt_dlp.utils.DownloadError(msg)


def _run_download(monkeypatch, exc):
    calls = {"n": 0}

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def download(self, urls):
            calls["n"] += 1
            raise exc

    monkeypatch.setattr("yt_dlp.YoutubeDL", FakeYDL)
    return calls


def test_login_required_message_and_retries(tmp_path, monkeypatch):
    calls = _run_download(monkeypatch, _boom("Sign in to confirm your age"))
    with pytest.raises(mfetch.FetchError) as e:
        mfetch.download("https://example.com/v", tmp_path / "s.mp4")
    assert calls["n"] == 3  # 1 try + 2 retries
    assert "đăng nhập" in str(e.value)


def test_403_message(tmp_path, monkeypatch):
    _run_download(monkeypatch, _boom("HTTP Error 403: Forbidden"))
    with pytest.raises(mfetch.FetchError) as e:
        mfetch.download("https://example.com/v", tmp_path / "s.mp4")
    assert "403" in str(e.value)


def test_douyin_ip_blocked(tmp_path, monkeypatch):
    _run_download(monkeypatch, _boom("This video is not available in your region"))
    with pytest.raises(mfetch.FetchError) as e:
        mfetch.download("https://douyin.com/x", tmp_path / "s.mp4")
    assert "khu vực/IP" in str(e.value)


def test_bad_link_message(tmp_path, monkeypatch):
    _run_download(monkeypatch, _boom("Unsupported URL: https://x"))
    with pytest.raises(mfetch.FetchError) as e:
        mfetch.download("https://x", tmp_path / "s.mp4")
    assert "tab File" in str(e.value)


def test_all_messages_suggest_manual_download(tmp_path, monkeypatch):
    # every FetchError must point the user to the File tab (edge 18)
    for msg in ("Login required", "403 Forbidden", "blocked by region",
                "Name or service not known"):
        _run_download(monkeypatch, _boom(msg))
        with pytest.raises(mfetch.FetchError) as e:
            mfetch.download("https://example.com/v", tmp_path / "s.mp4")
        assert "tab File" in str(e.value), msg


def test_local_file_passthrough(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"fake")
    out = mfetch.resolve(str(f), tmp_path)
    assert out == f


def test_missing_local_file(tmp_path):
    with pytest.raises(mfetch.FetchError):
        mfetch.resolve(str(tmp_path / "nope.mp4"), tmp_path)


def test_progress_callback(tmp_path, monkeypatch):
    seen = []

    class FakeYDL:
        def __init__(self, opts):
            self.hook = opts["progress_hooks"][0]
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def download(self, urls):
            self.hook({"status": "downloading", "downloaded_bytes": 50,
                       "total_bytes": 100, "speed_str": "1MiB/s"})
            # simulate finished file
            import pathlib
            pathlib.Path(self.out).write_bytes(b"x" * 10)
        out = None

    orig_init = FakeYDL.__init__
    def patched_init(self, opts):
        orig_init(self, opts)
        self.out = opts["outtmpl"]
    monkeypatch.setattr(FakeYDL, "__init__", patched_init)
    monkeypatch.setattr("yt_dlp.YoutubeDL", FakeYDL)
    dest = tmp_path / "s.mp4"
    mfetch.download("https://example.com/v", dest,
                    progress_cb=lambda pct, spd: seen.append((pct, spd)))
    assert seen and abs(seen[0][0] - 50.0) < 0.01
    assert dest.exists()
