"""Small, theme-independent window chrome for the Widgets desktop.

Use ``FramelessWindow`` in place of QMainWindow and put a ``TitleBar(self)``
inside the central widget. The central widget becomes ``windowShell``; its
background/radius colours are supplied by the application's QSS; use
``#windowShell[windowMaximized="true"]`` for square maximized/fullscreen edges.
A real window mask also clips opaque descendants and removes transparent
corners from hit testing, which a QSS border-radius alone does not do.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QKeySequence, QPainterPath, QRegion, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPlainTextEdit, QPushButton, QStyle, QTextEdit, QWidget,
)


_INTERACTIVE_WIDGETS = (
    QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
    QComboBox, QLineEdit, QPlainTextEdit, QTextEdit,
)
_NO_EDGES = Qt.Edge(0)
_NATIVE_HITS = {
    Qt.Edge.LeftEdge: 10, Qt.Edge.RightEdge: 11,
    Qt.Edge.TopEdge: 12, Qt.Edge.TopEdge | Qt.Edge.LeftEdge: 13,
    Qt.Edge.TopEdge | Qt.Edge.RightEdge: 14, Qt.Edge.BottomEdge: 15,
    Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: 16,
    Qt.Edge.BottomEdge | Qt.Edge.RightEdge: 17,
}


def resize_edges(position: QPoint, rect: QRect, border: int = 8) -> Qt.Edges:
    """Pure logical-pixel edge calculation; points outside rect never resize."""
    if border <= 0 or not rect.contains(position):
        return _NO_EDGES
    edges = _NO_EDGES
    if position.x() < rect.left() + border:
        edges |= Qt.Edge.LeftEdge
    elif position.x() > rect.right() - border:
        edges |= Qt.Edge.RightEdge
    if position.y() < rect.top() + border:
        edges |= Qt.Edge.TopEdge
    elif position.y() > rect.bottom() - border:
        edges |= Qt.Edge.BottomEdge
    return edges


def _native_client_position(hwnd: int, x: int, y: int) -> QPoint | None:
    """Convert native screen pixels to this HWND's native client pixels."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    screen_to_client = user32.ScreenToClient
    screen_to_client.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    screen_to_client.restype = wintypes.BOOL
    point = wintypes.POINT(x, y)
    if not screen_to_client(hwnd, ctypes.byref(point)):
        return None
    return QPoint(point.x, point.y)


