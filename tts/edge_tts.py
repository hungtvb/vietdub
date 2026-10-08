# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
#
# Pattern adapted from pyVideoTrans (https://github.com/jianchang512/pyvideotrans)
# by jianchang512, GPL-3.0: tts/_edgetts.py - async concurrency 10,
# retry 3+1, SAVE_TIMEOUT 30s per save (anti websocket-hang), fail policy:
# single-sentence failures become silence placeholders, raise only when
# ALL sentences fail; skip files that already exist (per-sentence cache).
"""Step [6a] - Edge-TTS dubbing, 2 fixed Vietnamese voices:
  female: vi-VN-HoaiMyNeural | male: vi-VN-NamMinhNeural

Checkpoint per sentence: stages/tts/seg_<index>.wav. Re-running resumes
from the first missing sentence (edge case 10).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from media import _bin
from project.schema import Segment

log = logging.getLogger("vietdub.tts")

MAX_CONCURRENT = 10
RETRY_NUMS = 3          # retries after first attempt
SAVE_TIMEOUT = 30       # seconds per save - never hang on websocket forever


class TTSError(Exception):
    pass


def _vail_file(path: str | Path, min_bytes: int = 1024) -> bool:
    p = Path(path)
    return p.exists() and p.stat().st_size >= min_bytes


def _cache_key(text: str, voice: str, rate: str, pitch: str) -> str:
    return hashlib.md5(f"{voice}|{rate}|{pitch}|{text}".encode("utf-8")).hexdigest()


class EdgeTTS:
    def __init__(self, voice_male: str = "vi-VN-NamMinhNeural",
                 voice_female: str = "vi-VN-HoaiMyNeural",
                 rate: str = "+0%", pitch: str = "+0Hz",
                 concurrency: int = MAX_CONCURRENT,
                 retries: int = RETRY_NUMS,
                 communicate_factory: Optional[Callable] = None):
        self.voice_male = voice_male
        self.voice_female = voice_female
        self.rate = self._clean_rate(rate)
        self.pitch = self._clean_pitch(pitch)
        self.concurrency = concurrency
        self.retries = retries
        # injectable for tests (sandbox blocks the real websocket)
        self._factory = communicate_factory

    @staticmethod
    def _clean_rate(rate: str) -> str:
        import re
        rate = (rate or "").strip()
        if re.match(r"^[+-]?\d+(\.\d+)?%$", rate):
            return rate if rate[0] in "+-" else f"+{rate}"
        return "+0%"

    @staticmethod
    def _clean_pitch(pitch: str) -> str:
        import re
        pitch = (pitch or "").strip().replace("hz", "Hz")
        if re.match(r"^[+-]?\d+(\.\d+)?Hz$", pitch, re.I):
            return pitch if pitch[0] in "+-" else f"+{pitch}"
        return "+0Hz"

    def voice_for(self, gender: str) -> str:
        return self.voice_female if gender == "female" else self.voice_male

    def _make_communicate(self, text: str, voice: str):
        if self._factory is not None:
            return self._factory(text, voice, self.rate, self.pitch)
        from edge_tts import Communicate
        return Communicate(text, voice=voice, rate=self.rate,
                           pitch=self.pitch, connect_timeout=5)

    async def _synthesize_one(self, item: Dict, sem: asyncio.Semaphore) -> bool:
        path = Path(item["filename"])
        if _vail_file(path):
            return True  # resume: already done (edge case 10)
        text = (item["text"] or "").strip()
        if not text:
            return False
        async with sem:
            for attempt in range(self.retries + 1):
                try:
                    comm = self._make_communicate(text, item["voice"])
                    mp3_tmp = str(path) + ".part.mp3"
                    await asyncio.wait_for(comm.save(mp3_tmp),
                                           timeout=SAVE_TIMEOUT)
                    if not _vail_file(mp3_tmp, min_bytes=512):
                        raise RuntimeError("TTS trả về file rỗng")
                    self._mp3_to_wav(mp3_tmp, str(path))
                    Path(mp3_tmp).unlink(missing_ok=True)
                    return True
                except asyncio.TimeoutError:
                    log.warning("TTS timeout câu %s (lần %d)", item["index"],
                                attempt + 1)
                except ValueError as e:
                    # unknown voice - retrying won't help
                    log.error("giọng TTS không tồn tại: %s", e)
                    return False
                except Exception as e:  # noqa: BLE001
                    log.warning("TTS lỗi câu %s (lần %d): %s", item["index"],
                                attempt + 1, str(e)[:160])
                if attempt < self.retries:
                    await asyncio.sleep(2 * (attempt + 1))
        return False

    @staticmethod
    def _mp3_to_wav(mp3_path: str, wav_path: str) -> None:
        p = subprocess.run(
            [_bin.ffmpeg_cmd(), "-y", "-v", "error", "-i", mp3_path,
             "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", wav_path],
            capture_output=True, text=True)
        if p.returncode != 0 or not Path(wav_path).exists():
            raise RuntimeError(f"đổi mp3->wav lỗi: {p.stderr[:200]}")

    async def _run_all(self, queue: List[Dict]) -> Dict[str, int]:
        sem = asyncio.Semaphore(self.concurrency)
        results = await asyncio.gather(
            *(self._synthesize_one(it, sem) for it in queue))
        ok = sum(1 for r in results if r)
        return {"ok": ok, "err": len(results) - ok}

    def synthesize(self, segments: List[Segment], out_dir: str | Path,
                   progress_cb: Optional[Callable[[int, int], None]] = None
                   ) -> List[Segment]:
        """Synthesize each segment -> stages/tts/seg_<index>.wav.

        Only raises when ALL sentences fail; single failures leave
        audio_vi empty and duration_fit inserts silence (port policy).
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        queue: List[Dict] = []
        for seg in segments:
            text = (seg.text_vi or seg.text_src or "").strip()
            fname = out_dir / f"seg_{seg.index:04d}.wav"
            # md5 cache: if text/voice changed, old file is stale -> redo
            key_file = fname.with_suffix(".md5")
            key = _cache_key(text, self.voice_for(seg.gender),
                             self.rate, self.pitch)
            if _vail_file(fname) and key_file.exists() \
                    and key_file.read_text().strip() == key:
                seg.audio_vi = str(fname)
                continue
            key_file.write_text(key)
            queue.append({"index": seg.index, "text": text,
                          "voice": self.voice_for(seg.gender),
                          "filename": str(fname), "seg": seg})

        if queue:
            try:
                stats = asyncio.run(self._run_all(queue))
            except RuntimeError:  # already-running loop (GUI thread, Wave 2)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    stats = ex.submit(asyncio.run, self._run_all(queue)).result()
            log.info("TTS xong: %d ok, %d lỗi", stats["ok"], stats["err"])
            if stats["ok"] == 0 and queue:
                raise TTSError(
                    "Lồng tiếng thất bại toàn bộ (Edge-TTS không phản hồi).\n"
                    "Cách khắc phục: kiểm tra mạng (Edge-TTS cần websocket "
                    "tới Microsoft), thử lại sau ít phút.")
            for it in queue:
                if _vail_file(it["filename"]):
                    it["seg"].audio_vi = it["filename"]
                else:
                    log.warning("câu %d TTS lỗi -> chèn im lặng ở bước khớp giờ",
                                it["index"])
        if progress_cb:
            progress_cb(len(segments), len(segments))
        return segments
