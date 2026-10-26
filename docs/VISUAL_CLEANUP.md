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
