import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from teachmechat.models import ChatMessage


class RobotStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from teachmechat.desktop.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        from teachmechat.desktop.status_robot import RobotStatus
        self.robot = RobotStatus()

    def tearDown(self):
        self.robot.close()
        self.robot.deleteLater()
        self.app.processEvents()

    def test_normal_and_error_have_exclusive_lights_and_accessible_labels(self):
        self.robot.set_state("ready", "已同步", "最新消息 12:30")
        self.assertTrue(self.robot.green.lit)
        self.assertFalse(self.robot.red.lit)
        self.assertIn("绿灯", self.robot.accessibleName())
        self.robot.set_state("error", "网络连接失败")
        self.assertTrue(self.robot.red.lit)
        self.assertFalse(self.robot.green.lit)
        self.assertIn("异常", self.robot.accessibleName())

    def test_waiting_busy_paused_never_show_success(self):
        for state in ("idle", "busy", "paused"):
            self.robot.set_state(state, "test")
            self.assertFalse(self.robot.red.lit)
            self.assertFalse(self.robot.green.lit)

    def test_signal_lamps_render_colored_lenses_without_rg_text(self):
        from PySide6.QtWidgets import QLabel
        self.robot.show()
        for state, lamp, channel in (("ready", self.robot.green, "green"), ("error", self.robot.red, "red")):
            self.robot.set_state(state, "test")
            self.app.processEvents()
            image = lamp.grab().toImage()
            color = image.pixelColor(image.width() // 2, image.height() // 2)
            if channel == "green":
                self.assertGreater(color.green(), color.red())
            else:
                self.assertGreater(color.red(), color.green())
        self.assertFalse(self.robot.lights.findChildren(QLabel))

    def test_expression_tracks_connection_and_answer_not_sync_success(self):
        self.robot.set_state("idle", "未连接", connected=False)
        self.assertEqual(self.robot.head.expression, "disconnected")
        self.assertIn("@@", self.robot.head.accessibleDescription())
        self.robot.set_state("busy", "读取中", connected=True)
        self.assertEqual(self.robot.head.expression, "neutral")
        self.robot.set_state("ready", "已同步", connected=True)
        self.assertEqual(self.robot.head.expression, "neutral")
        self.robot.set_state("answered", "回答已生成", connected=True)
        self.assertEqual(self.robot.head.expression, "smile")
        self.assertTrue(self.robot.green.lit)
        self.robot.set_state("error", "连接断开", connected=False)
        self.assertEqual(self.robot.head.expression, "disconnected")
        self.assertTrue(self.robot.red.lit)

    def test_lcd_is_parent_of_plain_readable_status_labels(self):
        self.assertEqual(self.robot.message.parentWidget(), self.robot.lcd)
        self.assertEqual(self.robot.detail.parentWidget(), self.robot.lcd)
        self.assertEqual(self.robot.lights.parentWidget(), self.robot.lcd)
        from teachmechat.desktop.status_robot import LCDText
        self.assertIsInstance(self.robot.detail, LCDText)
        self.assertGreaterEqual(self.robot.message.pixel_size, 18)
        self.assertGreaterEqual(self.robot.detail.pixel_size, 15)
        self.assertIn("#080e0a", self.robot.lcd.styleSheet())
        self.assertIn("#72ff69", self.robot.message.styleSheet())

    def test_generating_is_red_and_finished_is_green_without_caption(self):
        from PySide6.QtWidgets import QLabel
        self.robot.set_state("generating", "正在生成建议…", connected=True)
        self.assertTrue(self.robot.red.lit)
        self.assertFalse(self.robot.green.lit)
        self.assertEqual(self.robot.head.expression, "neutral")
        self.assertIn("生成", self.robot.accessibleName())
        self.robot.set_state("answered", "回答已生成", connected=True)
        self.assertFalse(self.robot.red.lit)
        self.assertTrue(self.robot.green.lit)
        self.assertNotIn("状态助手", [label.text() for label in self.robot.findChildren(QLabel)])

    def test_error_text_is_plain_bounded_and_full_tooltip(self):
        from PySide6.QtCore import Qt
        text = "<b>错误</b>" + "长错误" * 80
        self.robot.set_state("error", text)
        self.assertEqual(self.robot.message.textFormat(), Qt.TextFormat.PlainText)
        self.assertLessEqual(len(self.robot.message.text()), 44)
        self.assertIn(text, self.robot.toolTip())

    def test_text_interface_and_clear_reset_light(self):
        self.robot.set_state("error", "error")
        self.robot.setText("waiting")
        self.assertEqual(self.robot.text(), "waiting")
        self.assertEqual(self.robot.state, "idle")
        self.robot.clear()
        self.assertEqual(self.robot.state, "idle")

    def test_window_sync_error_pause_and_centering(self):
        from teachmechat.desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(Path(directory), demo=True)
            window.resize(1000, 700)
            window.show()
            self.app.processEvents()
            try:
                self.assertLess(abs(window.status.mapTo(window, window.status.rect().center()).x() - window.width() / 2), 4)
                actor = MagicMock()
                window.source_actor = actor
                window.selected_id = "synthetic"
                window.paused = False
                window._source_event(actor, "messages", ("synthetic", [ChatMessage("1", 100, "synthetic", "hello")]))
                self.assertEqual(window.status.state, "ready")
                self.assertEqual(window.status.text(), "已同步")
                self.assertIn("最新消息", window.status.detail.text())
                window.toggle_pause()
                self.assertEqual(window.status.state, "paused")
                window._source_failed(actor, "读取失败")
                self.assertEqual(window.status.state, "error")
                self.assertFalse(window.status.green.lit)
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()
