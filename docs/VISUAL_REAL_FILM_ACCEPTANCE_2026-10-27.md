## V13 — latest real-film review, supersedes V11

The latest delivered sample is **V13**, not the earlier V11. It was produced
with **real pretrained LaMa TorchScript CPU** inference and composited in
one encode from the original Chinese 91.80-second film.

Frame-level review discovered that a question-card icon appears several
frames **before** its full Chinese caption, at all three question-card
introductions. LaMa inference was run on an additional **19 early icon
frames**: #222–227, #1229–1234, and #1405–1411 inclusive. All three
fade-on intervals were manually checked in before/after decoded frames.

The Q&A panel expands from approximately 65 to 300 pixels, so a fixed
335-pixel LaMa rectangle was unnecessarily replacing visible human clothes,
referee movements and sideline detail. V13 uses **per-frame width
estimation from a reviewer-specified HSV blue/purple color band**;
only the visibly covered region borrows model-cleaned pixels. The
comparison at frames 1235–1260, 1412–1450 shows cleaner restoration
of unoccluded referee clothing and the white boundary line.

This method is now reusable in
`media/visual_dynamic_mask.py:expanding_graphic_mask` and opt-in
for reviewed `neural-window` entries of
`media/visual_lama_cpu.py` with `mask_style: "expanding-graphic"`.
Source-specific hue range, review box, time range and min width must be
chosen from the actual film. **Do not apply the Chinese video ROI presets
automatically to all videos.**

V13 final decoded QA: **2,295 / 2,295 frames**, 25 FPS,
**91.80 seconds**, zero full-stream FFmpeg decode errors. Mean outside
approved-region pixel MAE is **2.30/255**; highest reviewed frame's
outside-region average is **2.59/255**. Tesseract `chi_sim`
detects no readable original Chinese dialogue in cleaned caption ROIs
at sampled timestamps 0, 4, 7.88, 8.88, 20, 50, and 80 seconds.
At 58 seconds the Q&A-colored pixel proxy fell **45.5% → 1.9%**.
One-frame interview lower-third at frame #197 remains fixed.

Source audio is still **Chinese**, retained for visual QA. No claim of
Vietnamese dub or perfect pixel reconstruction is made. The last
branded end card is replaced by neutral white from frame #2170.
Human playback acceptance is still needed, especially for large
occlusions on moving bodies.

Sample output, iPhone-compatible version, before/after clips, 30-frame
contact sheet and JSON metrics are conversation artifacts rather than
files committed to GitHub. PR remains **Draft**.

**Reviewed plan example** (illustrative only):

```json
{
  "source": "neural-window",
  "kind": "subtitle",
  "start": 49.16,
  "end": 52.48,
  "box": [0, 245, 335, 316],
  "mask_style": "expanding-graphic",
  "mask_options": {
    "hue_min": 90, "hue_max": 158,
    "saturation_min": 55, "brightness_min": 75,
    "blue_fraction": 0.12,
    "min_width": 73, "padding": 15, "feather": 0
  }
}
```

---

# Visual cleanup — real Chinese broadcast output review (27 Oct 2026)

This is a sample-specific acceptance record for PR #6, **not** a claim that
every arbitrary watermark/subtitle can be reconstructed automatically. The
source video and derivative MP4s are kept as user conversation artifacts,
not committed to the repository.

## Real footage and pipeline

- Source: real Chinese interview / football montage, 640 × 360 pixels,
  constant 25 FPS, exactly **2,295 decoded source frames** (91.80 seconds).
- Open-source pretrained TorchScript **LaMa** was run for real on CPU with
  checkpoint SHA-256
  `344c77bbcb158f17dd143070d1e789f38a66c04202311ae3a258ef66667a9ea9`.
  This is not a test/mock network.
- `media/visual_hybrid.py` selects reviewed regions for different approaches.
  LaMa is used on moving/occluded regions and logos; temporal clean plates
  are used where nearby source frames contain a recoverable background;
  gradient/flat-strip repaint covers steady graphics under frequently changing
  dialogue.
