# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Màn 3 - Duyệt sub gốc (điểm dừng sau bước ASR).

Bảng: # | bắt đầu | kết thúc | loa | giới tính (dropdown) | nói với ai
(dropdown: chưa rõ/khán giả/tất cả/loa N) | nội dung (sửa trực tiếp, Enter
xuống dòng). Câu nào ASR confidence thấp được tô nổi bật.
[Nghe lại câu]: phát đoạn audio GỐC của câu đang chọn.
[Tiếp tục dịch]: lưu mọi sửa đổi vào checkpoint rồi chạy tiếp.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core import checkpoint as cp
from core.job import Job
from core.settings import Settings
from project import io as pio
from project.schema import (Segment, Speaker, audience_label_vi,
                            audience_value_vi)
from ui.common import error_box, fmt_time, info_box

GENDER_LABEL = {"female": "Nữ", "male": "Nam", "": "Không rõ"}
GENDER_VALUE = {"Nữ": "female", "Nam": "male", "Không rõ": ""}

# re-export cho delegate/test (logic nằm ở project/schema.py, không cần Qt)
audience_label = audience_label_vi
audience_value = audience_value_vi

COLS = ["#", "Bắt đầu", "Kết thúc", "Loa", "Giới tính", "Nói với ai",
        "Nội dung"]


class GenderDelegate(QStyledItemDelegate):
    """Dropdown Nữ/Nam/Không rõ trong ô giới tính."""

    def createEditor(self, parent, option, index):  # noqa: N802
        cb = QComboBox(parent)
        cb.addItems(["Nữ", "Nam", "Không rõ"])
        return cb

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setCurrentText(index.data(Qt.DisplayRole) or "Không rõ")

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, editor.currentText(), Qt.EditRole)


class AudienceDelegate(QStyledItemDelegate):
    """Dropdown Chưa rõ/Khán giả/Tất cả/Loa N trong ô 'Nói với ai'.

    Danh sách loa đọc động từ cột Loa hiện tại của bảng (người dùng có thể
    vừa sửa số loa), nên delegate nhận table_fn thay vì list cố định.
    """

    def __init__(self, parent, table_fn):
        super().__init__(parent)
        self._table_fn = table_fn

    def createEditor(self, parent, option, index):  # noqa: N802
        cb = QComboBox(parent)
        tbl = self._table_fn()
        sids = set()
        for r in range(tbl.rowCount()):
            try:
                sids.add(int(tbl.item(r, 3).text().strip()))
            except (ValueError, AttributeError):
                pass
        cb.addItems(["Chưa rõ", "Khán giả", "Tất cả"]
                    + [f"Loa {i}" for i in sorted(sids)])
        return cb

    def setEditorData(self, editor, index):  # noqa: N802
        editor.setCurrentText(index.data(Qt.DisplayRole) or "Chưa rõ")

    def setModelData(self, editor, model, index):  # noqa: N802
        model.setData(index, editor.currentText(), Qt.EditRole)


