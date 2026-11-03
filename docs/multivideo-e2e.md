# Real multi-video dubbing regression suite

Purpose: Detect overfitting to one Chinese football interview, using
independent real human-speaking videos, never synthetic translated dialogue.

| Case | Language | Real source | Excerpt | Pipeline | Licensing |
|---|---|---|---|---|---|
| zh-economy | Mandarin | 2026 Paul Chan economics interview (China News Service) | 0–48s | FunASR AutoModel -> Qwen2.5:3b -> Edge-TTS -> MP4 | CC BY 4.0, Commons review pending: do not publicly redistribute |
| zh-greetings | Mandarin | Ding Zhen New Year greeting (China News Service) | 14–35s | FunASR AutoModel -> Qwen2.5:3b -> Edge-TTS -> MP4 | CC BY 3.0 attribution |
| en-radio | English | Angel Tree Q&A radio interview (U.S. Navy) | 0–59s | faster-whisper base -> Qwen2.5:3b -> Edge-TTS -> MP4 | Public domain (US Navy) |

Exact source URLs and attribution metadata are in the workflow. Tests download
actual WebM videos from Wikimedia Commons and transcode short samples using
FFmpeg. The Chinese greeting excerpt stops at 35 seconds; its Tibetan section
is NOT translated, so no mixed-language translation success is claimed.

Success means technical pipeline execution, an actual MP4 with video+audio,
a real transcript, populated bilingual SRT, source-ID mapping preserved and
QA metrics collected. It does NOT mean human-verified translation, speaker
diarization, spoken naturalness or preservation of every question. Source
clips with unresolved speaker and linguistic QA remain UNAPPROVED. Review
questions, omissions, named entities, polarity and speech-speed per case.
