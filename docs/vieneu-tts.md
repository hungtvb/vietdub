# VieNeu-TTS v3 Turbo in VietDub

VieNeu-TTS is an **optional, local** dubbing provider. Edge-TTS remains the
default and does not require downloading the VieNeu model.

## Install

Use Python 3.10+ and install VietDub's usual requirements. Then install
the optional VieNeu SDK separately:

```bash
pip install -r requirements-vieneu.txt
```

The tested SDK target is `vieneu==3.8.3` from
https://github.com/pnnbao97/VieNeu-TTS. First inference downloads model
assets from Hugging Face; subsequent inference reuses the local model cache.
Allow enough disk space and RAM. There is **no remote hosted paid API** in
this integration.

If you plan to run the PyTorch/CUDA backend, consult upstream instructions
for matching PyTorch/CUDA/Transformers versions; otherwise choose
`ONNX CPU` in Settings. `INT8` ONNX needs VNNI-capable CPUs and may
produce garbled speech on unsupported CPUs; `FP32` is the safe default.

## Use

1. Open **Cài đặt → Giọng nói**, choose **VieNeu v3 Turbo**, set backend,
   precision, male and female voice names, and save.
2. On the main screen, pick **Công nghệ TTS → VieNeu v3 Turbo** and choose
   voices; **Nghe thử** tests the selected provider.
3. Review the source transcript and Vietnamese translation before running
   dubbing, as usual. The ASR, LLM translation and FFmpeg stages are unchanged.
4. Switch back to **Edge-TTS** any time. Each provider retains its own voice
   choices, and the per-sentence audio cache keys include the provider.

Default VieNeu preset voices: **Hải Đăng** (male) and **Mai Anh** (female).
Enter another supported preset name in the voice box if desired. This change
does not automatically clone movie actors' voices: speaker-to-character
verification and voice cloning are separate workflows.

## Compatibility and error policy

- The SDK produces 48 kHz WAV; VietDub transcodes each sentence to
  **44.1 kHz mono PCM** for its duration-fit, timeline and mix stages.
- Only the TTS step depends on the VieNeu package. Existing Edge-TTS
  installs work unchanged.
- One engine is loaded lazily and reused (up to two backend/precision
  combinations). Inference is serialized across the GUI preview and jobs.
- Cached sentences are reused only if provider, voice, backend, precision,
  text and audio format all match.
- VieNeu errors stop the step with a clear message instead of silently
  replacing missing voice lines with silence; successfully rendered sentences
  remain checkpointed for retries.
- Edge rate/pitch/concurrency settings **do not control** VieNeu's
  inference. The post-TTS timestamp fitting still applies.

## Tests

```bash
pytest -q tests/test_vieneu_tts.py
```

These use a mocked model and real FFmpeg (when available). A production E2E
audio-quality and video-render test needs the actual SDK/model download and a
representative licensed test video; passing mocks does **not** establish real
naturalness, synchronization or character-voice accuracy.

## Attribution

VieNeu-TTS SDK: https://github.com/pnnbao97/VieNeu-TTS (Apache-2.0).
Model: https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Turbo (Apache-2.0).
Keep upstream attribution/license notices when redistributing components.
Clone real people's voices only with authorization.
