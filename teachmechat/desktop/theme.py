from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

# Semantic surfaces avoid bright patches in secondary dialogs and custom widgets.
COLORS = {
    "canvas": "#b8c2bd", "surface": "#d2d9d2", "sidebar": "#c3cdc6",
    "card": "#dce2d9", "input": "#e0e5dd", "incoming": "#c4cfc7",
    "outgoing": "#b7cfbf", "selected": "#aec8b8", "hover": "#c0d0c5",
    "border": "#a7b6ac", "border_soft": "#bfcbc1", "text": "#263a32",
    "muted": "#3f5147", "accent": "#355d4b", "accent_hover": "#284a3a",
    "on_accent": "#edf1e8", "focus": "#4b705a", "error": "#883d37",
    "busy": "#3c566e", "paused": "#665238", "disabled": "#79897e",
}

STYLE = """
QWidget { background: @canvas; color: @text; font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI Variable', 'Segoe UI'; font-size: 14px; }
QMainWindow { background: transparent; }
QDialog { background: @canvas; }
QWidget#windowShell { background: @canvas; border: 1px solid @border; border-radius: 18px; }
QWidget#windowShell[windowMaximized="true"] { border: none; border-radius: 0; }
QWidget#titleBar { background: transparent; }
QPushButton#windowControl, QPushButton#windowClose { background: transparent; border: none; border-radius: 6px; padding: 0; color: @muted; }
QPushButton#windowControl:hover { background: @hover; }
QPushButton#windowClose:hover { background: @error; color: @on_accent; }
QLabel { background: transparent; }
QLabel#brand { font-size: 25px; font-weight: 700; color: @text; }
QLabel#hero { font-size: 24px; font-weight: 600; color: @text; }
QLabel#section { font-size: 17px; font-weight: 600; color: @text; }
QLabel#muted { color: @muted; font-size: 13px; }
QLabel#eyebrow { color: @muted; font-size: 12px; font-weight: 600; }
QLabel#badge { background: @selected; color: @text; padding: 7px 13px; border-radius: 12px; font-size: 12px; }
QLabel#avatar { background: @selected; color: @accent; border-radius: 14px; font-size: 18px; font-weight: 600; }
QLabel#replyText { font-size: 16px; color: @text; }
QLabel#bubbleBody { font-size: 15px; color: @text; }
QLabel#bubbleTitle { font-size: 15px; font-weight: 600; color: @text; }
QLabel#bubbleMeta { color: @muted; font-size: 12px; }
QLabel#error { color: @error; padding: 8px; }
QLabel[success="true"] { color: @accent; }
QLabel[success="false"] { color: @error; }
QWidget#canvas { background: @canvas; }
QFrame#surface, QWidget#surface { background: @surface; border: 1px solid @border_soft; border-radius: 14px; }
QFrame#sidebar { background: @sidebar; border: none; border-radius: 14px; }
QWidget#chatCanvas, QWidget#scrollCanvas { background: @surface; }
QFrame#card { background: @card; border: 1px solid @border_soft; border-radius: 10px; }
QFrame#incoming { background: @incoming; border: 1px solid @border_soft; border-radius: 12px; }
QFrame#outgoing { background: @outgoing; border: 1px solid @border; border-radius: 12px; }
QFrame#share { background: @card; border: 1px solid @border; border-radius: 10px; }
QFrame#notice { background: @outgoing; border: 1px solid @border; border-radius: 10px; }
QPushButton { background: @surface; border: 1px solid @border; border-radius: 7px; padding: 9px 15px; color: @text; }
QPushButton:hover { background: @hover; border-color: @focus; }
QPushButton:pressed { background: @selected; }
QPushButton:disabled { background: @sidebar; color: @disabled; border-color: @border_soft; }
QPushButton:focus { border-color: @focus; }
QPushButton#primary { background: @accent; color: @on_accent; border: 1px solid @accent; font-weight: 600; padding: 11px 18px; }
QPushButton#primary:hover { background: @accent_hover; }
QPushButton#primary:disabled { background: @sidebar; color: @muted; border-color: @border; }
QPushButton#quiet { background: transparent; border: none; color: @muted; padding: 7px 9px; }
QPushButton#quiet:hover { color: @text; background: @hover; }
QPushButton#raised { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 @input,stop:1 @surface); border:1px solid @border; border-bottom:3px solid @border; border-radius:8px; padding:8px 16px; font-weight:600; }
QPushButton#raised:pressed { background:@selected; border-bottom:1px solid @border; padding-top:10px; }
QPushButton#copy { background: @selected; color: @text; border: none; padding: 6px 12px; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: @input; color: @text; border: 1px solid @border; border-radius: 7px; padding: 9px; selection-background-color: @accent; selection-color: @on_accent; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: @focus; }
QComboBox QAbstractItemView { background: @input; color: @text; selection-background-color: @selected; selection-color: @text; padding: 6px; }
QListWidget { background: transparent; border: none; outline: none; padding: 3px; }
QListWidget::item { padding: 13px 12px; margin: 4px 0; border-radius: 7px; color: @text; }
QListWidget::item:selected { background: @selected; color: @text; font-weight: 600; }
QListWidget::item:hover { background: @hover; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px 0; }
QScrollBar::handle:vertical { background: @border; border-radius: 4px; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: @canvas; width: 12px; }
QTabWidget::pane { border: none; background: @surface; }
QTabBar::tab { background: transparent; color: @muted; font-size:16px; font-weight:600; padding: 11px 15px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: @accent; border-bottom: 2px solid @accent; font-weight: 600; }
QGroupBox { background: @surface; border: 1px solid @border; border-radius: 10px; margin-top: 14px; padding: 18px 12px 12px; }
QGroupBox#modelCard { margin-top:0; padding:0; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: @text; }
QCheckBox, QRadioButton { background: transparent; spacing: 8px; padding: 5px 0; color: @muted; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid @muted; border-radius: 4px; background: @input; }
QCheckBox::indicator:checked { background: @accent; border: 1px solid @accent; }
QCheckBox::indicator:disabled { background: @sidebar; border-color: @border; }
QToolTip { color: @on_accent; background: @text; border: none; padding: 7px; }
QMenu { background: @surface; border: 1px solid @border; padding: 5px; }
QMenu::item { padding: 8px 20px; }
QMenu::item:selected { background: @selected; color: @text; }
"""
for role, color in sorted(COLORS.items(), key=lambda item: -len(item[0])):
    STYLE = STYLE.replace("@" + role, color)

