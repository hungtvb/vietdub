# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Màn 2 - Đang xử lý: chạy Orchestrator trong QThread, UI nhận signal.

- Thanh tiến trình tổng 9 bước + % bước hiện tại, log realtime cuộn được.
- Nút [Tạm dừng] / [Tiếp tục] / [Hủy] có tác dụng thật (cờ pause_requested /
  cancel_requested của Job, orchestrator dừng GIỮA các bước, checkpoint
  giữ nguyên nên chạy tiếp được từ bước dở).
- Tới điểm dừng duyệt (REVIEW) -> tự mở Màn 3/4; xong duyệt quay lại đây
  chạy tiếp từ đúng bước resume.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core.job import CANCELLED, DONE, FAILED, PAUSED, REVIEW, Job
from core.orchestrator import STEP_LABEL, STEPS, Orchestrator
from core.settings import Settings
from ui.common import confirm_box, error_box, info_box

MAX_LOG_LINES = 2000


class JobRunner(QObject):
    """Chạy orchestrator.run() trong thread riêng. Signal an toàn giữa thread."""
    progressed = Signal(str, float, str)  # step, pct, msg
    logged = Signal(str)                  # 1 dòng log
    finished = Signal(str)                # DONE/REVIEW/FAILED/PAUSED/CANCELLED

    def __init__(self, job: Job, settings: Settings,
                 resume_from: Optional[str] = None):
        super().__init__()
        self.job = job
        self.settings = settings
        self.resume_from = resume_from
        self.orch: Orchestrator | None = None

    def run(self) -> None:
        job = self.job
        job.progress_cb = lambda s, p, m: self.progressed.emit(s, p, m)
        job.log_cb = lambda line: self.logged.emit(line)
        self.orch = Orchestrator(job, self.settings)
        result = self.orch.run(resume_from=self.resume_from)
        self.finished.emit(result)

    def last_error(self) -> str:
        return (self.orch.last_error or "") if self.orch else ""


