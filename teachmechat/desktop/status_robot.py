"""Compact pixel companion with a readable status screen and explicit signals."""
import re

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QFont, QImage, QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import COLORS as THEME


class PixelRobot(QWidget):
    SCALE = 1.25

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.expression = "disconnected"
        self.setFixedSize(round(70 * self.SCALE), round(76 * self.SCALE))
        self.setAccessibleName("像素机器人")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.SCALE, self.SCALE)
        outline = QColor(THEME["muted"])
        shell = QColor(THEME["selected"])
        ink = QColor(THEME["accent"])
        if self.state == "error":
            ink = QColor(THEME["error"])
        elif self.state == "busy":
            ink = QColor(THEME["busy"])
        painter.setPen(QPen(outline, 1.5))
        painter.drawLine(35, 12, 35, 19)
        painter.setBrush(ink)
        painter.drawRoundedRect(QRectF(32, 7, 6, 6), 2, 2)
        painter.setBrush(shell)
        painter.drawRoundedRect(QRectF(7, 28, 7, 15), 3, 3)
        painter.drawRoundedRect(QRectF(56, 28, 7, 15), 3, 3)
        painter.drawRoundedRect(QRectF(12, 18, 46, 37), 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(THEME["input"]))
        painter.drawRoundedRect(QRectF(18, 25, 34, 23), 5, 5)
        painter.setBrush(ink)
        if self.expression == "disconnected":
            painter.setPen(ink)
            font = QFont("Consolas", 10)
            font.setPixelSize(13)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(20, 27, 13, 16), Qt.AlignmentFlag.AlignCenter, "@")
            painter.drawText(QRectF(37, 27, 13, 16), Qt.AlignmentFlag.AlignCenter, "@")
        elif self.expression == "error":
            painter.setPen(QPen(ink, 2))
            for x in (25, 43):
                painter.drawLine(x - 2, 31, x + 2, 35)
                painter.drawLine(x + 2, 31, x - 2, 35)
        else:
            height = 2 if self.state == "paused" else 6
            painter.drawRoundedRect(QRectF(23, 30, 5, height), 1, 1)
            painter.drawRoundedRect(QRectF(42, 30, 5, height), 1, 1)
        painter.setPen(QPen(ink, 1.5))
        if self.expression == "smile":
            painter.drawLine(30, 40, 32, 42)
            painter.drawLine(32, 42, 38, 42)
            painter.drawLine(38, 42, 40, 40)
        else:
            painter.drawLine(31, 41, 39, 41)
        painter.setPen(QPen(outline, 1.5))
        painter.setBrush(shell)
        painter.drawRoundedRect(QRectF(23, 57, 24, 9), 3, 3)
        painter.drawRoundedRect(QRectF(20, 67, 12, 4), 2, 2)
        painter.drawRoundedRect(QRectF(38, 67, 12, 4), 2, 2)
        painter.end()


class SignalLamp(QWidget):
    def __init__(self, color, name, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.name = name
        self.lit = False
        self.setFixedSize(24, 24)
        self.set_lit(False)

    def set_lit(self, lit):
        self.lit = bool(lit)
        self.setAccessibleName(f"{self.name}：{'亮' if self.lit else '灭'}")
        self.setToolTip(self.accessibleName())
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.lit:
            glow = QRadialGradient(12, 12, 12)
            light = QColor(self.color)
            light.setAlpha(105)
            glow.setColorAt(0.45, light)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setBrush(glow)
            painter.drawEllipse(QRectF(0, 0, 24, 24))
        painter.setPen(QPen(QColor('#15231f'), 1))
        lens = QRadialGradient(10, 9, 11)
        lens.setColorAt(0, self.color.lighter(145) if self.lit else QColor('#45544e'))
        lens.setColorAt(.55, self.color if self.lit else QColor('#34423c'))
        lens.setColorAt(1, self.color.darker(135) if self.lit else QColor('#27362f'))
        painter.setBrush(lens)
        painter.drawEllipse(QRectF(5, 5, 14, 14))
        if self.lit:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 135))
            painter.drawEllipse(QRectF(8, 7, 5, 3))
        painter.end()


