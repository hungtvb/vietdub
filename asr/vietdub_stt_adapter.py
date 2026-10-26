"""Optional client for independent VietDub STT localhost service.

The recognizer lives in its own package. Keep CAM++ speaker verification in
VietDub until the dedicated service has validated diarization.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from urllib.parse import urlsplit

import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder

from asr.funasr_adapter import ASRError, FunASRAdapter, _wav_duration_sec
from project.schema import Segment

log = logging.getLogger("vietdub.asr.stt")


class VietDubSTTAdapter:
    def __init__(self, *, stt_url: str, quality: str = "fast",
                 source_language: str | None = "zh",
                 proper_nouns: list[str] | None = None,
                 diarizer: FunASRAdapter | None = None):
        url = stt_url.rstrip("/")
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("VietDub STT must use a localhost HTTP URL")
        if quality not in {"fast", "quality"}:
            raise ValueError("VietDub STT quality must be fast or quality")
        self.url = url + "/v1/transcribe"
        self.quality = quality
        self.language = source_language or "zh"
        self.proper_nouns = [name.strip()[:100] for name in (proper_nouns or [])
                             if isinstance(name, str) and name.strip()][:30]
        self._diarizer = diarizer

    def transcribe(self, wav_path: str | Path) -> list[Segment]:
        source = Path(wav_path)
        duration = _wav_duration_sec(source)
        # Match server upload limit before opening/streaming the request.
        if source.stat().st_size > 512 * 1024 * 1024:
            raise ASRError("Audio lớn hơn giới hạn VietDub STT 512 MiB.")
        try:
            with source.open("rb") as fp:
                encoder = MultipartEncoder(fields={
                    "file": (source.name, fp, "audio/wav"),
                    "language": self.language,
                    "quality": self.quality,
                    "proper_nouns": json.dumps(self.proper_nouns, ensure_ascii=False),
                })
                # Do not buffer complete long-film WAV files in RAM.
                # Ignore environment proxies for loopback-only requests.
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.post(
                        self.url, data=encoder,
                        headers={"Content-Type": encoder.content_type},
                        timeout=(5, 7200),
                    )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, OSError, ValueError) as exc:
            raise ASRError(
                "Không kết nối được VietDub STT local. Hãy chạy "
                "'python -m vietdub_stt.api' trên port 8768 trước. "
                f"Chi tiết: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
            raise ASRError("VietDub STT trả về schema không được hỗ trợ.")
        if payload.get("status") not in {"complete", "no_speech"}:
            raise ASRError("VietDub STT trả trạng thái không hợp lệ.")
        raw_segments = payload.get("segments")
        if not isinstance(raw_segments, list):
            raise ASRError("VietDub STT thiếu danh sách lời thoại.")

        if payload["status"] == "no_speech":
            # Do not advance the dubbing pipeline as if ASR had succeeded.
            raise ASRError(
                "VietDub STT không phát hiện thoại. Hãy kiểm tra audio/ASR "
                "trước khi tiếp tục lồng tiếng.")
        segments: list[Segment] = []
        unknown_speaker: list[int] = []
        original_review: list[bool] = []
        for i, raw in enumerate(raw_segments):
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                raise ASRError(f"VietDub STT segment {i}: lỗi text.")
            try:
                start, end = float(raw["start"]), float(raw["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ASRError(f"VietDub STT segment {i}: thiếu timestamp.") from exc
            if (not math.isfinite(start) or not math.isfinite(end)
                    or start < 0 or end <= start or end > duration + 0.05):
                raise ASRError(f"VietDub STT segment {i}: timestamp ngoài video.")
            if not raw["text"].strip():
                continue
            sid = raw.get("speaker_id")
            if sid is not None and (isinstance(sid, bool)
                                    or not isinstance(sid, int) or sid < 0):
                raise ASRError(f"VietDub STT segment {i}: speaker_id không hợp lệ.")
            if sid is None:
                unknown_speaker.append(len(segments))
            raw_confidence = raw.get("confidence")
            if raw_confidence is not None:
                if isinstance(raw_confidence, bool) or not isinstance(
                        raw_confidence, (int, float)):
                    raise ASRError(f"VietDub STT segment {i}: confidence không hợp lệ.")
                confidence = float(raw_confidence)
                if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ASRError(f"VietDub STT segment {i}: confidence ngoài [0,1].")
            else:
                # The engine returns null until calibrated scores exist.
                confidence = 0.0
            review = bool(raw.get("needs_review")) or raw_confidence is None
            original_review.append(review)
            segments.append(Segment(
                index=len(segments), start=start, end=end,
                speaker=sid if sid is not None else 0,
                text_src=raw["text"].strip(), confidence=confidence,
                needs_review=review or sid is None,
            ))

        if not segments:
            raise ASRError("VietDub STT không có câu nói mặc dù báo hoàn tất.")

        if unknown_speaker and self._diarizer:
            # Reuse VietDub's CAM++ diarizer. Require majority coverage from
            # speech turns; never map speakers by nearest turn in music/silence.
            try:
                turns = self._diarizer.transcribe(source)
                for index in unknown_speaker:
                    segment = segments[index]
                    overlaps: dict[int, float] = {}
                    for turn in turns:
                        overlap = max(0.0, min(segment.end, turn.end)
                                      - max(segment.start, turn.start))
                        if overlap > 0:
                            overlaps[turn.speaker] = overlaps.get(turn.speaker, 0.0) + overlap
                    if overlaps:
                        best_id = max(overlaps, key=overlaps.get)
                        if overlaps[best_id] >= (segment.end - segment.start) * 0.5:
                            segment.speaker = best_id
                            segment.needs_review = original_review[index]
                # If no coverage, speaker 0 is a required compatibility
                # placeholder and the segment stays needs_review=True.
            except Exception as exc:  # noqa: BLE001
                log.warning("CAM++ unable to label STT speakers: %s", exc)
        return segments
