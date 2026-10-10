"""Offscreen scroll regressions using synthetic messages only."""
import os
import time
import unittest
from unittest.mock import patch

from teachmechat.runtime import configure_runtime

configure_runtime()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel
from teachmechat.desktop.chat_view import ChatView
from teachmechat.desktop.theme import apply_theme
from teachmechat.models import ChatMessage


def fake_messages(count, long=True):
    text = ("合成测试内容 synthetic wrapped text <b>plain</b> " * 18 if long else "synthetic message")
    return [ChatMessage(str(i), 1700000000 + i * 600, "synthetic", f"{i} {text}",
                        outgoing=bool(i % 2)) for i in range(count)]


class ChatScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        self.view = ChatView()
        self.view.resize(620, 680)
        self.view.show()
        self.settle()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def settle(self):
        deadline = time.monotonic() + 90
        stable = 0
        while stable < 4 and time.monotonic() < deadline:
            self.app.processEvents()
            pending = self.view._batch_timer.isActive() or self.view._fit_timer.isActive()
            stable = 0 if pending else stable + 1
        self.assertEqual(stable, 4, "finite layout/batch work did not settle")

    def assert_bottom(self):
        bar = self.view.verticalScrollBar()
        self.assertEqual(bar.value(), bar.maximum())
        last = self.view._bubbles[-1]
        bottom = last.mapTo(self.view.viewport(), QPoint(0, last.height())).y()
        gap = self.view.viewport().height() - bottom
        self.assertGreaterEqual(gap, 0)
        self.assertLessEqual(gap, 20, f"last message leaves {gap}px below it")
        self.assertEqual(self.view.canvas.width(), self.view.viewport().width())

    def test_first_load_long_300_and_500_bottom_and_resize(self):
        for count in (300, 500):
            with self.subTest(count=count):
                self.view.clear()
                self.view.set_messages(fake_messages(count), "Synthetic", "fake")
                self.settle()
                self.assertEqual(len(self.view._bubbles), count)
                self.assert_bottom()
                for width in (360, 1000, 470):
                    self.view.resize(width, 700)
                    self.settle()
                    self.assert_bottom()
                for stack in self.view._bubbles:
                    for label in stack.findChildren(QLabel):
                        self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)
                        self.assertFalse(label.openExternalLinks())

    def test_short_chat_is_bottom_aligned_and_append_pushes_old_up(self):
        messages = fake_messages(1, long=False)
        self.view.set_messages(messages, "Synthetic", "fake")
        self.settle()
        self.assert_bottom()
        first = self.view._bubbles[0]
        old_y = first.mapTo(self.view.viewport(), QPoint()).y()
        self.view.set_messages(fake_messages(2, long=False), "Synthetic", "fake")
        self.settle()
        self.assertIs(self.view._bubbles[0], first)
        self.assertLess(first.mapTo(self.view.viewport(), QPoint()).y(), old_y)
        self.assert_bottom()

    def test_unchanged_no_rebuild_no_jump_and_append_follows(self):
        messages = fake_messages(300)
        self.view.set_messages(messages, "Synthetic", "fake")
        self.settle()
        rows = list(self.view._bubbles)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        previous = bar.value()
        with patch.object(self.view, "_fit", wraps=self.view._fit) as fit:
            self.view.set_messages(messages, "Synthetic", "fake")
            self.settle()
            fit.assert_not_called()
        self.assertEqual(rows, self.view._bubbles)
        self.assertEqual(bar.value(), previous)
        bar.setValue(bar.maximum())
        self.view.set_messages(fake_messages(301), "Synthetic", "fake")
        self.settle()
        self.assertEqual(rows, self.view._bubbles[:300])
        self.assert_bottom()

    def test_history_anchor_preserved_on_append_and_rewrap(self):
        self.view.set_messages(fake_messages(300), "Synthetic", "fake")
        self.settle()
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        anchor, offset = self.view._anchor()
        previous = bar.value()
        self.view.set_messages(fake_messages(305), "Synthetic", "fake")
        self.settle()
        self.assertEqual(bar.value(), previous)
        self.assertEqual(anchor.mapTo(self.view.viewport(), QPoint()).y(), offset)
        for width in (400, 900):
            self.view.resize(width, 700)
            self.settle()
            self.assertEqual(anchor.mapTo(self.view.viewport(), QPoint()).y(), offset)
            self.assertLess(bar.value(), bar.maximum())

    def test_large_load_batches_and_incremental_append(self):
        for count in (1000, 5000):
            with self.subTest(count=count):
                self.view.clear()
                messages = fake_messages(count, long=False)
                self.view.set_messages(messages, "Synthetic", "fake")
                self.assertLessEqual(len(self.view._bubbles), self.view._BATCH_SIZE)
                self.assertTrue(self.view._batch_timer.isActive())
                self.settle()
                self.assertEqual(len(self.view._bubbles), count)
                self.assert_bottom()
                first, last = self.view._bubbles[0], self.view._bubbles[-1]
                with patch.object(self.view, "_append_message", wraps=self.view._append_message) as append:
                    self.view.set_messages(fake_messages(count + 1, long=False), "Synthetic", "fake")
                    self.settle()
                    self.assertEqual(append.call_count, 1)
                self.assertIs(first, self.view._bubbles[0])
                self.assertIs(last, self.view._bubbles[-2])
                self.assert_bottom()

    def test_clear_and_replacement_cancel_pending_load(self):
        self.view.set_messages(fake_messages(500), "Synthetic", "fake")
        self.assertTrue(self.view._batch_timer.isActive())
        self.view.clear()
        self.settle()
        self.assertEqual(self.view._bubbles, [])
        self.assertEqual(self.view.toPlainText(), "")
        self.view.set_messages(fake_messages(500), "Synthetic", "fake")
        self.view.set_messages(fake_messages(2, long=False), "Other", "other")
        self.settle()
        self.assertEqual(len(self.view._bubbles), 2)
        self.assert_bottom()
        self.view.setPlainText("<img src=synthetic> literal")
        self.settle()
        self.assertEqual(self.view.toPlainText(), "<img src=synthetic> literal")

    def test_suffix_edit_and_pending_refresh_reuse_prefix(self):
        messages = fake_messages(300, long=False)
        self.view.set_messages(messages, "Synthetic", "fake")
        prefix = list(self.view._bubbles)
        self.view.set_messages(fake_messages(301, long=False), "Synthetic", "fake")
        self.settle()
        self.assertEqual(prefix, self.view._bubbles[:len(prefix)])
        self.assertEqual(len(self.view._bubbles), 301)
        self.assert_bottom()
        messages = fake_messages(301, long=False)
        rows = list(self.view._bubbles)
        messages[-1].text = "Synthetic edit <script>plain</script>"
        self.view.set_messages(messages, "Synthetic", "fake")
        self.settle()
        self.assertEqual(rows[:-1], self.view._bubbles[:-1])
        self.assertIn("Synthetic edit", self.view.toPlainText())
        self.assert_bottom()
        # A snapshot must notice mutation of the same source object.
        messages[-1].text = "Synthetic second edit"
        self.view.set_messages(messages, "Synthetic", "fake")
        self.settle()
        self.assertIn("Synthetic second edit", self.view.toPlainText())

    def test_rolling_recent_window_reuses_overlap_and_history_anchor(self):
        messages = fake_messages(310)
        self.view.set_messages(messages[:300], "Synthetic", "fake")
        self.settle()
        rows = list(self.view._bubbles)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum() // 2)
        anchor, offset = self.view._anchor()
        self.view.set_messages(messages[10:], "Synthetic", "fake")
        self.settle()
        self.assertEqual(rows[10:], self.view._bubbles[:290])
        self.assertEqual(anchor.mapTo(self.view.viewport(), QPoint()).y(), offset)
        self.assertLess(bar.value(), bar.maximum())
        bar.setValue(bar.maximum())
        self.assert_bottom()

    def test_hidden_first_load_and_empty_unchanged(self):
        self.view.hide()
        self.view.set_messages(fake_messages(300), "Synthetic", "fake")
        self.settle()
        self.view.resize(450, 600)
        self.view.show()
        self.settle()
        self.assert_bottom()
        self.view.set_messages([], "Synthetic", "fake")
        self.settle()
        children = self.view.canvas.findChildren(QLabel)
        self.view.set_messages([], "Synthetic", "fake")
        self.settle()
        self.assertEqual(children, self.view.canvas.findChildren(QLabel))


if __name__ == "__main__":
    unittest.main()
