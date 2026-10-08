# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Step [0] - fetch video. Local file -> pass through. http(s) link ->
download with yt-dlp (best mp4) into the job dir.

Edge case 18: bad link / login required / 403 / IP blocked -> friendly
Vietnamese error, 2 retries, never crash; message suggests downloading
manually and using the File tab instead.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("vietdub.fetch")

MAX_RETRIES = 2  # retries after the first attempt (3 tries total)


class FetchError(Exception):
    """Raised when a video link cannot be downloaded. Message is user-facing
    Vietnamese (safe to show in UI / logs)."""


def is_url(source: str) -> bool:
    s = (source or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def _friendly_message(url: str, raw: str) -> str:
    low = raw.lower()
    if any(k in low for k in ("login required", "sign in", "log in", "private video",
                              "cookies", "account")):
        return (f"Link yêu cầu đăng nhập tài khoản mới tải được.\n"
                f"Gợi ý: tải video về máy bằng tay rồi dùng tab File để lồng tiếng.")
    if "403" in low or "forbidden" in low:
        return (f"Máy chủ chặn tải link này (lỗi 403).\n"
                f"Gợi ý: tải video về máy bằng tay rồi dùng tab File để lồng tiếng.")
    if any(k in low for k in ("ip", "region", "geo", "not available in your country",
                              "blocked", "地域")):
        return (f"Link bị chặn theo khu vực/IP (thường gặp với Douyin).\n"
                f"Gợi ý: tải video về máy bằng tay (đổi mạng/VPN) rồi dùng tab File.")
    if any(k in low for k in ("unsupported url", "no video", "not found", "404",
                              "unable to", "name or service not known", "failed to resolve")):
        return (f"Link sai hoặc không tải được video từ link này.\n"
                f"Kiểm tra lại link, hoặc tải video về máy bằng tay rồi dùng tab File.")
    return (f"Không tải được video từ link (lỗi: {raw[:160]}).\n"
            f"Gợi ý: tải video về máy bằng tay rồi dùng tab File để lồng tiếng.")


def download(url: str, dest_path: str | Path,
             progress_cb: Optional[Callable[[float, str], None]] = None,
             max_retries: int = MAX_RETRIES) -> Path:
    """Download best-mp4 from url to dest_path. Returns dest_path.

    progress_cb(pct, speed_str) is called by yt-dlp's progress hook
    (Wave 2 UI shows % + speed).
    """
    try:
        import yt_dlp
    except ImportError as e:
        raise FetchError("Thiếu thư viện yt-dlp. Cài: pip install yt-dlp") from e

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _hook(d):
        if not progress_cb:
            return
        try:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                pct = (done / total * 100.0) if total else 0.0
                speed = d.get("speed_str", "") or ""
                progress_cb(pct, speed.strip())
        except Exception:
            pass

    opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": str(dest),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [_hook],
        "retries": 2,
        "fragment_retries": 2,
    }

    last_err = ""
    for attempt in range(max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if not dest.exists() or dest.stat().st_size == 0:
                raise RuntimeError("file tải về rỗng")
            log.info("downloaded %s -> %s", url, dest)
            return dest
        except Exception as e:  # noqa: BLE001 - mapped to friendly message below
            last_err = str(e)
            log.warning("fetch attempt %d/%d failed: %s", attempt + 1,
                        max_retries + 1, last_err[:200])
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
    raise FetchError(_friendly_message(url, last_err))


def resolve(source: str, job_dir: str | Path,
            progress_cb: Optional[Callable[[float, str], None]] = None) -> Path:
    """Step [0] entry: local file -> return as-is; link -> download to
    jobs/<job_id>/source.mp4."""
    if not is_url(source):
        p = Path(source)
        if not p.exists():
            raise FetchError(f"Không tìm thấy file video: {source}")
        return p
    dest = Path(job_dir) / "source.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        log.info("reuse already-downloaded %s", dest)
        return dest
    return download(source, dest, progress_cb=progress_cb)
