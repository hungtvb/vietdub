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
- Render with Gaussian ROI blur or OpenCV Telea inpainting, then FFmpeg H.264 video-only intermediate. Existing final renderer supplies mixed dubbed audio.

## Limits / validation
- Initial implementation targets **constant-frame-rate (CFR)** H.264-style input; VFR, rotation, HDR, and exact source timestamps need dedicated processing.
- Fast inpainting can produce artifacts on complex textures, especially moving faces; inspect the JSON/frames and re-export as needed.
- No generic visual logo recognizer is claimed. Static heuristic is conservative but can misidentify fixed scenery.
- OCR 3.x requires PaddlePaddle and model downloads, and CPU processing can be slow for full movies.
- Normal VietDub render remains unchanged unless explicitly enabled; cleanup errors fail the render rather than silently exporting unclean video.
