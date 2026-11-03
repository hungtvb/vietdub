"""Conservative scene-cut guard for video clean-plate reference frames.

Clean-plate interpolation across a hard cut can corrupt whole faces/scenes.
This gate rejects reference pairs if the non-caption image distribution changes
too much or adjacent sampled frames show a hard scene boundary. A rejection
means manual review is required, *not* that the engine should blindly inpaint.
"""
from __future__ import annotations

import cv2


def _frame_hist(frame, safe_height):
    safe_height = min(int(safe_height), frame.shape[0])
    if safe_height < 24:
        raise ValueError("not enough unoccluded pixels for scene validation")
    sample = cv2.resize(frame[:safe_height], (160, 72))
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [24, 16],
                        [0, 180, 0, 256])
    return cv2.normalize(hist, hist)


def scene_distance(a, b, safe_height):
    """Bhattacharyya distance (0 means same color distribution)."""
    ha, hb = _frame_hist(a, safe_height), _frame_hist(b, safe_height)
    return float(cv2.compareHist(ha, hb, cv2.HISTCMP_BHATTACHARYYA))


def validate_clean_plate_shot(cap, before_index, after_index, safe_height,
                              pair_limit=.37, cut_limit=.44):
    """Read samples inside [before_index, after_index] and reject clear cuts.

    The cap is opened by the caller; this method deliberately does not
    require OCR or a registered model. No global thresholds can prove same
    scene for every edited montage, so this is a strict fail-closed gate.
    """
    if not (0 <= before_index < after_index):
        raise ValueError("reference indices must be increasing")
    gap = after_index - before_index
    jump = max(1, round(gap / 12))
    indices = sorted(set([before_index, after_index] +
                         list(range(before_index, after_index + 1, jump))))
    frames = []
    for index in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if not ok:
            raise ValueError(f"cannot decode scene-check frame {index}")
        frames.append(_frame_hist(frame, safe_height))
    dist = lambda a,b: float(cv2.compareHist(a,b,cv2.HISTCMP_BHATTACHARYYA))
    pair = dist(frames[0], frames[-1])
    max_jump = max((dist(a,b) for a,b in zip(frames[:-1],frames[1:])),
                   default=0.0)
    if pair > pair_limit:
        raise ValueError(
            f"Unsafe temporal clean-plate: reference frames differ "
            f"(scene distance={pair:.3f}, limit={pair_limit:.3f}); "
            "choose same-shot references or a different reviewed method")
    if max_jump > cut_limit:
        raise ValueError(
            f"Unsafe temporal clean-plate: likely scene change "
            f"(sample jump={max_jump:.3f}, limit={cut_limit:.3f})")
    return {"reference_scene_distance":round(pair,4),
            "max_sample_jump":round(max_jump,4),
            "sampled_frames":len(indices)}
