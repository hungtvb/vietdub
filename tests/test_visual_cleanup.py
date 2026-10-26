"""Synthetic cleanup tests (no OCR model download, safe for CI)."""
import shutil

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from media.visual_cleanup import Config, VisualCleanup, VisualCleanupError, _kind


class DummyOCR:
    def __init__(self, always=True):
        self.always = always
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        if self.always or self.calls == 1:
            return [((36, 95, 164, 107), .98)]
        return []


def sample_video(path):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (200, 120))
    assert writer.isOpened()
    for k in range(20):
        f = np.full((120,200,3), 50, np.uint8)
        f[95:107,36:164] = 255
        f[30:45,(k*3)%130:(k*3)%130+12] = (100,200,20)
        writer.write(f)
    writer.release()


def test_region_classification():
    assert _kind((36,95,164,107),200,120) == "subtitle"
    assert _kind((179,0,194,12),200,120) == "logo"
    assert _kind((50,20,150,35),200,120) == "text"


def test_plan_tracks_repeated_text(tmp_path):
    source = tmp_path/"src.mp4"
    sample_video(source)
    plan_path = tmp_path/"regions.json"
    p = VisualCleanup(Config(sample_sec=.2, auto_logo=False), DummyOCR()).analyze(source,plan_path)
    assert plan_path.is_file()
    assert p["frames"] == 20
    assert len(p["regions"]) == 1
    assert p["regions"][0]["kind"] == "subtitle"
    assert p["regions"][0]["start"] == 0
    assert p["regions"][0]["end"] > 1.7


def test_one_frame_false_positive_is_suppressed(tmp_path):
    source = tmp_path/"src.mp4"
    sample_video(source)
    p = VisualCleanup(Config(sample_sec=.2, auto_logo=False),DummyOCR(False)).analyze(source)
    assert p["regions"] == []


def test_excluded_area_not_processed(tmp_path):
    source=tmp_path/"src.mp4"
    sample_video(source)
    conf=Config(sample_sec=.2,auto_logo=False,exclude=((0,85,200,120),))
    p=VisualCleanup(conf,DummyOCR()).analyze(source)
    assert p["regions"] == []


@pytest.mark.skipif(not shutil.which("ffmpeg"),reason="ffmpeg unavailable")
@pytest.mark.parametrize("mode",["blur","inpaint"])
def test_render_synthetic(tmp_path,mode):
    source=tmp_path/"src.mp4"
    sample_video(source)
    engine=VisualCleanup(Config(mode=mode,sample_sec=.2,auto_logo=False),DummyOCR())
    p=engine.analyze(source)
    result=engine.render(source,tmp_path/"out.mp4",p)
    assert result.is_file() and result.stat().st_size > 500
    a=cv2.VideoCapture(str(source));b=cv2.VideoCapture(str(result))
    ok1,f1=a.read();ok2,f2=b.read()
    a.release();b.release()
    assert ok1 and ok2
    assert np.mean(np.abs(f1[95:107,36:164].astype(float)-f2[95:107,36:164].astype(float))) > 2
    assert np.mean(np.abs(f1[:25,:].astype(float)-f2[:25,:].astype(float))) < 8


def test_validation():
    with pytest.raises(VisualCleanupError):
        VisualCleanup(Config(mode="invalid"))


def test_short_subtitle_two_confirmations(tmp_path):
    """A 350ms caption must be detected with a 650ms regular OCR cadence."""
    video = tmp_path/"short.mp4"
    writer = cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*"mp4v"),10,(200,120))
    assert writer.isOpened()
    for frame_idx in range(30):
        f = np.full((120,200,3), 35, np.uint8)
        if 6 <= frame_idx <= 9:  # 0.6s ... 0.9s
            f[95:107,36:164] = 255
        writer.write(f)
    writer.release()

    class ContentAwareDetector:
        def detect(self, frame):
            patch = frame[95:107,36:164]
            return [((36,95,164,107), .98)] if patch.mean() > 190 else []

    plan = VisualCleanup(
        Config(sample_sec=.65,auto_logo=False),ContentAwareDetector()
    ).analyze(video)
    captions = [x for x in plan["regions"] if x["kind"] == "subtitle"]
    assert len(captions) == 1
    assert .35 < captions[0]["start"] <= .6
    assert .8 <= captions[0]["end"] < 1.2


def test_corner_watermark_is_not_subtitle():
    # A lower-right corner watermark can be wider than 6% of the frame;
    # it must still be classified as logo, not subtitle.
    assert _kind((176,106,198,117),200,120) == "logo"