class ProgressWindow(QWidget):
    """Màn 2. on_close(): quay về màn chính (video khác / đóng job)."""

    def __init__(self, job: Job, settings: Settings,
                 on_close: Callable[[], None]):
        super().__init__()
        self.job = job
        self.settings = settings
        self.on_close = on_close
        self.setWindowTitle(f"VietDub — Đang xử lý: {job.project.name}")
        self.resize(680, 620)

        self._thread: QThread | None = None
        self._runner: JobRunner | None = None
        self._running = False
        self._review_win = None
        self._finish_win = None

        root = QVBoxLayout(self)
        self.lbl_title = QLabel(f"Đang xử lý: {job.project.name}")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(self.lbl_title)

        self.lbl_step = QLabel("Chuẩn bị…")
        root.addWidget(self.lbl_step)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        root.addWidget(self.bar)

        self.tbl = QTableWidget(len(STEPS), 2)
        self.tbl.setHorizontalHeaderLabels(["Bước", "Trạng thái"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setSelectionMode(QTableWidget.NoSelection)
        for i, step in enumerate(STEPS):
            self.tbl.setItem(i, 0, QTableWidgetItem(STEP_LABEL[step]))
            self.tbl.setItem(i, 1, QTableWidgetItem("Chờ"))
        self.tbl.setColumnWidth(0, 420)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setMaximumHeight(250)
        root.addWidget(self.tbl)

        root.addWidget(QLabel("Nhật ký chạy:"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_LINES)
        root.addWidget(self.log_view, 1)

        row = QHBoxLayout()
        self.btn_pause = QPushButton("Tạm dừng")
        self.btn_pause.clicked.connect(self.pause)
        self.btn_resume = QPushButton("Tiếp tục")
        self.btn_resume.clicked.connect(lambda: self.begin())
        self.btn_resume.setEnabled(False)
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_settings = QPushButton("Cài đặt")
        self.btn_settings.clicked.connect(self.open_settings)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_resume)
        row.addWidget(self.btn_cancel)
        row.addStretch(1)
        row.addWidget(self.btn_settings)
        root.addLayout(row)

    # ------------------------------------------------------------------ chạy
    def begin(self, resume_from: Optional[str] = None) -> None:
        """Bắt đầu (hoặc chạy tiếp) job trong thread mới."""
        if self._running:
            return
        self._running = True
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.lbl_step.setText("Đang chạy…")
        self._runner = JobRunner(self.job, self.settings, resume_from)
        thread = QThread(self)
        self._runner.moveToThread(thread)
        self._runner.progressed.connect(self._on_progress)
        self._runner.logged.connect(self._on_log)
        self._runner.finished.connect(self._on_finished)
        thread.started.connect(self._runner.run)
        self._runner.finished.connect(thread.quit)
        # finished của WORKER (phát trong thread khi event loop còn sống) ->
        # deleteLater được xử lý ngay, không leak 1 worker mỗi lần chạy.
        self._runner.finished.connect(self._runner.deleteLater)
        # dọn QThread cũ sau mỗi lần chạy (kể cả [Tiếp tục] nhiều lần).
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def _on_progress(self, step: str, pct: float, msg: str) -> None:
        if step in STEPS:
            idx = STEPS.index(step)
            overall = (idx * 100.0 + max(0.0, min(100.0, pct))) / len(STEPS)
            self.bar.setValue(int(overall))
            self.lbl_step.setText(f"{STEP_LABEL[step]} — {pct:.0f}%")
            status = "Đang chạy" if pct < 100 else "Xong"
            self.tbl.item(idx, 1).setText(status)
            if pct >= 100:
                for j in range(idx):
                    if self.tbl.item(j, 1).text() == "Chờ":
                        self.tbl.item(j, 1).setText("Xong")
        else:
            # pseudo-step: paused / cancelled -> giữ nguyên thanh tiến trình,
            # chỉ cập nhật nhãn (tránh gây hiểu lầm là đã xong 100%).
            self.lbl_step.setText(msg or step)

    def _on_log(self, line: str) -> None:
        self.log_view.appendPlainText(line.rstrip())

    def _on_finished(self, result: str) -> None:
        self._running = False
        if result == REVIEW:
            self._open_review()
        elif result == DONE:
            self._open_finish()
        elif result == PAUSED:
            self.lbl_step.setText("Đã tạm dừng — bấm [Tiếp tục] để chạy tiếp.")
            self.btn_pause.setEnabled(False)
            self.btn_resume.setEnabled(True)
            info_box(self, "Đã tạm dừng",
                     "Job đã tạm dừng. Checkpoint giữ nguyên — bấm [Tiếp tục] "
                     "để chạy tiếp từ bước dở.")
        elif result == CANCELLED:
            self.lbl_step.setText("Đã hủy.")
            self.btn_pause.setEnabled(False)
            self._ask_resume_after_cancel()
        elif result == FAILED:
            self.lbl_step.setText("Thất bại.")
            self.btn_pause.setEnabled(False)
            self._show_failure()

    # ------------------------------------------------------------- điều khiển
    def pause(self) -> None:
        if not self._running:
            return
        self.job.pause_requested = True
        self.btn_pause.setEnabled(False)
        self.lbl_step.setText("Sẽ tạm dừng sau khi bước hiện tại xong…")

    def cancel(self) -> None:
        if not self._running:
            return
        if not confirm_box(self, "Hủy job?",
                           "Hủy job? Bước hiện tại sẽ chạy nốt, checkpoint "
                           "tới bước đã xong được giữ lại — bạn có thể chạy "
                           "tiếp sau."):
            return
        self.job.cancel_requested = True
        self.btn_cancel.setEnabled(False)
        self.lbl_step.setText("Sẽ hủy sau khi bước hiện tại xong…")

    def open_settings(self) -> None:
        from ui.common import open_settings_dialog
        open_settings_dialog(self, self.settings)

    def _ask_resume_after_cancel(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Đã hủy job")
        box.setText("Job đã hủy. Checkpoint tới bước đã xong vẫn còn.")
        btn_resume = box.addButton("Chạy tiếp từ bước dở",
                                   QMessageBox.AcceptRole)
        btn_close = box.addButton("Đóng", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == btn_resume:
            self.begin(resume_from=self.job.resume_from)
        elif box.clickedButton() == btn_close:
            self.close()

    def _show_failure(self) -> None:
        err = (self._runner.last_error() if self._runner else "") or \
            "Không rõ nguyên nhân — xem nhật ký chạy."
        box = QMessageBox(self)
        box.setWindowTitle("Xử lý thất bại")
        box.setText(f"Job thất bại:\n\n{err}\n\nCheckpoint tới bước đã xong "
                    "vẫn còn.")
        btn_retry = box.addButton("Chạy tiếp từ bước lỗi",
                                  QMessageBox.AcceptRole)
        btn_close = box.addButton("Đóng", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == btn_retry:
            self.begin(resume_from=self.job.resume_from)
        elif box.clickedButton() == btn_close:
            self.close()

    # ------------------------------------------------------------- chuyển màn
    def _open_review(self) -> None:
        nxt = self.job.resume_from or ""
        self.hide()
        if nxt == "gender":
            from ui.review_source import ReviewSourceWindow
            self._review_win = ReviewSourceWindow(
                self.job, self.settings,
                on_continue=self._resume_after_review,
                on_back=self._back_from_review)
        else:
            from ui.review_vi import ReviewViWindow
            self._review_win = ReviewViWindow(
                self.job, self.settings,
                on_continue=self._resume_after_review,
                on_back=self._back_from_review)
        self._review_win.show()

    def _resume_after_review(self) -> None:
        if self._review_win:
            self._review_win.close()
            self._review_win = None
        self.show()
        self.begin(resume_from=self.job.resume_from)

    def _back_from_review(self) -> None:
        # Quay lại màn tiến trình mà KHÔNG chạy tiếp (chờ bấm [Tiếp tục]).
        if self._review_win:
            self._review_win.close()
            self._review_win = None
        self.show()
        self.lbl_step.setText("Đã duyệt — bấm [Tiếp tục] để chạy bước tiếp theo.")
        self.btn_resume.setEnabled(True)
        self.btn_pause.setEnabled(False)

    def _open_finish(self) -> None:
        from ui.finish import FinishWindow
        self.hide()
        self._finish_win = FinishWindow(self.job, self.settings,
                                        on_new=self._new_video)
        self._finish_win.show()

    def _new_video(self) -> None:
        if self._finish_win:
            self._finish_win.close()
            self._finish_win = None
        # closeEvent (idle) tự gọi on_close() -> hiện lại màn chính.
        self.close()

    def closeEvent(self, e) -> None:  # noqa: N802
        # ĐANG CHẠY: cấm đóng. QThread là con của window nên đóng window =
        # hủy QThread khi thread còn chạy ("QThread: Destroyed while thread
        # is still running" -> nguy cơ abort/crash). Bảo user tạm dừng/hủy
        # trước rồi mới đóng.
        if self._running:
            info_box(self, "Job đang chạy",
                     "Job đang chạy — không thể đóng cửa sổ lúc này.\n\n"
                     "Hãy bấm [Tạm dừng] hoặc [Hủy] trước rồi đóng.")
            e.ignore()
            return
        # IDLE: đóng = quay về màn hình chính, không quit app im lặng.
        # Nút "Đóng" sau khi hủy cũng đi qua đây -> tự về màn chính.
        self.on_close()
        super().closeEvent(e)
