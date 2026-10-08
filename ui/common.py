# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Helper dùng chung cho các màn hình UI (định dạng, dialog tiếng Việt)."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def fmt_time(sec: float) -> str:
    """Giây -> 'mm:ss' hoặc 'hh:mm:ss'."""
    sec = max(0.0, float(sec or 0))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_size(num_bytes: int) -> str:
    n = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}".replace(",", ".")
        n /= 1024
    return f"{n:.1f} GB"


def error_box(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)


def info_box(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def confirm_box(parent: QWidget | None, title: str, message: str) -> bool:
    # Qt không tự dịch nút Yes/No khi thiếu file QM tiếng Việt -> dùng nút
    # chữ Việt trực tiếp để đạt "tiếng Việt 100%".
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Question)
    btn_yes = box.addButton("Có", QMessageBox.YesRole)
    btn_no = box.addButton("Không", QMessageBox.NoRole)
    box.setDefaultButton(btn_no)
    box.exec()
    return box.clickedButton() == btn_yes


def open_settings_dialog(parent: QWidget | None, settings) -> bool:
    """Mở dialog Cài đặt. Trả về True nếu user bấm Lưu.

    Sau khi lưu: áp lại đường dẫn FFmpeg vào media._bin để luồng tải link
    (DownloadWorker) dùng path mới ngay, không cần restart app.
    """
    from ui.settings_dialog import SettingsDialog
    from media import _bin as mbin
    dlg = SettingsDialog(settings, parent)
    if dlg.exec():
        mbin.configure(settings.get("ffmpeg_path"))
        return True
    return False
