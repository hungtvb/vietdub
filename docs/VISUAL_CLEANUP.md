# VietDub Visual Cleanup Engine (experimental opt-in)

Goal: detect *burned-in* subtitles, on-screen text, and possible static top-corner logo overlays. Analyze before modifying; never overwrite the source.

## Install
Install a compatible PaddlePaddle runtime following https://www.paddleocr.ai/latest/en/quick_start.html, then:
\`\`\`bash
pip install -r requirements-visual-cleanup.txt
\`\`\`
PaddleOCR v3 runs locally. Initial model download requires internet. This optional dependency does **not** affect normal VietDub jobs when cleanup is disabled.

## Use in VietDub
Go to Settings -> Video / phụ đề -> enable **Tự động làm mờ chữ/logo gốc**; select Blur or Inpaint. This uses the input video before Vietnamese dub/subtitle export. Default: OFF. The raw video is never modified. Detection review plan is saved under job stages as \`visual_regions.json\`, and the intermediate video as \`visual_clean.mp4\`.

To omit all *new* subtitle overlays, select **Không thêm phụ đề**. Existing hard subtitles still require cleanup; stream remuxing is insufficient.

## Architecture
- OCR every ~0.65 s using PaddleOCR v3 Chinese/English text boxes, confidence threshold 0.65.
- Temporal matching (IoU and bottom-baseline compatibility); requires >=2 adjacent detections, reducing single-frame false positives.
- Geometry classification: bottom band = subtitle; corners = logo text; rest = hard text.
- Optional conservative pixel-stability heuristic for **opaque**, fixed top-corner watermark candidates. Transparent, animated, rotating or disappearing logos may require manual masks or future ML models.
- Reviewable JSON with exact time and pixel boxes, confidence, and source; add manual regions and exclusions programmatically through \`Config\`.
- **Tight masks (v2):** build a per-frame foreground mask inside each OCR box, instead of Gaussian-blurring the entire OCR rectangle. Manual logo masks are narrowed to their high-saturation/bright content when detectable. Unknown styles require review.
- **Refined boundaries (v2):** use a positive OCR frame as visual reference and inspect neighboring decoded frames for the first/last appearance. Different onset/offset thresholds avoid dropping the last part of a fading subtitle. Median-percentile boxes reject one-off OCR width explosions.
- Blur uses a Gaussian source image composited only where the tight mask is positive; Inpaint uses the same mask. FFmpeg creates a H.264 video-only intermediate; VietDub's final renderer supplies mixed dubbed audio.

## Limits / validation
- Initial implementation targets **constant-frame-rate (CFR)** H.264-style input; VFR, rotation, HDR, and exact source timestamps need dedicated processing.
- Fast inpainting can produce artifacts on complex textures, especially moving faces; inspect the JSON/frames and re-export as needed.
- No generic visual logo recognizer is claimed. Static heuristic is conservative but can misidentify fixed scenery.
- OCR 3.x requires PaddlePaddle and model downloads, and CPU processing can be slow for full movies.
- Normal VietDub render remains unchanged unless explicitly enabled; cleanup errors fail the render rather than silently exporting unclean video.

## Regression evidence (26 October 2026)
- Synthetic CI: **20 tests passed** after adding pixel-mask and first/last-frame timing regression tests.
- Unmocked PaddleOCR 3.x CI: **1 E2E passed**, with source/OCR/tracking/output screenshots uploaded as an Actions artifact. Note the CI fixture has generated English burned-in text.
- Separate local real-footage experiment: **21-second Chinese-language interview**, original 25 FPS; uses **Tesseract chi_sim**, not PaddleOCR, to supply authentic OCR regions for mask/timing verification. Previous OCR-box blur plan: about **21.2%** of frame masked at peak, with subtitle ending around **7.19 s**. Refined foreground-mask probe: about **8.4%** at peak, and subtitle masks end at **7.48 s** (exclusive). Subtitle starts around **3.00–3.04 s**. These measurements are from that one clip, not general accuracy estimates.
- Bright, high-contrast Chinese subtitles and solid-color logos are the main target. Text still can leave visible blurred glyph-shaped remnants; animated and semi-transparent marks or scene-matched typography may need a segmentation model/temporal clean-plate inpainting. Some original black subtitle bands may remain.


## User-selected blur/mosaic/inpaint regions (Qt editor)

For the latest user-directed workflow, including original-pixel drag
selection, timeline intervals, three-pass OCR suggestions, before/after
preview, and source-bound JSON plan persistence, see
[USER_MANUAL_VISUAL_REGIONS.md](USER_MANUAL_VISUAL_REGIONS.md).

User-approved rectangles use `source: "user"` and are applied
*without* the OCR glyph/brightness mask. Each region can choose its own
Gaussian blur, mosaic or Telea mode and exact frame interval. A manual-only
plan renders without installing PaddleOCR; OCR is only needed when the
user explicitly asks for suggestions. The mask remains static in screen
coordinates for its reviewed interval (no automatic object tracking yet).

## Operator-reviewed temporal clean-plate restoration (new)

The ordinary OCR pipeline deliberately remains conservative: a bounding box
cannot tell whether the source contains usable background. To **remove both
the caption glyphs and a semitransparent black lower-third panel** (instead of
merely blurring the letters), the operator may approve a *different* region
type with two clean source frames in the **same shot**, before and after the
overlay. The engine uses upper-frame optical flow to reproject this clean
background into the occluded pixels, feathering only the reviewed rectangle.

This is **not fully automatic**. Do not use it when the camera cuts, subject
motion is extreme, either reference still contains the overlay, or the
occluded scene cannot be inferred from the available frames.

Example plan region (change all time/box/frame values for your own footage):

```json
{
  "start": 2.60,
  "end": 7.68,
  "box": [0, 231, 572, 333],
  "kind": "subtitle",
  "source": "temporal-clean-plate",
  "confidence": 1.0,
  "reference_frames": [64, 196],
  "flow_height": 229,
  "blend_frames": [113, 145],
  "feather": 2.5
}
```

The times above are a sample annotation for a **21-second, 25 FPS,
640×360 Chinese interview**, not preset settings. There is intentional
pre-roll before the very first fading glyph: at frame 65 restoration already
tracks nearby unobstructed frames, preventing a discontinuity at the OCR hit.

If a channel mark appears across the entire video, there is no original
clean reference at that location. An **optional** `exemplar-patch` region
can borrow another source region of identical size from the current frame
and match local luminance/chroma before feathering; the result is an
approximation, **not genuine reconstruction** of the original pixels:

```json
{
  "start": 0.0,
  "end": 21.0,
  "box": [25, 10, 130, 63],
  "kind": "logo",
  "source": "exemplar-patch",
  "donor_box": [260, 10, 365, 63],
  "feather": 7
}
```

Save the full `visual_regions.json` plan, including `version: 1`,
`source` (the resolved video path), `width`, `height`, `fps`,
`frames`, and `regions`. Remove OCR boxes that are superseded by
manual clean-plate regions (overlapping OCR masks are also suppressed
programmatically). In Settings → Video, enable visual cleanup and browse
the reviewed JSON under **Plan clean-plate**. VietDub will validate it
and render with it, not rerun PaddleOCR. Settings or plan-file content
changes invalidate completed render checkpoints.

Standalone (video-only, existing audio is remuxed by final VietDub render):

```bash
python -m media.visual_cleanup_review   --video input.mp4 --plan reviewed-plan.json --out cleaned.mp4
```

### Real-footage review results and limitations

- Source: 21-second real Chinese video, 25 FPS, featuring a fading white
  two-line title and dark news lower-third over a **mostly static shot**.
- Reviewed plan: first clean reference #64, final clean reference #196,
  restored frames #65–191 (end exclusive 192).
- Visual inspection at 2.60, 2.80, 2.84, 2.88, 3.04, 4.00, 4.84,
  5.32, 7.40, 7.52 and 7.68 seconds: both white captions and black panel
  replaced, subject largely continuous. This is evidence for **that clip**,
  not broad production acceptance.
- The first prototype introduced a jump in robe pixels at frame 70:
  adjacent-frame difference 16.47 (same ROI). Beginning clean-plate
  reconstruction before overlay onset reduced it to 1.31.
- Approved logo exemplar removes the watermark visually but does not
  reconstruct what was underneath. Color matching reduces noticeable seams.
- Synthetic encoded-video regression and real OCR CI are necessary but
  insufficient: further multilingual, moving-camera, hard-cut, HDR/VFR,
  and 1080p/4K acceptance is required before treating this as general
  production-quality removal.


## Reviewed flat graphic-strip repaint (persistent changing subtitles)

A **different** operator-approved mode handles a video whose changing subtitles
are printed on top of a *smooth, mostly uniform color/gradient strip*, with
clean pixels directly beneath the subtitle rows. It reconstructs each caption
row from nearby unobstructed rows and matches each frame's left and right
gradient; no OCR confidence or static median is used. It must NOT be used to
cover dynamic film scenes, complex textures or a speaker's face.

Example review-plan region from a second **91.8s / 25 FPS / 640×360** Chinese
broadcast sample (again, not a global preset):

```json
{
  "start": 9.0,
  "end": 88.4,
  "box": [0, 315, 640, 352],
  "kind": "subtitle",
  "source": "flat-strip-repaint",
  "confidence": 1.0,
  "donor_rows": [352, 359],
  "left_samples": [15, 120],
  "right_samples": [530, 635],
  "feather": 1.4
}
```

All coordinate and time ranges require source-video review. The blue/gray
graphic lower bar was stable between about 9 and 88.4 seconds, but the intro
uses a different layout and the end is a white credit screen. Those regions
are **not** automatically touched. Persistent brand logos and the fixed name
card remain unless separately reviewed; this mode cleans **only the dialog
subtitle band**.

Actual full-length local render of the second clip was decoded and checked
at 12, 20, 30, 50, 70 and 82 seconds. A high-value/low-saturation
white-glyph proxy within the caption ROI dropped to zero at all six checked
timestamps; screenshots show no visible subtitles and stable clean bar.
This is not an automated full-clip quality metric. More varied clips and
logos still require human review.

The editor supports `sub_mode="none"` without writing an unwanted SRT.
Changing the cleanup settings or modifying an approved plan invalidates
the final-render checkpoint and forces an updated export.


## Neural video-inpainting backend for dynamic subtitles (optional)

The OpenCV / clean-plate methods cannot reconstruct arbitrary moving scenery
hidden under permanently burned-in text. When that real-video visual review
fails, VietDub now exposes an **optional, locally installed neural backend**
that invokes the separate open-source
[YaoFANGUK/video-subtitle-remover](https://github.com/YaoFANGUK/video-subtitle-remover)
(Apache-2.0). VietDub is NOT bundling, vendoring or training these models.

Install upstream VSR and its pretrained model files separately, following
its own instructions; choose in Settings > Video:
- **Engine xử lý:** AI video inpainting
- **Model AI:** \`sttn-det\` for automatic OCR-driven subtitle masks;
  \`lama\` for single-frame restoration; \`propainter\` for motion-heavy
  footage. \`sttn-auto\` is permitted only with explicitly reviewed areas.
- **VSR local:** path containing \`backend/main.py\`.
- Review an actual 10–20 second processed sample before a full export.
  If an optional approved plan is supplied, only its spatial text/subtitle
  rectangles are passed to VSR. Per-region time ranges are **not applied
  by upstream VSR**; use the reviewed local method for time-specific edits.

No silent fallback: missing weights/dependencies, subprocess errors,
timeout, frame loss or changed FPS fail the VietDub job. The original
source is left untouched; final VietDub render replaces the source audio
with the mixed Vietnamese dub.

The adapter has **CI-tested argument conversion / frame-count validation only**;
as of this change, actual **STTN/LaMa/ProPainter model inference has not been
validated on the real 91.8-second Chinese sample**. Do NOT infer production
quality from the adapter's passing tests. A model-run screenshot/video and
per-frame source/output review remain required.

## Structural acceptance reports

\`media.visual_acceptance.audit_video()\` reads and compares every decoded
source/output frame, checks FPS, missing final frames, unexpected changes
outside reviewed rectangles and one-frame jumps at mask boundaries. Optional
\`required_subtitle_times\` in an operator-reviewed plan causes a job to fail
if known caption frames have no reviewed cleanup coverage.

This audit is a **necessary** structural gate, not proof that every caption
was removed. OCR on the rendered video, scene-by-scene inspection, and user
acceptance are additional requirements. It is deliberately possible for a
video to pass structural checks and still retain captions.

Source-based regressions found:
- The original second-film V1 MP4 had **2,293** decoded frames versus
  **2,295** in the source because audio remux was done with \`-shortest\`
  while audio ended early. The corrected export uses AAC padding and contains
  2,295 / 2,295 frames, 25fps and 91.80 seconds. VietDub's core renderer
  now uses \`-af apad -t <video_stream_duration>\` (without \`-shortest\`), preserving the original picture duration without the portable FFmpeg 7 hang.
- The graphic-strip mask previously started at 9.00s; the source layout
  switches to the blue strip at 8.88s, so the sample's reviewed interval
  was corrected to 8.88–88.4s.
- The second-film intro (0–8.88s) places subtitles on *live scene pixels*.
  Spatial OpenCV inpainting and a multi-frame optical-flow donor experiment
  both visibly damaged clothing/background. Those experiments were **rejected**
  rather than presented as clean. They still require neural restoration
  and an actual model-run output review.

### Additional real-world regression: portable FFmpeg 7 deadlock

The first frame-loss fix (`-af apad -shortest`) worked on system FFmpeg
but **deadlocked** on the portable static FFmpeg 7.0.2 used by Actions.
The stalled CI run was made diagnosable with verbose per-test timeouts
(4 failed/35 passed, all failures from the render path).
We reproduced the hang with the exact portable binary. The corrected
renderer probes the source **video** duration and uses `-af apad -t DURATION`
(without `-shortest`); the test returned normally and preserved all
12/12 source frames. Latest smoke CI: **39/39 passed in ~2.5 seconds**.
