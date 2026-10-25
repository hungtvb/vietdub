"""Editor controls using the same light surfaces as the rest of the app."""

from ui.theme import APP_BACKGROUND

EDITOR_STYLESHEET = """
QWidget#editorRoot {
    background: @app-background@;
    color: #1d1d1f;
}
QWidget#editorRoot QWidget {
    color: #1d1d1f;
    font-size: 13px;
}
QWidget#editorRoot QLabel {
    background: transparent;
}
QWidget#editorRoot QLabel#editorEyebrow {
    color: #6e6e73;
    font-size: 10px;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorTitle {
    color: #1d1d1f;
    font-size: 23px;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorProject {
    color: #6e6e73;
    font-size: 12px;
}
QWidget#editorRoot QLabel#editorSection {
    color: #223047;
    font-size: 13px;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorHint,
QWidget#editorRoot QLabel[role="secondary"] {
    color: #6e6e73;
    font-size: 11px;
}
QWidget#editorRoot QLabel#editorTime {
    color: #1d1d1f;
    font-size: 12px;
    font-weight: 600;
}
QWidget#editorRoot QLabel#editorBadge {
    color: #1258a6;
    background: #e8f2ff;
    border: 1px solid #c8e0ff;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}
QWidget#editorRoot QLabel#editorMark {
    color: #1258a6;
    background: #dcecff;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 800;
}
QWidget#editorRoot QFrame#editorCard,
QWidget#editorRoot QWidget#editorCard {
    background: #ffffff;
    border: 1px solid #e1e6ee;
    border-radius: 15px;
}
QWidget#editorRoot QFrame#editorToolbar {
    background: #ffffff;
    border: 1px solid #e1e6ee;
    border-radius: 12px;
}
QWidget#editorRoot QGraphicsView {
    background: #10141c;
    border: 1px solid #e1e6ee;
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
    background: @app-background@;
    width: 10px;
    height: 10px;
}
QWidget#editorRoot QPushButton {
    color: #1d1d1f;
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 9px;
    padding: 7px 12px;
    min-height: 22px;
    font-weight: 600;
}
QWidget#editorRoot QPushButton:hover {
    background: #f9f9fb;
    border-color: #b8b8be;
}
QWidget#editorRoot QPushButton:pressed {
    background: #e9e9ee;
}
QWidget#editorRoot QPushButton:disabled {
    color: #8e8e93;
    background: #e5e5ea;
    border-color: #e5e5ea;
}
QWidget#editorRoot QPushButton[role="primary"] {
    color: #ffffff;
    background: #007aff;
    border-color: #007aff;
    font-weight: 600;
}
QWidget#editorRoot QPushButton[role="primary"]:hover {
    background: #147ce5;
    border-color: #147ce5;
}
QWidget#editorRoot QPushButton[role="primary"]:disabled {
    color: #8e8e93;
    background: #d1d1d6;
    border-color: #d1d1d6;
}
QWidget#editorRoot QPushButton[role="quiet"] {
    background: #ffffff;
    border-color: #d2d2d7;
}
QWidget#editorRoot QPushButton[role="danger"] {
    color: #c73229;
    background: #fff2f1;
    border-color: #ffd3d0;
}
QWidget#editorRoot QLineEdit,
QWidget#editorRoot QPlainTextEdit,
QWidget#editorRoot QDoubleSpinBox,
QWidget#editorRoot QComboBox,
QWidget#editorRoot QListWidget {
    color: #1d1d1f;
    background: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: #e8f2ff;
    selection-color: #1d1d1f;
}
QWidget#editorRoot QLineEdit:focus,
QWidget#editorRoot QPlainTextEdit:focus,
QWidget#editorRoot QDoubleSpinBox:focus,
QWidget#editorRoot QComboBox:focus,
QWidget#editorRoot QListWidget:focus {
    border-color: #007aff;
}
QWidget#editorRoot QListWidget::item {
    border-radius: 6px;
    margin: 2px;
    padding: 7px 5px;
}
QWidget#editorRoot QListWidget::item:selected {
    background: #e8f2ff;
    color: #1d1d1f;
}
QWidget#editorRoot QTabWidget::pane {
    border: none;
    background: transparent;
}
QWidget#editorRoot QTabBar::tab {
    color: #6e6e73;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    min-width: 68px;
}
QWidget#editorRoot QTabBar::tab:selected {
    color: #007aff;
    border-bottom-color: #007aff;
}
QWidget#editorRoot QSlider::groove:horizontal {
    height: 4px;
    background: #d1d1d6;
    border-radius: 2px;
}
QWidget#editorRoot QSlider::sub-page:horizontal {
    background: #007aff;
    border-radius: 2px;
}
QWidget#editorRoot QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #007aff;
    width: 13px;
    margin: -6px 0;
    border-radius: 8px;
}
QWidget#editorRoot QScrollBar:vertical,
QWidget#editorRoot QScrollBar:horizontal {
    background: transparent;
    width: 10px;
    height: 10px;
}
QWidget#editorRoot QScrollBar::handle:vertical,
QWidget#editorRoot QScrollBar::handle:horizontal {
    background: #c7c7cc;
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
    background: #ffffff;
    color: #1d1d1f;
    border: 1px solid #d2d2d7;
}
""".replace("@app-background@", APP_BACKGROUND)
