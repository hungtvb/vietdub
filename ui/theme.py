"""Shared light appearance inspired by Apple's desktop interfaces."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


# Semantic tokens shared by all desktop screens. Large containers use canvas;
# control is reserved for small controls and editable work surfaces.
UI_COLORS: dict[str, str] = {
    "canvas": "#F5F5F7",
    "text": "#1D1D1F",
    "secondary_text": "#515158",
    "primary": "#0066CC",
    "primary_hover": "#005BB5",
    "primary_pressed": "#004C99",
    "border": "#D2D2D7",
    "border_hover": "#A1A1AA",
    "control": "#FFFFFF",
    "control_hover": "#F0F0F4",
    "control_pressed": "#E5E5EA",
    "disabled_text": "#68686F",
    "disabled_surface": "#E5E5EA",
    "selection": "#DCEBFA",
    "alternate": "#FAFAFD",
    "media": "#10141C",
    "media_text": "#C2CCDA",
    "success": "#167347",
    "warning": "#855700",
    "danger": "#B42318",
    "danger_hover": "#9C1C13",
    "danger_pressed": "#80180F",
    "focus": "#0066CC",
}

UI_TYPE: dict[str, int] = {"body": 10, "caption": 9, "section": 11, "title": 18}
UI_LAYOUT: dict[str, int] = {"space_unit": 4, "control_radius": 8, "panel_radius": 12}
APP_BACKGROUND = UI_COLORS["canvas"]


def render_stylesheet(stylesheet: str) -> str:
    """Resolve shared semantic color, typography and layout tokens in Qt QSS."""
    for name, value in UI_COLORS.items():
        stylesheet = stylesheet.replace(f"@{name}@", value)
    for name, value in UI_TYPE.items():
        stylesheet = stylesheet.replace(f"@type-{name}@", f"{value}pt")
    for name, value in UI_LAYOUT.items():
        stylesheet = stylesheet.replace(f"@layout-{name}@", f"{value}px")
    return stylesheet


_CONTROL_STATES = """
QPushButton:focus, QToolButton:focus {
    border: 2px solid @focus@;
}
QPushButton[role="primary"]:focus, QPushButton[role="danger"]:focus {
    border: 2px solid @text@;
}
QPushButton[role="primary"]:pressed {
    background: @primary_pressed@;
    border-color: @primary_pressed@;
}
QPushButton[role="danger"]:pressed {
    color: @control@;
    background: @danger_pressed@;
    border-color: @danger_pressed@;
}
QPushButton[role="danger"]:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
    border-color: @border@;
}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover,
QSpinBox:hover, QDoubleSpinBox:hover, QListWidget:hover {
    border-color: @border_hover@;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QListWidget:focus,
QPlainTextEdit#runLog:focus, QTableView:focus, QTableWidget:focus {
    border: 2px solid @focus@;
}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QListWidget:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
    border-color: @border@;
}
QTableView::item:hover, QTableWidget::item:hover, QListWidget::item:hover {
    background: @control_hover@;
}
QTableView::item:selected, QTableWidget::item:selected, QListWidget::item:selected {
    color: @text@;
    background: @selection@;
}
QTableView::item:focus, QTableWidget::item:focus, QListWidget::item:focus {
    border: 1px solid @focus@;
}
QTabBar::tab:focus {
    border: 2px solid @focus@;
}
QTabBar::tab:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
}
QCheckBox:focus, QRadioButton:focus, QSlider:focus {
    border: 2px solid @focus@;
    border-radius: @layout-control_radius@;
}
QCheckBox:disabled, QRadioButton:disabled {
    color: @disabled_text@;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: @secondary_text@;
}
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {
    background: @text@;
}
"""


def control_states(scope: str = "") -> str:
    """Share state rules while matching a screen's more specific selectors."""
    if not scope:
        return _CONTROL_STATES
    rules = []
    for rule in _CONTROL_STATES.split("}"):
        if "{" not in rule:
            continue
        selectors, declarations = rule.split("{", 1)
        scoped = ",\n".join(f"{scope} {selector.strip()}" for selector in selectors.split(","))
        rules.append(f"{scoped} {{{declarations}}}")
    return "\n".join(rules)


