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
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from core import checkpoint as cp
from core.job import Job
from core.settings import Settings
from ui.common import error_box, fmt_time, info_box


class FinishWindow(QWidget):
    def __init__(self, job: Job, settings: Settings,
                 on_new: Callable[[], None]):
        super().__init__()
        self.job = job
        self.settings = settings
        self.on_new = on_new
        self.setWindowTitle(f"VietDub — Hoàn thành: {job.project.name}")
        self.resize(1080, 800)
        self.setMinimumSize(860, 680)

        data = cp.load_step(job.job_dir, "render") or {}
        self.video_out = data.get("video_out", "") or ""
        self.srt_path = data.get("srt", "") or ""

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        title = QLabel("Video đã lồng tiếng")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        note = QLabel("Xem thử thành phẩm hoặc mở thư mục lưu file.")
        note.setProperty("role", "secondary")
        root.addWidget(note)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(400)
        root.addWidget(self.video, 1)

        self._player: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None
        if not self.video_out or not Path(self.video_out).is_file():
            error_box(self, "Không thấy video kết quả",
                      f"Không tìm thấy file video:\n{self.video_out}")

        ctl = QHBoxLayout()
        self.btn_play = QPushButton("Phát")
        self.btn_play.clicked.connect(self.toggle_play)
        ctl.addWidget(self.btn_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._seek)
        ctl.addWidget(self.slider, 1)
        self.lbl_time = QLabel("00:00 / 00:00")
        ctl.addWidget(self.lbl_time)
        root.addLayout(ctl)

        files = QGroupBox("Tệp đầu ra")
        files_lay = QVBoxLayout(files)
        files_lay.setContentsMargins(14, 18, 14, 12)
        video_path = QLabel(f"Video  ·  {self.video_out or '—'}")
        video_path.setWordWrap(True)
        video_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        video_path.setProperty("role", "secondary")
        sub_path = QLabel(f"Phụ đề  ·  {self.srt_path or '—'}")
        sub_path.setWordWrap(True)
        sub_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sub_path.setProperty("role", "secondary")
        files_lay.addWidget(video_path)
        files_lay.addWidget(sub_path)
        root.addWidget(files)

        row = QHBoxLayout()
        btn_open = QPushButton("Mở thư mục")
        btn_open.setProperty("role", "secondary")
        btn_open.clicked.connect(self.open_folder)
        btn_new = QPushButton("Làm video khác")
        btn_new.setProperty("role", "primary")
        btn_new.clicked.connect(self.on_new)
        btn_settings = QPushButton("Cài đặt")
        btn_settings.clicked.connect(self.open_settings)
        row.addWidget(btn_open)
        row.addStretch(1)
        row.addWidget(btn_settings)
        row.addWidget(btn_new)
        root.addLayout(row)

    # -------------------------------------------------------------- phát thử
    def toggle_play(self) -> None:
        player = self._ensure_player()
        if player.playbackState() == QMediaPlayer.PlayingState:
            player.pause()
        else:
            player.play()

    def _ensure_player(self) -> QMediaPlayer:
        if self._player is None:
            self._player = QMediaPlayer(self)
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
            "Tạm dừng" if state == QMediaPlayer.PlayingState else "Phát")

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
