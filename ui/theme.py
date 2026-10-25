"""Shared light appearance inspired by Apple's desktop interfaces."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


APPLE_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    color: #1d1d1f;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #f5f5f7;
}
QLabel {
    background: transparent;
}
QLabel#appTitle {
    color: #1d1d1f;
    font-size: 25px;
    font-weight: 650;
}
QLabel#appSubtitle, QLabel[role="secondary"] {
    color: #6e6e73;
}
QLabel#pageTitle {
    color: #1d1d1f;
    font-size: 20px;
    font-weight: 650;
}
QLabel#statusText {
    color: #6e6e73;
    font-size: 12px;
}
QLabel#dropZone {
    background: #ffffff;
    color: #6e6e73;
    border: 1px dashed #c7c7cc;
    border-radius: 14px;
    padding: 20px;
    font-size: 14px;
}
QLabel#dropZone:hover {
    border-color: #007aff;
    color: #007aff;
    background: #fbfdff;
}
QPushButton {
    color: #1d1d1f;
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 9px;
    padding: 7px 14px;
    min-height: 20px;
}
QPushButton:hover {
    background: #f9f9fb;
    border-color: #b8b8be;
}
QPushButton:pressed {
    background: #e9e9ee;
}
QPushButton:disabled {
    color: #8e8e93;
    background: #e5e5ea;
    border-color: #e5e5ea;
}
QPushButton[role="primary"] {
    color: #ffffff;
    background: #007aff;
    border-color: #007aff;
    font-weight: 600;
}
QPushButton[role="primary"]:hover {
    background: #147ce5;
    border-color: #147ce5;
}
QPushButton[role="primary"]:pressed {
    background: #0064d1;
}
QPushButton[role="primary"]:disabled {
    color: #8e8e93;
    background: #d1d1d6;
    border-color: #d1d1d6;
}
QPushButton[role="danger"] {
    color: #ffffff;
    background: #ff3b30;
    border-color: #ff3b30;
}
QPushButton[role="danger"]:hover {
    background: #e73329;
    border-color: #e73329;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox,
QSpinBox, QDoubleSpinBox {
    color: #1d1d1f;
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #007aff;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #007aff;
}
QComboBox::drop-down {
    width: 26px;
    border: none;
}
QComboBox QAbstractItemView {
    color: #1d1d1f;
    background: #ffffff;
    border: 1px solid #d2d2d7;
    selection-background-color: #e8f2ff;
    selection-color: #1d1d1f;
    outline: none;
}
QTabWidget::pane {
    background: transparent;
    border: none;
    top: 0;
}
QTabBar::tab {
    color: #6e6e73;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 14px;
    margin: 2px 3px 8px 0;
}
QTabBar::tab:hover {
    color: #1d1d1f;
    background: #e9e9ee;
}
QTabBar::tab:selected {
    color: #1d1d1f;
    background: #ffffff;
    border-color: #e5e5ea;
}
QGroupBox {
    color: #1d1d1f;
    background: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 13px;
    margin-top: 12px;
    padding: 17px 14px 12px 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 13px;
    padding: 0 5px;
    color: #6e6e73;
    background: #f5f5f7;
    font-size: 12px;
    font-weight: 600;
}
QCheckBox {
    spacing: 8px;
}
QProgressBar {
    color: #1d1d1f;
    background: #e5e5ea;
    border: none;
    border-radius: 5px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: #007aff;
    border-radius: 5px;
}
QTableWidget, QTableView {
    color: #1d1d1f;
    background: #ffffff;
    alternate-background-color: #fafafd;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
    gridline-color: #eeeeF2;
    selection-background-color: #e8f2ff;
    selection-color: #1d1d1f;
    outline: none;
}
QHeaderView::section {
    color: #6e6e73;
    background: #f5f5f7;
    border: none;
    border-bottom: 1px solid #e5e5ea;
    padding: 8px 7px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: #f5f5f7;
    border: none;
}
QScrollBar:vertical {
    width: 10px;
    background: transparent;
    margin: 2px;
}
QScrollBar::handle:vertical {
    min-height: 28px;
    background: #c7c7cc;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}
QToolTip {
    color: #1d1d1f;
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 7px;
    padding: 5px 8px;
}
QMessageBox {
    background: #f5f5f7;
}
"""


def apply_apple_theme(app: QApplication) -> None:
    """Apply a restrained Apple-inspired light theme to the desktop app."""
    app.setStyleSheet(APPLE_STYLESHEET)
    font = app.font()
    # QApplication's platform font resolves to San Francisco on macOS and
    # the platform's native UI font on Windows/Linux.
    font.setPointSize(10)
    app.setFont(font)

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f5f5f7"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#1d1d1f"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#fafafd"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#1d1d1f"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#1d1d1f"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#007aff"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
