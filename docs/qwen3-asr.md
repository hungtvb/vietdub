# VietDub Qwen3-ASR local option

From Settings > ASR choose Qwen3-ASR + ForcedAligner.
Install with: pip install -r requirements-asr-qwen.txt

- Default ASR checkpoint: Qwen/Qwen3-ASR-0.6B
- Larger ASR checkpoint: Qwen/Qwen3-ASR-1.7B
- Timing model: Qwen/Qwen3-ForcedAligner-0.6B (required)
- Device: auto, CPU or CUDA
- Native Qwen ASR is separate from Ollama/Qwen2.5 LLM for translation.
- Default auto routing remains FunASR Chinese, Whisper others.

No guessed timestamps or silent fallback. When Qwen cannot align speech,
VietDub raises an actionable error. All Qwen segments are UNAPPROVED and
speaker identity is UNVERIFIED (one placeholder speaker); multi-speaker
voice continuity must be handled by an independent diarization step.
Model weights can be large and initial download/inference may be slow.
CPU execution is not performance-verified; compare using independent
real videos before choosing as default.
