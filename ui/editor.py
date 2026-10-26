# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Post-render video editor: trim, drag subtitle timing and add a logo."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRectF, QSizeF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QPainter, QPen,
                           QPixmap, QTextOption)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsTextItem, QGraphicsView, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from core import checkpoint as cp
from core.job import Job
from core.settings import Settings
from media import extract as mextract
from media.editor import export_edit
from project import io as pio
from project.schema import Segment
from ui.common import error_box, fmt_time, info_box
from ui.editor_style import EDITOR_STYLESHEET
from ui.poster_loader import PosterLoader
from ui.theme import UI_COLORS


class VideoCanvas(QGraphicsView):
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)


class Timeline(QWidget):
    seek_requested = Signal(int)
    subtitle_selected = Signal(int)
    subtitle_changed = Signal(int, float, float)
    trim_changed = Signal(float, float)

    def __init__(self, segments: list[Segment], duration: float):
        super().__init__()
        self.segments = segments
        self.duration = duration
        self.trim_start = 0.0
        self.trim_end = duration
        self.position = 0.0
        self.selected = -1
        self.px_per_sec = 24
        self.drag: tuple[str, int, float, float, float] | None = None
        self.setFixedHeight(160)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Dòng thời gian video và phụ đề")
        self.setAccessibleDescription(
            "Trái, Phải: tua 1 giây; Shift cùng Trái, Phải: tua 0,1 giây; "
            "Home: đầu video; End: cuối video. Dùng ô thời gian để chỉnh điểm cắt và phụ đề.")
        self.setToolTip(self.accessibleDescription())
        self.set_zoom(24)

    def set_zoom(self, value: int) -> None:
        self.px_per_sec = value
        viewport_width = self.parentWidget().width() if self.parentWidget() else 0
        self.setFixedWidth(max(viewport_width, 400,
                               int(self.duration * value) + 25))
        self.update()

    def _x(self, sec: float) -> float:
        return sec * self.px_per_sec + 12

    def _time(self, x: float) -> float:
        return max(0.0, min(self.duration, (x - 12) / self.px_per_sec))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(event.rect(), QColor(UI_COLORS["control"]))
        left = max(0, int(self._time(event.rect().left())) - 1)
        right = min(int(self.duration) + 1, int(self._time(event.rect().right())) + 2)
        tick = 1 if self.px_per_sec >= 55 else (5 if self.px_per_sec >= 18 else 10)
        p.setPen(QColor(UI_COLORS["secondary_text"]))
        for sec in range(left - left % tick, right + 1, tick):
            x = int(self._x(sec))
            p.drawLine(x, 19, x, 27)
            p.drawText(x + 5, 15, fmt_time(sec))
            p.setPen(QColor(UI_COLORS["border"]))
            p.drawLine(x, 29, x, 154)
            p.setPen(QColor(UI_COLORS["secondary_text"]))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(UI_COLORS["disabled_surface"]))
        p.drawRoundedRect(QRectF(12, 32, self.duration * self.px_per_sec, 38), 6, 6)
        p.setBrush(QColor(UI_COLORS["primary"]))
        p.drawRoundedRect(QRectF(self._x(self.trim_start), 32,
                                 max(1, (self.trim_end - self.trim_start)
                                     * self.px_per_sec), 38), 6, 6)
        p.setPen(QColor(UI_COLORS["control"]))
        p.drawText(int(self._x(self.trim_start)) + 10, 55, "HÌNH ẢNH")
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(UI_COLORS["selection"]))
        for sec in (self.trim_start, self.trim_end):
            p.drawRoundedRect(QRectF(self._x(sec) - 4, 32, 8, 38), 3, 3)
        p.setBrush(QColor("#e5f5f0"))
        p.drawRoundedRect(QRectF(12, 78, self.duration * self.px_per_sec, 28), 5, 5)
        p.setPen(QColor("#167253"))
        p.drawText(21, 97, "LỒNG TIẾNG")
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f1edf9"))
        p.drawRoundedRect(QRectF(12, 114, self.duration * self.px_per_sec, 36), 5, 5)
        for i, seg in enumerate(self.segments):
            x1, x2 = self._x(seg.start), self._x(seg.end)
            if x2 < event.rect().left() or x1 > event.rect().right():
                continue
            rect = QRectF(x1, 116, max(3, x2 - x1), 32)
            p.setBrush(QColor("#7655c3" if i == self.selected else "#d9cdf4"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect, 4, 4)
            p.setPen(QColor("#ffffff" if i == self.selected else "#44316e"))
            label = p.fontMetrics().elidedText(seg.text_vi or f"Câu {i + 1}",
                                                Qt.ElideRight, max(0, int(rect.width()) - 12))
            p.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter, label)
        p.setPen(QPen(QColor("#df6f32"), 2))
        x = int(self._x(self.position))
        p.drawLine(x, 27, x, 155)
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(UI_COLORS["focus"]), 2))
            p.drawRect(QRectF(self.visibleRegion().boundingRect()).adjusted(1, 1, -2, -2))
        p.end()

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            super().keyPressEvent(event)
            return
        if key in (Qt.Key_Left, Qt.Key_Right):
            step = 0.1 if event.modifiers() & Qt.ShiftModifier else 1.0
            position = self.position + (-step if key == Qt.Key_Left else step)
        elif key == Qt.Key_Home:
            position = 0.0
        elif key == Qt.Key_End:
            position = self.duration
        else:
            super().keyPressEvent(event)
            return
        self.position = max(0.0, min(self.duration, position))
        self.seek_requested.emit(round(self.position * 1000))
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        self.setFocus(Qt.MouseFocusReason)
        x, y = event.position().x(), event.position().y()
        if 32 <= y <= 72:
            if abs(x - self._x(self.trim_start)) <= 9:
                self.drag = ("trim_start", -1, x, self.trim_start, self.trim_end)
            elif abs(x - self._x(self.trim_end)) <= 9:
                self.drag = ("trim_end", -1, x, self.trim_start, self.trim_end)
            else:
                self.drag = ("seek", -1, x, 0.0, 0.0)
                self.seek_requested.emit(round(self._time(x) * 1000))
        elif 114 <= y <= 151:
            for i in range(len(self.segments) - 1, -1, -1):
                seg = self.segments[i]
                if self._x(seg.start) <= x <= self._x(seg.end):
                    edge = 7
                    mode = ("sub_start" if abs(x - self._x(seg.start)) <= edge
                            else "sub_end" if abs(x - self._x(seg.end)) <= edge
                            else "sub_move")
                    self.drag = (mode, i, x, seg.start, seg.end)
                    self.selected = i
                    self.subtitle_selected.emit(i)
                    self.update()
                    break
        else:
            self.drag = ("seek", -1, x, 0.0, 0.0)
            self.seek_requested.emit(round(self._time(x) * 1000))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.drag is None:
            x, y = event.position().x(), event.position().y()
            if 32 <= y <= 72 and any(
                    abs(x - self._x(sec)) <= 9
                    for sec in (self.trim_start, self.trim_end)):
                self.setCursor(Qt.SizeHorCursor)
            elif 114 <= y <= 151 and any(
                    self._x(seg.start) <= x <= self._x(seg.end)
                    for seg in self.segments):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return
        mode, index, x0, start, end = self.drag
        x = event.position().x()
        t = self._time(x)
        delta = (x - x0) / self.px_per_sec
        if mode == "seek":
            self.seek_requested.emit(round(t * 1000))
        elif mode == "trim_start":
            self.trim_start = max(0.0, min(t, self.trim_end - 0.1))
            self.trim_changed.emit(self.trim_start, self.trim_end)
        elif mode == "trim_end":
            self.trim_end = min(self.duration, max(t, self.trim_start + 0.1))
            self.trim_changed.emit(self.trim_start, self.trim_end)
        else:
            self.setCursor(Qt.ClosedHandCursor if mode == "sub_move"
                           else Qt.SizeHorCursor)
            if mode == "sub_start":
                a, b = max(0.0, min(start + delta, end - 0.1)), end
            elif mode == "sub_end":
                a, b = start, min(self.duration, max(start + 0.1, end + delta))
            else:
                a = max(0.0, min(self.duration - (end - start), start + delta))
                b = a + end - start
            self.subtitle_changed.emit(index, round(a, 2), round(b, 2))
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.drag = None
        self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)