APPLE_STYLESHEET = render_stylesheet("""
QMainWindow, QDialog, QWidget {
    color: @text@;
    font-size: @type-body@;
}
QMainWindow, QDialog {
    background: @canvas@;
}
QLabel {
    background: transparent;
}
QLabel#appTitle {
    color: @text@;
    font-size: @type-title@;
    font-weight: 650;
}
QLabel#appSubtitle, QLabel[role="secondary"] {
    color: @secondary_text@;
}
QWidget#mainShell {
    background: @canvas@;
}
QFrame#mainHeader, QFrame#mainCard, QFrame#mainFooter {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QFrame#mainFooter {
    border-radius: 0;
    border-left: none;
    border-right: none;
    border-bottom: none;
}
QLabel#mainMark {
    background: @selection@;
    color: @primary@;
    border-radius: 10px;
    font-weight: 800;
}
QFrame#mainHero {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QLabel#mainHeroKicker {
    color: @primary@;
    font-size: @type-caption@;
    font-weight: 700;
}
QLabel#mainHeroTitle {
    color: @text@;
    font-size: @type-title@;
    font-weight: 700;
}
QLabel#mainHeroNote {
    color: @secondary_text@;
    font-size: @type-caption@;
}
QLabel#sectionTitle {
    color: @text@;
    font-size: @type-section@;
    font-weight: 700;
}
QLabel#mainSourceStatus {
    color: @secondary_text@;
    font-size: @type-caption@;
}
QFrame#finishCard {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QLabel#finishBadge {
    color: @success@;
    font-size: @type-caption@;
    font-weight: 700;
}
QLabel#finishSection {
    color: @secondary_text@;
    font-size: @type-caption@;
    font-weight: 700;
}
QVideoWidget {
    background: @media@;
    border-radius: 10px;
}
QLabel#finishPoster {
    color: @media_text@;
    background: @media@;
    border-radius: 10px;
    font-size: @type-body@;
}
QFrame#workflowHeader {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QFrame#workflowCard {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QFrame#workflowFooter {
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
}
QLabel#workflowEyebrow, QLabel#workflowSection {
    color: @secondary_text@;
    font-size: @type-caption@;
    font-weight: 700;
}
QPlainTextEdit#runLog {
    color: @text@;
    background: @control@;
    border: 1px solid @border@;
    border-radius: @layout-control_radius@;
    font-family: monospace;
    font-size: @type-caption@;
    padding: 10px;
    selection-background-color: @selection@;
    selection-color: @text@;
}
QLabel#pageTitle {
    color: @text@;
    font-size: @type-title@;
    font-weight: 650;
}
QLabel#statusText {
    color: @secondary_text@;
    font-size: @type-caption@;
}
QLabel#dropZone {
    background: @control@;
    color: @secondary_text@;
    border: 1px dashed @border_hover@;
    border-radius: @layout-panel_radius@;
    padding: 20px;
    font-size: @type-body@;
}
QLabel#dropZone:hover {
    border-color: @primary@;
    color: @primary@;
    background: @control_hover@;
}
QPushButton {
    color: @text@;
    background: @control@;
    border: 1px solid @border@;
    border-radius: @layout-control_radius@;
    padding: 7px 14px;
    min-height: 20px;
}
QPushButton:hover {
    background: @control_hover@;
    border-color: @border_hover@;
}
QPushButton:pressed {
    background: @control_pressed@;
}
QPushButton:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
    border-color: @disabled_surface@;
}
QPushButton[role="primary"] {
    color: @control@;
    background: @primary@;
    border-color: @primary@;
    font-weight: 600;
}
QPushButton[role="primary"]:hover {
    background: @primary_hover@;
    border-color: @primary_hover@;
}
QPushButton[role="primary"]:pressed {
    background: @primary_pressed@;
}
QPushButton[role="primary"]:disabled {
    color: @disabled_text@;
    background: @disabled_surface@;
    border-color: @disabled_surface@;
}
QPushButton[role="danger"] {
    color: @control@;
    background: @danger@;
    border-color: @danger@;
}
QPushButton[role="danger"]:hover {
    background: @danger_hover@;
    border-color: @danger_hover@;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox,
QSpinBox, QDoubleSpinBox {
    color: @text@;
    background: @control@;
    border: 1px solid @border@;
    border-radius: @layout-control_radius@;
    padding: 7px 9px;
    selection-background-color: @primary@;
    selection-color: @control@;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid @primary@;
}
QComboBox::drop-down {
    width: 26px;
    border: none;
}
QComboBox QAbstractItemView {
    color: @text@;
    background: @control@;
    border: 1px solid @border@;
    selection-background-color: @selection@;
    selection-color: @text@;
}
QTabWidget::pane {
    background: transparent;
    border: none;
    top: 0;
}
QTabBar::tab {
    color: @secondary_text@;
    background: transparent;
    border: 1px solid transparent;
    border-radius: @layout-control_radius@;
    padding: 8px 14px;
    margin: 2px 3px 8px 0;
}
QTabBar::tab:hover {
    color: @text@;
    background: @control_pressed@;
}
QTabBar::tab:selected {
    color: @text@;
    background: @control@;
    border-color: @disabled_surface@;
}
QGroupBox {
    color: @text@;
    background: @canvas@;
    border: 1px solid @border@;
    border-radius: @layout-panel_radius@;
    margin-top: 12px;
    padding: 17px 14px 12px 14px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 13px;
    padding: 0 5px;
    color: @secondary_text@;
    background: @canvas@;
    font-size: @type-caption@;
    font-weight: 600;
}
QCheckBox {
    spacing: 8px;
}
QProgressBar {
    color: @text@;
    background: @disabled_surface@;
    border: none;
    border-radius: 5px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: @primary@;
    border-radius: 5px;
}
QTableWidget, QTableView {
    color: @text@;
    background: @control@;
    alternate-background-color: @alternate@;
    border: 1px solid @disabled_surface@;
    border-radius: 10px;
    gridline-color: @border@;
    selection-background-color: @selection@;
    selection-color: @text@;
}
QHeaderView::section {
    color: @secondary_text@;
    background: @canvas@;
    border: none;
    border-bottom: 1px solid @disabled_surface@;
    padding: 8px 7px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: @canvas@;
    border: none;
}
QScrollBar:vertical {
    width: 10px;
    background: transparent;
    margin: 2px;
}
QScrollBar::handle:vertical {
    min-height: 28px;
    background: @border_hover@;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}
QToolTip {
    color: @text@;
    background: @control@;
    border: 1px solid @border@;
    border-radius: 7px;
    padding: 5px 8px;
}
QMessageBox {
    background: @canvas@;
}
""" + control_states())


def apply_apple_theme(app: QApplication) -> None:
    """Apply a restrained Apple-inspired light theme to the desktop app."""
    app.setStyleSheet(APPLE_STYLESHEET)
    font = app.font()
    # QApplication's platform font resolves to San Francisco on macOS and
    # the platform's native UI font on Windows/Linux.
    font.setPointSize(UI_TYPE["body"])
    app.setFont(font)

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(APP_BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(UI_COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(UI_COLORS["control"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(UI_COLORS["alternate"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(UI_COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(UI_COLORS["control"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(UI_COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(UI_COLORS["primary"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(UI_COLORS["control"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(UI_COLORS["secondary_text"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(UI_COLORS["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(UI_COLORS["control"]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(UI_COLORS["disabled_text"]))
    app.setPalette(palette)
