import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from teachmechat.models import Advice, ChatMessage, ProviderConfig
from teachmechat.services import RequestBudget, OperationCancelled, analyze_context


class CancellationBoundaryTests(unittest.TestCase):
    def test_stop_after_media_never_calls_generation(self):
        budget = RequestBudget(limit=2)
        processor = MagicMock()
        def process(messages):
            budget.cancelled.set()
            return messages
        processor.process.side_effect = process
        with patch("teachmechat.coach.generate_advice") as generate:
            with self.assertRaises(OperationCancelled):
                analyze_context(MagicMock(), processor, [], "fake", budget)
            generate.assert_not_called()

    def test_retry_attempts_share_budget(self):
        budget = RequestBudget(limit=2)
        budget.before_request()
        budget.before_request()
        with self.assertRaises(Exception):
            budget.before_request()
        self.assertEqual(budget.count, 2)


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from teachmechat.desktop.theme import apply_theme
        cls.application = QApplication.instance() or QApplication([])
        apply_theme(cls.application)

    def setUp(self):
        from teachmechat.desktop.window import MainWindow
        self.temp = tempfile.TemporaryDirectory()
        self.window = MainWindow(Path(self.temp.name), demo=True)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()
        self.temp.cleanup()

    def test_demo_does_not_read_configuration_or_start_worker(self):
        self.assertEqual(self.window.actors, [])
        self.assertIn("示例", self.window.status.text())
        self.assertEqual(len(self.window.reply_labels), 3)

    def test_model_text_is_plain_not_html(self):
        from PySide6.QtCore import Qt
        self.window.display_advice(Advice(["<img src=x>", "b", "c"], "<script>bad</script>", "well"))
        self.assertEqual(self.window.reply_labels[0].textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<script>", self.window.analysis.toPlainText())

    def test_copy_requires_user_action_and_exact_text(self):
        clipboard = self.application.clipboard()
        clipboard.setText("sentinel")
        self.window.display_advice(Advice(["reply", "b", "c"], "a", "w"))
        self.assertEqual(clipboard.text(), "sentinel")
        self.window.copy_reply(0)
        self.assertEqual(clipboard.text(), "reply")

    def test_previous_conversation_read_is_discarded(self):
        self.window.demo = False
        actor = MagicMock()
        self.window.source_actor = actor
        self.window.selected_id = "new"
        before = self.window.context.toPlainText()
        self.window._source_event(actor, "messages", ("old", [ChatMessage("1", 100, "old", "private-old")]))
        self.assertEqual(self.window.context.toPlainText(), before)

    def test_invalid_source_revokes_consent_and_worker(self):
        self.window.consent = True
        self.window.source_valid = True
        actor = MagicMock()
        self.window.analysis_actor = actor
        self.window._invalidate("expired")
        actor.stop.assert_called_once()
        self.assertFalse(self.window.source_valid)
        self.assertFalse(self.window.consent)
        self.assertIsNone(self.window.analysis_actor)

    def test_pause_cancels_analysis_without_touching_wechat(self):
        actor = MagicMock()
        self.window.analysis_actor = actor
        self.window.toggle_pause()
        actor.stop.assert_called_once()
        self.assertTrue(self.window.paused)

    def test_saved_profile_reopens_without_configuration_dialog(self):
        from teachmechat.settings import Settings
        from teachmechat.desktop.window import MainWindow
        directory = Path(self.temp.name) / "config"
        Settings(directory).save_profiles(ProviderConfig(provider="glm", base_url="https://open.bigmodel.cn/api/paas/v4",
                                                         model="synthetic-model", api_key="synthetic-only"),
                                          remember_keys=True, options={"auto_refresh": False, "request_budget": 7})
        window = MainWindow(Path(self.temp.name), config_dir=directory, demo=True)
        try:
            with patch.object(window, "open_settings") as setup:
                window._load_configuration()
                setup.assert_not_called()
            self.assertEqual(window.primary.api_key, "synthetic-only")
            self.assertEqual(window.primary.provider, "glm")
            self.assertFalse(window.auto.isChecked())
            self.assertEqual(window.options["request_budget"], 7)
        finally:
            window.close()
            window.deleteLater()

    def test_process_actor_uses_fake_context_and_stops_own_worker(self):
        from teachmechat.desktop.tasks import ProcessActor
        from teachmechat.desktop.workers import source_worker
        import time
        actor = ProcessActor(source_worker, Path(self.temp.name), deadline=10)
        received = []
        actor.received.connect(lambda kind, data: received.append((kind, data)))
        try:
            self.assertTrue(actor.submit("open", {"mode": "manual"}))
            deadline = time.monotonic() + 10
            while not received and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(.01)
            self.assertTrue(received)
            self.assertEqual(received[0][0], "opened")
            self.assertTrue(actor.submit("recent", "synthetic-chat"))
            deadline = time.monotonic() + 5
            while len(received) < 2 and time.monotonic() < deadline:
                self.application.processEvents()
                time.sleep(.01)
            self.assertEqual(received[1], ("messages", ("synthetic-chat", [])))
        finally:
            actor.stop()
            actor.dispose()
            self.assertFalse(actor.process.is_alive())

    def test_chat_preview_summarizes_xml_without_mutating_context(self):
        from PySide6.QtWidgets import QLabel
        from PySide6.QtCore import Qt
        original = '<msg><appmsg><title>周末散步</title><des>安静的路线</des><type>5</type><url>https://example.com/path?token=secret</url></appmsg></msg>'
        message = ChatMessage("safe", 100, "wxid_example", original, kind="other")
        self.window.chat_title.setText("小林")
        self.window.selected_id = "wxid_example"
        self.window.messages = [message]
        self.window._render_context([message])
        text = self.window.context.toPlainText()
        self.assertIn("小林", text)
        self.assertIn("周末散步", text)
        self.assertNotIn("<msg>", text)
        self.assertNotIn("token=secret", text)
        self.assertNotIn("wxid_example", text)
        self.assertEqual(message.text, original)
        for item in self.window.context.findChildren(QLabel):
            self.assertEqual(item.textFormat(), Qt.TextFormat.PlainText)

    def test_unchanged_chat_preserves_scroll_and_widgets(self):
        messages = [ChatMessage(str(i), 100 + i, "friend", "内容" * 10) for i in range(100)]
        self.window.show()
        self.window._render_context(messages)
        self.application.processEvents()
        bar = self.window.context.verticalScrollBar()
        bar.setValue(20)
        rows = list(self.window.context._bubbles)
        self.window._render_context(messages)
        self.application.processEvents()
        self.assertEqual(bar.value(), 20)
        self.assertEqual(rows, self.window.context._bubbles)

    def test_switch_chat_clears_old_suggestions(self):
        self.window.display_advice(Advice(["old-one", "old-two", "old-three"], "old-analysis", "well"))
        self.window._invalidate("switch")
        self.assertNotIn("old-one", self.window.reply_labels[0].text())
        self.assertEqual(self.window.analysis.toPlainText(), "")
        self.assertTrue(all(not button.isEnabled() for button in self.window.copy_buttons))

    def test_quick_connect_does_not_open_advanced_source_dialog(self):
        from PySide6.QtWidgets import QMessageBox
        with patch("teachmechat.desktop.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            with patch.object(self.window, "connect_source") as connect:
                with patch.object(self.window, "open_source") as advanced:
                    self.window.quick_connect()
                    connect.assert_called_once_with({"mode": "auto"})
                    advanced.assert_not_called()

    def test_no_consent_prompt_before_selecting_conversation(self):
        self.window.demo = False
        self.window.source_ready = True
        self.window.manual = False
        self.window.selected_id = ""
        with patch("teachmechat.desktop.window.QMessageBox") as prompt:
            self.window.generate()
            prompt.assert_not_called()
        self.assertIn("先选", self.window.status.text())

    def test_cancelling_settings_restores_previous_pause_state(self):
        self.window.paused = False
        with patch("teachmechat.desktop.dialogs.SettingsDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            self.assertFalse(self.window.open_settings())
        self.assertFalse(self.window.paused)
        self.assertEqual(self.window.pause_button.text(), "暂停")

    def test_palette_is_muted_not_black_or_white(self):
        from PySide6.QtGui import QPalette
        from teachmechat.desktop.theme import COLORS
        palette = self.application.palette()
        self.assertEqual(palette.color(QPalette.ColorRole.Window).name(), COLORS["canvas"])
        self.assertGreater(palette.color(QPalette.ColorRole.Window).lightness(), 150)
        self.assertLess(palette.color(QPalette.ColorRole.Window).lightness(), 210)
        self.assertLess(palette.color(QPalette.ColorRole.Text).lightness(), 100)

    def test_compact_layout_removes_repeated_copy_and_native_title(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel
        self.window.show()
        self.application.processEvents()
        visible = [w.text() for w in self.window.findChildren(QLabel) if w.isVisible()]
        for old in ("想好再说，自在表达。", "换一种更舒服的表达", "你的选择，才会进入分析。", "只帮你起草，不替你发送。"):
            self.assertNotIn(old, visible)
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(self.window.centralWidget().objectName(), "windowShell")
        self.assertEqual(self.window.generate_button.text(), "换一组")

    def test_empty_suggestions_show_one_placeholder_not_three_cards(self):
        self.window._invalidate("changed")
        self.assertFalse(self.window.reply_empty.isHidden())
        self.assertTrue(all(card.isHidden() for card in self.window.reply_cards))
        self.window.display_advice(Advice(["1", "2", "3"], "a", "b"))
        self.assertTrue(self.window.reply_empty.isHidden())
        self.assertTrue(all(not card.isHidden() for card in self.window.reply_cards))

    def test_model_list_results_do_not_cross_targets_or_request_generations(self):
        actors = [MagicMock(), MagicMock(), MagicMock()]
        for actor in actors:
            actor.received.connect = MagicMock()
            actor.failed.connect = MagicMock()
        dialog = MagicMock()
        config = ProviderConfig(api_key="synthetic", model="")
        with patch.object(self.window, "_actor", side_effect=actors):
            self.window._fetch_models(dialog, config, "primary")
            old_callback = actors[0].received.connect.call_args.args[0]
            self.window._fetch_models(dialog, config, "primary")
            current_callback = actors[1].received.connect.call_args.args[0]
            self.window._fetch_models(dialog, config, "vision")
            vision_callback = actors[2].received.connect.call_args.args[0]
        old_callback("models", ["old"])
        dialog.set_models.assert_not_called()
        current_callback("models", ["new"])
        dialog.set_models.assert_called_with(["new"], target="primary")
        vision_callback("error", ("safe failure", 0))
        dialog.set_models.assert_called_with([], error="safe failure", target="vision")
        self.assertEqual(actors[0].submit.call_args.args[0], "models")
        self.assertEqual(actors[0].submit.call_args.args[1]["primary"].model, "")

    def test_context_presets_custom_and_worker_payload(self):
        window = self.window
        window._reload_source_spec = None
        window.context_limit_combo.setCurrentIndex(window.context_limit_combo.findData(1000))
        self.assertEqual(window.options["context_limit"], 1000)
        self.assertFalse(window.consent)
        window.context_limit_combo.setCurrentIndex(4)
        window.context_custom.setValue(750)
        self.assertEqual(window.options["context_limit"], 750)
        actor = MagicMock()
        actor.busy = False
        window.source_actor = actor
        window.selected_id = "synthetic"
        window.pending_read = True
        window._dispatch_read()
        actor.submit.assert_called_once_with("recent", {"conversation_id": "synthetic", "limit": 750})

    def test_context_custom_restores_and_saved_changes_preserve_key(self):
        from teachmechat.settings import Settings
        config = Path(self.temp.name) / "context-config"
        window = self.window
        window.config_dir = config
        window._save_mode = "remember"
        window.context_limit_combo.setCurrentIndex(window.context_limit_combo.findData(500))
        primary, _, options = Settings(config).load_profiles()
        self.assertEqual(options["context_limit"], 500)
        self.assertEqual(primary.api_key, window.primary.api_key)
        window.options["context_limit"] = 777
        window._restore_context_limit()
        self.assertEqual(window.context_limit_combo.currentIndex(), 4)
        self.assertEqual(window.context_custom.value(), 777)

    def test_connect_button_is_circular_lower_sidebar_and_keyboard_accessible(self):
        from PySide6.QtCore import QPoint, Qt
        self.window.show()
        self.application.processEvents()
        button = self.window.connect_button
        self.assertTrue(button.hitButton(QPoint(47, 46)))
        self.assertFalse(button.hitButton(QPoint(0, 0)))
        self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.StrongFocus)
        self.assertGreater(button.mapTo(self.window, QPoint(0, 0)).y(), self.window.height() / 2)
        self.assertLess(button.width(), 110)

    def test_unchanged_sync_keeps_completed_answer_expression(self):
        from teachmechat.scheduler import fingerprint
        messages = [ChatMessage("1", 100, "synthetic", "hello")]
        window = self.window
        actor = MagicMock()
        window.source_actor = actor
        window.selected_id = "synthetic"
        window.wechat_connected = True
        window.success_hash = fingerprint(messages, window.background.toPlainText())
        window._source_event(actor, "messages", ("synthetic", messages))
        self.assertEqual(window.status.state, "answered")
        self.assertEqual(window.status.head.expression, "smile")
        window._source_event(actor, "messages", ("synthetic", messages + [ChatMessage("2", 101, "synthetic", "new")]))
        self.assertEqual(window.status.head.expression, "neutral")

    def test_desktop_refresh_is_five_seconds_and_control_is_in_chat_header(self):
        from teachmechat.desktop.refresh_controls import RefreshSwitch
        from PySide6.QtCore import QPoint
        window = self.window
        window.show()
        self.application.processEvents()
        self.assertIsInstance(window.auto, RefreshSwitch)
        self.assertLess(window.auto.mapTo(window, QPoint(0, 0)).y(), 200)
        self.assertLess(window.refresh_button.mapTo(window, QPoint(0, 0)).y(), 200)
        actor = MagicMock()
        actor.busy = False
        window.source_actor = actor
        window.selected_id = "synthetic"
        window.pending_read = True
        with patch("teachmechat.desktop.window.time.monotonic", return_value=10):
            window._dispatch_read()
        self.assertEqual(window.next_refresh, 15)
        self.assertEqual(window.background_toggle.objectName(), "raised")

    def test_analysis_generation_turns_red_light_on(self):
        window = self.window
        window.consent = window.source_valid = True
        window.pending_read = False
        window.analysis_actor = None
        window.source_actor = None
        with patch.object(window, "_actor", return_value=MagicMock()):
            window._analyze_if_needed()
        self.assertEqual(window.status.state, "generating")
        self.assertTrue(window.status.red.lit)
        self.assertFalse(window.status.green.lit)

    def test_generation_waits_for_fresh_read(self):
        self.window.demo = False
        self.window.consent = self.window.source_valid = True
        self.window.pending_read = True
        with patch.object(self.window, "_actor") as create:
            self.window._analyze_if_needed()
            create.assert_not_called()