- The experimental output is **one-pass composited from original source
  frames**, to avoid lossy V2→V7→V8 transcodes. It only takes replacement
  pixels from separately inspected restoration donors in approved regions.
- Intervals reviewed on this *specific* clip: intro 0–8.88 s, graphics
  strip from 8.88 s, callouts around 9.12–12.64 s, 49.40–52.48 s and
  56.48–59.52 s. Blank outro starts at actual source scene cut
  **frame 2,170 = 86.80 seconds**.
- Persistent broadcaster logo at upper left was processed with LaMa
  keyframes separately for each scene, so background was not blended through
  the 54 detected scene changes. Dialogue captions were not merely blurred.

## Iteration / visual review

- V4: remaining rectangular blue-stage artefacts and insufficient Q&A
  inpaint box; rejected.
- V5: expanded Q&A box, corrected branded outro onset; still missed two
  recurring Q&A intervals.
- V6: removed two additional callouts; an early-source marker's Telea result
  had a conspicuous rectangular seam; rejected.
- V7: preferred LaMa for marker and Q&A; passed sample OCR/graphics checks,
  but multiple reencodes produced unnecessary degradation outside masks.
- V8: rebuilt from original frames in a single encode, with replaced pixels
  strictly scoped to reviewed masks.
- V9: cleaned blue-stage reconstruction artefacts in the 3.36–6.44 s
  speaker shot using constrained inpaint in flat blue background only.
- V10: detected a **one-frame reappearance** of the interviewee's lower
  third on frame **197 = 7.88 s**. Expanding the time interval was
  insufficient because that donor frame itself contained the text.
- **V11**: reconstructed frame 197 using the already-clean adjacent frames
  196 and 198, within the precise approved rectangle. The contiguous
  frames 194–199 were visually checked: **no reappearing lower-third**.

## Decoded output review for V11

| Check | Result |
|---|---|
| Source/output decoded frames | **2,295 / 2,295** |
| Output FPS and duration | **25 FPS / 91.80 s** |
| FFmpeg full-stream decoding | **0 errors** |
| Max unrelated-area mean absolute pixel difference (reviewed sample schedule, not worst individual pixel) | **2.59/255** |
| Mean unrelated-area mean absolute pixel difference | **2.30/255** |
| Tesseract `chi_sim` in dialogue regions at t = 0, 4, 7.88, 8.88, 20, 50, 80 s | Source dialogue recognizable, output **no readable characters** at those sampled timestamps |
| Upper-left red broadcaster mark in sampled frames | Red-mark pixel proxy fell to zero |
| Colored question graphics at t=51 s | Fraction in checked graphics ROI: **37.6% → 1.5%** |
| Colored question graphics at t=58 s | **45.5% → 1.9%** |

Source audio was preserved for image-quality verification; this sample is
**not a finished Vietnamese dub**. The main VietDub rendering pipeline can
later mux the actual synthesized Vietnamese dub.

All OCR/proxy checks are **necessary but not sufficient** for naturally
reconstructed video: LaMa may approximate missing fabric, skin, railings,
and moving foreground. A human must inspect the full video at playback speed,
especially the intro 0–8.88 seconds. The end-card branding is replaced by a
neutral white end card, not magically regenerated footage.

## Reproducibility / avoiding single-video hardcoding

V11's masks and time windows are *review annotations for this one source*,
not constants to bake into generic VietDub processing. The reusable
`media/visual_hybrid.py`, `visual_lama_cpu.py`, `visual_temporal.py`,
`visual_ocr_acceptance.py` and `visual_acceptance.py` should be driven
by an operator-approved JSON plan. Real-film source, generated donors, V11
MP4, per-timestamp source/output contact sheets, two comparison clips,
the sample-specific reproduction/QA scripts, and JSON report are supplied as
the user-visible evidence ZIP in the ChatGPT conversation.

**Merge status:** Keep PR #6 **Draft** until footage acceptance is
confirmed; green GitHub CI alone is never sufficient. Latest smoke CI
included `tests/test_visual_hybrid.py`: 47 passed / 1 skipped (PyTorch
not on the smoke runner), with separate real PaddleOCR smoke passing on
synthetic caption footage.
