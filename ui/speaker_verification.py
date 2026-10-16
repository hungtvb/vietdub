"""Native two-stage speaker identity review: original voice clips and each line.

No external speaker-identity service. All labels are human approved with source
audio/video and are stored in the current project's checkpoint only.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from speaker.verification import SpeakerVerification
from ui.common import error_box, info_box


class SpeakerVerificationDialog(QDialog):
    def __init__(self, job, segments, wav_path, parent=None):
        super().__init__(parent)
        self.job = job
        self.segments = segments
        self._initial_snapshot = [dict(s.__dict__) for s in segments]
        self.wav_path = Path(wav_path)
        self.source_video = Path(job.project.video_in) if job.project.video_in else None
        self.anchor_dir = job.stages_dir / "voice_anchor_review"
        manifest_path = self.anchor_dir / "voice_anchor_candidates.json"
        manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                    if manifest_path.exists() else None)
        self.store = SpeakerVerification(job.job_dir, segments, self.wav_path, manifest)
        self.anchors = list(self.store.candidates.values())
        self.setWindowTitle(f"Xác minh nhân vật V2 — {job.project.name}")
        self.resize(1100, 720)

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.pending_seek = None
        self.stop_at = None
        self.player.mediaStatusChanged.connect(self._media_loaded)
        self.player.positionChanged.connect(self._on_position)

        root = QVBoxLayout(self)
        note = QLabel(
            "Cụm giọng pyannote KHÔNG phải tên nhân vật. Duyệt mẫu âm thanh "
            "không tự phê duyệt toàn bộ cụm. Mỗi câu phải được nghe và đối chiếu "
            "hình ảnh video gốc trước khi xác nhận.")
        note.setWordWrap(True)
        root.addWidget(note)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)
        self.anchors_table = self._table(
            ["Mẫu", "Giây", "Cụm AI", "Lời tham chiếu (chưa duyệt)", "Nhân vật"],
            self.anchors)
        self.tabs.addTab(self.anchors_table, "Mẫu giọng")
        self.lines_table = self._table(
            ["#", "Giây", "Loa ASR", "Lời thoại", "Gợi ý chưa duyệt",
             "Danh tính đã xác minh"], self.segments)
        self.tabs.addTab(self.lines_table, "Từng câu thoại")
        self.tabs.currentChanged.connect(self._changed)
        self.anchors_table.itemSelectionChanged.connect(self._changed)
        self.lines_table.itemSelectionChanged.connect(self._changed)

        row = QHBoxLayout()
        left = QWidget(self)
        controls = QVBoxLayout(left)
        controls.addWidget(QLabel("Tên nhân vật (gõ tên mới hoặc chọn tên đã có)"))
        self.name = QComboBox(self)
        self.name.setEditable(True)
        self.name.setInsertPolicy(QComboBox.NoInsert)
        self.name.setMinimumWidth(250)
        controls.addWidget(self.name)
        self.note = QLineEdit(self)
        self.note.setPlaceholderText("Ghi chú bằng chứng (tùy chọn)")
        controls.addWidget(self.note)
        self.heard = QCheckBox("Tôi đã nghe audio GỐC", self)
        self.watched = QCheckBox("Tôi đã đối chiếu nhân vật trên video GỐC", self)
        controls.addWidget(self.heard)
        controls.addWidget(self.watched)
        for title, handler in (
            ("Nghe mẫu / câu", self.play_audio),
            ("Xem cảnh video gốc", self.play_video),
            ("XÁC MINH MỤC ĐANG CHỌN", self.verify_selected),
            ("Hủy xác minh mục", self.revoke_selected),
        ):
            btn = QPushButton(title)
            btn.clicked.connect(handler)
            controls.addWidget(btn)
        controls.addStretch()
        row.addWidget(left, 1)

        visual = QWidget(self)
        visual_layout = QVBoxLayout(visual)
        preview_note = QLabel("Kiểm tra khung hình từ video nguồn trước khi xác minh.")
        visual_layout.addWidget(preview_note)
        self.preview = QVideoWidget(self)
        self.preview.setMinimumSize(460, 260)
        self.player.setVideoOutput(self.preview)
        visual_layout.addWidget(self.preview, 1)
        row.addWidget(visual, 2)
        root.addLayout(row)

        footer = QHBoxLayout()
        self.summary_label = QLabel(self)
        footer.addWidget(self.summary_label, 1)
        cancel = QPushButton("Đóng không lưu")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Lưu xác minh")
        save.clicked.connect(self.save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)
        self._refresh()

    def _table(self, titles, items):
        table = QTableWidget(len(items), len(titles), self)
        table.setHorizontalHeaderLabels(titles)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate([70, 140, 100, 350, 170]):
            if column < len(titles):
                table.setColumnWidth(column, width)
        return table

    @staticmethod
    def _cell(table, row, col, text):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, col, item)

    def _refresh(self):
        self.store.apply_verified_lines()
        for row, anchor in enumerate(self.anchors):
            key = anchor["candidate_id"]
            decision = self.store.anchor_decisions.get(key, {})
            char = self.store.characters.get(decision.get("character_id"), {})
            values = (
                key, f'{anchor["start"]:.2f}–{anchor["end"]:.2f}',
                anchor.get("cluster", ""), anchor.get("transcript_context_unverified", ""),
                char.get("name", "CHƯA XÁC MINH"),
            )
            for col, value in enumerate(values):
                self._cell(self.anchors_table, row, col, value)
        for row, seg in enumerate(self.segments):
            proposed = self.store.suggest(seg.index)
            guess = proposed.get("character_name") or (
                "XUNG ĐỘT" if proposed["status"] == "CONFLICT" else "—")
            actual = (seg.character_name + " ✓"
                      if seg.identity_status == "VERIFIED" else "CHƯA XÁC MINH")
            values = (
                seg.index, f"{seg.start:.2f}–{seg.end:.2f}",
                seg.detected_speaker if seg.detected_speaker is not None else seg.speaker,
                seg.text_src, guess, actual,
            )
            for col, value in enumerate(values):
                self._cell(self.lines_table, row, col, value)
        self.name.clear()
        self.name.addItems([x["name"] for x in self.store.characters.values()])
        info = self.store.summary()
        self.summary_label.setText(
            f"Đã xác minh {info['verified_lines']}/{len(self.segments)} câu; "
            f"{info['verified_anchors']} mẫu; bản dịch CHƯA được duyệt.")

    def _selected(self):
        if self.tabs.currentIndex() == 0:
            rows = self.anchors_table.selectionModel().selectedRows()
            return ("anchor", self.anchors[rows[0].row()]) if rows else (None, None)
        rows = self.lines_table.selectionModel().selectedRows()
        return ("line", self.segments[rows[0].row()]) if rows else (None, None)

    def _changed(self, *args):
        kind, item = self._selected()
        self.heard.setChecked(False)
        self.watched.setChecked(False)
        if item is None:
            return
        if kind == "anchor":
            dec = self.store.anchor_decisions.get(item["candidate_id"], {})
            char = self.store.characters.get(dec.get("character_id"), {})
            self.name.setCurrentText(char.get("name", ""))
        else:
            self.name.setCurrentText(
                item.character_name or self.store.suggest(item.index).get("character_name", ""))

    def _media_loaded(self, status):
        if self.pending_seek is not None and status in (
                QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self.player.setPosition(self.pending_seek)
            self.pending_seek = None

    def _on_position(self, position):
        if self.stop_at is not None and self.pending_seek is None and position >= self.stop_at:
            self.player.stop()
            self.stop_at = None

    def _play(self, source, start, end):
        source = Path(source)
        if not source.is_file():
            error_box(self, "Thiếu media gốc", f"Không tìm thấy {source}")
            return
        self.player.stop()
        self.stop_at = int(float(end) * 1000)
        self.pending_seek = int(float(start) * 1000)
        self.player.setSource(QUrl.fromLocalFile(str(source.resolve())))
        self.player.play()

    def play_audio(self):
        kind, item = self._selected()
        if item is None:
            info_box(self, "Chưa chọn", "Hãy chọn mẫu hoặc một câu thoại.")
        elif kind == "anchor":
            self._play(self.anchor_dir / item["file"], 0.,
                       float(item["end"]) - float(item["start"]))
        else:
            self._play(self.wav_path, item.start, item.end)

    def play_video(self):
        kind, item = self._selected()
        if item is None:
            return
        if self.source_video is None or not self.source_video.is_file():
            error_box(self, "Thiếu video", "Không có video GỐC để đối chiếu hình ảnh.")
            return
        start = item.start if kind == "line" else item["start"]
        end = item.end if kind == "line" else item["end"]
        self._play(self.source_video, start, end)

    def verify_selected(self):
        kind, item = self._selected()
        if item is None:
            error_box(self, "Chưa chọn", "Hãy chọn một câu hoặc mẫu giọng.")
            return
        if self.source_video is None or not self.source_video.is_file():
            error_box(self, "Thiếu video", "Cần video nguồn để xác minh nhân vật.")
            return
        args = dict(heard_audio=self.heard.isChecked(),
                    checked_video=self.watched.isChecked(),
                    note=self.note.text())
        try:
            if kind == "anchor":
                self.store.verify_anchor(item["candidate_id"], self.name.currentText(), **args)
            else:
                self.store.verify_line(item.index, self.name.currentText(), **args)
        except (ValueError, KeyError) as exc:
            error_box(self, "Chưa đủ bằng chứng", str(exc))
            return
        self._refresh()
        self.heard.setChecked(False)
        self.watched.setChecked(False)

    def revoke_selected(self):
        kind, item = self._selected()
        if kind == "anchor":
            self.store.revoke_anchor(item["candidate_id"])
        elif kind == "line":
            self.store.revoke_line(item.index)
        self._refresh()

    def save(self):
        self.store.save()
        self.player.stop()
        self.accept()

    def reject(self):
        self.player.stop()
        for seg, before in zip(self.segments, self._initial_snapshot):
            seg.__dict__.update(before)
        super().reject()
