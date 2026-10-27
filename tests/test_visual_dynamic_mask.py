"""Per-frame expanding graphics must preserve unrelated people/background."""
import cv2
import numpy as np
import pytest

from media.visual_dynamic_mask import expanding_graphic_mask


def _scene(extent):
    image=np.full((180,320,3),(65,135,90),np.uint8)
    # Luminous purple/blue badge anchored to left reviewed ROI.
    cv2.rectangle(image,(0,111),(extent,157),(200,65,105),-1)
    # Subject outside the evolving overlay: NEVER part of the mask.
    cv2.rectangle(image,(245,110),(296,170),(35,45,145),-1)
    return image


def test_dynamic_mask_grows_with_graphic_in_source_frame():
    narrow=expanding_graphic_mask(_scene(65),(0,106,310,162),
                                  min_width=68,padding=12,feather=0)
    wide=expanding_graphic_mask(_scene(182),(0,106,310,162),
                                min_width=68,padding=12,feather=0)
    assert wide.sum()>narrow.sum()*2
    assert narrow[130,48]==1 and narrow[130,130]==0
    assert wide[130,165]==1
    # Red shirt outside the reviewed graphic must remain untouched.
    assert narrow[135,262]==0 and wide[135,262]==0


def test_mask_does_not_expand_when_badge_is_absent():
    frame=np.full((180,320,3),(65,135,90),np.uint8)
    mask=expanding_graphic_mask(frame,(0,106,310,162),
                                min_width=60,padding=9,feather=0)
    assert mask[135,40]==1 and mask[135,120]==0


@pytest.mark.parametrize("opts", [
    {"hue_min":158,"hue_max":90},
    {"min_width":500},
    {"row_start":.95,"row_end":.10},
    {"blue_fraction":1.5}
])
def test_dynamic_mask_rejects_invalid_review_settings(opts):
    with pytest.raises(ValueError):
        expanding_graphic_mask(_scene(70),(0,106,310,162),**opts)
