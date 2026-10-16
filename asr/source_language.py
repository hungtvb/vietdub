"""Source-language routing for arbitrary VietDub videos.

Language is probed acoustically before full ASR. Script inspection is only
a per-line hint: Latin letters alone cannot identify English vs French etc.
No detector result implies human-verified dialogue or speaker identity.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import re
import subprocess
import tempfile

LANGUAGES = {
    "auto": "Tự động nhận diện",
    "en": "English",
    "zh": "中文 / Tiếng Trung (giản thể và phồn thể)",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "th": "ภาษาไทย",
    "vi": "Tiếng Việt",
}
LANGUAGE_NAMES = {**LANGUAGES, "und": "Chưa xác định", "mixed": "Đa ngôn ngữ"}


def normalize_language(value: str | None) -> str:
    v = (value or "").strip().lower().replace("_", "-")
    aliases = {
        "": "auto", "automatic": "auto", "unknown": "und",
        "zh-cn": "zh", "zh-tw": "zh", "zh-hk": "zh",
        "zh-hans": "zh", "zh-hant": "zh", "cmn": "zh",
        "en-us": "en", "en-gb": "en", "jp": "ja",
    }
    return aliases.get(v, v.split("-")[0])


def segment_language(text: str, primary: str) -> str:
    """Detect strong script evidence; otherwise inherit acoustic source code.

    Kanji in Japanese and Hanzi in Chinese overlap, so prefer Japanese when
    audio detector reports Japanese unless kana/Hangul proves otherwise.
    """
    primary = normalize_language(primary)
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u0e00-\u0e7f]", text):
        return "th"
    if re.search(r"[\u3400-\u9fff]", text):
        return "ja" if primary == "ja" else "zh"
    return primary if primary not in {"auto", "mixed", "und"} else "und"


def alignment_language(part: dict, default: str = "und") -> str:
    """Use acoustic/per-segment language metadata ahead of script heuristics."""
    explicit = normalize_language(part.get("language"))
    if explicit not in {"auto", "und", "mixed"}:
        return segment_language(str(part.get("text", "")), explicit)
    return segment_language(str(part.get("text", "")), default)


@dataclass(frozen=True)
class LanguageDecision:
    requested: str
    primary: str
    mode: str
    confidence: float
    multilingual: bool
    review_required: bool
    observations: list[dict]
    warnings: list[str]

    def to_dict(self):
        return asdict(self)


def choose_language(observations: list[dict], requested: str = "auto",
                    min_confidence: float = .55, mixed_share: float = .25
                    ) -> LanguageDecision:
    requested = normalize_language(requested)
    if requested not in {"auto", "und"}:
        return LanguageDecision(requested=requested, primary=requested, mode="manual",
                                confidence=1., multilingual=False, review_required=False,
                                observations=list(observations), warnings=[])
    weights = defaultdict(float)
    counted = []
    for obs in observations:
        lang = normalize_language(obs.get("language"))
        prob = max(0., min(1., float(obs.get("probability", 0) or 0)))
        # Skip silence/background/music samples without recognized speech.
        if lang in {"auto", "und", "mixed"} or not obs.get("has_speech", True) or prob < .3:
            continue
        weights[lang] += prob
        counted.append(obs)
    if not weights:
        return LanguageDecision(requested="auto", primary="und", mode="unresolved",
                                confidence=0., multilingual=True, review_required=True,
                                observations=list(observations),
                                warnings=["Không đủ tiếng nói để xác định ngôn ngữ nguồn."])
    ranked = sorted(weights.items(), key=lambda pair: (-pair[1], pair[0]))
    primary, weight = ranked[0]
    total = sum(weights.values())
    share = weight / total
    secondary = ranked[1][1] / total if len(ranked) > 1 else 0.
    mixed = secondary >= mixed_share
    confidence = min(1., (weight / max(len(counted), 1)))
    warnings = []
    if mixed:
        warnings.append("Video có dấu hiệu nhiều ngôn ngữ; cần xác minh các đoạn đổi ngôn ngữ.")
    if confidence < min_confidence or share < .65:
        warnings.append("Nhận diện ngôn ngữ chưa chắc chắn; đề nghị kiểm tra thủ công.")
    return LanguageDecision(
        requested="auto", primary=primary, mode="mixed" if mixed else "detected",
        confidence=round(confidence, 3), multilingual=bool(mixed),
        review_required=bool(warnings), observations=list(observations), warnings=warnings)


def sample_starts(duration: float, sample_seconds: float = 16.):
    """Spread short probes across the VIDEO, not just the opening credits."""
    if duration <= 0:
        return [0.]
    latest = max(0., duration - sample_seconds)
    if latest <= .25:
        return [0.]
    starts = [round(latest * x, 2) for x in (.08, .48, .86)]
    return list(dict.fromkeys(starts))


def _probe_duration(wav_path, ffprobe="ffprobe"):
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(wav_path)], check=True, capture_output=True, text=True)
    return float(json.loads(proc.stdout)["format"]["duration"])


def detect_source_language(wav_path, whisper_model, requested: str = "auto",
                           *, ffmpeg=None, ffprobe=None,
                           sample_seconds=16.) -> LanguageDecision:
    """Probe source speech at 3 distant times before doing the full transcription.

    Manual language skips probes entirely. Works on any input video/audio with
    ffmpeg; does not assume language based on a filename or subtitles.
    """
    requested = normalize_language(requested)
    if requested != "auto":
        return choose_language([], requested=requested)
    source = Path(wav_path)
    if not source.is_file():
        raise FileNotFoundError(source)
    from media import _bin
    ffmpeg = ffmpeg or _bin.ffmpeg_cmd()
    ffprobe = ffprobe or _bin.ffprobe_cmd()
    duration = _probe_duration(source, ffprobe=ffprobe)
    observations = []
    with tempfile.TemporaryDirectory(prefix="vietdub_lang_probe_") as temp:
        for idx, start in enumerate(sample_starts(duration, sample_seconds)):
            clip = Path(temp) / f"probe_{idx:02d}.wav"
            subprocess.run(
                [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                 "-y", "-ss", str(start), "-i", str(source), "-t",
                 str(sample_seconds), "-vn", "-ac", "1", "-ar", "16000",
                 "-c:a", "pcm_s16le", str(clip)],
                check=True, capture_output=True)
            try:
                stream, info = whisper_model.transcribe(
                    str(clip), language=None, multilingual=False,
                    beam_size=1, vad_filter=True,
                    condition_on_previous_text=False)
                parts = list(stream)
                has_speech = any((seg.text or "").strip() for seg in parts)
                observations.append({
                    "start": start, "language": getattr(info, "language", "und"),
                    "probability": float(getattr(info, "language_probability", 0) or 0),
                    "has_speech": bool(has_speech)})
            except Exception as exc:
                observations.append({"start": start, "language": "und",
                                     "probability": 0., "has_speech": False,
                                     "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    return choose_language(observations)
