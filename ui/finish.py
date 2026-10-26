# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Màn 5 - Hoàn thành: xem thử video đã lồng tiếng + phụ đề.

- QMediaPlayer + QVideoWidget phát thử video kết quả.
- [Mở thư mục]: mở thư mục chứa video bằng trình quản lý file của hệ thống.
- [Làm video khác]: quay về màn hình chính.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget)

from core import checkpoint as cp
from core.job import Job
from core.settings import Settings
from ui.common import error_box, fmt_time, info_box
from ui.poster_loader import PosterLoader
from ui.theme import APP_BACKGROUND


class PosterLabel(QLabel):
    def __init__(self):
        super().__init__("Đang chuẩn bị hình xem trước…")
        self.setObjectName("finishPoster")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._original = QPixmap()
        self._placeholder = "Đang chuẩn bị hình xem trước…"

    def set_poster(self, path: Path) -> None:
        self._original = QPixmap(str(path))
        self._fit()

    def clear_poster(self) -> None:
        self._original = QPixmap()
        self._placeholder = "Đang chuẩn bị hình xem trước…"
        self.clear()
        self.setText(self._placeholder)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._original.isNull():
            self.setText(self._placeholder)
        else:
            self.setPixmap(self._original.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class FinishWindow(QWidget):
    def __init__(self, job: Job, settings: Settings,
                 on_new: Callable[[], None]):
        super().__init__()
        self.job = job
        self.settings = settings
        self.on_new = on_new
        self.setWindowTitle(f"VietDub — Hoàn thành: {job.project.name}")
        self.resize(1080, 800)
        self.setMinimumSize(650, 500)
        self.setObjectName("finishRoot")
        self.setStyleSheet(f"QWidget#finishRoot, QWidget#finishContent {{ background: {APP_BACKGROUND}; }}")

        data = cp.load_step(job.job_dir, "render") or {}
        self.video_out = data.get("video_out", "") or ""
        self.srt_path = data.get("srt", "") or ""

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(13)
        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        badge = QLabel("●  XUẤT HOÀN TẤT")
        badge.setObjectName("finishBadge")
        title_stack.addWidget(badge)
        title = QLabel("Video đã sẵn sàng")
        title.setObjectName("pageTitle")
        title.setWordWrap(True)
        title_stack.addWidget(title)
        header.addLayout(title_stack)
        header.addStretch(1)
        new = QPushButton("Video mới")
        new.setProperty("role", "secondary")
        new.clicked.connect(self.on_new)
        header.addWidget(new)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("finishContent")
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        preview_card = QFrame()
        preview_card.setObjectName("finishCard")
        preview_lay = QVBoxLayout(preview_card)
        preview_lay.setContentsMargins(13, 11, 13, 12)
        preview_lay.setSpacing(9)
        preview_title = QLabel("XEM TRƯỚC THÀNH PHẨM")
        preview_title.setObjectName("finishSection")
        preview_lay.addWidget(preview_title)
        self.preview_stack = QStackedWidget()
        self.preview_stack.setMinimumHeight(150)
        self.poster = PosterLabel()
        self.video = QVideoWidget()
        self.video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview_stack.addWidget(self.poster)
        self.preview_stack.addWidget(self.video)
        preview_lay.addWidget(self.preview_stack, 1)

        self._player: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None
        self._poster_loader = PosterLoader(self)
        self._poster_loader.ready.connect(self._poster_ready)
        if not self.video_out or not Path(self.video_out).is_file():
            error_box(self, "Không thấy video kết quả",
                      f"Không tìm thấy file video:\n{self.video_out}")
        else:
            self._load_poster()

        ctl = QHBoxLayout()
        self.btn_play = QPushButton("▶  Phát")
        self.btn_play.clicked.connect(self.toggle_play)
        ctl.addWidget(self.btn_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setAccessibleName("Vị trí phát video")
        self.slider.sliderMoved.connect(self._seek)
        ctl.addWidget(self.slider, 1)
        self.lbl_time = QLabel("00:00 / 00:00")
        ctl.addWidget(self.lbl_time)
        preview_lay.addLayout(ctl)
        content_lay.addWidget(preview_card, 1)

        files = QFrame()
        files.setObjectName("finishCard")
        files_lay = QVBoxLayout(files)
        files_lay.setContentsMargins(13, 11, 13, 12)
        files_title = QLabel("TỆP ĐẦU RA")
        files_title.setObjectName("finishSection")
        files_lay.addWidget(files_title)
        files_lay.addWidget(QLabel("VIDEO MP4"))
        self.video_path_label = QLineEdit(self.video_out or "—")
        self.video_path_label.setReadOnly(True)
        self.video_path_label.setAccessibleName("Đường dẫn video đầu ra")
        files_lay.addWidget(self.video_path_label)
        files_lay.addWidget(QLabel("PHỤ ĐỀ SRT"))
        self.sub_path_label = QLineEdit(self.srt_path or "—")
        self.sub_path_label.setReadOnly(True)
        self.sub_path_label.setAccessibleName("Đường dẫn phụ đề đầu ra")
        files_lay.addWidget(self.sub_path_label)
        self._refresh_output_paths()
        content_lay.addWidget(files)

        row = QHBoxLayout()
        btn_open = QPushButton("Mở thư mục")
        btn_open.setProperty("role", "secondary")
        btn_open.clicked.connect(self.open_folder)
        btn_edit = QPushButton("Biên tập video")
        btn_edit.setProperty("role", "primary")
        btn_edit.clicked.connect(self.open_editor)
        btn_settings = QPushButton("Cài đặt")
        btn_settings.clicked.connect(self.open_settings)
        row.addWidget(btn_open)
        row.addWidget(btn_settings)
        row.addStretch(1)
        row.addWidget(btn_edit)
        root.addLayout(row)

    def _refresh_output_paths(self) -> None:
        for field, path in ((self.video_path_label, self.video_out),
                            (self.sub_path_label, self.srt_path)):
            field.setMinimumWidth(0)
            field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            field.setText(path or "Không có tệp")
            field.setToolTip(path or "Không có tệp")
            # Keep the filename visible; the full path can be selected/copied.
            field.setCursorPosition(len(field.text()))

    # -------------------------------------------------------------- phát thử
    def toggle_play(self) -> None:
        player = self._ensure_player()
        if player.playbackState() == QMediaPlayer.PlayingState:
            player.pause()
        else:
            self.preview_stack.setCurrentWidget(self.video)
            player.play()

    def _load_poster(self) -> None:
        self._poster_loader.request(self.video_out, str(self.job.stages_dir))

    def _poster_ready(self, source: str, path: str) -> None:
        if source != self.video_out:
            return
        if path:
            self.poster.set_poster(Path(path))
        else:
            self.poster._placeholder = "Phát để xem video"
            self.poster.setText(self.poster._placeholder)

    def _ensure_player(self) -> QMediaPlayer:
        if self._player is None:
            self._player = QMediaPlayer(self)
            if QGuiApplication.platformName() != "offscreen":
                self._audio_out = QAudioOutput(self)
                self._player.setAudioOutput(self._audio_out)
            self._player.setVideoOutput(self.video)
            self._player.setSource(QUrl.fromLocalFile(self.video_out))
            self._player.positionChanged.connect(self._on_position)
            self._player.durationChanged.connect(self._on_duration)
            self._player.playbackStateChanged.connect(self._on_state)
        return self._player

    def _on_state(self, state) -> None:
        self.btn_play.setText(
            "Ⅱ  Tạm dừng" if state == QMediaPlayer.PlayingState else "▶  Phát")

    def _on_position(self, pos: int) -> None:
        self.slider.setValue(pos)
        self.lbl_time.setText(
            f"{fmt_time(pos / 1000)} / "
            f"{fmt_time(self._player.duration() / 1000)}")

    def _on_duration(self, dur: int) -> None:
        self.slider.setRange(0, dur)

    def _seek(self, pos: int) -> None:
        if self._player is not None:
            self._player.setPosition(pos)

    # ------------------------------------------------------------------ nút
    def open_folder(self) -> None:
        folder = str(Path(self.video_out).parent) if self.video_out else ""
        if not folder or not Path(folder).is_dir():
            error_box(self, "Không mở được thư mục",
                      f"Thư mục không tồn tại:\n{folder}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            info_box(self, "Thư mục", f"Video nằm ở:\n{folder}")

    def open_settings(self) -> None:
        from ui.common import open_settings_dialog
        open_settings_dialog(self, self.settings)

    def open_editor(self) -> None:
        if getattr(self, "_editor", None) is not None and self._editor.isVisible():
            self._editor.raise_()
            self._editor.activateWindow()
            return
        from ui.editor import EditorWindow
        try:
            self._editor = EditorWindow(self.job, self.settings, self._on_edited)
        except Exception as exc:  # noqa: BLE001 - missing original assets
            error_box(self, "Không mở được trình biên tập", str(exc))
            return
        self._editor.show()

    def _on_edited(self, video: str, srt: str) -> None:
        self.video_out, self.srt_path = video, srt
        self._refresh_output_paths()
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(video))
        self.preview_stack.setCurrentWidget(self.poster)
        self.poster.clear_poster()
        self._load_poster()

    def closeEvent(self, event) -> None:  # noqa: N802
        editor = getattr(self, "_editor", None)
        if editor is not None and editor.isVisible():
            editor.close()
            if editor.isVisible():  # background export is still active
                event.ignore()
                return
        self._poster_loader.stop()
        super().closeEvent(event)
