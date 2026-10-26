# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Same-session sequential queue for local video files."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog,
                               QHeaderView, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from core.job import CANCELLED, DONE, FAILED, PAUSED, REVIEW, Job
from core.orchestrator import STEPS, STEP_LABEL
from core.settings import Settings
from ui.common import confirm_box, info_box
from ui.theme import UI_COLORS

VIDEO_FILTER = "Video (*.mp4 *.mkv *.avi *.mov *.webm *.ts *.m4v);;Tất cả (*.*)"


@dataclass
class QueueEntry:
    path: str
    state: str = "queued"
    progress: int = 0
    message: str = ""
    job: Job | None = None


class BatchQueueWindow(QDialog):
    """Run queued local files one by one through the existing job UI."""

    def __init__(self, main_window, settings: Settings,
                 on_close: Callable[[], None]):
        super().__init__(main_window, Qt.Window)
        self.main_window = main_window
        self.settings = settings
        self.on_close = on_close
        self.entries: list[QueueEntry] = []
        self._current_index: int | None = None
        self._progress_window = None
        self._active_job: Job | None = None
        self._started = False
        self._queue_active = False
        self._blocked = False
        self._all_finished = False
        self._stopped = False
        self._notified_close = False

        self.setWindowTitle("VietDub — Hàng đợi video")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(820, 590)
        self.setMinimumSize(640, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 17, 20, 18)
        root.setSpacing(12)
        title = QLabel("Hàng đợi lồng tiếng")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.description = QLabel(
            "Thêm video từ máy tính để xử lý lần lượt. Mỗi video dùng một job "
            "riêng và rãnh âm thanh đầu tiên. Danh sách chỉ được giữ trong "
            "phiên hiện tại; checkpoint của từng job vẫn được lưu.")
        self.description.setWordWrap(True)
        self.description.setProperty("role", "secondary")
        root.addWidget(self.description)

        self.table = QTableWidget(0, 3)
        self.table.setAccessibleName("Video trong hàng đợi")
        self.table.setHorizontalHeaderLabels(["Video", "Trạng thái", "Tiến độ"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_controls)
        root.addWidget(self.table, 1)

        edit_row = QHBoxLayout()
        self.btn_add = QPushButton("Thêm video…")
        self.btn_add.setProperty("role", "secondary")
        self.btn_add.clicked.connect(self.add_files)
        self.btn_remove = QPushButton("Xóa khỏi hàng đợi")
        self.btn_remove.setProperty("role", "secondary")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_up = QPushButton("Lên")
        self.btn_up.clicked.connect(lambda: self.move_selected(-1))
        self.btn_down = QPushButton("Xuống")
        self.btn_down.clicked.connect(lambda: self.move_selected(1))
        edit_row.addWidget(self.btn_add)
        edit_row.addWidget(self.btn_remove)
        edit_row.addStretch(1)
        edit_row.addWidget(self.btn_up)
        edit_row.addWidget(self.btn_down)
        root.addLayout(edit_row)

        self.status = QLabel("Chưa có video trong hàng đợi.")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "secondary")
        root.addWidget(self.status)

        action_row = QHBoxLayout()
        self.btn_start = QPushButton("Bắt đầu hàng đợi")
        self.btn_start.setProperty("role", "primary")
        self.btn_start.clicked.connect(self.start_queue)
        self.btn_resume = QPushButton("Tiếp tục / chạy lại video này")
        self.btn_resume.setProperty("role", "primary")
        self.btn_resume.clicked.connect(self.resume_current)
        self.btn_skip = QPushButton("Bỏ qua video này")
        self.btn_skip.setProperty("role", "danger")
        self.btn_skip.clicked.connect(self.skip_current)
        self.btn_close = QPushButton("Đóng")
        self.btn_close.setProperty("role", "secondary")
        self.btn_close.clicked.connect(self.request_close)
        action_row.addWidget(self.btn_start)
        action_row.addWidget(self.btn_resume)
        action_row.addWidget(self.btn_skip)
        action_row.addStretch(1)
        action_row.addWidget(self.btn_close)
        root.addLayout(action_row)
        self._update_controls()

    # ----------------------------------------------------------- list editing
    @staticmethod
    def _path_key(path: str) -> str:
        return os.path.normcase(str(Path(path).resolve()))

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Thêm video vào hàng đợi", "", VIDEO_FILTER)
        if not paths:
            return
        known = {self._path_key(entry.path) for entry in self.entries}
        added = 0
        rejected: list[str] = []
        for raw_path in paths:
            path = str(Path(raw_path).expanduser())
            if not Path(path).is_file():
                rejected.append(Path(path).name or path)
                continue
            key = self._path_key(path)
            if key in known:
                continue
            known.add(key)
            self.entries.append(QueueEntry(path=path))
            added += 1
        self._refresh_table()
        self._update_controls()
        self.status.setText(f"Đã thêm {added} video. Thứ tự có thể đổi trước khi chạy.")
        if rejected:
            info_box(self, "Một số tệp không hợp lệ",
                     "Không thêm được các tệp này:\n" + "\n".join(rejected[:8]))

    def remove_selected(self) -> None:
        if self._started:
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()},
                      reverse=True)
        for row in rows:
            if 0 <= row < len(self.entries):
                self.entries.pop(row)
        self._refresh_table()
        self._update_controls()

    def move_selected(self, delta: int) -> None:
        if self._started:
            return
        selected = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected:
            return
        if selected != list(range(selected[0], selected[-1] + 1)):
            return
        start, end = selected[0], selected[-1]
        if delta < 0 and start > 0:
            preceding = self.entries.pop(start - 1)
            self.entries.insert(end, preceding)
            start -= 1
            end -= 1
        elif delta > 0 and end < len(self.entries) - 1:
            following = self.entries.pop(end + 1)
            self.entries.insert(start, following)
            start += 1
            end += 1
        self._refresh_table()
        self.table.clearSelection()
        for row in range(start, end + 1):
            self.table.selectRow(row)

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            name = QTableWidgetItem(Path(entry.path).name)
            name.setToolTip(entry.path)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(self._state_label(entry)))
            self.table.setItem(row, 2, QTableWidgetItem(f"{entry.progress}%"))
        self.table.resizeRowsToContents()

    @staticmethod
    def _state_label(entry: QueueEntry) -> str:
        labels = {
            "queued": "Trong hàng",
            "running": "Đang chạy",
            "review": "Đang chờ duyệt",
            "paused": "Đã tạm dừng",
            "failed": "Thất bại",
            "cancelled": "Đã hủy",
            "done": "Hoàn tất",
            "skipped": "Đã bỏ qua",
        }
        return labels.get(entry.state, entry.state)

    def _update_entry(self, index: int) -> None:
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        status_item = self.table.item(index, 1)
        progress_item = self.table.item(index, 2)
        if status_item is None or progress_item is None:
            self._refresh_table()
            return
        status_item.setText(self._state_label(entry))
        color = (UI_COLORS["success"] if entry.state == "done" else
                 UI_COLORS["danger"] if entry.state in {"failed", "cancelled"} else
                 UI_COLORS["primary"] if entry.state in {"running", "review", "paused"} else
                 UI_COLORS["secondary_text"])
        status_item.setForeground(QColor(color))
        status_item.setToolTip(entry.message or entry.path)
        progress_item.setText(f"{entry.progress}%")

    # -------------------------------------------------------------- execution
    def start_queue(self) -> None:
        if self._started or not self.entries:
            return
        if not self.main_window._validate_provider_choice(parent=self):
            return
        self._started = True
        self._queue_active = True
        self.status.setText("Hàng đợi chạy lần lượt. Duyệt, lỗi hoặc tạm dừng sẽ giữ tại video hiện tại.")
        self._update_controls()
        self._run_next()

    def _run_next(self) -> None:
        if not self._queue_active:
            return
        next_index = next((i for i, item in enumerate(self.entries)
                           if item.state == "queued"), None)
        if next_index is None:
            self._queue_active = False
            self._all_finished = True
            done = sum(item.state == "done" for item in self.entries)
            failed = sum(item.state == "failed" for item in self.entries)
            cancelled = sum(item.state == "cancelled" for item in self.entries)
            skipped = sum(item.state == "skipped" for item in self.entries)
            self.status.setText(
                f"Hàng đợi kết thúc · {done} hoàn tất · {failed} lỗi · "
                f"{cancelled} đã hủy · {skipped} bỏ qua.")
            self._update_controls()
            self.show()
            self.raise_()
            return

        self._current_index = next_index
        entry = self.entries[next_index]
        self.status.setText(
            f"Đang xử lý video {next_index + 1}/{len(self.entries)} · "
            f"{Path(entry.path).name}")
        if not Path(entry.path).is_file():
            entry.state = "failed"
            entry.message = "Tệp video không còn tồn tại hoặc không đọc được."
            self._blocked = True
            self._queue_active = False
            self.status.setText(f"Không tìm thấy tệp: {entry.path}")
            self._update_entry(next_index)
            self._update_controls()
            return
        entry.state = "running"
        entry.progress = 0
        entry.message = "Đang khởi tạo job"
        try:
            entry.job = self.main_window.create_batch_job(entry.path)
        except Exception as exc:  # noqa: BLE001 - job creation error is item-scoped
            entry.state = "failed"
            entry.message = str(exc)
            self._blocked = True
            self._queue_active = False
            self.status.setText(f"Không thể tạo job cho {Path(entry.path).name}: {exc}")
            self._update_entry(next_index)
            self._update_controls()
            return
        self._active_job = entry.job
        self._update_entry(next_index)
        self._launch_progress()

    def _launch_progress(self, *, show_review: bool = False) -> None:
        if self._active_job is None:
            return
        from ui.progress import ProgressWindow
        self._progress_window = ProgressWindow(
            self._active_job, self.settings,
            on_close=self._progress_closed,
            on_progress=self._job_progress,
            on_result=self._job_result)
        self._progress_window.show()
        if show_review:
            self._progress_window.show_current_review()
        else:
            self._progress_window.begin(resume_from=self._active_job.resume_from)
        self._update_controls()

    def _job_progress(self, step: str, pct: float, msg: str) -> None:
        if self._current_index is None:
            return
        entry = self.entries[self._current_index]
        if step in STEPS:
            position = STEPS.index(step)
            value = (position * 100 + max(0.0, min(100.0, pct))) / len(STEPS)
            entry.progress = int(value)
            entry.state = "running"
            entry.message = f"{STEP_LABEL[step]} · {pct:.0f}%"
        else:
            entry.message = msg or step
        self._update_entry(self._current_index)

    def _job_result(self, job: Job, result: str) -> None:
        if self._current_index is None:
            return
        entry = self.entries[self._current_index]
        if result == DONE:
            entry.state = "done"
            entry.progress = 100
            entry.message = "Đã tạo video đầu ra."
        elif result == REVIEW:
            entry.state = "review"
            entry.message = "Hãy hoàn tất bước duyệt để tiếp tục video này."
        elif result == PAUSED:
            entry.state = "paused"
            entry.message = "Checkpoint được giữ; tiếp tục hoặc bỏ qua rõ ràng."
        elif result == FAILED:
            entry.state = "failed"
            entry.message = "Xem lỗi và log trong cửa sổ xử lý."
        elif result == CANCELLED:
            entry.state = "cancelled"
            entry.message = "Job đã hủy; cần tiếp tục hoặc bỏ qua rõ ràng."
        self._update_entry(self._current_index)

    def _progress_closed(self) -> None:
        window = self._progress_window
        self._progress_window = None
        if window is not None:
            window.deleteLater()
        if self._current_index is None:
            self._update_controls()
            return
        entry = self.entries[self._current_index]
        if entry.job is not None and entry.job.status == DONE:
            entry.state = "done"
            entry.progress = 100
            entry.message = "Đã tạo video đầu ra."
            self._update_entry(self._current_index)
            self._current_index = None
            self._active_job = None
            self._queue_active = True
            self._update_controls()
            QTimer.singleShot(0, self._run_next)
            return

        self._queue_active = False
        self._blocked = True
        if entry.job is not None:
            self._state_from_job(entry, entry.job)
        self.status.setText(
            "Hàng đợi đang dừng tại video này. Tiếp tục/chạy lại hoặc bỏ qua "
            "video bằng nút bên dưới.")
        self._update_entry(self._current_index)
        self._update_controls()
        self.show()
        self.raise_()

    def _state_from_job(self, entry: QueueEntry, job: Job) -> None:
        if job.status == PAUSED:
            entry.state = "paused"
        elif job.status == FAILED:
            entry.state = "failed"
        elif job.status == CANCELLED:
            entry.state = "cancelled"
        elif job.status == REVIEW:
            entry.state = "review"

    def resume_current(self) -> None:
        if (not self._blocked or self._current_index is None
                or self._progress_window is not None):
            return
        entry = self.entries[self._current_index]
        if entry.job is None:
            entry.state = "queued"
            entry.message = "Thử tạo lại job cho video này."
            self._update_entry(self._current_index)
            self._current_index = None
            self._queue_active = True
            self._blocked = False
            self._run_next()
            return
        self._blocked = False
        self._queue_active = True
        show_review = entry.job.status == REVIEW
        if show_review:
            entry.state = "review"
            entry.message = "Mở lại bước duyệt trước khi tiếp tục."
        else:
            entry.state = "running"
            entry.message = "Đang tiếp tục từ checkpoint đã lưu."
        self._active_job = entry.job
        self._update_entry(self._current_index)
        self.status.setText(
            f"{'Mở lại bước duyệt' if show_review else 'Đang tiếp tục'} · "
            f"{Path(entry.path).name}")
        self._launch_progress(show_review=show_review)

    def skip_current(self) -> None:
        if (not self._blocked or self._current_index is None
                or self._progress_window is not None):
            return
        if not confirm_box(
                self, "Bỏ qua video này?",
                "Video này sẽ được đánh dấu bỏ qua; checkpoint của job vẫn còn "
                "trong thư mục dữ liệu để xử lý lại sau."):
            return
        entry = self.entries[self._current_index]
        entry.state = "skipped"
        entry.message = f"Bỏ qua sau trạng thái {entry.job.status if entry.job else 'lỗi khởi tạo'}."
        self._update_entry(self._current_index)
        self.status.setText(f"Đã bỏ qua {Path(entry.path).name}; chuyển video tiếp theo.")
        self._current_index = None
        self._active_job = None
        self._blocked = False
        self._queue_active = True
        self._update_controls()
        self._run_next()

    # ------------------------------------------------------------ window flow
    def _update_controls(self) -> None:
        editable = not self._started
        self.btn_add.setEnabled(editable)
        self.btn_remove.setEnabled(editable and bool(self.table.selectedItems()))
        self.btn_up.setEnabled(editable and bool(self.table.selectedItems()))
        self.btn_down.setEnabled(editable and bool(self.table.selectedItems()))
        self.btn_start.setEnabled(editable and bool(self.entries))
        can_act = (self._blocked and self._current_index is not None
                   and self._progress_window is None)
        can_resume = can_act
        if can_resume and self._current_index is not None:
            current = self.entries[self._current_index]
            if current.job is None and not Path(current.path).is_file():
                can_resume = False
        self.btn_resume.setEnabled(can_resume)
        if can_act and self._current_index is not None:
            current = self.entries[self._current_index]
            self.btn_resume.setText(
                "Mở lại bước duyệt" if current.state == "review"
                else "Tiếp tục / chạy lại video này")
        self.btn_skip.setEnabled(can_act)
        self.btn_close.setEnabled(not self._queue_active
                                  and self._progress_window is None)

    def request_close(self) -> None:
        if self._queue_active or self._progress_window is not None:
            info_box(self, "Hàng đợi đang chạy",
                     "Hãy tạm dừng hoặc hủy job hiện tại trước khi đóng "
                     "hàng đợi.")
            return
        if self._started and not self._all_finished and not self._stopped:
            if not confirm_box(
                    self, "Dừng hàng đợi?",
                    "Các checkpoint của job hiện tại vẫn được giữ. Danh sách "
                    "video còn chờ không được lưu sau khi đóng cửa sổ."):
                return
            self._stopped = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._queue_active or self._progress_window is not None:
            event.ignore()
            self.status.setText(
                "Job hiện tại còn hoạt động. Hãy dùng cửa sổ xử lý để tạm dừng "
                "hoặc hủy trước khi đóng hàng đợi.")
            return
        if self._started and not self._all_finished and not self._stopped:
            event.ignore()
            self.request_close()
            return
        if not self._notified_close:
            self._notified_close = True
            self.on_close()
        super().closeEvent(event)
