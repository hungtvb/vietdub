# VietDub: chọn vùng làm mờ / xóa chữ, logo trực tiếp trên video

## NEW: Follow a moving logo or on-screen caption (tracking)

The editor now supports **Vùng cố định trên khung hình** (default, safer for
burned-in TV logos), or **Tự bám theo vùng + keyframe** for moving text.

1. Choose a distinctive text/logo rectangle on its **first visible frame**.
   Set precise start/end seconds, then choose the moving/track mode.
2. Click **Thêm vùng** / **Cập nhật**.
3. Click **▶ Phân tích tracking**. The work runs in a background thread and
   checks each decoded frame, the template-correlation confidence, a reverse
   matching consistency check and hard scene changes.
4. Scrub through the video to inspect the **green tracked rectangle** and
   toggle Blur/Mosaic/Telea preview. The UI **does not pretend a moving mask
   is static** before tracking is verified.
5. If the rectangle drifts, draw it at the correct location on that frame and
   click **◆ Đặt keyframe tại đây** (the box must stay the same size).
   Analyze again; the manual keyframe restarts matching from that frame.
6. If the scene changes, **split the region at the cut** and add a new
   reviewed interval. Do not let a mask continue onto a different person.
7. Saving a moving plan is blocked until every moving region has been
   successfully analyzed in this editing session. Rendering independently
   recomputes and validates the track: a stale or unverified JSON plan
   cannot force a wrong blur through the renderer.

### Reviewed moving region JSON

```json
{
  "source": "user",
  "start": 0.0,
  "end": 3.0,
  "box": [45, 54, 111, 85],
  "kind": "logo",
  "mode": "blur",
  "strength": 14,
  "feather": 2.0,
  "tracking": "template",
  "keyframes": [
    {"frame": 0, "box": [45, 54, 111, 85]},
    {"frame": 30, "box": [62, 59, 128, 90]}
  ]
}
```

The tracking code is in `media/visual_tracking.py`. A confidence
below the approved threshold, low-texture logo, reverse-match drift, invalid
geometry, or probable hard cut **fails closed**. The renderer doesn't
fall back to stationary blur. On the audit side,
`media/visual_acceptance.py` recomputes the exact path to
exclude the **moving mask**, not merely the original rectangle, when
checking whether unrelated source pixels were modified.

Limitations: simple template matching works best when the watermark remains
legible, similar in shape/scale and within the nearby search radius. Rotation,
perspective, scale changes, temporary occlusion, and sharp animation can
cause a deliberate stop. User corrections/keyframes are the supported way
to re-anchor; this is **not** a segmentation, object identity or DeepSORT
tracker.

### Output-led evidence

A synthetic moving "V D" watermark was composited over **real** Chinese
interview footage. The source was tracked through 72 frames (2.88 seconds
at 25fps), with **0 pixel position error** against the known synthetic
ground truth and minimal correlation confidence >99%. The H.264 baseline
before/after and 7-timepoint visual contact sheet are delivered in the
ChatGPT conversation. On a longer input that included an actual broadcast
shot change at frame 84, the tracker **rejected the cross-shot interpolation**
rather than blurring a wrong person/background.

CI tests use deterministic generated encoded videos with known trajectories:
exact position error, corrected keyframes, frame-loss checks, cross-shot
failure, confidence checks and end-to-end encoded blur, plus Qt offscreen
background tracking and save validation. These sample-specific results are
not a universal accuracy benchmark.

---



> Feature in PR #6, branch `feat/visual-cleanup-engine`.
> This is independent of the video dubbing track and **does not require
> PaddleOCR if the user manually selects a rectangle**.

## GUI workflow

1. On the main screen, select a video file or complete a URL download. The
   **▣ Chọn vùng chữ/logo cần làm mờ…** button becomes enabled only when
   the source is present.
2. Drag the cursor across the original video preview (letterboxing is
   accounted for). Adjust the native-pixel **X1/Y1/X2/Y2** numeric fields
   when precision matters.
3. Choose the exact **start/end** seconds. The effect activates on
   `round(start*fps)` through `round(end*fps)-1` inclusive. Review the
   transition frames by scrubbing the frame-based timeline.
