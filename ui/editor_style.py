"""Editor controls using the same light surfaces as the rest of the app."""

from ui.theme import control_states, render_stylesheet

EDITOR_STYLESHEET = render_stylesheet("""
QWidget#editorRoot {
    background: @canvas@;
    color: @text@;
}
QWidget#editorRoot QWidget {
    color: @text@;
    font-size: @type-body@;
}
QWidget#editorRoot QLabel {
    background: transparent;
}
QWidget#editorRoot QLabel#editorEyebrow {
    color: @secondary_text@;
    font-size: @type-caption@;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorTitle {
    color: @text@;
    font-size: @type-title@;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorProject {
    color: @secondary_text@;
    font-size: @type-caption@;
}
QWidget#editorRoot QLabel#editorSection {
    color: @text@;
    font-size: @type-body@;
    font-weight: 700;
}
QWidget#editorRoot QLabel#editorHint,
QWidget#editorRoot QLabel[role="secondary"] {
    color: @secondary_text@;
    font-size: @type-caption@;
}
QWidget#editorRoot QLabel#editorSyncNotice {
    color: @warning@;
    background: @control@;
    border: 1px solid @border@;
    border-radius: 8px;
    padding: 7px 9px;
    font-size: @type-caption@;
}
QWidget#editorRoot QLabel#editorTime {
    color: @text@;
    font-size: @type-caption@;
    font-weight: 600;
}
QWidget#editorRoot QLabel#editorBadge {
    color: @primary@;
    background: @selection@;
    border: 1px solid @border@;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: @type-caption@;
    font-weight: 600;
}
QWidget#editorRoot QLabel#editorMark {
    color: @primary@;
    background: @selection@;
    border-radius: 10px;
    font-size: @type-body@;
    font-weight: 800;
}
QWidget#editorRoot QFrame#editorCard,
QWidget#editorRoot QWidget#editorCard {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QWidget#editorRoot QFrame#editorToolbar {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QWidget#editorRoot QGraphicsView {
    background: @media@;
    border: 1px solid @border@;
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
    background: @canvas@;
    width: 10px;
    height: 10px;
}
QWidget#editorRoot QPushButton {
    color: @text@;
    background: @control@;
    border: 1px solid @border@;
    border-radius: @layout-control_radius@;
    padding: 7px 12px;
    min-height: 22px;
    font-weight: 600;
}
QWidget#editorRoot QPushButton:hover {
    background: @control_hover@;
    border-color: @border_hover@;
}
QWidget#editorRoot QPushButton:pressed {
    background: @control_pressed@;
}
QWidget#editorRoot QPushButton:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
    border-color: @disabled_surface@;
}
QWidget#editorRoot QPushButton[role="primary"] {
    color: @control@;
    background: @primary@;
    border-color: @primary@;
    font-weight: 600;
}
QWidget#editorRoot QPushButton[role="primary"]:hover {
    background: @primary_hover@;
    border-color: @primary_hover@;
}
QWidget#editorRoot QPushButton[role="primary"]:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
    border-color: @disabled_surface@;
}
QWidget#editorRoot QPushButton[role="quiet"] {
    background: @control@;
    border-color: @border@;
}
QWidget#editorRoot QPushButton[role="danger"] {
    color: @danger@;
    background: @control@;
    border-color: @danger@;
}
QWidget#editorRoot QLineEdit,
QWidget#editorRoot QPlainTextEdit,
QWidget#editorRoot QDoubleSpinBox,
QWidget#editorRoot QComboBox,
QWidget#editorRoot QListWidget {
    color: @text@;
    background: @control@;
    border: 1px solid @border@;
    border-radius: @layout-control_radius@;
    padding: 7px 9px;
    selection-background-color: @selection@;
    selection-color: @text@;
}
QWidget#editorRoot QLineEdit:focus,
QWidget#editorRoot QPlainTextEdit:focus,
QWidget#editorRoot QDoubleSpinBox:focus,
QWidget#editorRoot QComboBox:focus,
QWidget#editorRoot QListWidget:focus {
    border-color: @primary@;
}
QWidget#editorRoot QListWidget::item {
    border-radius: 6px;
    margin: 2px;
    padding: 7px 5px;
}
QWidget#editorRoot QListWidget::item:selected {
    background: @selection@;
    color: @text@;
}
QWidget#editorRoot QTabWidget::pane {
    border: none;
    background: transparent;
}
QWidget#editorRoot QTabBar::tab {
    color: @secondary_text@;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    min-width: 68px;
}
QWidget#editorRoot QTabBar::tab:selected {
    color: @primary@;
    border-bottom-color: @primary@;
}
QWidget#editorRoot QSlider::groove:horizontal {
    height: 4px;
    background: @disabled_surface@;
    border-radius: 2px;
}
QWidget#editorRoot QSlider::sub-page:horizontal {
    background: @primary@;
    border-radius: 2px;
}
QWidget#editorRoot QSlider::handle:horizontal {
    background: @control@;
    border: 2px solid @primary@;
    width: 13px;
    margin: -6px 0;
    border-radius: @layout-control_radius@;
}
QWidget#editorRoot QScrollBar:vertical,
QWidget#editorRoot QScrollBar:horizontal {
    background: transparent;
    width: 10px;
    height: 10px;
}
QWidget#editorRoot QScrollBar::handle:vertical,
QWidget#editorRoot QScrollBar::handle:horizontal {
    background: @border_hover@;
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
    background: @control@;
    color: @text@;
    border: 1px solid @border@;
}

QWidget#editorRoot QPushButton[role="quiet"]:hover {
    background: @control_hover@;
    border-color: @border_hover@;
}
QWidget#editorRoot QPushButton[role="quiet"]:pressed {
    background: @control_pressed@;
}
QWidget#editorRoot QPushButton[role="quiet"]:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
    border-color: @border@;
}

QWidget#editorRoot QPushButton[role="danger"]:hover {
    color: @control@;
    background: @danger_hover@;
    border-color: @danger_hover@;
}
QWidget#editorRoot QTabBar::tab:hover {
    color: @text@;
    background: @control_hover@;
}
QWidget#editorRoot QSlider::handle:horizontal:hover {
    background: @selection@;
}
QWidget#editorRoot QSlider::handle:horizontal:pressed {
    background: @primary_pressed@;
}
QWidget#editorRoot QSlider::handle:horizontal:disabled {
    background: @disabled_surface@;
    border-color: @disabled_text@;
}
QWidget#editorRoot QSlider::sub-page:horizontal:disabled {
    background: @disabled_text@;
}
""" + control_states("QWidget#editorRoot"))
