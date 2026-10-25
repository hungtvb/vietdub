"""Small cached poster image for video previews."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from threading import Lock

from media import _bin

_lock = Lock()


def poster_for(video_path: str | Path, cache_dir: str | Path) -> Path | None:
    video_path = Path(video_path)
    cache_dir = Path(cache_dir)
    with _lock:
        try:
            if not video_path.is_file():
                return None
            cache_dir.mkdir(parents=True, exist_ok=True)
            stat = video_path.stat()
            identity = f"{video_path}:{stat.st_size}:{stat.st_mtime_ns}"
            key = hashlib.md5(identity.encode("utf-8")).hexdigest()[:12]
            poster = cache_dir / f"poster-{key}.jpg"
            if poster.is_file() and poster.stat().st_size > 0:
                return poster
        except OSError:
            return None
        for seek in ("1", "0"):
            try:
                subprocess.run(
                    [_bin.ffmpeg_cmd(), "-y", "-v", "error", "-ss", seek,
                     "-i", str(video_path), "-frames:v", "1",
                     "-vf", "scale=960:-2", str(poster)],
                    capture_output=True, timeout=10, check=True)
            except (OSError, subprocess.SubprocessError):
                continue
            if poster.is_file() and poster.stat().st_size > 0:
                return poster
        if poster.is_file() and poster.stat().st_size > 0:
            return poster
        return None