class ExportWorker(QObject):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, args: tuple, kwargs: dict):
        super().__init__()
        self.args, self.kwargs = args, kwargs

    def run(self) -> None:
        try:
            self.done.emit(str(export_edit(*self.args, **self.kwargs)))
        except Exception as exc:  # noqa: BLE001 - displayed in editor
            self.failed.emit(str(exc))


class EditorWindow(QWidget):
    def __init__(self, job: Job, settings: Settings,
                 on_export: Callable[[str, str], None]):
        super().__init__()
        self.job, self.settings, self.on_export = job, settings, on_export
        fetch = cp.load_step(job.job_dir, "fetch") or {}
        mix = cp.load_step(job.job_dir, "mix") or {}
        render = cp.load_step(job.job_dir, "render") or {}
        self.source = fetch.get("video_path") or job.project.video_in
        self.mixed_wav = mix.get("mixed_wav", "")
        if not Path(self.source).is_file() or not Path(self.mixed_wav).is_file():
            raise ValueError("Cần video gốc và audio đã trộn để biên tập.")
        self.duration = mextract.duration_sec(self.source)
        if self.duration <= 0:
            raise ValueError("Không đọc được thời lượng video.")
        self.segments = [Segment.from_dict(s.to_dict()) for s in
                         (pio.load_segments(job.job_dir, "tts") or
                          pio.load_segments(job.job_dir, "translate") or [])]
        self.draft_path = job.stages_dir / "editor.json"
        base = Path(render.get("video_out") or job.project.video_out or
                    job.job_dir / "video.mp4")
        stem = base.stem[:-5] if base.stem.endswith("_edit") else base.stem
        self.output_path = base.with_name(stem + "_edit.mp4")
        self.logo_path = ""
        self._thread: QThread | None = None
        self._worker: ExportWorker | None = None
        self._pending_result: str | None = None
        self._pending_error: str | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._save_draft)
        self._ready = False
        self._draft_error = ""
        self._media_errors: dict[str, str] = {}
        self._resetting_media = False
        draft = self._load_draft()

        self.setWindowTitle(f"VietDub — Biên tập: {job.project.name}")
        self.resize(1280, 800)
        self.setMinimumSize(650, 560)
        self._tools_open = False
        self.setObjectName("editorRoot")
        self.setStyleSheet(EDITOR_STYLESHEET)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)
        header_bar = QFrame()
        header_bar.setObjectName("editorToolbar")
        header_layout = QVBoxLayout(header_bar)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(8)
        header_layout.addLayout(header)
        back = QPushButton("←")
        back.setProperty("role", "quiet")
        back.setToolTip("Về màn thành phẩm")
        back.setAccessibleName("Về màn thành phẩm")
        back.setFixedWidth(38)
        back.clicked.connect(self.close)
        header.addWidget(back)
        mark = QLabel("VD")
        mark.setObjectName("editorMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(34, 34)
        header.addWidget(mark)
        self.brand_mark = mark
        identity = QVBoxLayout()
        identity.setSpacing(0)
        title = QLabel("VietDub · Biên tập")
        title.setObjectName("editorTitle")
        identity.addWidget(title)
        self.project_label = QLabel(Path(self.source).name)
        self.project_label.setObjectName("editorProject")
        self.project_label.setMaximumWidth(250)
        self.project_label.setToolTip(self.source)
        identity.addWidget(self.project_label)
        header.addLayout(identity)
        header.addStretch(1)
        self.draft_badge = QLabel("Chưa lưu bản nháp")
        self.draft_badge.setObjectName("editorBadge")
        self.draft_badge.setAccessibleName("Trạng thái lưu bản nháp")
        header.addWidget(self.draft_badge)
        self.btn_save = QPushButton("Lưu nháp")
        self.btn_save.setToolTip("Lưu ngay hoặc thử lại khi không lưu được bản nháp")
        self.btn_save.clicked.connect(self._save_draft)
        header.addWidget(self.btn_save)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        header_layout.addLayout(actions)
        self.btn_tools = QPushButton("Công cụ")
        self.btn_tools.setProperty("role", "quiet")
        self.btn_tools.clicked.connect(self._toggle_tools)
        actions.addWidget(self.btn_tools)
        choose_output = QPushButton("Nơi lưu…")
        choose_output.setProperty("role", "quiet")
        choose_output.setMaximumWidth(105)
        choose_output.clicked.connect(self._choose_output)
        actions.addWidget(choose_output)
        self.btn_output = choose_output
        self.btn_export = QPushButton("Xuất MP4")
        self.btn_export.setProperty("role", "primary")
        self.btn_export.setMaximumWidth(125)
        self.btn_export.clicked.connect(self.export)
        actions.addWidget(self.btn_export)
        root.addWidget(header_bar)

        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.workspace_scroll.setAccessibleName("Vùng biên tập; cuộn để xem đầy đủ công cụ")
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        self.workspace_split = split
        self.workspace_scroll.setWidget(split)
        top = QSplitter(Qt.Horizontal)
        top.setChildrenCollapsible(False)
        top.setMinimumHeight(245)
        preview = QFrame()
        preview.setObjectName("editorCard")
        preview_lay = QVBoxLayout(preview)
        preview_lay.setContentsMargins(12, 8, 12, 12)
        preview_lay.setSpacing(8)
        preview_head = QHBoxLayout()
        preview_name = QLabel("XEM TRƯỚC")
        preview_name.setObjectName("editorEyebrow")
        preview_head.addWidget(preview_name)
        preview_head.addStretch(1)
        source_label = QLabel(f"NGUỒN GỐC  ·  {fmt_time(self.duration)}")
        source_label.setObjectName("editorHint")
        preview_head.addWidget(source_label)
        preview_lay.addLayout(preview_head)
        self.scene = QGraphicsScene(self)
        self.poster_pix = QPixmap()
        self._has_shown_video_frame = False
        self.poster_item = QGraphicsPixmapItem()
        self.poster_item.setZValue(-1)
        self.scene.addItem(self.poster_item)
        self.video_item = QGraphicsVideoItem()
        self.video_item.setSize(QSizeF(1280, 720))
        self.scene.addItem(self.video_item)
        self.scene.setSceneRect(QRectF(0, 0, 1280, 720))
        self._fit_poster()
        self.sub_back = QGraphicsRectItem()
        self.sub_back.setBrush(QColor(0, 0, 0, 160))
        self.sub_back.setPen(Qt.NoPen)
        self.sub_back.setZValue(2)
        self.scene.addItem(self.sub_back)
        self.sub_item = QGraphicsTextItem()
        self.sub_item.setDefaultTextColor(Qt.white)
        self.sub_item.setZValue(3)
        self.scene.addItem(self.sub_item)
        self.logo_item = QGraphicsPixmapItem()
        self.logo_item.setZValue(1)
        self.scene.addItem(self.logo_item)
        self.canvas = VideoCanvas(self.scene)
        self.canvas.setFrameShape(QFrame.NoFrame)
        self.canvas.setBackgroundBrush(QColor(UI_COLORS["media"]))
        self.canvas.setMinimumSize(120, 72)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas.setAccessibleName("Xem trước video với phụ đề và logo")
        self.canvas.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        preview_lay.addWidget(self.canvas, 1)
        media_row = QHBoxLayout()
        self.media_status = QLabel("Đang tải hình ảnh và lồng tiếng…")
        self.media_status.setProperty("role", "secondary")
        self.media_status.setWordWrap(True)
        self.media_status.setMinimumWidth(0)
        self.media_status.setAccessibleDescription("Trạng thái xem trước")
        media_row.addWidget(self.media_status, 1)
        self.btn_retry_media = QPushButton("Thử tải lại")
        self.btn_retry_media.clicked.connect(self._retry_media)
        self.btn_retry_media.hide()
        media_row.addWidget(self.btn_retry_media)
        preview_lay.addLayout(media_row)
        transport = QFrame()
        transport.setObjectName("editorToolbar")
        controls = QHBoxLayout(transport)
        controls.setContentsMargins(8, 4, 8, 4)
        controls.setSpacing(8)
        self.btn_play = QPushButton("▶  Phát")
        self.btn_play.setProperty("role", "quiet")
        self.btn_play.clicked.connect(self.toggle_play)
        controls.addWidget(self.btn_play)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, round(self.duration * 1000))
        self.seek.setSingleStep(1000)
        self.seek.setPageStep(5000)
        self.seek.setAccessibleName("Vị trí phát video")
        self.seek.setToolTip("Dùng phím Trái hoặc Phải để tua 1 giây")
        self.seek.valueChanged.connect(self._seek)
        controls.addWidget(self.seek, 1)
        self.time_label = QLabel("00:00 / " + fmt_time(self.duration))
        self.time_label.setObjectName("editorTime")
        controls.addWidget(self.time_label)
        preview_lay.addWidget(transport)
        self.preview_panel = preview
        self.inspector_panel = self._build_inspector()
        top.addWidget(self.preview_panel)
        top.addWidget(self.inspector_panel)
        corner = self.corner.findData(draft.get("logo_corner", "top-right"))
        self.corner.setCurrentIndex(max(0, corner))
        self.logo_size.setValue(int(draft.get("logo_width_pct", 12)))
        self.logo_opacity.setValue(int(draft.get("logo_opacity_pct", 85)))
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 2)

        timeline_panel = QFrame()
        timeline_panel.setObjectName("editorCard")
        timeline_panel.setMinimumHeight(300)
        timeline_lay = QVBoxLayout(timeline_panel)
        timeline_lay.setContentsMargins(12, 8, 12, 12)
        timeline_lay.setSpacing(4)
        tools = QHBoxLayout()
        track_title = QLabel("DÒNG THỜI GIAN")
        track_title.setObjectName("editorSection")
        tools.addWidget(track_title)
        self.trim_label = QLabel()
        self.trim_label.setProperty("role", "secondary")
        tools.addWidget(self.trim_label)
        tools.addStretch(1)
        zoom_label = QLabel("THU PHÓNG")
        zoom_label.setObjectName("editorEyebrow")
        tools.addWidget(zoom_label)
        zoom = QSlider(Qt.Horizontal)
        zoom.setRange(8, 160)
        zoom.setValue(24)
        zoom.setMaximumWidth(140)
        zoom.setAccessibleName("Thu phóng dòng thời gian")
        zoom_label.setBuddy(zoom)
        self.zoom_slider = zoom
        self._zoom_user_adjusted = False
        zoom.sliderPressed.connect(
            lambda: setattr(self, "_zoom_user_adjusted", True))
        tools.addWidget(zoom)
        timeline_lay.addLayout(tools)
        self.timeline = Timeline(self.segments, self.duration)
        self.timeline.trim_start = max(0.0, min(float(draft.get("trim_start", 0)),
                                                self.duration - 0.1))
        self.timeline.trim_end = max(self.timeline.trim_start + 0.1,
                                     min(float(draft.get("trim_end", self.duration)),
                                         self.duration))
        trim_controls = QHBoxLayout()
        self.trim_start_spin = QDoubleSpinBox()
        self.trim_end_spin = QDoubleSpinBox()
        for label_text, spin in (("Cắt từ", self.trim_start_spin),
                                 ("Cắt đến", self.trim_end_spin)):
            label = QLabel(label_text)
            label.setBuddy(spin)
            spin.setAccessibleName(f"{label_text} (giây)")
            spin.setDecimals(2)
            spin.setRange(0, self.duration)
            spin.setSingleStep(0.1)
            spin.setSuffix(" giây")
            spin.setMinimumWidth(110)
            spin.editingFinished.connect(self._numeric_trim_changed)
            trim_controls.addWidget(label)
            trim_controls.addWidget(spin, 1)
        timeline_lay.addLayout(trim_controls)
        self._trim_changed(self.timeline.trim_start, self.timeline.trim_end)
        self.timeline.seek_requested.connect(self._seek)
        self.timeline.subtitle_selected.connect(self._select_from_timeline)
        self.timeline.subtitle_changed.connect(self._change_segment)
        self.timeline.trim_changed.connect(self._trim_changed)
        zoom.valueChanged.connect(self.timeline.set_zoom)
        scroll = QScrollArea()
        scroll.setWidget(self.timeline)
        scroll.setWidgetResizable(False)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("timelineScroll")
        self.timeline_scroll = scroll
        timeline_lay.addWidget(scroll, 1)
        seek_controls = QHBoxLayout()
        for text, target in (("Về đầu", lambda: 0),
                             ("−1 giây", lambda: round(self.timeline.position * 1000) - 1000),
                             ("+1 giây", lambda: round(self.timeline.position * 1000) + 1000),
                             ("Về cuối", lambda: round(self.duration * 1000))):
            button = QPushButton(text)
            button.setAccessibleName(f"Tua video: {text.lower()}")
            button.clicked.connect(lambda _checked=False, target=target: self._seek(target()))
            seek_controls.addWidget(button)
        keyboard_hint = QLabel("← →: 1 giây · Shift: 0,1 giây · Home / End: đầu / cuối video")
        keyboard_hint.setObjectName("editorHint")
        keyboard_hint.setWordWrap(True)
        timeline_lay.addLayout(seek_controls)
        timeline_lay.addWidget(keyboard_hint)
        split.addWidget(top)
        split.addWidget(timeline_panel)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        root.addWidget(self.workspace_scroll, 1)
        footer = QHBoxLayout()
        self.status = QLabel("Kéo mép video hoặc nhập điểm cắt; chọn câu để sửa phụ đề.")
        self.status.setMinimumWidth(0)
        self.status.setMaximumHeight(58)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setAccessibleDescription("Trạng thái biên tập và xuất video")
        self.status.setProperty("role", "secondary")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 0)
        self.export_progress.setMaximumWidth(105)
        self.export_progress.setAccessibleName("Đang xuất video; chưa có phần trăm tiến độ")
        self.export_progress.hide()
        footer.addWidget(self.export_progress)
        self.footer_hint = QLabel("HÌNH  /  LỒNG TIẾNG  /  PHỤ ĐỀ")
        self.footer_hint.setObjectName("editorEyebrow")
        footer.addWidget(self.footer_hint)
        root.addLayout(footer)

        self.player = QMediaPlayer(self)
        # The source video's sound stays muted; the dubbed mix is played by
        # the second player. Delay opening the sound device until Play so an
        # unavailable audio backend cannot prevent the editor from opening.
        self.player.setVideoOutput(self.video_item)
        self.dub_player = QMediaPlayer(self)
        self.dub_audio: QAudioOutput | None = None
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(self._on_playback)
        for name, player in (("Hình ảnh", self.player), ("Lồng tiếng", self.dub_player)):
            player.mediaStatusChanged.connect(lambda _status: self._update_media_status())
            player.errorOccurred.connect(
                lambda _error, message, name=name: self._media_failed(name, message))
        self.video_item.nativeSizeChanged.connect(self._video_size_changed)
        self.player.setSource(QUrl.fromLocalFile(self.source))
        self.dub_player.setSource(QUrl.fromLocalFile(self.mixed_wav))
        self._update_logo()
        self._update_subtitle(0)
        if self.segments:
            self._select_segment(0)
        self._ready = True
        self._set_draft_state("Đã mở bản nháp" if draft else "Chưa lưu bản nháp")
        if self._draft_error:
            self._set_draft_state("Không đọc được bản nháp", self._draft_error, error=True)
        self._apply_responsive_layout()
        self.poster_loader = PosterLoader(self)
        self.poster_loader.ready.connect(self._poster_ready)
        self.poster_loader.request(self.source, str(job.stages_dir))

    def _build_inspector(self) -> QFrame:
        card = QFrame()
        card.setObjectName("editorCard")
        card.setMinimumWidth(280)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)
        eyebrow = QLabel("CÔNG CỤ BIÊN TẬP")
        eyebrow.setObjectName("editorEyebrow")
        layout.addWidget(eyebrow)
        self.inspector_tabs = QTabWidget()
        layout.addWidget(self.inspector_tabs, 1)

        subtitle_page = QWidget()
        sl = QVBoxLayout(subtitle_page)
        sl.setContentsMargins(4, 8, 4, 4)
        sl.setSpacing(8)
        list_head = QHBoxLayout()
        list_title = QLabel("Danh sách câu")
        list_title.setObjectName("editorSection")
        list_head.addWidget(list_title)
        list_head.addStretch(1)
        self.subtitle_count_label = QLabel(f"{len(self.segments)} câu")
        self.subtitle_count_label.setObjectName("editorHint")
        list_head.addWidget(self.subtitle_count_label)
        sl.addLayout(list_head)
        self.sub_list = QListWidget()
        self.sub_list.setMinimumHeight(80)
        self.sub_list.setMaximumHeight(140)
        self.sub_list.setAccessibleName("Danh sách câu phụ đề")
        self.sub_list.currentRowChanged.connect(self._select_from_list)
        for i in range(len(self.segments)):
            self.sub_list.addItem(self._segment_label(i))
        sl.addWidget(self.sub_list, 1)
        text_label = QLabel("NỘI DUNG PHỤ ĐỀ")
        text_label.setObjectName("editorEyebrow")
        sl.addWidget(text_label)
        self.sub_text = QPlainTextEdit()
        self.sub_text.setPlaceholderText("Chọn một câu để chỉnh nội dung…")
        self.sub_text.setToolTip("Sửa chữ phụ đề không đổi lời lồng tiếng đã tạo.")
        self.sub_text.setMaximumHeight(88)
        self.sub_text.setMinimumHeight(58)
        self.sub_text.setAccessibleName("Nội dung phụ đề đã chọn")
        text_label.setBuddy(self.sub_text)
        self.sub_text.textChanged.connect(self._text_changed)
        sl.addWidget(self.sub_text)
        time_label = QLabel("THỜI GIAN HIỂN THỊ")
        time_label.setObjectName("editorEyebrow")
        sl.addWidget(time_label)
        times = QHBoxLayout()
        times.setSpacing(8)
        self.start_spin = QDoubleSpinBox()
        self.end_spin = QDoubleSpinBox()
        for label_text, spin in (("Bắt đầu", self.start_spin), ("Kết thúc", self.end_spin)):
            column = QVBoxLayout()
            label = QLabel(label_text)
            label.setBuddy(spin)
            column.addWidget(label)
            column.addWidget(spin)
            times.addLayout(column, 1)
            spin.setAccessibleName(f"{label_text} phụ đề (giây)")
            spin.setSingleStep(0.1)
            spin.setDecimals(2)
            spin.setRange(0, self.duration)
            spin.setSuffix(" giây")
            spin.editingFinished.connect(self._time_changed)
        sl.addLayout(times)
        actions = QHBoxLayout()
        add = QPushButton("＋  Thêm câu")
        add.clicked.connect(self._add_segment)
        remove = QPushButton("Xóa câu")
        remove.setProperty("role", "danger")
        remove.clicked.connect(self._remove_segment)
        actions.addWidget(add, 1)
        actions.addWidget(remove)
        sl.addLayout(actions)
        note = QLabel("Kéo khối tím hoặc nhập thời gian bắt đầu, kết thúc để chỉnh phụ đề.")
        note.setObjectName("editorHint")
        note.setWordWrap(True)
        sl.addWidget(note)
        sub_scroll = QScrollArea()
        sub_scroll.setWidgetResizable(True)
        sub_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sub_scroll.setWidget(subtitle_page)
        self.inspector_tabs.addTab(sub_scroll, "Phụ đề")

        logo_page = QWidget()
        ll = QVBoxLayout(logo_page)
        ll.setContentsMargins(4, 8, 4, 4)
        ll.setSpacing(12)
        logo_title = QLabel("Đóng logo")
        logo_title.setObjectName("editorSection")
        ll.addWidget(logo_title)
        note = QLabel("Ảnh PNG nền trong cho kết quả đẹp nhất.")
        note.setObjectName("editorHint")
        note.setWordWrap(True)
        ll.addWidget(note)
        self.logo_edit = QLineEdit(self.logo_path)
        self.logo_edit.setReadOnly(True)
        self.logo_edit.setAccessibleName("Đường dẫn ảnh logo")
        self.logo_edit.setPlaceholderText("Chưa chọn ảnh logo")
        ll.addWidget(self.logo_edit)
        logo_row = QHBoxLayout()
        choose = QPushButton("Chọn ảnh…")
        choose.clicked.connect(self._choose_logo)
        logo_row.addWidget(choose, 1)
        clear = QPushButton("Bỏ logo")
        clear.setProperty("role", "quiet")
        clear.clicked.connect(self._clear_logo)
        logo_row.addWidget(clear)
        ll.addLayout(logo_row)
        position_label = QLabel("VỊ TRÍ")
        position_label.setObjectName("editorEyebrow")
        ll.addWidget(position_label)
        self.corner = QComboBox()
        self.corner.setAccessibleName("Vị trí logo")
        position_label.setBuddy(self.corner)
        for label, value in (("Trên trái", "top-left"), ("Trên phải", "top-right"),
                             ("Dưới trái", "bottom-left"),
                             ("Dưới phải", "bottom-right")):
            self.corner.addItem(label, value)
        self.corner.currentIndexChanged.connect(self._update_logo)
        ll.addWidget(self.corner)
        size_row = QHBoxLayout()
        size_label = QLabel("KÍCH THƯỚC")
        size_label.setObjectName("editorEyebrow")
        size_row.addWidget(size_label)
        size_row.addStretch(1)
        self.logo_size_value = QLabel("12%")
        self.logo_size_value.setObjectName("editorHint")
        size_row.addWidget(self.logo_size_value)
        ll.addLayout(size_row)
        self.logo_size = QSlider(Qt.Horizontal)
        self.logo_size.setRange(5, 50)
        self.logo_size.setAccessibleName("Kích thước logo theo phần trăm chiều rộng")
        size_label.setBuddy(self.logo_size)
        self.logo_size.setValue(12)
        self.logo_size.valueChanged.connect(self._update_logo)
        ll.addWidget(self.logo_size)
        opacity_row = QHBoxLayout()
        opacity_label = QLabel("ĐỘ HIỆN")
        opacity_label.setObjectName("editorEyebrow")
        opacity_row.addWidget(opacity_label)
        opacity_row.addStretch(1)
        self.logo_opacity_value = QLabel("85%")
        self.logo_opacity_value.setObjectName("editorHint")
        opacity_row.addWidget(self.logo_opacity_value)
        ll.addLayout(opacity_row)
        self.logo_opacity = QSlider(Qt.Horizontal)
        self.logo_opacity.setRange(0, 100)
        self.logo_opacity.setAccessibleName("Độ hiện logo theo phần trăm")
        opacity_label.setBuddy(self.logo_opacity)
        self.logo_opacity.setValue(85)
        self.logo_opacity.valueChanged.connect(self._update_logo)
        ll.addWidget(self.logo_opacity)
        ll.addStretch(1)
        logo_scroll = QScrollArea()
        logo_scroll.setWidgetResizable(True)
        logo_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        logo_scroll.setWidget(logo_page)
        self.inspector_tabs.addTab(logo_scroll, "Logo")
        return card

    def _segment_label(self, i: int) -> str:
        s = self.segments[i]
        return f"{fmt_time(s.start)}  {s.text_vi.replace(chr(10), ' ')[:50]}"

    def _select_segment(self, i: int) -> None:
        if not 0 <= i < len(self.segments):
            return
        self.timeline.selected = i
        self.timeline.update()
        self.sub_list.blockSignals(True)
        self.sub_list.setCurrentRow(i)
        self.sub_list.blockSignals(False)
        seg = self.segments[i]
        self.sub_text.blockSignals(True)
        self.sub_text.setPlainText(seg.text_vi)
        self.sub_text.blockSignals(False)
        for spin, value in ((self.start_spin, seg.start), (self.end_spin, seg.end)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _select_from_list(self, i: int) -> None:
        self._select_segment(i)
        if 0 <= i < len(self.segments):
            self._seek(round(self.segments[i].start * 1000))

    def _select_from_timeline(self, i: int) -> None:
        self._select_segment(i)
        if 0 <= i < len(self.segments):
            self._seek(round(self.segments[i].start * 1000))

    def _change_segment(self, i: int, start: float, end: float) -> None:
        if not 0 <= i < len(self.segments) or end - start < 0.09:
            return
        self.segments[i].start, self.segments[i].end = start, end
        self.sub_list.item(i).setText(self._segment_label(i))
        if i == self.timeline.selected:
            self._select_segment(i)
        self.timeline.update()
        self._update_subtitle(self.player.position() / 1000)
        self._schedule_save()

    def _time_changed(self) -> None:
        i = self.timeline.selected
        if i >= 0:
            a, b = self.start_spin.value(), self.end_spin.value()
            if b > a + 0.09:
                self._change_segment(i, a, b)
            else:
                self.status.setText("Thời điểm kết thúc phải sau thời điểm bắt đầu.")
                self._select_segment(i)

    def _text_changed(self) -> None:
        i = self.timeline.selected
        if i >= 0:
            self.segments[i].text_vi = self.sub_text.toPlainText()
            self.sub_list.item(i).setText(self._segment_label(i))
            self.timeline.update()
            self._update_subtitle(self.player.position() / 1000)
            self._schedule_save()

    def _add_segment(self) -> None:
        at = min(self.duration - 0.1, self.player.position() / 1000)
        seg = Segment(index=len(self.segments), start=max(0, at),
                      end=min(self.duration, max(0, at) + 2), speaker=-1,
                      text_vi="Phụ đề mới")
        self.segments.append(seg)
        self.sub_list.addItem(self._segment_label(len(self.segments) - 1))
        self.subtitle_count_label.setText(f"{len(self.segments)} câu")
        self._select_segment(len(self.segments) - 1)
        self.timeline.update()
        self._schedule_save()

    def _remove_segment(self) -> None:
        i = self.timeline.selected
        if i < 0:
            return
        self.segments.pop(i)
        self.sub_list.takeItem(i)
        self.subtitle_count_label.setText(f"{len(self.segments)} câu")
        for n, seg in enumerate(self.segments):
            seg.index = n
        self.timeline.selected = -1
        if self.segments:
            self._select_segment(min(i, len(self.segments) - 1))
        else:
            self.sub_text.clear()
        self.timeline.update()
        self._update_subtitle(self.player.position() / 1000)
        self._schedule_save()

    def _trim_changed(self, start: float, end: float) -> None:
        self.timeline.trim_start, self.timeline.trim_end = start, end
        self.trim_label.setText(f"{fmt_time(start)} → {fmt_time(end)}")
        for spin, value in ((self.trim_start_spin, start), (self.trim_end_spin, end)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.timeline.update()
        self._schedule_save()

    def _numeric_trim_changed(self) -> None:
        start, end = self.trim_start_spin.value(), self.trim_end_spin.value()
        if end - start < 0.1 - 1e-8:
            self.status.setText("Điểm cắt cuối phải sau điểm cắt đầu ít nhất 0,1 giây.")
            self._trim_changed(self.timeline.trim_start, self.timeline.trim_end)
            return
        self._trim_changed(start, end)

    def _choose_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn logo", "", "Ảnh (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            if QPixmap(path).isNull():
                error_box(self, "Logo không hợp lệ", "Không đọc được ảnh logo.")
                return
            self.logo_path = path
            self.logo_edit.setText(path)
            self._update_logo()
            if self.width() < 760 and self._tools_open:
                self._tools_open = False
                self._apply_responsive_layout()

    def _choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu video đã biên tập", str(self.output_path), "Video MP4 (*.mp4)")
        if path:
            self.output_path = Path(path).with_suffix(".mp4")
            self.status.setText("Đã chọn nơi lưu video. Di chuột vào đây để xem đường dẫn.")
            self.status.setToolTip(str(self.output_path))
            self._schedule_save()

    def _clear_logo(self) -> None:
        self.logo_path = ""
        self.logo_edit.clear()
        self._update_logo()

    def _video_size_changed(self, size: QSizeF) -> None:
        if size.width() <= 0 or size.height() <= 0:
            return
        self.video_item.setSize(size)
        self.scene.setSceneRect(QRectF(0, 0, size.width(), size.height()))
        self._fit_poster()
        self.canvas.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._update_logo()
        self._update_subtitle(self.player.position() / 1000)

    def _fit_poster(self) -> None:
        if self.poster_pix.isNull():
            return
        rect = self.scene.sceneRect()
        pix = self.poster_pix.scaled(rect.size().toSize(),
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.poster_item.setPixmap(pix)
        self.poster_item.setPos((rect.width() - pix.width()) / 2,
                                (rect.height() - pix.height()) / 2)

    def _poster_ready(self, source: str, path: str) -> None:
        if source != self.source or not path or self._has_shown_video_frame:
            return
        self.poster_pix = QPixmap(path)
        if not self.poster_pix.isNull():
            self._fit_poster()
            self.poster_item.show()
            self.video_item.hide()

    def _show_video_frame(self) -> None:
        self._has_shown_video_frame = True
        self.poster_item.hide()
        self.video_item.show()

    def _update_logo(self, *_args) -> None:
        self.logo_size_value.setText(f"{self.logo_size.value()}%")
        self.logo_opacity_value.setText(f"{self.logo_opacity.value()}%")
        pix = QPixmap(self.logo_path) if self.logo_path else QPixmap()
        if pix.isNull():
            self.logo_item.hide()
        else:
            rect = self.scene.sceneRect()
            width = max(8, round(rect.width() * self.logo_size.value() / 100))
            pix = pix.scaledToWidth(width, Qt.SmoothTransformation)
            self.logo_item.setPixmap(pix)
            self.logo_item.setOpacity(self.logo_opacity.value() / 100)
            corner = self.corner.currentData()
            margin = max(8, round(min(rect.width(), rect.height()) * .025))
            x = margin if corner.endswith("left") else rect.width() - pix.width() - margin
            y = margin if corner.startswith("top") else rect.height() - pix.height() - margin
            self.logo_item.setPos(x, y)
            self.logo_item.show()
        self._schedule_save()

    def _update_subtitle(self, sec: float) -> None:
        text = next((s.text_vi for s in self.segments
                     if s.start <= sec < s.end and s.text_vi.strip()), "")
        rect = self.scene.sceneRect()
        self.sub_item.setFont(QFont("", max(14, round(rect.width() * .027))))
        self.sub_item.setTextWidth(rect.width() * .9)
        option = QTextOption(Qt.AlignHCenter)
        self.sub_item.document().setDefaultTextOption(option)
        self.sub_item.setPlainText(text)
        width, height = self.sub_item.boundingRect().width(), self.sub_item.boundingRect().height()
        x, y = rect.width() * .05, rect.height() - height - rect.height() * .05
        self.sub_item.setPos(x, y)
        self.sub_back.setRect(QRectF(x, y, width, height))
        self.sub_back.setVisible(bool(text))

    def _media_failed(self, name: str, message: str) -> None:
        if self._resetting_media:
            return
        self._media_errors[name] = message or "Không đọc được tệp xem trước."
        self.player.pause()
        self.dub_player.pause()
        self._update_media_status()

    def _update_media_status(self) -> None:
        if self._resetting_media:
            return
        players = (("Hình ảnh", self.player), ("Lồng tiếng", self.dub_player))
        for name, player in players:
            if player.mediaStatus() == QMediaPlayer.InvalidMedia:
                self._media_errors.setdefault(name, player.errorString() or "Tệp không hợp lệ.")
        stalled = any(player.mediaStatus() == QMediaPlayer.StalledMedia for _, player in players)
        self.btn_retry_media.setVisible(bool(self._media_errors) or stalled)
        if self.width() < 900 and self._tools_open:
            self.btn_tools.setText("Xem trước · lỗi" if self._media_errors else "Xem trước")
        self.media_status.setStyleSheet(
            f"color: {UI_COLORS['danger' if self._media_errors else 'secondary_text']};")
        if self._media_errors:
            failed = ", ".join(name.lower() for name in self._media_errors)
            self.media_status.setText(f"Không tải được {failed}. Thử tải lại; vẫn có thể biên tập.")
            self.media_status.setToolTip("\n".join(
                f"{name}: {message}" for name, message in self._media_errors.items()))
            self.btn_play.setEnabled(False)
            return
        loading = any(player.mediaStatus() in (
            QMediaPlayer.NoMedia, QMediaPlayer.LoadingMedia) for _, player in players)
        self.btn_play.setEnabled(not loading)
        if stalled:
            self.media_status.setText("Tải xem trước bị gián đoạn. Bấm Thử tải lại.")
        elif loading:
            self.media_status.setText("Đang tải hình ảnh và lồng tiếng…")
        elif self.player.mediaStatus() == QMediaPlayer.EndOfMedia:
            self.media_status.setText("Đã phát hết video. Bấm Phát để xem lại khoảng cắt.")
        elif self.player.playbackState() == QMediaPlayer.PlayingState:
            self.media_status.setText(
                "Đang phát hình ảnh; phiên này không phát âm thanh."
                if QGuiApplication.platformName() == "offscreen"
                else "Đang phát hình ảnh và lồng tiếng.")
        elif self.player.playbackState() == QMediaPlayer.PausedState:
            self.media_status.setText("Đã tạm dừng xem trước.")
        else:
            self.media_status.setText("Đã tải hình ảnh và lồng tiếng. Sẵn sàng xem trước.")
        self.media_status.setToolTip(self.media_status.text())
        if not loading and getattr(self, "_retry_position", None) is not None:
            position, self._retry_position = self._retry_position, None
            self._seek(position)

    def _retry_media(self) -> None:
        self._resetting_media = True
        self._retry_position = round(self.timeline.position * 1000)
        self.player.stop()
        self.dub_player.stop()
        self.player.setSource(QUrl())
        self.dub_player.setSource(QUrl())
        self._media_errors.clear()
        self._resetting_media = False
        self.player.setSource(QUrl.fromLocalFile(self.source))
        self.dub_player.setSource(QUrl.fromLocalFile(self.mixed_wav))
        self._update_media_status()
        self.poster_loader.request(self.source, str(self.job.stages_dir))

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.dub_player.pause()
        else:
            if self._media_errors:
                self._retry_media()
                return
            if self.player.position() / 1000 >= self.timeline.trim_end:
                self._seek(round(self.timeline.trim_start * 1000))
            # Qt's PipeWire backend can crash when an offscreen session has
            # no audio server. Visual preview still works without audio.
            audio_available = QGuiApplication.platformName() != "offscreen"
            if audio_available and self.dub_audio is None:
                self.dub_audio = QAudioOutput(self)
                self.dub_player.setAudioOutput(self.dub_audio)
            self.dub_player.setPosition(self.player.position())
            self._show_video_frame()
            self.player.play()
            if audio_available:
                self.dub_player.play()

    def _on_playback(self, state) -> None:
        self.btn_play.setText("Ⅱ  Tạm dừng" if state == QMediaPlayer.PlayingState
                              else "▶  Phát")
        if state != QMediaPlayer.PlayingState:
            self.dub_player.pause()
        self._update_media_status()

    def _seek(self, ms: int) -> None:
        ms = max(0, min(round(self.duration * 1000), ms))
        self._show_video_frame()
        self.player.setPosition(ms)
        self.dub_player.setPosition(ms)
        self._on_position(ms)

    def _on_position(self, ms: int) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState and \
                ms / 1000 >= self.timeline.trim_end:
            self.player.pause()
            self.dub_player.pause()
        elif self.player.playbackState() == QMediaPlayer.PlayingState and \
                abs(self.dub_player.position() - ms) > 500:
            self.dub_player.setPosition(ms)
        self.seek.blockSignals(True)
        self.seek.setValue(ms)
        self.seek.blockSignals(False)
        if self.timeline.hasFocus():
            self.workspace_scroll.ensureWidgetVisible(self.timeline_scroll)
            self.timeline_scroll.ensureVisible(int(self.timeline._x(ms / 1000)), 80, 40, 0)
        self.time_label.setText(f"{fmt_time(ms / 1000)} / {fmt_time(self.duration)}")
        self.timeline.position = ms / 1000
        self.timeline.update()
        self._update_subtitle(ms / 1000)

    def _load_draft(self) -> dict:
        try:
            data = json.loads(self.draft_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Bản nháp phải chứa dữ liệu biên tập hợp lệ.")
            if data.get("source") != self.source:
                return {}
            saved = data.get("segments")
            if isinstance(saved, list):
                self.segments = [Segment.from_dict(s) for s in saved]
            logo = str(data.get("logo_path", ""))
            self.logo_path = logo if Path(logo).is_file() else ""
            output = data.get("output_path")
            if output:
                self.output_path = Path(output)
            return data
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self._draft_error = str(exc)
            return {}

    def _set_draft_state(self, text: str, detail: str = "", *, error: bool = False) -> None:
        self.draft_badge.setText(text)
        self.draft_badge.setAccessibleName(text)
        self.draft_badge.setToolTip(detail or text)
        self.draft_badge.setAccessibleDescription(detail or text)
        self.draft_badge.setStyleSheet(
            f"color: {UI_COLORS['danger' if error else 'primary']};")
        self.btn_save.setText("Thử lưu lại" if error else "Lưu nháp")

    def _schedule_save(self) -> None:
        if not self._ready:
            return
        self._set_draft_state("Có thay đổi chưa lưu")
        self._save_timer.start()

    def _save_draft(self) -> bool:
        if not self._ready:
            return False
        self._save_timer.stop()
        self._set_draft_state("Đang lưu bản nháp…")
        data = {"source": self.source, "output_path": str(self.output_path),
                "segments": [s.to_dict() for s in self.segments],
                "trim_start": self.timeline.trim_start,
                "trim_end": self.timeline.trim_end,
                "logo_path": self.logo_path,
                "logo_corner": self.corner.currentData(),
                "logo_width_pct": self.logo_size.value(),
                "logo_opacity_pct": self.logo_opacity.value()}
        temp = self.draft_path.with_suffix(".json.tmp")
        try:
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")
            temp.replace(self.draft_path)
        except OSError as exc:
            self._set_draft_state("Lưu bản nháp thất bại", str(exc), error=True)
            self.status.setText("Không lưu được bản nháp. Bấm Thử lưu lại; giữ cửa sổ mở để bảo toàn thay đổi.")
            self.status.setToolTip(str(exc))
            return False
        self._set_draft_state("Đã lưu bản nháp", str(self.draft_path))
        if self.status.text().startswith("Không lưu được bản nháp"):
            self.status.setText("Đã lưu bản nháp. Có thể tiếp tục biên tập hoặc xuất video.")
            self.status.setToolTip("")
        return True

    def export(self) -> None:
        if self._thread is not None:
            return
        self._save_draft()
        if self.timeline.trim_end - self.timeline.trim_start < 0.1:
            error_box(self, "Khoảng cắt quá ngắn", "Cần giữ ít nhất 0,1 giây video.")
            return
        target = self.output_path
        version = 2
        while target.exists():
            target = self.output_path.with_name(
                f"{self.output_path.stem}_{version}.mp4")
            version += 1
        self.btn_export.setEnabled(False)
        self.export_progress.show()
        self.status.setText("Đang xuất video… Chờ hoàn tất trước khi đóng cửa sổ.")
        self.status.setToolTip(f"Đang xuất: {target}")
        self.player.pause()
        self.dub_player.pause()
        kwargs = dict(trim_start=self.timeline.trim_start,
                      trim_end=self.timeline.trim_end,
                      logo_path=self.logo_path,
                      logo_corner=self.corner.currentData(),
                      logo_width_pct=self.logo_size.value(),
                      logo_opacity_pct=self.logo_opacity.value(),
                      sub_mode=self.settings.get("sub_mode", "burn"),
                      crf=int(self.settings.get("crf", 20)),
                      font=self.settings.get("sub_font", ""),
                      font_size=int(self.settings.get("sub_font_size", 0) or 0),
                      font_color=self.settings.get("sub_font_color", ""))
        # Snapshot mutable subtitles before starting the worker thread.
        args = (self.source, self.mixed_wav,
                [Segment.from_dict(s.to_dict()) for s in self.segments],
                target)
        self._worker = ExportWorker(args, kwargs)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._export_done)
        self._worker.failed.connect(self._export_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._export_thread_finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _export_done(self, path: str) -> None:
        self._pending_result = path

    def _export_failed(self, message: str) -> None:
        self._pending_error = message

    def _export_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.btn_export.setEnabled(True)
        self.export_progress.hide()
        if self._pending_result:
            path = self._pending_result
            self._pending_result = None
            srt = str(Path(path).with_suffix(".srt"))
            try:
                cp.save_step(self.job.job_dir, "render", {"video_out": path,
                                                          "srt": srt})
                self.job.project.video_out = path
                pio.save_project(self.job.job_dir, self.job.project)
                self.on_export(path, srt)
                self.status.setText("Đã xuất video. Di chuột vào đây để xem đường dẫn.")
                self.status.setToolTip(path)
                info_box(self, "Xuất xong", f"Video đã lưu tại:\n{path}")
            except Exception as exc:  # noqa: BLE001 - video still exists
                self.status.setText("Đã xuất video, nhưng không cập nhật được dự án. Xem chi tiết lỗi để khôi phục.")
                self.status.setToolTip(str(exc))
                error_box(self, "Không cập nhật được dự án",
                          f"Video đã lưu tại:\n{path}\n\n{exc}")
        elif self._pending_error:
            error = self._pending_error
            self._pending_error = None
            self.status.setText("Xuất video thất bại. Bạn có thể sửa rồi thử lại.")
            error_box(self, "Xuất video thất bại", error)

    def _toggle_tools(self) -> None:
        self._tools_open = not self._tools_open
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        compact = self.width() < 900
        short = self.height() < 700
        self.layout().setContentsMargins(8 if compact else 16, 8 if short else 16,
                                        8 if compact else 16, 8)
        self.layout().setSpacing(8 if short else 12)
        self.brand_mark.setVisible(not compact)
        self.project_label.setVisible(not compact)
        self.draft_badge.show()
        self.btn_tools.setVisible(compact)
        self.btn_tools.setText(("Xem trước · lỗi" if self._media_errors else "Xem trước")
                               if self._tools_open else "Công cụ")
        self.btn_tools.setAccessibleName("Hiện xem trước" if self._tools_open else "Hiện công cụ phụ đề và logo")
        self.btn_output.setText("Lưu…" if compact else "Nơi lưu…")
        self.preview_panel.setVisible(not compact or not self._tools_open)
        self.inspector_panel.setVisible(not compact or self._tools_open)
        self.footer_hint.setVisible(self.width() >= 1040)
        # Keep both splitter sections usable; the workspace scrolls when the
        # window is too short instead of squeezing transport or editing tools.
        self.workspace_split.setMinimumHeight(560 if short else 600)
        if not self._zoom_user_adjusted and self.timeline_scroll.viewport().width() > 200:
            fit_zoom = int(self.timeline_scroll.viewport().width() * .72 /
                           self.duration)
            self.zoom_slider.setValue(max(16, min(160, fit_zoom)))
        self.timeline.set_zoom(self.timeline.px_per_sec)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "timeline_scroll"):
            QTimer.singleShot(0, self._apply_responsive_layout)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._thread is not None:
            info_box(self, "Đang xuất video", "Chờ xuất xong rồi đóng cửa sổ.")
            event.ignore()
            return
        self._save_timer.stop()
        if not self._save_draft():
            event.ignore()
            return
        self.poster_loader.stop()
        self.player.stop()
        self.dub_player.stop()
        super().closeEvent(event)
