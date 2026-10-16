# Chinese ASR optimization and benchmark evidence

This optimization applies to **any new Chinese-speaking video**, not to the
interview script or translated content. Source-language routing happens before
full transcription: clear Mandarin -> FunASR; other/mixed/uncertain sources ->
multilingual Whisper. The user may override the backend.

## Actual Mandarin audio benchmark — 2026-10-16

Source: Wikimedia Commons, [China women's football interview](https://commons.wikimedia.org/wiki/File:〖两会30秒〗水庆霞：中国女足非世界顶级，但会不断追赶.webm).
Clip: first **25 seconds**, PCM 16 kHz mono, GitHub-hosted Ubuntu standard CPU.
Both FunASR backends used the same audio. These are measurements from two
independent CI runs, not reference transcription-quality scores.

| Actual measurement | Legacy ModelScope pipeline | FunASR AutoModel |
| --- | ---: | ---: |
| Model initialization incl. initial download | 137.832 sec | 163.006 sec |
| Audio inference (same 25 sec) | 4.037 sec | **3.278 sec** |
| Cold total | **141.869 sec** | 166.285 sec |
| Real-time factor (inference only) | 0.1615 | **0.1311** |
| Transcript segments | 12 | 10 |
| CJK characters extracted | 123 | 124 |

**Important trade-off:** AutoModel achieved **18.8% lower inference
latency** for this sample, but its first-load startup was about 25 seconds
slower. These are not guarantees across CPUs, audio, GPU platforms or video
lengths. Keep the proven legacy backend as default until a broader sample
benchmark and transcript reference are available; select AutoModel in Settings
for experimental speed testing.

Transcript text produced by both backends is ~97.17% similar after removal
of punctuation. This is **cross-model agreement**, not CER or WER. Both
outputs lack a verified human ground-truth transcript, and some speaker IDs
are unverified.

- [AutoModel benchmark CI](https://github.com/hungtvb/vietdub/actions/runs/38916558536)
- [ModelScope benchmark CI](https://github.com/hungtvb/vietdub/actions/runs/38917438382)
- [Chinese vs Whisper Small comparison CI](https://github.com/hungtvb/vietdub/actions/runs/38916993799)

Whisper Small was transcribed on the **same interview's first 30 seconds**
and took 4.208 seconds of CPU inference in one recorded run. Once OpenCC
normalizes Simplified/Traditional, its transcript has **86.32% character
sequence agreement** with legacy FunASR on that excerpt; without
normalization it has **63.86%**. Neither score identifies which text is
correct. Each divergent window remains an editorial QA candidate.

## Verified warm-cache rerun (same AutoModel and audio)

GitHub Actions restored cache key `Linux-vietdub-modelscope-automodel-v2`
successfully (about **1,913 MiB** uncompressed). A second independent CI
runner processed the exact same 25-second speech sample.

| Measured AutoModel metric | Initial run | Restored cache run |
| --- | ---: | ---: |
| Model load | 163.006 s | **45.256 s** |
| Audio inference | 3.278 s | 4.121 s |
| Total ASR operation | 166.285 s | **49.378 s** |
| Segments / recognized Hanzi | 10 / 124 | 10 / 124 |

The restored-cache model load time improved by **72.2%** and total ASR time by
**70.3%**. These timings include CPU runner variance. **The cache avoids
network download but does not eliminate deserialization**. The one-model
in-memory pool inside the desktop process eliminates repeated deserialization
for subsequent videos while the same model remains loaded and the process
is alive. This behavior is validated with offline automated tests, not yet
a multi-video GPU end-to-end benchmark.

- [Warm-cache proof and run logs](https://github.com/hungtvb/vietdub/actions/runs/38918612292)

## Reusable local optimization

VietDub keeps ModelScope weights on disk at
`~/.config/VietDub/models` (Windows: `%APPDATA%/VietDub/models`) unless
the user provides `MODELSCOPE_CACHE`. Disk cache avoids downloading weights
again but does not remove neural-network deserialization and warmup.

VietDub can also keep a **single initialized FunASR model in RAM** between
jobs (Settings > ASR > Reuse model). The in-memory registry is bounded to one
model; switching model/device/backend replaces its cached instance. Shared
inference is guarded by an RLock because ASR internals are not safely
concurrent by default. Turn this off on memory-limited systems.

Each FunASR result records `asr_quality.performance` with independent
`model_load_seconds`, `inference_seconds`, `total_seconds`,
`reused_loaded_model`, `real_time_factor`, `cache_dir` and
`segment_count`. Separate CI scripts benchmark actual audio, never mock it
for published performance numbers.

The experimental AutoModel backend configures
`paraformer-zh` + FSMN VAD (15 s max segment) + CT punctuation + CAM++
speaker model, with bounded 60-second dynamic batches and CPU thread
settings. Full-video pyannote can reconcile speaker identities but does not
automatically identify film characters. Chinese lines still require
translation/editorial review; neither CI nor model agreement writes
`translations/approved.json`.

## Where to run future tests

- Real Chinese audio smoke: `.github/workflows/vietdub-chinese-routing-smoke.yml`
- Real Chinese FunASR benchmark: `.github/workflows/vietdub-chinese-regression.yml`
- Independent Chinese/Whisper comparison:
  `.github/workflows/vietdub-chinese-compare.yml`
- Offline test suite: `tests/test_funasr_performance.py`,
  `tests/test_funasr_model_pool.py` and
  `tests/test_chinese_comparison.py`

Do not promote any ASR backend to "most accurate" without comparing to a
human-verified transcript from the same acoustic sample.
