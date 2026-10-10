"""Painted refresh controls with keyboard and accessibility support."""
from PySide6.QtCore import Qt, QRectF, QPointF, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QCheckBox, QPushButton

from .theme import COLORS

REFRESH_INTERVAL_SECONDS = 5


class RefreshSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__("自动刷新", parent)
        self._position = 0.0
        self.setFixedSize(120, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("自动刷新，每5秒")
        self.setToolTip("每5秒刷新聊天；已授权的自动分析可能产生 API 费用。")
        self.animation = QPropertyAnimation(self, b"position", self)
        self.animation.setDuration(130)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.toggled.connect(self._animate)

    def get_position(self):
        return self._position

    def set_position(self, value):
        self._position = value
        self.update()

    position = Property(float, get_position, set_position)

    def _animate(self, checked):
        self.animation.stop()
        if not self.isVisible():
            self.set_position(1.0 if checked else 0.0)
            return
        self.animation.setStartValue(self._position)
        self.animation.setEndValue(1.0 if checked else 0.0)
        self.animation.start()

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(COLORS["muted"]))
        font = self.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, 64, 32), Qt.AlignmentFlag.AlignVCenter, "自动刷新")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["accent"] if self.isChecked() else "#8f9f95"))
        painter.drawRoundedRect(QRectF(70, 5, 44, 24), 12, 12)
        x = 72 + 20 * self._position
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.drawEllipse(QRectF(x, 8, 20, 20))
        painter.setBrush(QColor("#edf2e9"))
        painter.drawEllipse(QRectF(x, 7, 20, 20))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLORS["focus"]), 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(QRectF(1, 1, 118, 30), 6, 6)
        painter.end()


class RefreshButton(QPushButton):
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self.setAccessibleName("立即刷新聊天")
        self.setToolTip("立即刷新聊天")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(callback)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["selected"] if self.isDown() else COLORS["hover"] if self.underMouse() else COLORS["surface"]))
        painter.drawRoundedRect(QRectF(0, 0, 32, 32), 8, 8)
        painter.setPen(QPen(QColor(COLORS["accent"]), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(QRectF(8, 8, 16, 16), 42 * 16, 285 * 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["accent"]))
        painter.drawPolygon(QPolygonF([QPointF(24, 7), QPointF(23, 15), QPointF(17, 10)]))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(COLORS["focus"]), 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(QRectF(1, 1, 30, 30), 7, 7)
        painter.end()