class FramelessWindow(QMainWindow):
    """QMainWindow with 18px clipped corners and an 8px system-resize border."""

    CORNER_RADIUS = 18
    RESIZE_BORDER = 8

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._window_shell: QWidget | None = None
        self._resize_cursor = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setMouseTracking(True)
        # Keep close routed through the subclass's closeEvent (including vetoes).
        self._close_shortcut = QShortcut(QKeySequence("Alt+F4"), self)
        self._close_shortcut.activated.connect(self.close)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def setCentralWidget(self, widget: QWidget | None) -> None:
        self._window_shell = widget
        if widget is not None:
            widget.setObjectName("windowShell")
            widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
            widget.setAttribute(Qt.WidgetAttribute.WA_Hover)
            widget.setMouseTracking(True)
        super().setCentralWidget(widget)
        self._update_window_mask()

    def _square_corners(self) -> bool:
        return self.isMaximized() or self.isFullScreen()

    def _update_window_mask(self) -> None:
        square = self._square_corners()
        for widget in (self, self._window_shell):
            if widget is None:
                continue
            if square:
                widget.clearMask()
            elif not widget.size().isEmpty():
                radius = min(self.CORNER_RADIUS, widget.width() / 2, widget.height() / 2)
                path = QPainterPath()
                path.addRoundedRect(QRectF(widget.rect()), radius, radius)
                widget.setMask(QRegion(path.toFillPolygon().toPolygon()))
            # QWidget.maximized is a built-in read-only property; a child
            # shell needs its own property for state-dependent QSS selectors.
            if widget.property("windowMaximized") != square:
                widget.setProperty("windowMaximized", square)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_window_mask()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_window_mask()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._update_window_mask()
            self._clear_resize_cursor()

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _interactive_at(self, position: QPoint) -> bool:
        widget = self.childAt(position)
        while widget is not None and widget is not self:
            if (isinstance(widget, _INTERACTIVE_WIDGETS)
                    or widget.property("chromeInteractive")
                    or widget.focusPolicy() != Qt.FocusPolicy.NoFocus):
                return True
            if isinstance(widget, QLabel) and widget.textInteractionFlags() != Qt.TextInteractionFlag.NoTextInteraction:
                # A normal QLabel uses LinksAccessibleByMouse by default. Only
                # selection/actual links should suppress a title-label drag.
                if (widget.textInteractionFlags() & (Qt.TextInteractionFlag.TextSelectableByMouse
                        | Qt.TextInteractionFlag.TextSelectableByKeyboard)
                        or (widget.textFormat() != Qt.TextFormat.PlainText and "<a " in widget.text())):
                    return True
            widget = widget.parentWidget()
        return False

    def hit_test(self, global_position: QPoint | QPointF) -> Qt.Edges:
        """Return resize edges without moving/resizing or consulting native APIs.

        Positions are Qt global logical coordinates (e.g. mouse.globalPosition),
        never Win32 physical screen coordinates. Controls/inputs win over edges.
        """
        if self._square_corners():
            return _NO_EDGES
        if isinstance(global_position, QPointF):
            global_position = global_position.toPoint()
        position = self.mapFromGlobal(global_position)
        if not self.mask().isEmpty() and not self.mask().contains(position):
            return _NO_EDGES
        if self._interactive_at(position):
            return _NO_EDGES
        edges = resize_edges(position, self.rect(), self.RESIZE_BORDER)
        if self.minimumWidth() == self.maximumWidth():
            edges &= ~(Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
        if self.minimumHeight() == self.maximumHeight():
            edges &= ~(Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
        return edges

    def _clear_resize_cursor(self) -> None:
        if self._resize_cursor:
            self.unsetCursor()
            self._resize_cursor = False

    def _update_resize_cursor(self, edges: Qt.Edges) -> None:
        if not edges:
            self._clear_resize_cursor()
            return
        if edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            cursor = Qt.CursorShape.SizeFDiagCursor
        elif edges in (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            cursor = Qt.CursorShape.SizeBDiagCursor
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            cursor = Qt.CursorShape.SizeHorCursor
        else:
            cursor = Qt.CursorShape.SizeVerCursor
        self.setCursor(cursor)
        self._resize_cursor = True

    def eventFilter(self, watched, event) -> bool:
        if isinstance(watched, QWidget) and watched.window() is self:
            kind = event.type()
            if watched is self._window_shell and kind == QEvent.Type.Resize:
                self._update_window_mask()
            elif kind in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                self._update_resize_cursor(self.hit_test(event.globalPosition()))
            elif kind == QEvent.Type.Leave and watched is self:
                self._clear_resize_cursor()
            elif kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                edges = self.hit_test(event.globalPosition())
                handle = self.windowHandle()
                if edges and handle is not None and handle.startSystemResize(edges):
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _native_global_position(self, hwnd: int, x: int, y: int) -> QPoint | None:
        local = _native_client_position(hwnd, x, y)
        if local is None:
            return None
        # Divide the CLIENT offset, not the global screen coordinate. Windows
        # and Qt have different screen origins on mixed-DPI/negative monitors.
        scale = self.devicePixelRatioF()
        logical = QPoint(round(local.x() / scale), round(local.y() / scale))
        return self.mapToGlobal(logical)

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            import ctypes
            from ctypes import wintypes
            native = wintypes.MSG.from_address(int(message))
            if native.message == 0x0084:  # WM_NCHITTEST; lParam contains signed physical screen pixels.
                x = ctypes.c_short(native.lParam & 0xFFFF).value
                y = ctypes.c_short((native.lParam >> 16) & 0xFFFF).value
                position = self._native_global_position(native.hWnd, x, y)
                if position is not None:
                    hit = _NATIVE_HITS.get(self.hit_test(position))
                    if hit is not None:
                        return True, hit
        return super().nativeEvent(event_type, message)


class TitleBar(QWidget):
    """Draggable title/brand, optional actions, then the three window controls.

    ``add_brand(widget)`` replaces the default icon/title on its first call;
    ``add_action(widget)`` inserts an interactive widget before the controls.
    Object names are exposed for the application's QSS, not styled here.
    """

    def __init__(self, parentwindow: FramelessWindow, title: str = "交我聊"):
        super().__init__(parentwindow)
        self._parentwindow = parentwindow
        self._custom_brand = False
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setMinimumHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(10)
        self._brand = QHBoxLayout()
        self._brand.setSpacing(10)
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("windowIcon")
        self.icon_label.setFixedSize(24, 24)
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("windowTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._brand.addWidget(self.icon_label)
        self._brand.addWidget(self.title_label)
        layout.addLayout(self._brand)
        layout.addStretch(1)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
        layout.addLayout(self._actions)
        self._controls = QHBoxLayout()
        self._controls.setSpacing(4)
        layout.addLayout(self._controls)
        self.minimize_button = self._control("windowControl", "最小化", QStyle.StandardPixmap.SP_TitleBarMinButton)
        self.maximize_button = self._control("windowControl", "最大化", QStyle.StandardPixmap.SP_TitleBarMaxButton)
        self.close_button = self._control("windowClose", "关闭", QStyle.StandardPixmap.SP_TitleBarCloseButton)
        self.minimize_button.clicked.connect(parentwindow.showMinimized)
        self.maximize_button.clicked.connect(parentwindow.toggle_maximized)
        self.close_button.clicked.connect(parentwindow.close)
        parentwindow.installEventFilter(self)
        parentwindow.windowIconChanged.connect(self._sync_icon)
        parentwindow.windowTitleChanged.connect(self.title_label.setText)
        self._sync_icon()
        self._sync_maximize()

    def _control(self, name: str, tooltip: str, icon: QStyle.StandardPixmap) -> QPushButton:
        button = QPushButton(self)
        button.setObjectName(name)
        button.setProperty("chromeInteractive", True)
        button.setProperty("windowControl", True)
        button.setFlat(True)
        button.setFixedSize(36, 32)
        button.setIconSize(QSize(14, 14))
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._controls.addWidget(button)
        return button

    def add_action(self, widget: QWidget) -> QWidget:
        widget.setProperty("chromeInteractive", True)
        self._actions.addWidget(widget)
        return widget

    def add_brand(self, widget: QWidget) -> QWidget:
        if not self._custom_brand:
            self.icon_label.hide()
            self.title_label.hide()
            self._custom_brand = True
        self._brand.addWidget(widget)
        return widget

    def _sync_icon(self, *_args) -> None:
        icon = self._parentwindow.windowIcon()
        self.icon_label.setPixmap(icon.pixmap(24, 24))
        self.icon_label.setVisible(not self._custom_brand and not icon.isNull())

    def _sync_maximize(self) -> None:
        maximized = self._parentwindow.isMaximized()
        text = "还原" if maximized else "最大化"
        icon = QStyle.StandardPixmap.SP_TitleBarNormalButton if maximized else QStyle.StandardPixmap.SP_TitleBarMaxButton
        self.maximize_button.setToolTip(text)
        self.maximize_button.setAccessibleName(text)
        self.maximize_button.setIcon(self.style().standardIcon(icon))

    def eventFilter(self, watched, event) -> bool:
        if watched is self._parentwindow and event.type() == QEvent.Type.WindowStateChange:
            self._sync_maximize()
        return super().eventFilter(watched, event)

    def _draggable(self, event) -> bool:
        point = event.globalPosition().toPoint()
        return (event.button() == Qt.MouseButton.LeftButton
                and not self._parentwindow.hit_test(point)
                and not self._parentwindow._interactive_at(self._parentwindow.mapFromGlobal(point)))

    def mousePressEvent(self, event) -> None:
        if self._draggable(event):
            handle = self._parentwindow.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._draggable(event):
            self._parentwindow.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