class ReviewSourceWindow(QWidget):
    def __init__(self, job: Job, settings: Settings,
                 on_continue: Callable[[], None],
                 on_back: Callable[[], None]):
        super().__init__()
        self.job = job
        self.settings = settings
        self.on_continue = on_continue
        self.on_back = on_back
        self.setWindowTitle(f"VietDub — Duyệt sub gốc: {job.project.name}")
        self.resize(860, 560)

        self.segments: List[Segment] = pio.load_segments(job.job_dir, "asr") or []
        self.speakers: Dict[int, Speaker] = \
            pio.load_speakers(job.job_dir, "gender") or {}

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._stop_playback)
        self._playing_row = -1
        self._pending_seek: int | None = None
        self._player.mediaStatusChanged.connect(self._on_media_status)
        # True khi window bị đóng bởi chính nút [Quay lại]/[Tiếp tục] ->
        # closeEvent không schedule on_back lần nữa.
        self._close_via_button = False

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Duyệt phụ đề gốc (tiếng Trung) — sửa trực tiếp trong bảng, "
            "Enter để xuống dòng tiếp theo."))
        n_review = sum(1 for s in self.segments if s.needs_review)
        # Điểm dừng #1 chạy TRƯỚC bước gender -> checkpoint "gender" chưa có;
        # đếm loa distinct từ chính các segment (không đếm self.speakers).
        n_speakers = len({s.speaker for s in self.segments})
        self.lbl_note = QLabel(
            f"Tổng {len(self.segments)} câu, {n_speakers} loa"
            + (f" — {n_review} câu tô vàng cần kiểm tra kỹ (ASR nghe không "
               "chắc)." if n_review else "."))
        root.addWidget(self.lbl_note)

        self.tbl = QTableWidget(len(self.segments), len(COLS))
        self.tbl.setHorizontalHeaderLabels(COLS)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setItemDelegateForColumn(4, GenderDelegate(self))
        self.tbl.setItemDelegateForColumn(5, AudienceDelegate(
            self, lambda: self.tbl))
        for r, seg in enumerate(self.segments):
            self._fill_row(r, seg)
        self.tbl.setColumnWidth(0, 44)
        self.tbl.setColumnWidth(1, 80)
        self.tbl.setColumnWidth(2, 80)
        self.tbl.setColumnWidth(3, 52)
        self.tbl.setColumnWidth(4, 92)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl.setSelectionMode(QTableWidget.SingleSelection)
        root.addWidget(self.tbl, 1)

        row = QHBoxLayout()
        self.btn_play = QPushButton("Nghe lại câu")
        self.btn_play.clicked.connect(self.play_selected)
        self.btn_split = QPushButton("Tách câu")
        self.btn_split.setToolTip(
            "Tách câu đang chọn thành 2 câu tại dấu câu gần giữa nhất")
        self.btn_split.clicked.connect(self.split_selected)
        self.btn_merge = QPushButton("Gộp với câu dưới")
        self.btn_merge.clicked.connect(self.merge_with_next)
        btn_settings = QPushButton("Cài đặt")
        btn_settings.clicked.connect(self.open_settings)
        btn_back = QPushButton("Quay lại")
        btn_back.clicked.connect(self._back_clicked)
        btn_next = QPushButton("Tiếp tục dịch →")
        btn_next.setStyleSheet("font-weight: bold;")
        btn_next.clicked.connect(self.save_and_continue)
        row.addWidget(self.btn_play)
        row.addWidget(self.btn_split)
        row.addWidget(self.btn_merge)
        row.addStretch(1)
        row.addWidget(btn_settings)
        row.addWidget(btn_back)
        row.addWidget(btn_next)
        root.addLayout(row)

    def open_settings(self) -> None:
        from ui.common import open_settings_dialog
        open_settings_dialog(self, self.settings)

    def closeEvent(self, e) -> None:  # noqa: N802
        # Bấm X = [Quay lại]: về màn tiến trình, không quit app, không mất
        # checkpoint (màn tiến trình đang hide). Trì hoãn qua singleShot để
        # tránh gọi close() đệ quy (on_back tự đóng window này).
        # Nếu đóng là do bấm nút [Quay lại]/[Tiếp tục] thì on_back/on_continue
        # đã chạy rồi -> không schedule thêm lần nữa.
        self._stop_playback()
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
        self.tbl.setItem(r, 1, ro(fmt_time(seg.start)))
        self.tbl.setItem(r, 2, ro(fmt_time(seg.end)))
        self.tbl.setItem(r, 3, QTableWidgetItem(str(seg.speaker)))
        self.tbl.setItem(r, 4, QTableWidgetItem(
            GENDER_LABEL.get(seg.gender, "Không rõ")))
        self.tbl.setItem(r, 5, QTableWidgetItem(audience_label(seg.audience)))
        self.tbl.setItem(r, 6, QTableWidgetItem(seg.text_src or ""))
        if seg.needs_review:
            for c in range(len(COLS)):
                self.tbl.item(r, c).setBackground(QColor("#fff3b0"))

    # ------------------------------------------------------------ nghe lại
    def _wav_path(self) -> str:
        data = cp.load_step(self.job.job_dir, "extract") or {}
        return data.get("wav_path", "")

    def play_selected(self) -> None:
        if self._playing_row >= 0:
            self._stop_playback()
            return
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            error_box(self, "Chưa chọn câu",
                      "Hãy bấm chọn một dòng trong bảng rồi bấm Nghe lại câu.")
            return
        r = rows[0].row()
        seg = self.segments[r]
        wav = self._wav_path()
        if not wav or not Path(wav).is_file():
            error_box(self, "Không có audio gốc",
                      "Không tìm thấy file audio đã tách.\n\n"
                      "Cách khắc phục: chạy lại từ bước [1] Tách audio.")
            return
        self._pending_seek = int(seg.start * 1000)
        self._player.setSource(QUrl.fromLocalFile(wav))
        self._player.play()
        ms = max(300, int((seg.end - seg.start) * 1000))
        self._stop_timer.start(ms)
        self._playing_row = r
        self.btn_play.setText("Dừng")

    def _on_media_status(self, status) -> None:
        # Seek chỉ chắc có tác dụng khi media đã load xong: gọi
        # setPosition() ngay sau setSource() thì backend chưa kịp load nên
        # seek bị bỏ qua (phát từ đầu file thay vì đúng câu).
        if self._pending_seek is not None and status in (
                QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._player.setPosition(self._pending_seek)
            self._pending_seek = None

    def _stop_playback(self) -> None:
        self._stop_timer.stop()
        self._player.stop()
        self._playing_row = -1
        self.btn_play.setText("Nghe lại câu")

    # ------------------------------------------------------- tách / gộp câu
    def _renumber(self) -> None:
        for i, seg in enumerate(self.segments):
            seg.index = i

    def _rebuild_table(self) -> None:
        self.tbl.setRowCount(len(self.segments))
        for r, seg in enumerate(self.segments):
            self._fill_row(r, seg)
        n_speakers = len({s.speaker for s in self.segments})
        n_review = sum(1 for s in self.segments if s.needs_review)
        self.lbl_note.setText(
            f"Tổng {len(self.segments)} câu, {n_speakers} loa"
            + (f" — {n_review} câu tô vàng cần kiểm tra kỹ (ASR nghe không "
               "chắc)." if n_review else "."))

    def split_selected(self) -> None:
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            error_box(self, "Chưa chọn câu",
                      "Hãy chọn một dòng trong bảng rồi bấm Tách câu.")
            return
        r = rows[0].row()
        if not self._read_table():  # đọc sửa tại chỗ trước khi tách
            return
        seg = self.segments[r]
        text = (seg.text_src or "").strip()
        n = len(text)
        cut = -1
        if n > 1:
            mid = n / 2
            # Ưu tiên tách tại dấu câu gần giữa câu nhất.
            punct = [m.start()
                     for m in re.finditer(r"[,，.。!！?？、;；:：]", text)]
            if punct:
                cut = min(punct, key=lambda i: abs(i - mid)) + 1
            else:
                spaces = [m.start() for m in re.finditer(r"\s", text)]
                if spaces:
                    cut = min(spaces, key=lambda i: abs(i - mid))
        t1, t2 = text[:cut].strip(), text[cut:].strip()
        if cut <= 0 or not t1 or not t2:
            error_box(self, "Không tách được",
                      "Câu quá ngắn hoặc không tìm được điểm tách hợp lý "
                      "(cần có dấu câu hoặc khoảng trắng giữa câu).")
            return
        # Chia timestamp theo tỉ lệ độ dài ký tự của 2 câu con.
        dur = max(0.1, seg.end - seg.start)
        ratio = len(t1) / max(1, len(t1) + len(t2))
        mid_t = seg.start + dur * ratio
        seg1 = Segment(index=seg.index, start=seg.start, end=mid_t,
                       speaker=seg.speaker, gender=seg.gender, text_src=t1,
                       audience=seg.audience,
                       confidence=seg.confidence,
                       needs_review=seg.needs_review)
        seg2 = Segment(index=seg.index + 1, start=mid_t, end=seg.end,
                       speaker=seg.speaker, gender=seg.gender, text_src=t2,
                       audience=seg.audience,
                       confidence=seg.confidence,
                       needs_review=seg.needs_review)
        self.segments[r:r + 1] = [seg1, seg2]
        self._renumber()
        self._rebuild_table()
        self.tbl.selectRow(r + 1)
        info_box(self, "Đã tách", f"Câu {r + 1} đã tách thành 2 câu.")

    def merge_with_next(self) -> None:
        rows = self.tbl.selectionModel().selectedRows()
        if not rows:
            error_box(self, "Chưa chọn câu",
                      "Hãy chọn một dòng trong bảng rồi bấm Gộp với câu dưới.")
            return
        r = rows[0].row()
        if r >= len(self.segments) - 1:
            error_box(self, "Không gộp được",
                      "Đây là câu cuối cùng, không có câu dưới để gộp.")
            return
        if not self._read_table():  # đọc sửa tại chỗ trước khi gộp
            return
        a, b = self.segments[r], self.segments[r + 1]
        a.text_src = ((a.text_src or "").rstrip() + " " +
                      (b.text_src or "").lstrip()).strip()
        a.end = max(a.end, b.end)
        a.needs_review = a.needs_review or b.needs_review
        a.confidence = min(a.confidence, b.confidence)
        del self.segments[r + 1]
        self._renumber()
        self._rebuild_table()
        self.tbl.selectRow(r)
        info_box(self, "Đã gộp", f"Đã gộp câu {r + 1} với câu {r + 2}.")

    # ------------------------------------------------------------ lưu + tiếp
    def _read_table(self) -> bool:
        """Đọc bảng vào segments/speakers. False = lỗi nhập liệu."""
        for r in range(self.tbl.rowCount()):
            seg = self.segments[r]
            try:
                spk = int(self.tbl.item(r, 3).text().strip())
            except (ValueError, AttributeError):
                error_box(self, "Loa không hợp lệ",
                          f"Dòng {r + 1}: cột Loa phải là số nguyên "
                          f"(vd 0, 1). Bạn nhập: "
                          f"'{self.tbl.item(r, 3).text()}'.")
                self.tbl.selectRow(r)
                return False
            gender = GENDER_VALUE.get(
                self.tbl.item(r, 4).text().strip(), "")
            aud = audience_value(self.tbl.item(r, 5).text())
            if aud is None:
                error_box(self, "Nói với ai không hợp lệ",
                          f"Dòng {r + 1}: cột 'Nói với ai' phải chọn trong "
                          f"dropdown (Chưa rõ/Khán giả/Tất cả/Loa N). "
                          f"Bạn nhập: '{self.tbl.item(r, 5).text()}'.")
                self.tbl.selectRow(r)
                return False
            seg.speaker = spk
            seg.gender = gender
            seg.audience = aud
            seg.text_src = self.tbl.item(r, 6).text()
        # đồng bộ giới tính vào speakers (bước dịch dùng speakers)
        for seg in self.segments:
            spk = self.speakers.get(seg.speaker)
            if spk is None:
                spk = Speaker(id=seg.speaker)
                self.speakers[seg.speaker] = spk
            if seg.gender:
                spk.gender = seg.gender
        return True

    def save_and_continue(self) -> None:
        self._stop_playback()
        if not self._read_table():
            return
        pio.save_segments(self.job.job_dir, "asr", self.segments)
        pio.save_speakers(self.job.job_dir, "gender", self.speakers)
        info_box(self, "Đã lưu",
                 f"Đã lưu {len(self.segments)} câu đã duyệt. "
                 "Chạy tiếp bước phân tích quan hệ và dịch.")
        self._close_via_button = True  # on_continue tự đóng window này
        self.on_continue()
