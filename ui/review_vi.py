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
from PySide6.QtWidgets import (QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core.job import Job
from core.settings import Settings
from project import io as pio
from project.schema import Segment
from ui.common import error_box, fmt_time, info_box
from ui.review_source import TranscriptTable

META_FIELDS = [("genre", "Thể loại"),
               ("style", "Phong cách"),
               ("setting", "Bối cảnh"),
               ("tone_notes", "Ghi chú giọng điệu")]
COLS = ["#", "Thời gian", "Loa", "Bản dịch"]
GENDER_LABEL = {"female": "Nữ", "male": "Nam"}


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
        self.resize(1180, 760)
        self.setMinimumSize(700, 520)
        # True khi window bị đóng bởi chính nút [Quay lại]/[Lồng tiếng] ->
        # closeEvent không schedule on_back lần nữa.
        self._close_via_button = False

        self.segments: List[Segment] = \
            pio.load_segments(job.job_dir, "translate") or []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        header = QFrame()
        header.setObjectName("workflowHeader")
        header_lay = QVBoxLayout(header)
        header_lay.setContentsMargins(15, 10, 15, 12)
        header_lay.setSpacing(3)
        eyebrow = QLabel("DUYỆT NỘI DUNG  ·  2/2")
        eyebrow.setObjectName("workflowEyebrow")
        header_lay.addWidget(eyebrow)
        title = QLabel("Duyệt bản dịch")
        title.setObjectName("pageTitle")
        header_lay.addWidget(title)
        instruction = QLabel(
            "Sửa nội dung trực tiếp trong bảng. Enter để xuống dòng tiếp theo.")
        instruction.setWordWrap(True)
        instruction.setProperty("role", "secondary")
        header_lay.addWidget(instruction)
        n_review = sum(1 for s in self.segments if s.needs_review)
        note = QLabel(
            f"Tổng {len(self.segments)} câu. Đại từ xưng hô đã khóa theo "
            "bảng quan hệ ở bước phân tích — sửa tay nếu thấy chưa hợp."
            + (f" {n_review} câu tô vàng có dấu hiệu cần kiểm tra kỹ."
               if n_review else ""))
        note.setProperty("role", "secondary")
        note.setWordWrap(True)
        header_lay.addWidget(note)
        root.addWidget(header)

        # Metadata tổng thể (bước [4b]) — xem/sửa; sai thì sửa rồi bấm Dịch lại
        self.meta = pio.load_video_metadata(job.job_dir) or {}
        self._meta_user_toggled = False
        self.btn_meta = QPushButton("Bối cảnh và giọng điệu  ▾")
        self.btn_meta.setProperty("role", "secondary")
        self.btn_meta.clicked.connect(self._toggle_meta)
        root.addWidget(self.btn_meta)
        meta_box = QGroupBox("Bối cảnh và giọng điệu")
        self.meta_box = meta_box
        meta_grid = QGridLayout(meta_box)
        meta_grid.setContentsMargins(14, 18, 14, 12)
        meta_grid.setHorizontalSpacing(12)
        meta_grid.setVerticalSpacing(6)
        self.meta_edits: Dict[str, QLineEdit] = {}
        for col, (key, label) in enumerate(META_FIELDS):
            lbl = QLabel(label)
            lbl.setProperty("role", "secondary")
            ed = QLineEdit(str(self.meta.get(key, "")))
            ed.setPlaceholderText(label)
            self.meta_edits[key] = ed
            group_row, group_col = divmod(col, 2)
            meta_grid.addWidget(lbl, group_row * 2, group_col)
            meta_grid.addWidget(ed, group_row * 2 + 1, group_col)
        self.meta_scroll = QScrollArea()
        self.meta_scroll.setWidgetResizable(True)
        self.meta_scroll.setFrameShape(QFrame.NoFrame)
        self.meta_scroll.setWidget(meta_box)
        self.meta_scroll.setFixedHeight(200)
        root.addWidget(self.meta_scroll)

        self.tbl = TranscriptTable(len(self.segments), len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.verticalHeader().setVisible(False)
        for r, seg in enumerate(self.segments):
            self._fill_row(r, seg)
        self.tbl.setColumnWidth(0, 44)
        self.tbl.setColumnWidth(1, 160)
        self.tbl.setColumnWidth(2, 100)
        self.tbl.setColumnWidth(3, 720)
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl.setAlternatingRowColors(True)
        table_card = QFrame()
        table_card.setObjectName("workflowCard")
        table_lay = QVBoxLayout(table_card)
        table_lay.setContentsMargins(11, 9, 11, 10)
        section = QLabel("CÁC CÂU ĐÃ DỊCH")
        section.setObjectName("workflowSection")
        table_lay.addWidget(section)
        table_lay.addWidget(self.tbl, 1)
        root.addWidget(table_card, 1)

        footer = QFrame()
        footer.setObjectName("workflowFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(11, 7, 11, 7)
        btn_settings = QPushButton("Cài đặt")
        btn_settings.clicked.connect(self.open_settings)
        btn_retranslate = QPushButton("Dịch lại")
        btn_retranslate.setProperty("role", "secondary")
        btn_retranslate.setToolTip(
            "Lưu 4 ô metadata ở trên rồi dịch lại toàn bộ với metadata mới.")
        btn_retranslate.clicked.connect(self._retranslate_clicked)
        btn_back = QPushButton("Quay lại")
        btn_back.setProperty("role", "secondary")
        btn_back.clicked.connect(self._back_clicked)
        btn_next = QPushButton("Lồng tiếng →")
        btn_next.setProperty("role", "primary")
        btn_next.clicked.connect(self.save_and_continue)
        row.addWidget(btn_settings)
        row.addWidget(btn_retranslate)
        row.addStretch(1)
        row.addWidget(btn_back)
        row.addWidget(btn_next)
        root.addWidget(footer)

    def _toggle_meta(self) -> None:
        self._meta_user_toggled = True
        self._set_meta_visible(not self.meta_scroll.isVisible())

    def _set_meta_visible(self, visible: bool) -> None:
        self.meta_scroll.setVisible(visible)
        self.btn_meta.setText("Bối cảnh và giọng điệu  " +
                              ("▴" if visible else "▾"))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "meta_scroll"):
            self.meta_scroll.setFixedHeight(120 if self.height() < 650 else 200)
            if not self._meta_user_toggled:
                self._set_meta_visible(self.width() >= 800)

    def open_settings(self) -> None:
        from ui.common import open_settings_dialog
        open_settings_dialog(self, self.settings)

    def closeEvent(self, e) -> None:  # noqa: N802
        if self._close_via_button:
            super().closeEvent(e)
            return
        if not self._save_review():
            e.ignore()
            return
        self._close_via_button = True
        super().closeEvent(e)
        QTimer.singleShot(0, self.on_back)

    def _back_clicked(self) -> None:
        if not self._save_review():
            return
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
                self.tbl.item(r, c).setBackground(QColor("#fff4ce"))

    def _retranslate_clicked(self) -> None:
        if self.on_retranslate is None or not self._save_review():
            return
        self._close_via_button = True  # on_retranslate tự xử lý window này
        self.on_retranslate(self.meta)

    def _save_review(self) -> bool:
        self.tbl.commit_active_editor()
        for r in range(self.tbl.rowCount()):
            self.segments[r].text_vi = self.tbl.item(r, 3).text()
        # Retain metadata keys that are not exposed by these four editors.
        meta = dict(self.meta)
        meta.update({k: ed.text().strip() for k, ed in self.meta_edits.items()})
        action = "lưu bản dịch (translate)"
        try:
            pio.save_segments(self.job.job_dir, "translate", self.segments)
            action = "lưu bối cảnh và giọng điệu"
            pio.save_video_metadata(self.job.job_dir, meta)
        except Exception as exc:
            error_box(self, "Chưa lưu được nội dung duyệt",
                      f"Không thể {action}:\n{exc}\n\n"
                      "Nội dung sửa vẫn ở đây. Hãy thử lưu lại.")
            return False
        self.meta = meta
        return True

    def save_and_continue(self) -> None:
        if not self._save_review():
            return
        info_box(self, "Đã lưu",
                 f"Đã lưu {len(self.segments)} câu dịch. "
                 "Chạy tiếp bước lồng tiếng (TTS).")
        self._close_via_button = True  # on_continue tự đóng window này
        self.on_continue()
