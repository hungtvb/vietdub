# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Step [6] fallback - gTTS (single Vietnamese voice).

Fallback chain (DESIGN.md section 2, edge case 6): when Edge-TTS fails for
ALL sentences (websocket down), the orchestrator falls back to gTTS.
Single voice only (no male/female split) - the log says so explicitly.

Same synthesize() interface as EdgeTTS, including the per-sentence
md5 cache: re-running resumes from the first missing sentence.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Callable, List, Optional

from media import _bin
from project.schema import Segment

log = logging.getLogger("vietdub.tts.gtts")

RETRY_NUMS = 2


class GTTSError(Exception):
    pass


def _vail_file(path: str | Path, min_bytes: int = 1024) -> bool:
    p = Path(path)
    return p.exists() and p.stat().st_size >= min_bytes


def _mp3_to_wav(mp3_path: str | Path, wav_path: str | Path) -> None:
    import subprocess
    p = subprocess.run(
        [_bin.ffmpeg_cmd(), "-y", "-v", "error", "-i", str(mp3_path),
         "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)],
        capture_output=True, text=True)
    if p.returncode != 0 or not Path(wav_path).exists():
        raise RuntimeError(f"đổi mp3->wav lỗi: {p.stderr[:200]}")


class GTTS:
    """gTTS fallback: one Vietnamese voice for every sentence."""

    name = "gtts"

    def __init__(self, retries: int = RETRY_NUMS):
        self.retries = retries

    def _synthesize_one(self, text: str, mp3_path: Path) -> bool:
        try:
            from gtts import gTTS as _LibGTTS
        except ImportError as e:
            raise GTTSError(
                "Chưa cài thư viện gtts.\n"
                "Cách khắc phục: pip install gtts") from e
        for attempt in range(self.retries + 1):
            try:
                _LibGTTS(text=text, lang="vi").save(str(mp3_path))
                if _vail_file(mp3_path, min_bytes=512):
                    return True
                raise RuntimeError("gTTS trả về file rỗng")
            except Exception as e:  # noqa: BLE001
                log.warning("gTTS lỗi (lần %d): %s", attempt + 1, str(e)[:160])
                if attempt < self.retries:
                    time.sleep(2 * (attempt + 1))
        return False

    def synthesize(self, segments: List[Segment], out_dir: str | Path,
                   progress_cb: Optional[Callable[[int, int], None]] = None
                   ) -> List[Segment]:
        """Synthesize each segment -> stages/tts/seg_<index>.wav (giọng đơn).

        Same fail policy as EdgeTTS: only raises when ALL sentences fail;
        single failures leave audio_vi empty and duration_fit inserts silence.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = err = 0
        did_work = False  # True once we actually call the network
        for seg in segments:
            text = (seg.text_vi or seg.text_src or "").strip()
            fname = out_dir / f"seg_{seg.index:04d}.wav"
            if not text:
                continue
            key_file = fname.with_suffix(".md5")
            key = "gtts|" + hashlib.md5(text.encode("utf-8")).hexdigest()
            if _vail_file(fname) and key_file.exists() \
                    and key_file.read_text().strip() == key:
                seg.audio_vi = str(fname)
                continue
            did_work = True
            key_file.write_text(key)
            mp3 = fname.with_suffix(".mp3")
            if self._synthesize_one(text, mp3):
                _mp3_to_wav(mp3, fname)
                mp3.unlink(missing_ok=True)
                seg.audio_vi = str(fname)
                ok += 1
            else:
                err += 1
                log.warning("câu %d gTTS lỗi -> chèn im lặng ở bước khớp giờ",
                            seg.index)
        log.info("gTTS xong: %d ok, %d lỗi (giọng đơn, không phân biệt nam/nữ)",
                 ok, err)
        if did_work and ok == 0:
            raise GTTSError(
                "gTTS thất bại toàn bộ (mạng chặn hoặc Google từ chối).\n"
                "Cách khắc phục: kiểm tra mạng rồi chạy lại.")
        if progress_cb:
            progress_cb(len(segments), len(segments))
        return segments
