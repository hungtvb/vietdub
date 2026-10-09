# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Màn 4 - Duyệt bản dịch (điểm dừng sau bước dịch).

Bảng: # | thời gian | loa | bản dịch (sửa trực tiếp, Enter xuống dòng).
[Lồng tiếng →]: lưu bản dịch đã sửa vào checkpoint rồi chạy tiếp bước TTS.
[Dịch lại]: lưu metadata đã sửa tay rồi dịch lại toàn bộ với metadata mới.
"""
from __future__ import annotations

from typing import Callable, Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from core.job import Job
from core.settings import Settings
from project import io as pio
from project.schema import Segment
from ui.common import fmt_time, info_box

META_FIELDS = [("genre", "Thể loại"),
               ("style", "Phong cách"),
               ("setting", "Bối cảnh"),
               ("tone_notes", "Ghi chú giọng điệu")]


class ReviewViWindow(QWidget):
    def __init__(self, job: Job, settings: Settings,
                 on_continue: Callable[[], None],
                 on_back: Callable[[], None],
                 on_retranslate: Callable[[Dict[str, str]], None] | None = None):
        super().__init__()
        self.on_retranslate = on_retranslate
        self.job = job
        self.settings = settings
        self.on_continue = on_continue
        self.on_back = on_back
        self.setWindowTitle(f"VietDub — Duyệt bản dịch: {job.project.name}")
        self.resize(860, 560)
        # True khi window bị đóng bởi chính nút [Quay lại]/[Lồng tiếng] ->
        # closeEvent không schedule on_back lần nữa.
        self._close_via_button = False

        self.segments: List[Segment] = \
            pio.load_segments(job.job_dir, "translate") or []

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Duyệt bản dịch tiếng Việt — sửa trực tiếp trong bảng, "
            "Enter để xuống dòng tiếp theo."))
        n_review = sum(1 for s in self.segments if s.needs_review)
        root.addWidget(QLabel(
            f"Tổng {len(self.segments)} câu. Đại từ xưng hô đã khóa theo "
            "bảng quan hệ ở bước phân tích — sửa tay nếu thấy chưa hợp."
            + (f" {n_review} câu tô vàng mất đại từ so với bảng, cần kiểm tra kỹ."
               if n_review else "")))

        # Metadata tổng thể (bước [4b]) — xem/sửa; sai thì sửa rồi bấm Dịch lại
        self.meta = pio.load_video_metadata(job.job_dir) or {}
        meta_form = QFormLayout()
        self.meta_edits: Dict[str, QLineEdit] = {}
        for key, label in META_FIELDS:
            ed = QLineEdit(str(self.meta.get(key, "")))
            ed.setPlaceholderText(label)
            self.meta_edits[key] = ed
            meta_form.addRow(f"{label}:", ed)
        root.addLayout(meta_form)

        self.tbl = QTableWidget(len(self.segments), len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)        self.tbl.verticalHeader().setVisible(False)
        for r, seg in enumerate(self.segments):
            self._fill_row(r, seg)
        self.tbl.setColumnWidth(0, 44)
        self.tbl.setColumnWidth(1, 150)
        self.tbl.setColumnWidth(2, 80)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setSelectionMode(QTableWidget.SingleSelection)
        root.addWidget(self.tbl, 1)

        row = QHBoxLayout()
        btn_settings = QPushButton("Cài đặt")
        btn_settings.clicked.connect(self.open_settings)
        btn_retranslate = QPushButton("Dịch lại với metadata này")
        btn_retranslate.setToolTip(
            "Lưu 4 ô metadata ở trên rồi dịch lại toàn bộ với metadata mới.")
        btn_retranslate.clicked.connect(self._retranslate_clicked)
        btn_back = QPushButton("Quay lại")
        btn_back.clicked.connect(self._back_clicked)
        btn_next = QPushButton("Lồng tiếng →")
        btn_next.setStyleSheet("font-weight: bold;")
        btn_next.clicked.connect(self.save_and_continue)
        row.addWidget(btn_settings)
        row.addWidget(btn_retranslate)
        row.addStretch(1)
        row.addWidget(btn_back)
        row.addWidget(btn_next)
        root.addLayout(row)

    def open_settings(self) -> None:
        from ui.common import open_settings_dialog
        open_settings_dialog(self, self.settings)

    def closeEvent(self, e) -> None:  # noqa: N802
        # Bấm X = [Quay lại]: về màn tiến trình, không quit app, không mất
        # checkpoint. Trì hoãn qua singleShot để tránh gọi close() đệ quy
        # (on_back tự đóng window này).
        # Nếu đóng là do bấm nút [Quay lại]/[Lồng tiếng] thì on_back/on_continue
        # đã chạy rồi -> không schedule thêm lần nữa.
        via_button, self._close_via_button = self._close_via_button, False
        super().closeEvent(e)
        if not via_button:
            QTimer.singleShot(0, self.on_back)

    def _back_clicked(self) -> None:
        self._close_via_button = True
        self.on_back()

    def _fill_row(self, r: int, seg: Segment) -> None:
        def ro(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            return it

        self.tbl.setItem(r, 0, ro(str(seg.index)))
        self.tbl.setItem(r, 1, ro(
            f"{fmt_time(seg.start)} → {fmt_time(seg.end)}"))
        self.tbl.setItem(r, 2, ro(
            f"Loa {seg.speaker} ({GENDER_LABEL.get(seg.gender, '?')})"))
        self.tbl.setItem(r, 3, QTableWidgetItem(seg.text_vi or ""))
        if seg.needs_review:
            for c in range(len(COLS)):
                self.tbl.item(r, c).setBackground(QColor("#fff3b0"))

    def _retranslate_clicked(self) -> None:
        meta = {k: ed.text().strip() for k, ed in self.meta_edits.items()}
        pio.save_video_metadata(self.job.job_dir, meta)
        self._close_via_button = True  # on_retranslate tự xử lý window này
        if self.on_retranslate is not None:
            self.on_retranslate(meta)

    def save_and_continue(self) -> None:
        for r in range(self.tbl.rowCount()):
            self.segments[r].text_vi = self.tbl.item(r, 3).text()
        pio.save_segments(self.job.job_dir, "translate", self.segments)
        info_box(self, "Đã lưu",
                 f"Đã lưu {len(self.segments)} câu dịch. "
                 "Chạy tiếp bước lồng tiếng (TTS).")
        self._close_via_button = True  # on_continue tự đóng window này
        self.on_continue()