4. Choose a category (subtitle, text, logo) and treatment:
   **Blur Gaussian** (soften), **Mosaic** (pixelated hiding), or
   **Inpaint Telea** (remove content and approximate underlying pixels).
   Adjust strength and edge feather (0–16 px).
5. Click **Thêm vùng**. You can add multiple independent masks/intervals,
   select and **Cập nhật** an existing mask or **Xóa** one.
6. Toggle **Xem kết quả đã xử lý (trước/sau)**. Preview uses exactly
   the same `media.visual_user_regions.apply_user_regions()` method that
   the final video renderer invokes. Playback is visual-only in this editor.
7. Optional: click **OCR nâng cao** on the current frame. It runs OCR in
   a background thread, using original-size, 2× enlarged and CLAHE
   contrast-enhanced passes, with confidence and overlapping boxes
   consolidated. Orange boxes are *suggestions*, not automatically selected
   or rendered. Pick one, resize the rectangle and click **Thêm vùng**.
   OCR requires the optional PaddleOCR dependencies/model.
8. Click **Lưu vùng & dùng khi render**. VietDub enables Visual Cleanup,
   assigns the source-specific JSON plan, and uses the CV backend for
   manual-only cleanup; an existing neural region plan remains Hybrid.
   The plan is automatically included when the main dubbing pipeline renders.

## Protection against accidental destructive edits

- **User masks cover the whole approved rectangle**, not just bright OCR
  glyphs, which avoids leaving a dark subtitle box or red halo.
- **No user mask changes a pixel outside the approved rectangle**, even
  with edge feather. Processing of blur and inpaint is local to the ROI;
  4K videos do not allocate full-frame blur masks for each small edit.
- Time is **frame-exact** for constant frame-rate video. The plan is
  bound to source absolute path, FPS, video dimensions and frame count.
  Selecting a different video disables the previous saved selection.
- In the preview a green border is an approved region; yellow is the
  current selection; orange dotted lines are OCR suggestions that the
  user has not approved.
- A blurred area may include people's clothing or moving scene detail
  beneath the rectangle. Use a tightly bounded mask and inspect edges.
  For challenging motion requiring plausible background restoration,
  use the separately reviewed neural-window / LaMa workflow.
- The editor does **not** perform automatic moving-object tracking in this
  iteration. Create multiple time intervals/boxes for moving overlay
  positions; never assume a static box will follow a moving watermark.
- The JSON is written atomically to a deterministic source-specific path
  under the VietDub settings directory, in `visual_plans/`. It does not
  overwrite the video source and does not require write access to its folder.

## Example reviewed JSON

```json
{
  "version": 1,
  "source": "/absolute/path/to/source.mp4",
  "width": 1920,
  "height": 1080,
  "fps": 25.0,
  "frames": 2500,
  "reviewed": true,
  "regions": [
    {
      "source": "user",
      "kind": "logo",
      "mode": "blur",
      "start": 0.0,
      "end": 100.0,
      "box": [25, 15, 160, 75],
      "strength": 18,
      "feather": 3.0,
      "confidence": 1.0
    },
    {
      "source": "user",
      "kind": "subtitle",
      "mode": "pixelate",
      "start": 2.5,
      "end": 14.0,
      "box": [240, 880, 1690, 1010],
      "strength": 22,
      "feather": 2.0,
      "confidence": 1.0
    }
  ]
}
```

Source metadata must match the actual video. Coordinates and timestamps above
are only examples; never hardcode them globally.

## Automated evidence

- `tests/test_visual_user_regions.py`: blur, mosaic, inpaint,
  validation failures, frame-accurate [start,end), exact unmodified outside
  area and a real FFmpeg-encoded/decoded MP4 check without OCR weights.
- `tests/test_visual_detection.py`: native/2× mapping, overlapping
  OCR proposals, confidence filtering, CLAHE pass and high-res memory guard.
- `tests/test_ui_visual_region_editor.py`: real PySide6
  Qt offscreen rectangle drag, letterboxing, timeline, preview,
  save/reload, and rejection of an unrelated video's plan.
- Separate GitHub Actions: **Visual cleanup smoke** and
  **Visual region editor UI**.
