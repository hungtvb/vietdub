"""Qt offscreen integration for interactive video-region editing.

Run with QT_QPA_PLATFORM=offscreen; no GPU or PaddleOCR model needed.
"""
import json

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ui.visual_region_editor import VisualRegionEditor, VideoRegionCanvas


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def video(tmp_path):
    source=tmp_path/"source.mp4"
    wr=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"mp4v"),10,(320,180))
    assert wr.isOpened()
    for i in range(20):
        img=np.full((180,320,3),(100,140,180),np.uint8)
        cv2.putText(img,"TITLE",(85,147),cv2.FONT_HERSHEY_SIMPLEX,
                    .85,(255,255,255),3,cv2.LINE_AA)
        wr.write(img)
    wr.release()
    return source


def test_canvas_geometry_accurate_with_letterboxing(app):
    widget=VideoRegionCanvas()
    widget.resize(640,500)
    widget.set_frame(np.zeros((180,320,3),dtype=np.uint8))
    rect=widget._image_rect()
    # Width-based scale = 2x; image occupies y=70..430.
    assert round(rect.left())==0
    assert round(rect.top())==70
    assert widget._source_point(rect.center())==(160,90)
    assert widget._source_point(QPoint(2,5)) is None


def test_dialog_draw_add_preview_save_and_reopen(app,video,tmp_path):
    dest=tmp_path/"plan.json"
    dialog=VisualRegionEditor(video,dest)
    dialog.show()
    app.processEvents()
    canvas=dialog.canvas
    canvas.resize(620,350)
    app.processEvents()
    # Simulate real drag in displayed image coordinates.
    sx,sy,ex,ey=30,110,280,158
    p1=canvas._visible_box([sx,sy,sx+1,sy+1]).topLeft()
    p2=canvas._visible_box([ex,ey,ex+1,ey+1]).topLeft()
    QTest.mousePress(canvas,Qt.LeftButton,Qt.NoModifier,p1.toPoint())
    QTest.mouseMove(canvas,p2.toPoint())
    QTest.mouseRelease(canvas,Qt.LeftButton,Qt.NoModifier,p2.toPoint())
    app.processEvents()
    box=dialog.canvas.selection
    assert box is not None
    assert abs(box[0]-sx)<=2 and abs(box[2]-ex)<=3
    assert abs(box[1]-sy)<=2 and abs(box[3]-ey)<=3

    dialog.from_sec.setValue(.4)
    dialog.to_sec.setValue(1.5)
    dialog.mode.setCurrentIndex(dialog.mode.findData("pixelate"))
    dialog._add()
    assert len(dialog.regions)==1
    assert dialog.regions[0]["source"]=="user"
    assert dialog.regions[0]["mode"]=="pixelate"

    dialog.slider.setValue(8)
    dialog.preview.setChecked(True)
    app.processEvents()
    assert not dialog.canvas.image.isNull()
    dialog._save()
    assert dest.is_file()
    plan=json.loads(dest.read_text(encoding="utf-8"))
    assert plan["regions"][0]["start"]==.4
    assert plan["regions"][0]["end"]==1.5

    restored=VisualRegionEditor(video,dest)
    assert len(restored.regions)==1
    restored.close()


def test_dialog_rejects_other_video_source_plan(app,video,tmp_path):
    dest=tmp_path/"wrong.json"
    dest.write_text(json.dumps({
        "version":1,"source":"/other/source.mp4","width":320,
        "height":180,"fps":10,"frames":20,
        "regions":[{"source":"user","start":0,"end":1,
                    "box":[0,0,30,30],"kind":"logo","mode":"blur"}]
    }),encoding="utf-8")
    # Avoid modal warning stopping headless CI; capture it.
    from PySide6.QtWidgets import QMessageBox
    orig=QMessageBox.warning
    QMessageBox.warning=staticmethod(lambda *a,**k: QMessageBox.Ok)
    try:
        dialog=VisualRegionEditor(video,dest)
        assert dialog.regions==[]
        dialog.close()
    finally:
        QMessageBox.warning=orig
