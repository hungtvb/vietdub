# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Lazy, state-aware history and recovery actions for saved jobs."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QBoxLayout, QDialog, QFrame, QHeaderView,
                               QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core.job import REVIEW, Job
from core.job_recovery import JobInspection, discover_jobs, inspect_job
from core.job_store import JobStore
from core.queue_store import QueueStore, QueueStoreError
from core.orchestrator import STEP_LABEL
from core.settings import Settings
from ui.common import confirm_box, error_box, info_box
from ui.theme import UI_COLORS


_STATUS_LABELS = {
    "idle": "Chưa chạy",
    "running": "Đang chạy",
    "interrupted": "Bị gián đoạn",
    "paused": "Đã tạm dừng",
    "review": "Chờ duyệt",
    "done": "Hoàn tất",
    "failed": "Thất bại",
    "cancelled": "Đã hủy",
    "damaged": "Không đọc được",
}


class JobHistoryDialog(QDialog):
    """Show saved jobs and require an explicit choice before recovery."""

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent, Qt.Window)
        self.settings = settings
        self.job_store = JobStore()
        self.queue_store = QueueStore()
        self.inspections: list[JobInspection] = []
        self.resume_job: Job | None = None
        self.resume_from: str | None = None
        self.resume_review = False
        self.restore_queue_requested = False

        self.setWindowTitle("VietDub — Lịch sử công việc")
        self.resize(940, 650)
        self.setMinimumSize(600, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 17, 20, 18)
        root.setSpacing(12)

        title = QLabel("Lịch sử công việc")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Xem các job đã lưu và chọn rõ ràng công việc muốn tiếp tục. "
            "Việc mở lịch sử không chạy model hay thay đổi video.")
        subtitle.setWordWrap(True)
        subtitle.setProperty("role", "secondary")
        root.addWidget(subtitle)

        self.queue_notice = QLabel()
        self.queue_notice.setWordWrap(True)
        self.queue_notice.setTextFormat(Qt.PlainText)
        self.queue_notice.setProperty("role", "secondary")
        self.queue_notice.setStyleSheet(
            f"background: {UI_COLORS['control']}; "
            f"border: 1px solid {UI_COLORS['border']}; "
            "border-radius: 10px; padding: 9px 11px;")
        self.queue_notice.hide()
        root.addWidget(self.queue_notice)

        self.table = QTableWidget(0, 4)
        self.table.setAccessibleName("Lịch sử job VietDub")
        self.table.setHorizontalHeaderLabels(
            ["Nguồn video", "Trạng thái", "Bước cuối", "Cập nhật"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setSortingEnabled(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.table, 1)

        self.detail = QLabel("Chọn một job để xem thông tin và thao tác.")
        self.detail.setObjectName("historyDetail")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.PlainText)
        self.detail.setMinimumHeight(58)
        self.detail.setProperty("role", "secondary")
        self.detail.setStyleSheet(
            f"background: {UI_COLORS['control']}; "
            f"border: 1px solid {UI_COLORS['border']}; "
            "border-radius: 10px; padding: 9px 11px;")
        root.addWidget(self.detail)

        footer = QFrame()
        actions = self.actions = QBoxLayout(QBoxLayout.LeftToRight, footer)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.btn_continue = QPushButton("Tiếp tục / chạy lại")
        self.btn_continue.setProperty("role", "primary")
        self.btn_continue.clicked.connect(self._continue_selected)
        self.btn_open = QPushButton("Mở kết quả / nhật ký")
        self.btn_open.setProperty("role", "secondary")
        self.btn_open.clicked.connect(self._open_selected)
        self.btn_restore = QPushButton("Khôi phục hàng đợi")
        self.btn_restore.setProperty("role", "secondary")
        self.btn_restore.clicked.connect(self._restore_queue)
        self.btn_close = QPushButton("Đóng")
        self.btn_close.setProperty("role", "secondary")
        self.btn_close.clicked.connect(self.reject)
        actions.addWidget(self.btn_continue)
        actions.addWidget(self.btn_open)
        actions.addWidget(self.btn_restore)
        actions.addStretch(1)
        actions.addWidget(self.btn_close)
        root.addWidget(footer)

        self._load_queue_state()
        self._load_history()
        self._selection_changed()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "actions"):
            direction = (QBoxLayout.TopToBottom if self.width() < 760
                         else QBoxLayout.LeftToRight)
            if self.actions.direction() != direction:
                self.actions.setDirection(direction)

    def _load_queue_state(self) -> None:
        """Read only the small queue manifest; history remains lazy."""
        try:
            manifest = self.queue_store.load()
        except (QueueStoreError, OSError, ValueError) as exc:
            corrupt = self.queue_store.path.with_name(
                self.queue_store.path.name + ".corrupt")
            suffix = f" Tệp lỗi được giữ tại: {corrupt}." if corrupt.exists() else ""
            self.queue_notice.setText(
                f"Không đọc được hàng đợi đã lưu: {exc}.{suffix} "
                "Lịch sử job vẫn có thể xem bình thường.")
            self.queue_notice.show()
            self.btn_restore.setEnabled(False)
            return

        corrupt = self.queue_store.path.with_name(
            self.queue_store.path.name + ".corrupt")
        if manifest is not None and manifest.entries:
            self.queue_notice.setText(
                "Có hàng đợi đã lưu. Hãy khôi phục để xem mục đang hoạt động; "
                "queue sẽ không tự chạy khi mở.")
            self.queue_notice.show()
            self.btn_restore.setEnabled(True)
        elif corrupt.exists() or corrupt.is_symlink():
            self.queue_notice.setText(
                f"Một manifest lỗi được giữ tại {corrupt}. "
                "Lịch sử job vẫn dùng được; hãy xử lý tệp này trước khi tạo queue mới.")
            self.queue_notice.show()
            self.btn_restore.setEnabled(False)
        else:
            self.btn_restore.hide()

    def _load_history(self) -> None:
        self.table.setRowCount(0)
        try:
            self.inspections = discover_jobs(
                self.job_store,
                sub_mode=self.settings.get("sub_mode", "burn") or "burn")
        except Exception as exc:  # noqa: BLE001 - history errors are isolated from app startup
            self.inspections = []
            self.detail.setText(f"Không thể đọc lịch sử job: {exc}")
            return

        self.table.setRowCount(len(self.inspections))
        for row, inspection in enumerate(self.inspections):
            source = inspection.source_label or inspection.job_id
            source_item = QTableWidgetItem(source)
            source_item.setToolTip(source)
            source_item.setData(Qt.UserRole, row)
            self.table.setItem(row, 0, source_item)

            status = _STATUS_LABELS.get(inspection.display_status,
                                       inspection.display_status)
            if inspection.source_changed:
                status += " · Nguồn đã đổi"
            status_item = QTableWidgetItem(status)
            status_item.setForeground(
                QColor(UI_COLORS["danger"]) if inspection.damaged
                else QColor(UI_COLORS["warning"]) if inspection.blocked_reason
                else QColor(UI_COLORS["success"]) if inspection.display_status == "done"
                else QColor(UI_COLORS["primary"]))
            status_item.setToolTip(inspection.blocked_reason or status)
            self.table.setItem(row, 1, status_item)

            stage = STEP_LABEL.get(inspection.last_stage or "", "—")
            stage_item = QTableWidgetItem(stage)
            stage_item.setToolTip(inspection.last_stage or "Chưa có bước hoàn tất")
            self.table.setItem(row, 2, stage_item)
            updated_item = QTableWidgetItem(self._format_timestamp(
                inspection.updated_at))
            updated_item.setToolTip(inspection.updated_at or "")
            self.table.setItem(row, 3, updated_item)

        self.table.resizeRowsToContents()
        if self.inspections:
            self.table.selectRow(0)
        else:
            self.detail.setText("Chưa có job nào được lưu trên thiết bị này.")

    @staticmethod
    def _format_timestamp(value: str | None) -> str:
        if not value:
            return "—"
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError):
            return value

    def _selected_inspection(self) -> JobInspection | None:
        row = self.table.currentRow()
        return self.inspections[row] if 0 <= row < len(self.inspections) else None

    @staticmethod
    def _valid_review(inspection: JobInspection) -> bool:
        return inspection.can_open_review

    @classmethod
    def _can_continue(cls, inspection: JobInspection) -> bool:
        if (inspection.damaged or inspection.project is None
                or inspection.blocked_reason
                or inspection.display_status == "done"):
            return False
        if cls._valid_review(inspection):
            return True
        return (bool(inspection.resume_from and inspection.rebuild_steps)
                or inspection.resume_from is None and not inspection.rebuild_steps)

    def _selection_changed(self) -> None:
        inspection = self._selected_inspection()
        if inspection is None:
            self.btn_continue.setEnabled(False)
            self.btn_open.setEnabled(False)
            return

        details = [f"Job: {inspection.job_id}"]
        if inspection.blocked_reason:
            details.append(f"Không thể tiếp tục: {inspection.blocked_reason}")
        elif inspection.source_changed:
            details.append("Nguồn đã thay đổi; cần xác nhận chạy lại từ bước lấy video.")
        elif inspection.can_open_review:
            details.append("Mở lại bước duyệt; nội dung đã lưu vẫn chờ bạn xác nhận.")
        elif inspection.rebuild_steps and inspection.resume_from:
            details.append(
                f"Tiếp tục từ {STEP_LABEL.get(inspection.resume_from, inspection.resume_from)}; "
                f"các bước sẽ dựng lại: {', '.join(STEP_LABEL.get(s, s) for s in inspection.rebuild_steps)}.")
        elif (inspection.display_status != "done"
              and inspection.resume_from is None
              and not inspection.blocked_reason):
            details.append(
                "Các checkpoint đều hợp lệ; không cần chạy lại bước nào. "
                "Bạn có thể xác nhận để ghi nhận job hoàn tất.")
        elif inspection.display_status == "done":
            details.append("Job đã hoàn tất. Có thể mở video đầu ra hoặc nhật ký.")
        if inspection.legacy:
            details.append("Job cũ chưa có metadata; trạng thái được suy ra từ project và checkpoint.")
        self.detail.setText("\n".join(details))

        self.btn_continue.setEnabled(self._can_continue(inspection))
        self.btn_continue.setText("Mở lại bước duyệt" if inspection.can_open_review
                                  else "Tiếp tục / chạy lại")
        output_exists = bool(inspection.output_path and
                             inspection.output_path.is_file())
        log_exists = bool(inspection.run_log_path and
                          inspection.run_log_path.is_file())
        self.btn_open.setEnabled(output_exists or log_exists)

    def _continue_selected(self) -> None:
        inspection = self._selected_inspection()
        if inspection is None:
            return
        inspection = inspect_job(self.job_store, inspection.job_id,
                                 sub_mode=self.settings.get("sub_mode", "burn"))
        if not self._can_continue(inspection):
            error_box(self, "Không thể tiếp tục", inspection.blocked_reason or
                      "Trạng thái job đã thay đổi. Hãy mở lại lịch sử.")
            return

        show_review = self._valid_review(inspection)
        if inspection.source_changed:
            first = "fetch"
            rebuild = inspection.rebuild_steps
            source_kind = ("link nguồn" if inspection.project and
                           inspection.project.video_source == "url" else "tệp nguồn")
            explanation = (f"{source_kind.capitalize()} đã thay đổi. Job sẽ chạy lại từ "
                           f"{STEP_LABEL['fetch']} và dựng lại các bước: "
                           f"{', '.join(STEP_LABEL.get(step, step) for step in rebuild)}.")
            if not confirm_box(self, "Xác nhận khởi động lại từ video nguồn",
                               explanation):
                return
        elif not show_review:
            first = inspection.resume_from
            rebuild = inspection.rebuild_steps
            if first:
                explanation = (
                    f"Job sẽ tiếp tục từ {STEP_LABEL.get(first, first)}. "
                    f"Các bước sẽ chạy lại: "
                    f"{', '.join(STEP_LABEL.get(step, step) for step in rebuild)}.")
            else:
                explanation = (
                    "Các checkpoint đều hợp lệ. Xác nhận để đánh dấu job hoàn tất "
                    "mà không chạy lại pipeline.")
            if not confirm_box(self, "Xác nhận tiếp tục job", explanation):
                return
        else:
            first = inspection.review_resume_from

        job = Job(
            job_id=inspection.job_id,
            project=inspection.project,
            status=REVIEW if show_review else "idle",
            resume_from=first)
        if inspection.source_changed and job.project.video_source == "url":
            # This flag is intentionally set only after the explicit prompt.
            job.force_fetch = True
        self.resume_job = job
        self.resume_from = first
        self.resume_review = show_review
        self.accept()

    def _open_selected(self) -> None:
        inspection = self._selected_inspection()
        if inspection is None:
            return
        path = None
        if inspection.display_status == "done" and inspection.output_path:
            if inspection.output_path.is_file():
                path = inspection.output_path
        if path is None and inspection.run_log_path:
            if inspection.run_log_path.is_file():
                path = inspection.run_log_path
        if path is None:
            info_box(self, "Không tìm thấy kết quả",
                     "Không có video đầu ra hoặc nhật ký cho job này.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            error_box(self, "Không mở được tệp",
                      f"Không mở được tệp này:\n{path}")

    def _restore_queue(self) -> None:
        if not self.btn_restore.isEnabled():
            return
        self.restore_queue_requested = True
        self.accept()
