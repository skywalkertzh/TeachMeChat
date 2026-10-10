import os
import unittest
from unittest.mock import MagicMock, patch


class RefreshControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_switch_mouse_keyboard_and_semantics(self):
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        from teachmechat.desktop.refresh_controls import RefreshSwitch
        switch = RefreshSwitch()
        switch.show()
        try:
            self.assertEqual(switch.text(), "自动刷新")
            self.assertIn("5秒", switch.accessibleName())
            QTest.mouseClick(switch, Qt.MouseButton.LeftButton, pos=QPoint(95, 16))
            self.assertTrue(switch.isChecked())
            QTest.keyClick(switch, Qt.Key.Key_Space)
            self.assertFalse(switch.isChecked())
        finally:
            switch.close()
            switch.deleteLater()

    def test_refresh_button_has_accessible_name_and_calls_once(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from teachmechat.desktop.refresh_controls import RefreshButton
        callback = MagicMock()
        button = RefreshButton(callback)
        button.show()
        try:
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            callback.assert_called_once()
            self.assertEqual(button.text(), "")
            self.assertIn("刷新", button.accessibleName())
        finally:
            button.close()
            button.deleteLater()

    def test_analysis_bold_headers_and_literal_html(self):
        from teachmechat.desktop.advice_view import AdviceAnalysis
        from teachmechat.models import Advice
        widget = AdviceAnalysis()
        widget.show_advice(Advice(["1", "2", "3"], "已知事实：**重要** <img src=x>", "休息", []))
        try:
            self.assertIn("<img src=x>", widget.toPlainText())
            self.assertNotIn("**重要**", widget.toPlainText())
            cursor = widget.document().find("重要")
            self.assertGreater(cursor.charFormat().fontWeight(), 400)
            header = widget.document().find("对话里发生了什么")
            self.assertGreater(header.charFormat().fontWeight(), 400)
        finally:
            widget.deleteLater()
