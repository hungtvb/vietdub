"""Deterministic multi-pass OCR tests: no real model weights downloaded."""
import cv2
import numpy as np
import pytest

from media.visual_detection import detect_frame_candidates


class FakeDetector:
    def __init__(self):
        self.calls=[]

    def detect(self,frame):
        h,w=frame.shape[:2]
        self.calls.append((w,h))
        if (w,h)==(320,180):
            yield (56,60,170,88),.79
        elif (w,h)==(640,360):
            # Slightly shifted box, but still equivalent original rectangle.
            yield (114,122,344,180),.93
            yield (400,230,520,268),.55
        else:
            raise AssertionError("Unexpected image size")


def test_enlarged_ocr_box_maps_to_native_coordinates_and_merges():
    image=np.full((180,320,3),(70,80,90),np.uint8)
    det=FakeDetector()
    candidates=detect_frame_candidates(image,det,
                                       include_contrast=False)
    assert det.calls==[(320,180),(640,360)]
    assert len(candidates)==2
    assert candidates[0][0][0] in (56,57)
    assert candidates[0][0][2]>=170
    assert candidates[0][1]==pytest.approx(.93)
    assert candidates[1][0]==(200,115,260,134)


def test_low_confidence_is_ignored():
    class Poor:
        def detect(self,frame):
            yield (5,5,50,35),.2
    image=np.zeros((90,160,3),np.uint8)
    assert detect_frame_candidates(image,Poor())==[]


def test_contrast_pass_runs_on_original_resolution():
    class Recorder:
        def __init__(self):self.lengths=[]
        def detect(self,img):
            self.lengths.append(img.shape[:2])
            yield (10,10,40,28),.8
    model=Recorder()
    detect_frame_candidates(np.zeros((90,160,3),np.uint8),model)
    assert model.lengths==[(90,160),(180,320),(90,160)]


def test_large_images_do_not_upscale_to_8k():
    class Recorder:
        def __init__(self):self.count=0
        def detect(self,frame):
            assert frame.shape[:2]==(900,1700)
            self.count+=1
            return []
    model=Recorder()
    detect_frame_candidates(np.zeros((900,1700,3),np.uint8),model)
    assert model.count==2


def test_bad_frame_rejected():
    with pytest.raises(ValueError):
        detect_frame_candidates(np.zeros((8,8),np.uint8),FakeDetector())
