"""Select a native ASR engine after audio-first source-language detection.

Chinese defaults to FunASR; English/other/mixed/uncertain audio goes to
multilingual Whisper. A policy choice, not an accuracy guarantee.
"""
from dataclasses import asdict, dataclass
from asr.source_language import LanguageDecision, normalize_language

@dataclass(frozen=True)
class ASRRoute:
    engine: str
    language: str
    policy: str
    reason: str
    language_review_required: bool
    manual_override: bool
    whisper_comparison_recommended: bool

    def to_dict(self):
        return asdict(self)


def select_asr_engine(decision: LanguageDecision, requested_engine="auto",
                      *, chinese_min_confidence=.70):
    engine = (requested_engine or "auto").strip().lower()
    primary = normalize_language(decision.primary)
    if engine not in {"auto", "funasr", "whisper_pyannote"}:
        raise ValueError(f"Unknown ASR engine selection: {engine}")
    if engine == "funasr":
        if normalize_language(decision.requested) != "zh":
            raise ValueError("FunASR chỉ dành cho tiếng Trung. Chọn ngôn ngữ "
                             "video là 'zh' để ép FunASR, hoặc dùng ASR tự động.")
        return ASRRoute("funasr", "zh", "manual",
                        "User forced FunASR for Chinese", False, True, True)
    if engine == "whisper_pyannote":
        return ASRRoute("whisper_pyannote", primary, "manual",
                        "User requested multilingual Whisper",
                        bool(decision.review_required), True, False)
    if (primary == "zh" and decision.mode != "mixed"
            and decision.confidence >= chinese_min_confidence
            and not decision.review_required):
        return ASRRoute("funasr", "zh", "automatic",
                        "Confident Mandarin source: route to FunASR",
                        False, False, True)
    uncertain = (bool(decision.review_required) or primary in
                 {"und", "mixed", "auto"} or
                 decision.confidence < chinese_min_confidence)
    return ASRRoute("whisper_pyannote", primary, "automatic",
                    "Multilingual Whisper for other, mixed or uncertain speech",
                    uncertain, False, False)
