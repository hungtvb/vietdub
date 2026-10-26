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
        self.proper_nouns = list(proper_nouns or [])
        self._diarizer = diarizer

    def transcribe(self, wav_path: str | Path) -> list[Segment]:
        source = Path(wav_path)
        duration = _wav_duration_sec(source)
        # Use a file stream to avoid loading 90-minute audio into Python RAM.
        try:
            with source.open("rb") as fp:
                response = requests.post(
                    self.url,
                    files={"file": (source.name, fp, "audio/wav")},
                    data={"language": self.language, "quality": self.quality,
                          "proper_nouns": json.dumps(self.proper_nouns, ensure_ascii=False)},
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
            original_review.append(bool(raw.get("needs_review")))
            segments.append(Segment(
                index=len(segments), start=start, end=end,
                speaker=sid if sid is not None else 0,
                text_src=raw["text"].strip(), confidence=1.0,
                # No credible score supplied: never invent certainty.
                needs_review=bool(raw.get("needs_review")) or sid is None,
            ))

        if not segments:
            if payload["status"] == "no_speech":
                log.warning("VietDub STT reports no speech, check input audio.")
                return []
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
