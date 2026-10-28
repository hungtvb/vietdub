"""Pixel-level cleanup masks and frame-accurate temporal boundaries.

Only regions inferred by OCR/user are eligible. Frame content may be used to
refine those regions; this is not a general scene-object remover.
"""
from __future__ import annotations


def pixel_mask(frame, box, kind, padding=1):
    """Return clipped ROI and a glyph/mark mask, never a broad OCR rectangle.

    Best on light subtitles and solid-color station bugs. Unusual low-contrast
    caption styles require a segmentation model or manually reviewed masks.
    """
    import cv2
    import numpy as np
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = map(int, box)
    x1, y1 = max(0, x1 - padding), max(0, y1 - padding)
    x2, y2 = min(width, x2 + padding), min(height, y2 + padding)
    roi = (x1, y1, x2, y2)
    if x2 <= x1 or y2 <= y1:
        return roi, np.zeros((0, 0), dtype=np.uint8)
    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    local = cv2.GaussianBlur(gray, (0, 0), 3.5)
    contrast = gray.astype(np.int16) - local.astype(np.int16)
    if kind == "logo":
        # Saturated artwork or white lettering. Derive a tight rectangle around
        # actual colored/bright pixels rather than blurring a large manual ROI.
        colored = (hsv[:, :, 1] > 108) & (hsv[:, :, 2] > 74)
        bright = (hsv[:, :, 2] > 180) & (hsv[:, :, 1] < 90) & (contrast > 20)
        candidate = (colored | bright).astype(np.uint8) * 255
        ys, xs = np.where(candidate > 0)
        mask = np.zeros_like(candidate)
        if xs.size > 10:
            xa, xb = max(0, int(xs.min()) - 1), min(mask.shape[1], int(xs.max()) + 2)
            ya, yb = max(0, int(ys.min()) - 1), min(mask.shape[0], int(ys.max()) + 2)
            # Don't infer that a mostly colorful ROI is one logo.
            if (xb-xa)*(yb-ya) <= .85*mask.size:
                mask[ya:yb, xa:xb] = 255
        return roi, mask
    mask = ((hsv[:, :, 2] > 165) & (hsv[:, :, 1] < 125)
            & (contrast > 21)).astype(np.uint8) * 255
    # Solid synthetic title cards have no internal contrast: mask the tiny OCR
    # rectangle in this special case, not a union across multiple positions.
    if mask.mean() < 3 and float(gray.mean()) > 190 and float(gray.std()) < 28:
        mask[:] = 255
    elif mask.mean() < 3:
        mask = cv2.Canny(gray, 65, 150)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    return roi, mask


def tight_box(boxes, width, height):
    """Robust OCR box: reject large one-off text hallucinations."""
    import numpy as np
    if not boxes:
        raise ValueError("boxes must not be empty")
    a = np.array(boxes, dtype=np.float32)
    r = [int(np.quantile(a[:, i], .25 if i in (0, 1) else .75))
         for i in range(4)]
    return (max(0, r[0]), max(0, r[1]), min(width, r[2]), min(height, r[3]))


def refine_subtitle_bounds(video, start_frame, last_frame, first_box, last_box,
                           fps, duration, sample_sec):
    """Search frames around first/last OCR hit for actual overlay appearance.

    Distinct confidence thresholds handle fade-in vs disappearance. No blind
    fixed +/- .65s expansion, and no changes to logo/manual region lifetimes.
    """
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return max(0, start_frame/fps-.15), min(duration, last_frame/fps+.15)
    max_frame = max(0, int(round(duration*fps))-1)

    def frame_at(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n))
        ok, frame = cap.read()
        return frame if ok else None

    def overlap(ref_mask, frame, box):
        if frame is None or ref_mask.size == 0:
            return 0
        _, m = pixel_mask(frame, box, "subtitle", padding=0)
        if m.shape != ref_mask.shape:
            return 0
        return cv2.countNonZero(cv2.bitwise_and(ref_mask, m)) / max(1, cv2.countNonZero(ref_mask))

    try:
        first_frame = frame_at(start_frame)
        last = frame_at(last_frame)
        if first_frame is None or last is None:
            return max(0, start_frame/fps-.15), min(duration, last_frame/fps+.15)
        _, first_mask = pixel_mask(first_frame, first_box, "subtitle", padding=0)
        _, last_mask = pixel_mask(last, last_box, "subtitle", padding=0)
        if not (cv2.countNonZero(first_mask) > 6 and cv2.countNonZero(last_mask) > 6):
            return max(0, start_frame/fps-.15), min(duration, last_frame/fps+.15)
        radius = max(2, round(fps*min(1.5, 2*sample_sec)))
        beginning = start_frame
        for i in range(start_frame-1, max(-1, start_frame-radius-1), -1):
            if overlap(first_mask, frame_at(i), first_box) < .35:
                break
            beginning = i
        ending = last_frame
        for i in range(last_frame+1, min(max_frame, last_frame+radius)+1):
            if overlap(last_mask, frame_at(i), last_box) < .40:
                break
            ending = i
        # Guard one video frame on appearance; end is exclusive.
        return max(0, (beginning-1)/fps), min(duration, (ending+1)/fps)
    finally:
        cap.release()