class LCDText(QLabel):
    """Rasterize plain Unicode text at low resolution for a subtle dot-matrix face."""
    def __init__(self, pixel_size=20, bold=False, parent=None):
        super().__init__(parent)
        self.pixel_size = pixel_size
        self.bold = bold
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumHeight(pixel_size + 10)
        self.setStyleSheet("background:transparent; color:#72ff69;")

    def paintEvent(self, event):
        scale = 1.5
        font = QFont("Consolas")
        font.setFamilies(["Consolas", "Microsoft YaHei UI"])
        font.setPixelSize(round(self.pixel_size / scale))
        font.setBold(self.bold)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        image = QImage(max(1, round(self.width() / scale)), max(1, round(self.height() / scale)), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        ink = QPainter(image)
        ink.setFont(font)
        ink.setPen(QColor("#72ff69"))
        text = QFontMetrics(font).elidedText(self.text(), Qt.TextElideMode.ElideRight, image.width())
        ink.drawText(image.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        ink.end()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(self.rect(), image)
        painter.end()


class LCDScreen(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("lcdScreen")
        self.setStyleSheet("QFrame#lcdScreen {background:#080e0a; border:2px solid #53644e; border-radius:6px;}")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(QColor(77, 142, 67, 22), 1))
        for y in range(5, self.height() - 4, 4):
            painter.drawLine(5, y, self.width() - 5, y)
        painter.setPen(QPen(QColor(238, 244, 218, 85), 1))
        painter.drawLine(6, 4, self.width() - 6, 4)
        painter.end()


class RobotStatus(QWidget):
    COLORS = {state: "#72ff69" for state in ("ready", "answered", "busy", "generating", "error", "paused", "idle")}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("robotStatus")
        self.setMinimumWidth(480)
        self.setMaximumWidth(640)
        self.state = "idle"
        self._text = ""
        self._detail = ""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        panel = QFrame()
        panel.setObjectName("robotPanel")
        panel.setStyleSheet("QFrame#robotPanel {background:" + THEME["card"] + "; border:1px solid " + THEME["border"] + "; border-radius:12px;}")
        outer.addWidget(panel)
        body = QHBoxLayout(panel)
        body.setContentsMargins(12, 5, 18, 5)
        body.setSpacing(14)
        self.head = PixelRobot()
        body.addWidget(self.head, 0, Qt.AlignmentFlag.AlignVCenter)
        self.lcd = LCDScreen()
        lcd_layout = QHBoxLayout(self.lcd)
        lcd_layout.setContentsMargins(12, 9, 12, 9)
        lcd_layout.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.message = LCDText(20, bold=True)
        self.detail = LCDText(16)
        text.addWidget(self.message)
        text.addWidget(self.detail)
        lcd_layout.addLayout(text, 1)
        self.lights = QWidget()
        self.lights.setStyleSheet("background:transparent;")
        lamps = QVBoxLayout(self.lights)
        lamps.setContentsMargins(0, 0, 0, 0)
        lamps.setSpacing(6)
        self.red = SignalLamp("#ef5350", "红灯：生成中或异常")
        self.green = SignalLamp("#37cc83", "绿灯：正常")
        lamps.addWidget(self.red, 0, Qt.AlignmentFlag.AlignCenter)
        lamps.addWidget(self.green, 0, Qt.AlignmentFlag.AlignCenter)
        lcd_layout.addWidget(self.lights, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addWidget(self.lcd, 1)
        self.set_state("idle", "等待连接")

    @staticmethod
    def _label(text, size, color, bold=False):
        widget = QLabel(text)
        widget.setTextFormat(Qt.TextFormat.PlainText)
        widget.setStyleSheet(f"background:transparent; color:{color}; font-size:{size}px; font-weight:{600 if bold else 400};")
        return widget

    @staticmethod
    def _clean(value):
        return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value)).strip()

    def set_state(self, state, message, detail="", *, connected=None):
        if state not in self.COLORS:
            raise ValueError("Unknown robot status")
        self.state = state
        self._text = self._clean(message)
        self._detail = self._clean(detail)
        visible = self._text if len(self._text) <= 44 else self._text[:43] + "…"
        self.message.setText(visible)
        self.detail.setText(self._detail[:48])
        self.detail.setVisible(bool(self._detail))
        self.message.setAccessibleName(self._text)
        self.head.state = state
        if state == "answered":
            self.head.expression = "smile"
        elif connected is False or (connected is None and state == "idle"):
            self.head.expression = "disconnected"
        elif state == "error":
            self.head.expression = "error"
        else:
            self.head.expression = "neutral"
        self.head.setAccessibleDescription({"smile": "微笑：回答已生成", "disconnected": "@@眼睛：微信尚未连接", "error": "异常", "neutral": "平静：已连接或处理中"}[self.head.expression])
        self.head.update()
        self.red.set_lit(state in {"error", "generating"})
        self.green.set_lit(state in {"ready", "answered"})
        meaning = {"ready": "绿灯：正常", "answered": "绿灯：回答已生成", "error": "红灯：异常", "generating": "红灯：正在生成", "busy": "处理中", "idle": "等待", "paused": "已暂停"}[state]
        self.lights.setToolTip("红灯：正在生成或异常，请看屏幕文字区分；绿灯：正常或回答已生成。")
        self.setToolTip("\n".join(part for part in (meaning, self._text, self._detail) if part))
        self.setAccessibleName(f"状态机器人，{meaning}")
        self.setAccessibleDescription(self._text + " " + self._detail)

    def setText(self, text):
        self.set_state("idle", text or "等待操作")

    def text(self):
        return self._text

    def clear(self):
        self.set_state("idle", "等待操作")