ASCII_MARK = " .-----------------.\n |  TeachMeChat    |\n '------------.----'\n              '"


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(COLORS["accent"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 17, 17)
    painter.setPen(QPen(QColor(COLORS["on_accent"]), 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(15, 17, 34, 24, 7, 7)
    painter.drawLine(23, 41, 23, 48)
    painter.drawLine(23, 48, 31, 41)
    painter.drawLine(23, 26, 41, 26)
    painter.drawLine(23, 33, 36, 33)
    painter.end()
    return QIcon(pixmap)


def apply_theme(application):
    from PySide6.QtGui import QPalette
    # Reapplying an identical stylesheet forces Qt to re-polish every live widget;
    # with large accumulated widget trees that can spin indefinitely. Skip when the
    # application already carries this theme.
    if application.styleSheet() == STYLE:
        return
    application.setStyle("Fusion")
    palette = QPalette()
    for role, token in ((QPalette.ColorRole.Window, "canvas"), (QPalette.ColorRole.WindowText, "text"),
                        (QPalette.ColorRole.Base, "input"), (QPalette.ColorRole.AlternateBase, "surface"),
                        (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "surface"),
                        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "accent"),
                        (QPalette.ColorRole.HighlightedText, "on_accent"),
                        (QPalette.ColorRole.PlaceholderText, "muted"),
                        (QPalette.ColorRole.ToolTipBase, "text"), (QPalette.ColorRole.ToolTipText, "on_accent")):
        palette.setColor(role, QColor(COLORS[token]))
    application.setPalette(palette)
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI Variable", "Segoe UI"])
    font.setPixelSize(14)
    font.setWeight(QFont.Weight.Normal)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    application.setFont(font)
    application.setStyleSheet(STYLE)
    application.setWindowIcon(app_icon())
