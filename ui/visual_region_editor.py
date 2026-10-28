"""Interactive, reviewer-controlled overlay cleanup editor.

UI contract:
- User draws a rectangle on a decoded video frame; geometry is saved in
  ORIGINAL video pixel coordinates (not scaled preview coordinates).
- Times are explicitly approved; multiple regions/modes are supported.
- OCR is a one-frame, background-thread suggestion only, never auto-applied.
- Preview applies exactly the same user-region processor as the renderer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QPushButton, QSlider, QSpinBox, QSplitter,
    QVBoxLayout, QWidget
)

from media.visual_user_regions import (
    UserRegionError, apply_user_regions, validate_plan,
    validate_region, video_metadata
)


class VideoRegionCanvas(QWidget):
    """Letterboxed image view: map drag points back into native source pixels."""

    selectionChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 270)
        self.setMouseTracking(True)
        self.image = QImage()
        self.frame_size = (0, 0)
        self.selection = None
        self.regions = []
        self.suggestions = []
        self._drag_start = None

    def set_frame(self, bgr):
        height, width = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.image = QImage(rgb.data, width, height, rgb.strides[0],
                            QImage.Format_RGB888).copy()
        self.frame_size = (width, height)
        self.update()

    def _image_rect(self):
        width, height = self.frame_size
        if width < 1 or height < 1:
            return QRectF()
        scale = min(self.width()/width, self.height()/height)
        new_w, new_h = width*scale, height*scale
        return QRectF((self.width()-new_w)/2, (self.height()-new_h)/2,
                      new_w, new_h)

    def _source_point(self, pos):
        rect = self._image_rect()
        if rect.isEmpty() or not rect.contains(pos):
            return None
        width, height = self.frame_size
        x = max(0, min(width-1, int((pos.x()-rect.left())*width/rect.width())))
        y = max(0, min(height-1, int((pos.y()-rect.top())*height/rect.height())))
        return x, y

    def _visible_box(self, box):
        rect = self._image_rect()
        width, height = self.frame_size
        if width == 0 or height == 0:
            return QRectF()
        x1, y1, x2, y2 = box
        return QRectF(rect.left()+x1*rect.width()/width,
                      rect.top()+y1*rect.height()/height,
                      (x2-x1)*rect.width()/width,
                      (y2-y1)*rect.height()/height)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#161b25"))
        if self.image.isNull():
            painter.setPen(QColor("#eeeeee"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Không đọc được frame video")
            return
        painter.drawImage(self._image_rect(), self.image)
        for box in self.regions:
            painter.setPen(QPen(QColor("#00d49c"), 2))
            painter.drawRect(self._visible_box(box))
        for box in self.suggestions:
            painter.setPen(QPen(QColor("#f1a33c"), 1, Qt.DashLine))
            painter.drawRect(self._visible_box(box))
        if self.selection is not None:
            painter.setPen(QPen(QColor("#fff067"), 2))
            painter.drawRect(self._visible_box(self.selection))
        painter.end()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        point = self._source_point(event.position())
        if point is not None:
            self._drag_start = point
            self.selection = None
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_start is None:
            return
        point = self._source_point(event.position())
        if point is None:
            # Drag outside image: clamp to source image edges.
            rect = self._image_rect()
            point = self._source_point(
                type(event.position())(
                    min(max(event.position().x(), rect.left()+.01), rect.right()-.01),
                    min(max(event.position().y(), rect.top()+.01), rect.bottom()-.01)))
        if point is not None:
            x0,y0 = self._drag_start
            x1,y1 = point
            self.selection = [min(x0,x1),min(y0,y1),
                              max(x0,x1)+1,max(y0,y1)+1]
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_start is None:
            return
        self.mouseMoveEvent(event)
        self._drag_start = None
        if self.selection is not None:
            self.selectionChanged.emit(self.selection)


class OCRFrameWorker(QThread):
    suggestionsReady = Signal(object)
    detectionFailed = Signal(str)

    def __init__(self, frame, parent=None):
        super().__init__(parent)
        self.frame = frame.copy()

    def run(self):
        try:
            from media.visual_cleanup import PaddleDetector
            from media.visual_detection import detect_frame_candidates
            detector = PaddleDetector()
            # Three-pass detection runs entirely in the worker thread.
            self.suggestionsReady.emit(
                detect_frame_candidates(self.frame, detector))
        except Exception as exc:
            self.detectionFailed.emit(str(exc))


class VisualRegionEditor(QDialog):
    """Draw/edit blur regions and save a source-bound JSON review plan."""

    def __init__(self, video, plan_path, parent=None):
        super().__init__(parent)
        self.source = str(Path(video).expanduser().resolve())
        self.plan_path = Path(plan_path)
        self.meta = video_metadata(self.source)
        self.fps = self.meta["fps"]
        self.count = self.meta["frames"]
        self.duration = self.count / self.fps
        self.cap = cv2.VideoCapture(self.source)
        self.frame_number = 0
        self.frame = None
        self.regions = []
        self.other_regions = []
        self._ocr_worker = None
        self._ocr_boxes = []
        self._ocr_frame_number = None
        self._loading = False
        self.setWindowTitle("VietDub — Chọn vùng chữ/logo cần xử lý")
        self.resize(1120, 740)
        self.setMinimumSize(760, 560)
        self._build_ui()
        self._load_reviewed()
        self._show_frame(0)

    @staticmethod
    def default_plan_path(video, config_dir):
        import os
        path = Path(video).expanduser().resolve()
        fingerprint = hashlib.sha256(
            (str(path)+":"+str(path.stat().st_size)+":"+
             str(path.stat().st_mtime_ns)).encode("utf-8")).hexdigest()[:20]
        return Path(config_dir)/"visual_plans"/f"{fingerprint}.json"

    def _build_ui(self):
        root = QVBoxLayout(self)
        tip = QLabel(
            "Kéo chuột trên video để chọn vùng. Chỉnh thời gian bắt đầu/kết thúc "
            "và cách xử lý rồi bấm Thêm vùng. Màu xanh = vùng đã duyệt; "
            "màu cam = gợi ý OCR (chưa áp dụng)."
        )
        tip.setWordWrap(True)
        root.addWidget(tip)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        l = QVBoxLayout(left)
        self.canvas = VideoRegionCanvas()
        self.canvas.selectionChanged.connect(self._selection_from_canvas)
        l.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶ Phát")
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.count-1)
        self.slider.valueChanged.connect(self._show_frame)
        controls.addWidget(self.slider, 1)
        self.position = QLabel("00:00.000")
        controls.addWidget(self.position)
        l.addLayout(controls)
        self.preview = QCheckBox("Xem kết quả đã xử lý (trước/sau)")
        self.preview.toggled.connect(lambda _: self._show_frame(self.frame_number))
        l.addWidget(self.preview)
        splitter.addWidget(left)

        right = QWidget()
        r = QVBoxLayout(right)
        self.status = QLabel("Vùng chọn: chưa có")
        self.status.setWordWrap(True)
        r.addWidget(self.status)
        self.coords = {}
        coord_grid = QGridLayout()
        for i,(name,caption) in enumerate((
                ("x1","Trái X1"),("y1","Trên Y1"),
                ("x2","Phải X2"),("y2","Dưới Y2"))):
            control = QSpinBox()
            control.setRange(0, self.meta["width"] if name.startswith("x")
                             else self.meta["height"])
            control.valueChanged.connect(self._update_pending_from_fields)
            self.coords[name] = control
            coord_grid.addWidget(QLabel(caption),i//2*2,i%2)
            coord_grid.addWidget(control,i//2*2+1,i%2)
        r.addLayout(coord_grid)

        form = QFormLayout()
        self.from_sec = QDoubleSpinBox()
        self.to_sec = QDoubleSpinBox()
        for x in (self.from_sec, self.to_sec):
            x.setRange(0, self.duration)
            x.setDecimals(3)
            x.setSingleStep(1/self.fps)
            x.setSuffix(" s")
        self.from_sec.setValue(0)
        self.to_sec.setValue(min(self.duration,5))
        form.addRow("Bắt đầu:",self.from_sec)
        form.addRow("Kết thúc:",self.to_sec)
        self.kind = QComboBox()
        for label,code in (("Phụ đề","subtitle"),("Chữ cố định","text"),
                           ("Logo","logo")):
            self.kind.addItem(label,code)
        form.addRow("Loại vùng:",self.kind)
        self.mode = QComboBox()
        self.mode.addItem("Blur Gaussian","blur")
        self.mode.addItem("Mosaic / che pixel","pixelate")
        self.mode.addItem("Xóa & lấp nền (Telea)","inpaint")
        form.addRow("Cách xử lý:",self.mode)
        self.strength = QSpinBox()
        self.strength.setRange(1,64)
        self.strength.setValue(16)
        form.addRow("Cường độ:",self.strength)
        self.feather = QDoubleSpinBox()
        self.feather.setRange(0,16)
        self.feather.setSingleStep(.5)
        self.feather.setValue(2)
        form.addRow("Mềm cạnh:",self.feather)
        r.addLayout(form)

        row = QHBoxLayout()
        self.add_btn = QPushButton("＋ Thêm vùng")
        self.add_btn.clicked.connect(self._add)
        row.addWidget(self.add_btn)
        self.update_btn = QPushButton("Cập nhật")
        self.update_btn.clicked.connect(self._update)
        row.addWidget(self.update_btn)
        self.delete_btn = QPushButton("Xóa")
        self.delete_btn.clicked.connect(self._remove)
        row.addWidget(self.delete_btn)
        r.addLayout(row)
        r.addWidget(QLabel("Danh sách vùng đã chọn:"))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._pick_region)
        r.addWidget(self.list,1)
        self.detect_btn = QPushButton("✨ OCR nâng cao: tìm chữ ở frame này")
        self.detect_btn.clicked.connect(self._detect_frame)
        r.addWidget(self.detect_btn)
        self.suggestions = QComboBox()
        self.suggestions.addItem("Chưa có gợi ý OCR")
        self.suggestions.currentIndexChanged.connect(self._select_suggestion)
        r.addWidget(self.suggestions)
        root_info = QLabel(
            "Nhận diện OCR chỉ là gợi ý. Không tự thêm vùng hoặc tự làm mờ; "
            "user quyết định vị trí, thời gian và phương pháp xử lý."
        )
        root_info.setWordWrap(True)
        r.addWidget(root_info)
        splitter.addWidget(right)
        splitter.setSizes([715,385])

        buttons = QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Lưu vùng & dùng khi render")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)

    def _load_reviewed(self):
        if not self.plan_path.is_file():
            return
        try:
            plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
            _,manual = validate_plan(plan,self.source)
            self.regions = manual
            self.other_regions = [r for r in plan.get("regions",[])
                                  if r.get("source")!="user"]
            self._refresh_regions()
        except (OSError,ValueError,TypeError,KeyError) as exc:
            QMessageBox.warning(self,"Plan không hợp lệ",
                f"Plan cũ không dùng được với video này:\n{exc}\n"
                "Các vùng cũ chưa được áp dụng. Hãy duyệt lại và lưu.")

    def _show_frame(self, frame_index):
        self.frame_number = max(0,min(self.count-1,int(frame_index)))
        if self._ocr_frame_number != self.frame_number:
            self._ocr_boxes = []
            self.canvas.suggestions = []
            self.suggestions.blockSignals(True)
            self.suggestions.clear()
            self.suggestions.addItem("Chưa có gợi ý OCR cho frame này")
            self.suggestions.blockSignals(False)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES,self.frame_number)
        ok,frame = self.cap.read()
        if not ok:
            self.status.setText("Không đọc được frame; kiểm tra định dạng video.")
            return
        self.frame = frame
        canvas_frame = frame
        if self.preview.isChecked():
            try:
                canvas_frame = apply_user_regions(
                    frame,self.regions,self.frame_number,self.fps)
            except UserRegionError as exc:
                self.status.setText(f"Preview lỗi: {exc}")
        self.canvas.set_frame(canvas_frame)
        self.canvas.regions = [
            r["box"] for r in self.regions
            if round(r["start"]*self.fps)<=self.frame_number<
               round(r["end"]*self.fps)]
        self.canvas.update()
        minute,second = divmod(self.frame_number/self.fps,60)
        self.position.setText(f"{int(minute):02d}:{second:06.3f} "
                              f"({self.frame_number}/{self.count-1})")
        if self.slider.value()!=self.frame_number:
            self.slider.blockSignals(True)
            self.slider.setValue(self.frame_number)
            self.slider.blockSignals(False)

    def _advance(self):
        if self.frame_number>=self.count-1:
            self._toggle_play(False)
            return
        self._show_frame(self.frame_number+1)

    def _toggle_play(self, force=None):
        playing = not self.timer.isActive() if force is None else bool(force)
        if playing:
            self.timer.start(max(20,int(1000/self.fps)))
            self.play_btn.setText("⏸ Dừng")
        else:
            self.timer.stop()
            self.play_btn.setText("▶ Phát")

    def _selection_from_canvas(self,box):
        self._set_box(box)
        if self.list.currentRow()<0:
            t=self.frame_number/self.fps
            self.from_sec.setValue(t)
            self.to_sec.setValue(min(self.duration,t+3))
        self.status.setText(f"Đã chọn vùng {box}. Bấm Thêm vùng để áp dụng.")

    def _set_box(self,box):
        for key,value in zip(("x1","y1","x2","y2"),box):
            self.coords[key].blockSignals(True)
            self.coords[key].setValue(int(value))
            self.coords[key].blockSignals(False)
        self.canvas.selection = list(box)
        self.canvas.update()

    def _update_pending_from_fields(self):
        box=[self.coords[key].value()
             for key in ("x1","y1","x2","y2")]
        if box[0]<box[2] and box[1]<box[3]:
            self.canvas.selection=box
        else:
            self.canvas.selection=None
        self.canvas.update()

    def _current_record(self):
        box = [self.coords[key].value()
               for key in ("x1","y1","x2","y2")]
        return validate_region({
            "source":"user","box":box,
            "start":self.from_sec.value(),"end":self.to_sec.value(),
            "kind":self.kind.currentData(),"mode":self.mode.currentData(),
            "strength":self.strength.value(),"feather":self.feather.value()
        },self.meta["width"],self.meta["height"],self.duration)

    def _add(self):
        try:
            item=self._current_record()
        except UserRegionError as exc:
            QMessageBox.warning(self,"Vùng không hợp lệ",str(exc))
            return
        self.regions.append(item)
        self._refresh_regions()
        self.list.setCurrentRow(len(self.regions)-1)
        self._show_frame(self.frame_number)

    def _update(self):
        index=self.list.currentRow()
        if index<0:
            QMessageBox.information(self,"Chọn vùng","Chọn vùng trong danh sách để cập nhật.")
            return
        try:
            item=self._current_record()
        except UserRegionError as exc:
            QMessageBox.warning(self,"Vùng không hợp lệ",str(exc))
            return
        self.regions[index]=item
        self._refresh_regions()
        self.list.setCurrentRow(index)
        self._show_frame(self.frame_number)

    def _remove(self):
        index=self.list.currentRow()
        if index<0:
            return
        self.regions.pop(index)
        self._refresh_regions()
        self._show_frame(self.frame_number)

    def _refresh_regions(self):
        self.list.blockSignals(True)
        self.list.clear()
        for region in self.regions:
            x1,y1,x2,y2=region["box"]
            self.list.addItem(
                f'{region["kind"]} · {region["mode"]} · '
                f'{region["start"]:.2f}–{region["end"]:.2f}s '
                f'· [{x1},{y1}→{x2},{y2}]')
        self.list.blockSignals(False)

    def _pick_region(self,index):
        if index<0 or index>=len(self.regions):
            return
        r=self.regions[index]
        self._set_box(r["box"])
        self.from_sec.setValue(r["start"])
        self.to_sec.setValue(r["end"])
        self.kind.setCurrentIndex(max(0,self.kind.findData(r["kind"])))
        self.mode.setCurrentIndex(max(0,self.mode.findData(r["mode"])))
        self.strength.setValue(r["strength"])
        self.feather.setValue(r["feather"])

    def _detect_frame(self):
        if self.frame is None or self._ocr_worker is not None:
            return
        self.detect_btn.setEnabled(False)
        self.detect_btn.setText("Đang nhận diện OCR…")
        worker=OCRFrameWorker(self.frame,self)
        worker.requested_frame = self.frame_number
        self._ocr_worker=worker
        worker.suggestionsReady.connect(self._ocr_ready)
        worker.detectionFailed.connect(self._ocr_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._ocr_finished)
        worker.start()

    def _ocr_ready(self,items):
        if (self._ocr_worker is None or
                self._ocr_worker.requested_frame != self.frame_number):
            return  # Discard suggestions from an earlier frame after scrubbing.
        self._ocr_frame_number = self.frame_number
        self._ocr_boxes=[]
        for box,score in items:
            if score<.35:
                continue
            x1,y1,x2,y2=map(int,box)
            w,h=self.meta["width"],self.meta["height"]
            box=[max(0,x1-6),max(0,y1-6),
                 min(w,x2+6),min(h,y2+6)]
            if box[0]<box[2] and box[1]<box[3]:
                self._ocr_boxes.append((box,float(score)))
        self.suggestions.blockSignals(True)
        self.suggestions.clear()
        self.suggestions.addItem(
            f"Chọn một trong {len(self._ocr_boxes)} vùng OCR gợi ý")
        for index,(box,score) in enumerate(self._ocr_boxes):
            self.suggestions.addItem(
                f"#{index+1} · {score:.0%} · {box}",index)
        self.suggestions.blockSignals(False)
        self.canvas.suggestions=[box for box,_ in self._ocr_boxes]
        self.canvas.update()
        self.status.setText(
            f"OCR đề xuất {len(self._ocr_boxes)} vùng ở frame {self.frame_number}. "
            "Chọn gợi ý để chỉnh và thêm; chưa vùng nào tự được xử lý.")

    def _ocr_failed(self,message):
        QMessageBox.warning(self,"OCR chưa sẵn sàng",
                            "Không thể nhận diện frame hiện tại.\n"
                            "Anh vẫn có thể tự khoanh vùng bằng chuột.\n\n"+message)

    def _ocr_finished(self):
        self._ocr_worker=None
        self.detect_btn.setEnabled(True)
        self.detect_btn.setText("✨ OCR nâng cao: tìm chữ ở frame này")

    def _select_suggestion(self,index):
        if index<=0 or index>len(self._ocr_boxes):
            return
        box,_score=self._ocr_boxes[index-1]
        self.list.clearSelection()
        self.list.setCurrentRow(-1)
        self._set_box(box)
        t=self.frame_number/self.fps
        self.from_sec.setValue(t)
        self.to_sec.setValue(min(self.duration,t+3))
        self.status.setText("Đã lấy gợi ý OCR, có thể kéo/chỉnh tọa độ rồi Thêm vùng.")

    def _save(self):
        if not self.regions and not self.other_regions:
            QMessageBox.warning(self,"Chưa chọn vùng",
                                "Hãy khoanh ít nhất một vùng cần làm mờ.")
            return
        try:
            clean = [validate_region(x,self.meta["width"],
                        self.meta["height"],self.duration) for x in self.regions]
            plan={**self.meta,"regions":self.other_regions+clean,
                  "reviewed":True}
            self.plan_path.parent.mkdir(parents=True,exist_ok=True)
            # Atomic write prevents a truncated plan if app closes mid-save.
            tmp=self.plan_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(plan,ensure_ascii=False,indent=2),
                           encoding="utf-8")
            tmp.replace(self.plan_path)
        except (UserRegionError,OSError,ValueError) as exc:
            QMessageBox.critical(self,"Không lưu được plan",str(exc))
            return
        self.accept()

    def closeEvent(self,event):  # noqa: N802
        self.timer.stop()
        if self._ocr_worker is not None:
            # The decoder frame copy is owned by the thread; let OCR finish
            # before the dialog and its QObject parent are destroyed.
            self._ocr_worker.wait()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        super().closeEvent(event)

    def done(self,result):
        self.timer.stop()
        if self._ocr_worker is not None:
            self._ocr_worker.wait()
        if self.cap is not None:
            self.cap.release()
            self.cap=None
        super().done(result)
