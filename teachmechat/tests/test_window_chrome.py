"""Chrome-only tests: synthetic widgets, no MainWindow or private data."""
import ctypes
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from teachmechat.desktop.chrome import FramelessWindow, TitleBar, resize_edges


class ResizeEdgesTests(unittest.TestCase):
    def test_all_edges_and_corners(self):
        rect = QRect(0, 0, 400, 300)
        cases = (
            (QPoint(0, 150), Qt.Edge.LeftEdge),
            (QPoint(399, 150), Qt.Edge.RightEdge),
            (QPoint(200, 0), Qt.Edge.TopEdge),
            (QPoint(200, 299), Qt.Edge.BottomEdge),
            (QPoint(7, 7), Qt.Edge.TopEdge | Qt.Edge.LeftEdge),
            (QPoint(392, 7), Qt.Edge.TopEdge | Qt.Edge.RightEdge),
            (QPoint(7, 292), Qt.Edge.BottomEdge | Qt.Edge.LeftEdge),
            (QPoint(392, 292), Qt.Edge.BottomEdge | Qt.Edge.RightEdge),
        )
        for position, expected in cases:
            with self.subTest(position=position):
                self.assertEqual(resize_edges(position, rect), expected)

    def test_boundary_and_outside_points(self):
        rect = QRect(0, 0, 400, 300)
        for position in (QPoint(8, 8), QPoint(391, 291), QPoint(200, 150),
                         QPoint(-1, 50), QPoint(400, 50), QPoint(200, -1), QPoint(200, 300)):
            with self.subTest(position=position):
                self.assertFalse(resize_edges(position, rect))
        self.assertFalse(resize_edges(QPoint(0, 10), rect, border=0))

    def test_nonzero_rect_origin(self):
        self.assertEqual(resize_edges(QPoint(24, 35), QRect(20, 30, 400, 300)),
                         Qt.Edge.TopEdge | Qt.Edge.LeftEdge)


class WindowChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = FramelessWindow()
        self.window.resize(640, 400)
        self.window.move(100, 100)
        self.root = QWidget()
        self.layout = QVBoxLayout(self.root)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.titlebar = TitleBar(self.window)
        self.layout.addWidget(self.titlebar)
        self.input = QLineEdit()
        self.input.setPlaceholderText("synthetic input")
        self.layout.addWidget(self.input)
        self.layout.addStretch()
        self.window.setCentralWidget(self.root)
        self.window.show()
        self.application.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def global_point(self, x, y):
        return self.window.mapToGlobal(QPoint(x, y))

    def test_window_flags_and_shell_contract(self):
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(self.window.windowType(), Qt.WindowType.Window)
        self.assertTrue(self.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual(self.root.objectName(), "windowShell")
        self.assertFalse(self.root.property("windowMaximized"))
        self.assertEqual(self.titlebar.title_label.text(), "交我聊")
        self.assertEqual(self.titlebar.title_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(self.titlebar.minimize_button.objectName(), "windowControl")
        self.assertEqual(self.titlebar.maximize_button.objectName(), "windowControl")
        self.assertEqual(self.titlebar.close_button.objectName(), "windowClose")
        self.assertIsInstance(self.titlebar.close_button, QPushButton)

    def test_click_minimize_maximize_restore_and_close(self):
        normal_size = self.window.size()
        QTest.mouseClick(self.titlebar.minimize_button, Qt.MouseButton.LeftButton)
        self.application.processEvents()
        self.assertTrue(self.window.isMinimized())
        self.window.showNormal()
        QTest.mouseClick(self.titlebar.maximize_button, Qt.MouseButton.LeftButton)
        self.application.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.assertEqual(self.titlebar.maximize_button.toolTip(), "还原")
        self.assertEqual(self.titlebar.maximize_button.accessibleName(), "还原")
        QTest.mouseClick(self.titlebar.maximize_button, Qt.MouseButton.LeftButton)
        self.application.processEvents()
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.size(), normal_size)
        self.assertEqual(self.titlebar.maximize_button.toolTip(), "最大化")
        QTest.mouseClick(self.titlebar.close_button, Qt.MouseButton.LeftButton)
        self.application.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_external_state_change_updates_tooltip_and_square_mask(self):
        self.window.showMaximized()
        self.application.processEvents()
        self.assertEqual(self.titlebar.maximize_button.toolTip(), "还原")
        self.assertTrue(self.root.property("windowMaximized"))
        self.assertTrue(self.window.mask().isEmpty())
        self.assertTrue(self.root.mask().isEmpty())
        self.assertFalse(self.window.hit_test(self.global_point(1, 100)))
        self.window.showNormal()
        self.application.processEvents()
        self.assertEqual(self.titlebar.maximize_button.toolTip(), "最大化")
        self.assertFalse(self.root.property("windowMaximized"))
        self.assertFalse(self.window.mask().isEmpty())

    def test_round_masks_follow_multiple_sizes_and_exclude_corners(self):
        for width, height in ((640, 400), (900, 650), (420, 280)):
            self.window.resize(width, height)
            self.application.processEvents()
            for widget in (self.window, self.root):
                with self.subTest(size=(width, height), widget=widget.objectName()):
                    mask = widget.mask()
                    self.assertEqual(mask.boundingRect(), widget.rect())
                    self.assertFalse(mask.contains(QPoint(0, 0)))
                    self.assertFalse(mask.contains(QPoint(widget.width() - 1, 0)))
                    self.assertFalse(mask.contains(QPoint(0, widget.height() - 1)))
                    self.assertFalse(mask.contains(QPoint(widget.width() - 1, widget.height() - 1)))
                    self.assertTrue(mask.contains(QPoint(widget.width() // 2, 0)))
                    self.assertTrue(mask.contains(QPoint(0, widget.height() // 2)))
                    self.assertTrue(mask.contains(QPoint(7, 7)))
            self.assertFalse(self.window.hit_test(self.global_point(0, 0)))
            self.assertIsNone(self.root.childAt(QPoint(0, 0)))

    def test_opaque_child_cannot_paint_outside_rounded_shell(self):
        opaque = QWidget(self.root)
        opaque.setGeometry(self.root.rect())
        opaque.setStyleSheet("background: #ff0000;")
        opaque.show()
        self.application.processEvents()
        image = self.window.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(image.width() - 1, image.height() - 1).alpha(), 0)
        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2), QColor("#ff0000"))

    def test_hit_test_uses_global_logical_coordinates(self):
        self.assertEqual(self.window.hit_test(QPointF(self.global_point(0, 200))), Qt.Edge.LeftEdge)
        self.assertEqual(self.window.hit_test(self.global_point(639, 200)), Qt.Edge.RightEdge)
        self.assertEqual(self.window.hit_test(self.global_point(320, 0)), Qt.Edge.TopEdge)
        self.assertEqual(self.window.hit_test(self.global_point(320, 399)), Qt.Edge.BottomEdge)
        self.assertEqual(self.window.hit_test(self.global_point(7, 7)), Qt.Edge.TopEdge | Qt.Edge.LeftEdge)
        self.assertEqual(self.window.hit_test(self.global_point(632, 392)), Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
        self.assertFalse(self.window.hit_test(self.global_point(-1, 200)))
        self.assertFalse(self.window.hit_test(self.global_point(640, 200)))
        self.assertFalse(self.window.hit_test(self.global_point(320, 200)))

    def test_buttons_and_custom_actions_win_over_resize_edges(self):
        # Deliberately place controls within the 8px edge: the buttons must win.
        self.titlebar.layout().setContentsMargins(12, 1, 0, 1)
        self.titlebar.setFixedHeight(34)
        action = self.titlebar.add_action(QPushButton("synthetic action"))
        self.application.processEvents()
        for button in (self.titlebar.minimize_button, self.titlebar.maximize_button,
                       self.titlebar.close_button, action):
            point = button.mapToGlobal(QPoint(button.width() // 2, 1))
            self.assertTrue(resize_edges(self.window.mapFromGlobal(point), self.window.rect()))
            self.assertFalse(self.window.hit_test(point))
        self.assertLess(action.geometry().right(), self.titlebar.minimize_button.geometry().left())
        point = self.titlebar.close_button.mapToGlobal(QPoint(self.titlebar.close_button.width() - 1, 16))
        self.assertFalse(self.window.hit_test(point))

    def test_input_on_border_is_editable_and_does_not_resize(self):
        handle = self.window.windowHandle()
        with patch.object(handle, "startSystemResize", return_value=True) as resize:
            QTest.mouseClick(self.input, Qt.MouseButton.LeftButton, pos=QPoint(1, self.input.height() // 2))
            QTest.keyClicks(self.input, "synthetic")
            resize.assert_not_called()
        self.assertEqual(self.input.text(), "synthetic")
        self.assertFalse(self.window.hit_test(self.input.mapToGlobal(QPoint(1, 1))))

    def test_border_starts_system_resize_and_middle_does_not(self):
        handle = self.window.windowHandle()
        with patch.object(handle, "startSystemResize", return_value=True) as resize:
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=QPoint(1, 200))
            resize.assert_called_once_with(Qt.Edge.LeftEdge)
            resize.reset_mock()
            QTest.mouseClick(self.root, Qt.MouseButton.LeftButton, pos=QPoint(320, 200))
            resize.assert_not_called()

    def test_fixed_dimension_disables_only_that_resize_axis(self):
        self.window.setFixedWidth(self.window.width())
        self.assertFalse(self.window.hit_test(self.global_point(1, 200)))
        self.assertEqual(self.window.hit_test(self.global_point(7, 7)), Qt.Edge.TopEdge)

    def test_title_drag_uses_system_move_and_not_actions(self):
        action = self.titlebar.add_action(QPushButton("action"))
        self.application.processEvents()
        handle = self.window.windowHandle()
        with patch.object(handle, "startSystemMove", return_value=True) as move:
            QTest.mouseClick(self.titlebar, Qt.MouseButton.LeftButton, pos=QPoint(250, 24))
            move.assert_called_once_with()
            move.reset_mock()
            QTest.mouseClick(action, Qt.MouseButton.LeftButton)
            move.assert_not_called()
            QTest.mouseClick(self.input, Qt.MouseButton.LeftButton)
            move.assert_not_called()

    def test_double_click_empty_title_toggles_state(self):
        QTest.mouseDClick(self.titlebar, Qt.MouseButton.LeftButton, pos=QPoint(250, 24))
        self.application.processEvents()
        self.assertTrue(self.window.isMaximized())
        QTest.mouseDClick(self.titlebar, Qt.MouseButton.LeftButton, pos=QPoint(250, 24))
        self.application.processEvents()
        self.assertFalse(self.window.isMaximized())

    def test_brand_replaces_default_title_and_icon(self):
        pixmap = QPixmap(24, 24)
        pixmap.fill(QColor("#008080"))
        self.window.setWindowIcon(QIcon(pixmap))
        self.assertFalse(self.titlebar.icon_label.isHidden())
        brand = self.titlebar.add_brand(QLabel("Synthetic brand"))
        self.application.processEvents()
        self.assertTrue(self.titlebar.icon_label.isHidden())
        self.assertTrue(self.titlebar.title_label.isHidden())
        self.assertTrue(brand.isVisible())
        self.window.setWindowIcon(QIcon(pixmap))
        self.assertTrue(self.titlebar.icon_label.isHidden())

    def test_escape_does_not_close_and_alt_f4_does(self):
        self.window.activateWindow()
        self.input.setFocus()
        self.application.processEvents()
        QTest.keyClick(self.input, Qt.Key.Key_Escape)
        self.assertTrue(self.window.isVisible())
        QTest.keyClick(self.input, Qt.Key.Key_F4, Qt.KeyboardModifier.AltModifier)
        self.application.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_close_button_respects_close_event_veto(self):
        from PySide6.QtGui import QCloseEvent
        with patch.object(self.window, "closeEvent", side_effect=QCloseEvent.ignore) as close:
            QTest.mouseClick(self.titlebar.close_button, Qt.MouseButton.LeftButton)
            self.assertTrue(close.called)
            self.assertTrue(self.window.isVisible())

    def test_other_windows_are_not_intercepted(self):
        other = QWidget()
        other.resize(400, 300)
        other.show()
        self.application.processEvents()
        try:
            with patch.object(self.window.windowHandle(), "startSystemResize", return_value=True) as resize:
                QTest.mouseClick(other, Qt.MouseButton.LeftButton, pos=QPoint(1, 100))
                resize.assert_not_called()
        finally:
            other.close()
            other.deleteLater()

    def test_fullscreen_has_square_corners_and_no_resize(self):
        self.window.showFullScreen()
        self.application.processEvents()
        self.assertTrue(self.window.mask().isEmpty())
        self.assertTrue(self.root.mask().isEmpty())
        self.assertFalse(self.window.hit_test(self.global_point(1, 100)))

    @unittest.skipUnless(sys.platform == "win32", "Windows native message conversion")
    def test_native_hit_test_signed_screen_coordinates_and_dpi(self):
        from ctypes import wintypes
        message = wintypes.MSG()
        message.hWnd = 123
        message.message = 0x0084
        # Negative-origin monitor; Qt screen origins need not equal native/dpr.
        message.lParam = ((-300 & 0xFFFF) << 16) | (-1500 & 0xFFFF)
        with patch("teachmechat.desktop.chrome._native_client_position", return_value=QPoint(3, 300)) as convert:
            with patch.object(self.window, "devicePixelRatioF", return_value=1.5):
                handled, hit = self.window.nativeEvent(b"windows_generic_MSG", ctypes.addressof(message))
        self.assertTrue(handled)
        self.assertEqual(hit, 10)  # HTLEFT
        convert.assert_called_once_with(123, -1500, -300)

    def test_native_mapping_divides_client_offset_not_global_screen_origin(self):
        for scale in (1.0, 1.25, 1.5, 2.0):
            with self.subTest(scale=scale):
                with patch("teachmechat.desktop.chrome._native_client_position", return_value=QPoint(round(4 * scale), round(200 * scale))):
                    with patch.object(self.window, "devicePixelRatioF", return_value=scale):
                        position = self.window._native_global_position(123, -1500, -300)
                        self.assertEqual(position, self.global_point(4, 200))
                        self.assertEqual(self.window.hit_test(position), Qt.Edge.LeftEdge)


if __name__ == "__main__":
    unittest.main()
