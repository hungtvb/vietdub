# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Persistent sequential queue for local video files."""
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

from core.job import CANCELLED, DONE, FAILED, PAUSED, REVIEW, RUNNING, Job
from core.orchestrator import STEPS, STEP_LABEL
from core.job_recovery import JobInspection, inspect_job
from core.job_store import JobRecord, JobRecordError, JobStore
from core.queue_store import QueueItemRecord, QueueManifest, QueueStore, QueueStoreError
from core.settings import Settings
from ui.common import confirm_box, error_box, info_box
from ui.theme import UI_COLORS

VIDEO_FILTER = "Video (*.mp4 *.mkv *.avi *.mov *.webm *.ts *.m4v);;Tất cả (*.*)"


@dataclass
class QueueEntry:
    path: str
    entry_id: str
    state: str = "queued"
    progress: int = 0
    message: str = ""
    job_id: str | None = None
    job: Job | None = None
    inspection: JobInspection | None = None
    blocked_reason: str | None = None


class BatchQueueWindow(QDialog):
    """Run queued local files one by one through the existing job UI."""

    def __init__(self, main_window, settings: Settings,
                 on_close: Callable[[], None], *,
                 queue_store: QueueStore | None = None,
                 manifest: QueueManifest | None = None):
        super().__init__(main_window, Qt.Window)
        self.main_window = main_window
        self.settings = settings
        self.on_close = on_close
        self.queue_store = queue_store or QueueStore()
        self.job_store = JobStore()
        self.sub_mode = self.settings.get("sub_mode", "burn") or "burn"
        self.entries: list[QueueEntry] = []
        self._current_index: int | None = None
        self._progress_window = None
        self._active_job: Job | None = None
        self._started = False
        self._restored_unfinished = False
        self._queue_active = False
        self._blocked = False
        self._all_finished = False
        self._stopped = False
        self._notified_close = False
        self._active_entry_id: str | None = None
        self._needs_done_reconcile = False
        self._needs_finalize = False

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
            "riêng và rãnh âm thanh đầu tiên. Thứ tự cùng job đang hoạt động "
            "được lưu để có thể khôi phục sau khi mở lại ứng dụng.")
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
        if manifest is not None:
            self._restore_manifest(manifest)
        self._update_controls()

    # ----------------------------------------------------------- list editing
    @staticmethod
    def _path_key(path: str) -> str:
        return os.path.normcase(str(Path(path).resolve()))

    def _manifest_snapshot(self, *, active_entry_id: str | None = None) -> QueueManifest:
        entries = []
        for entry in self.entries:
            state = entry.state if entry.state in {"done", "skipped"} else "queued"
            job_id = entry.job.job_id if entry.job is not None else entry.job_id
            entries.append(QueueItemRecord(
                path=entry.path, state=state, job_id=job_id,
                entry_id=entry.entry_id))
        return QueueManifest(entries=entries, active_entry_id=active_entry_id)

    def _persist_queue(self, *, active_entry_id: str | None = None) -> bool:
        """Save the current manifest; leave in-memory ownership to the caller."""
        try:
            if self.entries:
                self.queue_store.save(self._manifest_snapshot(
                    active_entry_id=active_entry_id))
            else:
                self.queue_store.clear()
        except (OSError, QueueStoreError, ValueError) as exc:
            message = f"Không thể lưu hàng đợi: {exc}"
            self.status.setText(message)
            error_box(self, "Không thể lưu hàng đợi", message)
            return False
        self._active_entry_id = active_entry_id
        return True

    def _all_resolved(self) -> bool:
        return all(entry.state in {"done", "skipped"} for entry in self.entries)

    def _first_unresolved(self, start: int = 0) -> int | None:
        return next((index for index in range(max(0, start), len(self.entries))
                     if self.entries[index].state not in {"done", "skipped"}), None)

    def _finalize_if_resolved(self) -> bool:
        if not self._all_resolved():
            return True
        try:
            self.queue_store.clear()
        except (OSError, QueueStoreError, ValueError) as exc:
            self._needs_finalize = True
            self._blocked = True
            message = f"Không thể dọn hàng đợi đã hoàn tất: {exc}"
            self.status.setText(message)
            error_box(self, "Không thể hoàn tất hàng đợi", message)
            return False
        self._active_entry_id = None
        self._needs_finalize = False
        self._all_finished = True
        return True

    def _restore_manifest(self, manifest: QueueManifest) -> None:
        """Rebuild only manifest-linked jobs; never enumerate the jobs root."""
        active_index: int | None = None
        for item in manifest.entries:
            entry = QueueEntry(path=item.path, entry_id=item.entry_id,
                               state=item.state, job_id=item.job_id)
            if item.state == "skipped":
                entry.state = "skipped"
            elif item.job_id:
                inspection = inspect_job(
                    self.job_store, item.job_id, sub_mode=self.sub_mode)
                entry.inspection = inspection
                if inspection.damaged or inspection.project is None:
                    entry.state = "failed"
                    entry.blocked_reason = inspection.blocked_reason or "Job hỏng hoặc không thể đọc."
                    entry.message = entry.blocked_reason
                else:
                    try:
                        record = None if inspection.legacy else self.job_store.load(item.job_id)
                    except (JobRecordError, OSError, ValueError) as exc:
                        entry.state = "failed"
                        entry.blocked_reason = f"Không thể đọc trạng thái job: {exc}"
                        entry.message = entry.blocked_reason
                    else:
                        entry.progress = int(record.progress) if record else 0
                        saved_status = record.status if record else inspection.display_status
                        entry.job = Job(
                            job_id=item.job_id, project=inspection.project,
                            status=REVIEW if inspection.can_open_review else saved_status,
                            resume_from=(inspection.review_resume_from if inspection.can_open_review
                                         else inspection.resume_from))
                        if saved_status == DONE:
                            entry.state = "done"
                            entry.progress = 100
                            entry.message = "Job đã hoàn tất; hàng đợi sẽ đối chiếu trạng thái."
                        elif inspection.pending_review:
                            entry.state = "review" if self._review_checkpoint_valid(
                                inspection, record) else "interrupted"
                            entry.message = ("Đang chờ duyệt." if entry.state == "review"
                                             else "Checkpoint duyệt không còn hợp lệ; cần dựng lại.")
                        elif saved_status == PAUSED:
                            entry.state = "paused"
                            entry.message = "Job đã tạm dừng; cần xác nhận tiếp tục."
                        elif saved_status == FAILED:
                            entry.state = "failed"
                            entry.message = record.last_error or "Job thất bại; cần xác nhận chạy lại."
                        elif saved_status == CANCELLED:
                            entry.state = "cancelled"
                            entry.message = "Job đã hủy; cần xác nhận tiếp tục."
                        elif saved_status in {RUNNING, "interrupted"}:
                            entry.state = "interrupted"
                            entry.message = "Ứng dụng đã đóng khi job đang chạy."
                        else:
                            entry.state = "queued"
                            entry.message = "Job chưa bắt đầu."
                        if inspection.blocked_reason:
                            entry.blocked_reason = inspection.blocked_reason
                            entry.message = inspection.blocked_reason
            if item.entry_id == manifest.active_entry_id:
                active_index = len(self.entries)
            self.entries.append(entry)

        self._active_entry_id = manifest.active_entry_id
        if active_index is None:
            active_index = next((index for index, entry in enumerate(self.entries)
                                 if (entry.blocked_reason
                                     or (entry.job is not None
                                         and entry.state not in {"done", "skipped", "queued"}))
                                 and entry.state not in {"done", "skipped"}), None)
            if active_index is not None:
                self._active_entry_id = self.entries[active_index].entry_id

        self._refresh_table()
        if not self.entries:
            return
        if self._all_resolved():
            if not self._finalize_if_resolved():
                return
            self.status.setText("Hàng đợi đã hoàn tất.")
            return
        self._restored_unfinished = True
        if active_index is not None:
            self._current_index = active_index
            entry = self.entries[active_index]
            self._started = True
            self._blocked = True
            self._queue_active = False
            if (entry.job is not None and entry.job.status == DONE
                    and any(candidate.state not in {"done", "skipped"}
                            for candidate in self.entries[active_index + 1:])):
                entry.state = "done"
                entry.progress = 100
                entry.message = "Job đã hoàn tất. Chọn tiếp tục để ghi nhận và chạy video tiếp theo."
                self._needs_done_reconcile = True
            elif entry.blocked_reason:
                self.status.setText(entry.blocked_reason)
            else:
                self.status.setText(
                    f"Đã khôi phục video {active_index + 1}/{len(self.entries)} · "
                    f"{Path(entry.path).name}. Chọn Tiếp tục hoặc Bỏ qua.")
            self.table.selectRow(active_index)
            self._update_entry(active_index)
            return
        self.status.setText(
            "Đã khôi phục danh sách hàng đợi. Bấm Bắt đầu để tiếp tục xử lý.")

    @staticmethod
    def _review_checkpoint_valid(inspection: JobInspection,
                                 record: JobRecord | None = None) -> bool:
        return inspection.can_open_review

    def add_files(self) -> None:
        if self._started or self._restored_unfinished:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Thêm video vào hàng đợi", "", VIDEO_FILTER)
        if not paths:
            return
        known = {self._path_key(entry.path) for entry in self.entries}
        before = list(self.entries)
        added = 0
        rejected: list[str] = []
        for raw_path in paths:
            path = str(Path(raw_path).expanduser().resolve())
            if not Path(path).is_file():
                rejected.append(Path(path).name or path)
                continue
            key = self._path_key(path)
            if key in known:
                continue
            known.add(key)
            record = QueueItemRecord(path=path)
            self.entries.append(QueueEntry(path=path, entry_id=record.entry_id))
            added += 1
        if added and not self._persist_queue(active_entry_id=self._active_entry_id):
            self.entries = before
            self._refresh_table()
            self._update_controls()
            return
        self._refresh_table()
        self._update_controls()
        self.status.setText(f"Đã thêm {added} video. Thứ tự có thể đổi trước khi chạy.")
        if rejected:
            info_box(self, "Một số tệp không hợp lệ",
                     "Không thêm được các tệp này:\n" + "\n".join(rejected[:8]))

    def remove_selected(self) -> None:
        if self._started or self._restored_unfinished:
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()},
                      reverse=True)
        before = list(self.entries)
        for row in rows:
            if 0 <= row < len(self.entries):
                self.entries.pop(row)
        if self.entries != before and not self._persist_queue(
                active_entry_id=self._active_entry_id):
            self.entries = before
            self._refresh_table()
            self._update_controls()
            return
        self._refresh_table()
        self._update_controls()

    def move_selected(self, delta: int) -> None:
        if self._started or self._restored_unfinished:
            return
        selected = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not selected:
            return
        if selected != list(range(selected[0], selected[-1] + 1)):
            return
        before = list(self.entries)
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
        if self.entries != before and not self._persist_queue(
                active_entry_id=self._active_entry_id):
            self.entries = before
            self._refresh_table()
            for row in selected:
                self.table.selectRow(row)
            self._update_controls()
            return
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
            "interrupted": "Bị gián đoạn",
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
                 UI_COLORS["primary"] if entry.state in {
                     "running", "review", "paused", "interrupted"} else
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
        next_index = self._first_unresolved()
        if next_index is None:
            self._finalize_if_resolved()
            return
        active_id = self.entries[next_index].entry_id
        if not self._persist_queue(active_entry_id=active_id):
            return
        self._started = True
        self._queue_active = True
        self._blocked = False
        self._current_index = next_index
        self.status.setText(
            "Hàng đợi chạy lần lượt. Duyệt, lỗi hoặc tạm dừng sẽ giữ tại video hiện tại.")
        self._update_controls()
        self._run_next()

    def _run_next(self) -> None:
        if not self._queue_active:
            return
        next_index = self._first_unresolved()
        if next_index is None:
            self._queue_active = False
            if self._all_resolved() and not self._finalize_if_resolved():
                self._current_index = None
                self._blocked = True
                self._update_controls()
                return
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

        entry = self.entries[next_index]
        self._current_index = next_index
        if self._active_entry_id != entry.entry_id:
            if not self._persist_queue(active_entry_id=entry.entry_id):
                self._queue_active = False
                self._blocked = True
                self.status.setText(
                    "Không thể lưu video đang hoạt động; chưa chuyển sang video tiếp theo.")
                self._update_controls()
                return
        self.status.setText(
            f"Đang xử lý video {next_index + 1}/{len(self.entries)} · "
            f"{Path(entry.path).name}")
        if entry.blocked_reason:
            self._blocked = True
            self._queue_active = False
            self.status.setText(entry.blocked_reason)
            self._update_entry(next_index)
            self._update_controls()
            return
        if entry.state not in {"queued", "running"}:
            self._queue_active = False
            self._blocked = True
            self.status.setText(entry.message or
                                "Video này cần được tiếp tục hoặc bỏ qua rõ ràng.")
            self.table.selectRow(next_index)
            self._update_entry(next_index)
            self._update_controls()
            return
        if not Path(entry.path).is_file():
            entry.state = "failed"
            entry.message = "Tệp video không còn tồn tại hoặc không đọc được."
            self._blocked = True
            self._queue_active = False
            self.status.setText(f"Không tìm thấy tệp: {entry.path}")
            self._update_entry(next_index)
            self._update_controls()
            return
        if entry.job is None:
            if entry.job_id:
                self._blocked = True
                self._queue_active = False
                self.status.setText(entry.message or "Job đã lưu nhưng không thể mở.")
                self._update_controls()
                return
            try:
                entry.job = self.main_window.create_batch_job(entry.path)
                entry.job_id = entry.job.job_id
            except Exception as exc:  # noqa: BLE001 - job creation error is item-scoped
                entry.state = "failed"
                entry.message = str(exc)
                self._blocked = True
                self._queue_active = False
                self.status.setText(
                    f"Không thể tạo job cho {Path(entry.path).name}: {exc}")
                self._update_entry(next_index)
                self._update_controls()
                return
            # Job metadata is saved by create_batch_job(); link its ID before
            # launching so a restart can find this active job.
            if not self._persist_queue(active_entry_id=entry.entry_id):
                self._blocked = True
                self._queue_active = False
                entry.state = "queued"
                entry.message = "Job đã tạo nhưng liên kết hàng đợi chưa lưu được."
                self.status.setText(entry.message)
                self._update_entry(next_index)
                self._update_controls()
                return
        entry.state = "running"
        if entry.progress == 0:
            entry.message = "Đang khởi tạo job"
        self._blocked = False
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
            self._mark_done(self._current_index)
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

    def _mark_done(self, index: int) -> None:
        """Persist completion before making a later item eligible to run."""
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        entry.state = "done"
        entry.progress = 100
        entry.message = "Đã tạo video đầu ra."
        next_index = self._first_unresolved(index + 1)
        next_entry = (self.entries[next_index] if next_index is not None else None)
        active_id = next_entry.entry_id if next_entry else None
        if not self._persist_queue(active_entry_id=active_id):
            # JobStore has already saved DONE. Keep this in-memory resolution
            # and block until the queue manifest can be reconciled.
            self._needs_done_reconcile = True
            self._blocked = True
            self._queue_active = False
            entry.message = "Job đã xong; chưa lưu được hàng đợi. Bấm tiếp tục để đối chiếu."
            self._update_entry(index)
            return
        self._needs_done_reconcile = False
        if self._all_resolved():
            self._finalize_if_resolved()
        self._update_entry(index)

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
            if entry.state != "done":
                self._mark_done(self._current_index)
            if self._needs_done_reconcile or self._needs_finalize:
                self._queue_active = False
                self._blocked = True
                self.status.setText(entry.message)
                self._update_entry(self._current_index)
                self._update_controls()
                self.show()
                self.raise_()
                return
            self._current_index = None
            self._active_job = None
            if self._all_resolved():
                self._queue_active = False
                self._update_controls()
                self.show()
                self.raise_()
                return
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
        if self._progress_window is not None:
            return
        if self._needs_finalize:
            if self._finalize_if_resolved():
                self._blocked = False
                self._update_controls()
                self.status.setText("Hàng đợi đã hoàn tất.")
            return
        if not self._blocked or self._current_index is None:
            return
        if self._needs_done_reconcile:
            current_index = self._current_index
            next_index = self._first_unresolved(current_index + 1)
            next_entry = (self.entries[next_index] if next_index is not None else None)
            active_id = next_entry.entry_id if next_entry else None
            if not self._persist_queue(active_entry_id=active_id):
                return
            self._needs_done_reconcile = False
            self._blocked = False
            self._current_index = None
            self._active_job = None
            if self._all_resolved():
                if not self._finalize_if_resolved():
                    self._current_index = current_index
                    self._update_controls()
                    return
                self.status.setText("Hàng đợi đã hoàn tất.")
                self._update_controls()
                return
            if next_entry is not None and next_entry.state != "queued":
                self._current_index = next_index
                self._active_job = next_entry.job
                self._blocked = True
                self.status.setText(next_entry.message or
                                    "Video tiếp theo cần được tiếp tục hoặc bỏ qua.")
                self._update_entry(next_index)
                self._update_controls()
                return
            # This click is the explicit user instruction to advance after
            # recovering a job whose DONE record outlived its queue write.
            self._queue_active = True
            self._update_controls()
            self._run_next()
            return
        entry = self.entries[self._current_index]
        if entry.job is None:
            if entry.blocked_reason and entry.job_id:
                self.status.setText(entry.blocked_reason)
                return
            if not Path(entry.path).is_file():
                entry.blocked_reason = "Tệp video không còn tồn tại hoặc không đọc được."
                entry.message = entry.blocked_reason
                self.status.setText(entry.blocked_reason)
                self._update_entry(self._current_index)
                self._update_controls()
                return
            if not self.main_window._validate_provider_choice(parent=self):
                return
            entry.blocked_reason = None
            entry.state = "queued"
            self._queue_active = True
            self._blocked = False
            self._run_next()
            return

        inspection = entry.inspection
        review_record: JobRecord | None = None
        if entry.job_id:
            inspection = inspect_job(
                self.job_store, entry.job_id, sub_mode=self.sub_mode)
            entry.inspection = inspection
            if inspection.damaged or inspection.project is None:
                entry.blocked_reason = (inspection.blocked_reason or
                                        "Job hỏng hoặc không thể đọc.")
                entry.message = entry.blocked_reason
                self.status.setText(entry.blocked_reason)
                self._update_entry(self._current_index)
                self._update_controls()
                return
            entry.job.project = inspection.project
            entry.job.resume_from = inspection.resume_from
            entry.blocked_reason = (inspection.blocked_reason
                                    if not inspection.source_changed else None)
            try:
                review_record = None if inspection.legacy else self.job_store.load(entry.job_id)
            except (JobRecordError, OSError, ValueError) as exc:
                entry.blocked_reason = f"Không thể đọc trạng thái job: {exc}"
                self.status.setText(entry.blocked_reason)
                self._update_controls()
                return
            entry.job.status = review_record.status if review_record else "idle"
        if entry.blocked_reason or (inspection and inspection.blocked_reason
                                    and not inspection.source_changed):
            message = entry.blocked_reason or inspection.blocked_reason
            self.status.setText(message or "Không thể tiếp tục job này.")
            return
        show_review = (inspection.can_open_review if inspection is not None
                       else entry.job.status == REVIEW)
        if show_review:
            entry.job.status = REVIEW
            if inspection:
                entry.job.resume_from = inspection.review_resume_from
        if inspection and inspection.rebuild_steps and not show_review:
            first = inspection.resume_from or inspection.rebuild_steps[0]
            labels = ", ".join(STEP_LABEL.get(step, step)
                               for step in inspection.rebuild_steps)
            if inspection.source_changed:
                source_note = ("Link nguồn đã thay đổi." if
                               entry.job.project.video_source == "url" else
                               "Tệp nguồn đã thay đổi.")
                explanation = (f"{source_note} Chạy lại từ {STEP_LABEL.get(first, first)} "
                               f"và dựng lại: {labels}.")
            else:
                explanation = (f"Checkpoint hợp lệ kết thúc trước {STEP_LABEL.get(first, first)}. "
                               f"Các bước sẽ chạy lại: {labels}.")
            if not confirm_box(self, "Xác nhận tiếp tục job", explanation):
                return
            if inspection.source_changed and entry.job.project.video_source == "url":
                entry.job.force_fetch = True
            entry.job.resume_from = first

        if entry.job.status == REVIEW and not show_review:
            # A stale review checkpoint must be rebuilt from the earliest
            # invalid stage; Orchestrator will stop at review again.
            entry.job.resume_from = (inspection.resume_from if inspection
                                     else entry.job.resume_from)
            entry.job.status = "idle"
        if not self._persist_queue(active_entry_id=entry.entry_id):
            return
        self._blocked = False
        self._queue_active = True
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
        current_index = self._current_index
        entry = self.entries[current_index]
        old_state, old_message = entry.state, entry.message
        entry.state = "skipped"
        entry.message = f"Bỏ qua sau trạng thái {entry.job.status if entry.job else 'lỗi khởi tạo'}."
        next_index = self._first_unresolved(current_index + 1)
        next_entry = (self.entries[next_index] if next_index is not None else None)
        active_id = next_entry.entry_id if next_entry else None
        if not self._persist_queue(active_entry_id=active_id):
            entry.state, entry.message = old_state, old_message
            self._blocked = True
            self._queue_active = False
            self._update_entry(current_index)
            self._update_controls()
            return
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
        editable = not self._started and not self._restored_unfinished
        self.btn_add.setEnabled(editable)
        self.btn_remove.setEnabled(editable and bool(self.table.selectedItems()))
        self.btn_up.setEnabled(editable and bool(self.table.selectedItems()))
        self.btn_down.setEnabled(editable and bool(self.table.selectedItems()))
        self.btn_start.setEnabled(not self._started and bool(self.entries))
        can_act = (self._blocked and self._current_index is not None
                   and self._progress_window is None)
        can_resume = can_act or self._needs_finalize
        if can_resume and self._current_index is not None and not (
                self._needs_done_reconcile or self._needs_finalize):
            current = self.entries[self._current_index]
            if current.blocked_reason or (
                    current.job is None and not Path(current.path).is_file()):
                can_resume = False
        self.btn_resume.setEnabled(can_resume)
        if self._needs_done_reconcile:
            self.btn_resume.setText("Ghi nhận hoàn tất và tiếp tục")
        elif self._needs_finalize:
            self.btn_resume.setText("Hoàn tất dọn hàng đợi")
        elif can_act and self._current_index is not None:
            current = self.entries[self._current_index]
            self.btn_resume.setText(
                "Mở lại bước duyệt" if current.state == "review"
                else "Tiếp tục video này")
        self.btn_skip.setEnabled(can_act and not (
            self._needs_done_reconcile or self._needs_finalize))
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
                    "Job hiện tại và các video còn chờ sẽ được lưu để khôi phục "
                    "khi mở lại hàng đợi."):
                return
            active_id = (self.entries[self._current_index].entry_id
                         if self._current_index is not None else self._active_entry_id)
            if not self._persist_queue(active_entry_id=active_id):
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
