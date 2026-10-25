"""Visual language for the focused video editing workspace."""

EDITOR_STYLESHEET = """
QWidget#editorRoot {
    background: #0b0e14;
    color: #eef2f8;
}
QWidget#editorRoot QWidget {
    color: #eef2f8;
    font-size: 13px;
}
QWidget#editorRoot QLabel {
    background: transparent;
}
QWidget#editorRoot QLabel#editorEyebrow {
    color: #7f8ca2;
    font-size: 10px;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorTitle {
    color: #f7f9fc;
    font-size: 23px;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorProject {
    color: #9daabe;
    font-size: 12px;
}
QWidget#editorRoot QLabel#editorSection {
    color: #e8eef8;
    font-size: 13px;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorHint,
QWidget#editorRoot QLabel[role="secondary"] {
    color: #91a0b6;
    font-size: 11px;
}
QWidget#editorRoot QLabel#editorTime {
    color: #dfe9fa;
    font-size: 12px;
    font-weight: 600;
}
QWidget#editorRoot QLabel#editorBadge {
    color: #93c5fd;
    background: #17304f;
    border: 1px solid #265078;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}
QWidget#editorRoot QLabel#editorMark {
    color: #071628;
    background: #8cc3ff;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 800;
}
QWidget#editorRoot QFrame#editorCard,
QWidget#editorRoot QWidget#editorCard {
    background: #141a25;
    border: 1px solid #273142;
    border-radius: 15px;
}
QWidget#editorRoot QFrame#editorToolbar {
    background: #111722;
    border: 1px solid #273142;
    border-radius: 12px;
}
QWidget#editorRoot QGraphicsView {
    background: #070a0f;
    border: 1px solid #303c50;
    border-radius: 10px;
}
QWidget#editorRoot QScrollArea {
    background: transparent;
    border: none;
}
QWidget#editorRoot QScrollArea > QWidget > QWidget {
    background: transparent;
}
QWidget#editorRoot QSplitter::handle {
    background: #0b0e14;
    width: 10px;
    height: 10px;
}
QWidget#editorRoot QPushButton {
    color: #e4eaf4;
    background: #202938;
    border: 1px solid #344257;
    border-radius: 9px;
    padding: 7px 12px;
    min-height: 22px;
    font-weight: 600;
}
QWidget#editorRoot QPushButton:hover {
    background: #2a3850;
    border-color: #5276a6;
}
QWidget#editorRoot QPushButton:pressed {
    background: #1a3458;
}
QWidget#editorRoot QPushButton:disabled {
    color: #687588;
    background: #1a2230;
    border-color: #293444;
}
QWidget#editorRoot QPushButton[role="primary"] {
    color: #081421;
    background: #83bcff;
    border-color: #83bcff;
    font-weight: 700;
}
QWidget#editorRoot QPushButton[role="primary"]:hover {
    background: #a8d1ff;
    border-color: #a8d1ff;
}
QWidget#editorRoot QPushButton[role="quiet"] {
    background: transparent;
    border-color: #344257;
}
QWidget#editorRoot QPushButton[role="danger"] {
    color: #ffb9b6;
    background: #382329;
    border-color: #5c333c;
}
QWidget#editorRoot QLineEdit,
QWidget#editorRoot QPlainTextEdit,
QWidget#editorRoot QDoubleSpinBox,
QWidget#editorRoot QComboBox,
QWidget#editorRoot QListWidget {
    color: #e8edf7;
    background: #0f1520;
    border: 1px solid #354257;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #2c5f9a;
    selection-color: #ffffff;
}
QWidget#editorRoot QLineEdit:focus,
QWidget#editorRoot QPlainTextEdit:focus,
QWidget#editorRoot QDoubleSpinBox:focus,
QWidget#editorRoot QComboBox:focus,
QWidget#editorRoot QListWidget:focus {
    border-color: #7cb6ff;
}
QWidget#editorRoot QListWidget::item {
    border-radius: 6px;
    margin: 2px;
    padding: 7px 5px;
}
QWidget#editorRoot QListWidget::item:selected {
    background: #244a79;
    color: #ffffff;
}
QWidget#editorRoot QTabWidget::pane {
    border: none;
    background: transparent;
}
QWidget#editorRoot QTabBar::tab {
    color: #96a5b9;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    min-width: 68px;
}
QWidget#editorRoot QTabBar::tab:selected {
    color: #b8d9ff;
    border-bottom-color: #83bcff;
}
QWidget#editorRoot QSlider::groove:horizontal {
    height: 4px;
    background: #354257;
    border-radius: 2px;
}
QWidget#editorRoot QSlider::sub-page:horizontal {
    background: #83bcff;
    border-radius: 2px;
}
QWidget#editorRoot QSlider::handle:horizontal {
    background: #d6e8ff;
    border: 2px solid #4672a5;
    width: 13px;
    margin: -6px 0;
    border-radius: 8px;
}
QWidget#editorRoot QScrollBar:vertical,
QWidget#editorRoot QScrollBar:horizontal {
    background: #111722;
    width: 10px;
    height: 10px;
}
QWidget#editorRoot QScrollBar::handle:vertical,
QWidget#editorRoot QScrollBar::handle:horizontal {
    background: #3b4b63;
    border-radius: 5px;
    min-height: 30px;
    min-width: 30px;
}
QWidget#editorRoot QScrollBar::add-line,
QWidget#editorRoot QScrollBar::sub-line,
QWidget#editorRoot QScrollBar::add-page,
QWidget#editorRoot QScrollBar::sub-page {
    background: transparent;
    border: none;
}
QWidget#editorRoot QToolTip {
    background: #182231;
    color: #eef2f8;
    border: 1px solid #3b4b63;
}
"""
