"""Tactile, keyboard-accessible connection control with a circular hit target."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton


class ConnectButton(QPushButton):
    def __init__(self, callback, parent=None):
        super().__init__("连接微信", parent)
        self.setFixedSize(94, 98)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("连接微信")
        self.clicked.connect(callback)

    def hitButton(self, position):
        delta = QPointF(position) - QPointF(47, 46)
        return delta.x() ** 2 + delta.y() ** 2 <= 40 ** 2

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for margin, alpha in ((2, 13), (5, 16), (8, 18)):
            painter.setBrush(QColor(17, 33, 26, alpha))
            painter.drawEllipse(QRectF(7 - margin / 2, 10 - margin / 2, 80 + margin, 80 + margin))
        shift = 3 if self.isDown() else 0
        painter.setBrush(QColor("#1a3027"))
        painter.drawEllipse(QRectF(7, 10, 80, 80))
        face = QLinearGradient(10, 7, 65, 88)
        face.setColorAt(0, QColor("#426958" if self.underMouse() else "#365a49"))
        face.setColorAt(1, QColor("#1d382c"))
        painter.setBrush(face)
        painter.setPen(QPen(QColor("#6b8677"), 1))
        painter.drawEllipse(QRectF(7, 6 + shift, 80, 80))
        painter.setPen(QPen(QColor(231, 243, 230, 70), 1))
        painter.drawArc(QRectF(10, 9 + shift, 74, 74), 30 * 16, 120 * 16)
        painter.setPen(QPen(QColor("#d9e9db"), 1.7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(34, 22 + shift, 26, 18), 5, 5)
        painter.drawLine(39, 40 + shift, 39, 45 + shift)
        painter.drawLine(39, 45 + shift, 45, 40 + shift)
        painter.drawPoint(QPointF(41, 31 + shift))
        painter.drawPoint(QPointF(48, 31 + shift))
        painter.drawPoint(QPointF(55, 31 + shift))
        font = self.font()
        font.setPixelSize(12)
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(10, 48 + shift, 74, 23), Qt.AlignmentFlag.AlignCenter, self.text())
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#476a58"), 2, Qt.PenStyle.DashLine))
            painter.drawEllipse(QRectF(3, 2, 88, 88))
        painter.end()
