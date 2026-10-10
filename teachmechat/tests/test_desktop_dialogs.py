"""Offscreen dialog checks using synthetic configs, paths and file-picker results."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QWidget
    from teachmechat.desktop.dialogs import ModelCombo, ProviderForm, SettingsDialog, SourceDialog
    from teachmechat.desktop.theme import apply_theme
    QT_AVAILABLE = True
except ModuleNotFoundError as exc:
    if exc.name != "PySide6":
        raise
    QT_AVAILABLE = False

from teachmechat import model_catalog
from teachmechat.models import ProviderConfig, TeachMeChatError
from teachmechat.provider_specs import PROVIDERS


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is optional outside the desktop environment")
class DesktopDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._previous_style = cls.app.style().objectName()
        cls._previous_font = cls.app.font()
        cls._previous_stylesheet = cls.app.styleSheet()
        cls._previous_icon = cls.app.windowIcon()
        apply_theme(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyle(cls._previous_style)
        cls.app.setFont(cls._previous_font)
        cls.app.setStyleSheet(cls._previous_stylesheet)
        cls.app.setWindowIcon(cls._previous_icon)

    def setUp(self):
        self.widgets = []
        # A real settings file, user database or network request is never needed.
        for target in ("builtins.open", "pathlib.Path.open", "pathlib.Path.read_text", "pathlib.Path.write_text",
                       "pathlib.Path.mkdir", "teachmechat.providers.LLMClient",
                       "socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("Unexpected disk or API access"))
            guard.start()
            self.addCleanup(guard.stop)
        self.primary = ProviderConfig(
            provider="openai", base_url="https://primary.example.invalid/v1", model="gpt-5",
            api_key="fake-primary-secret", reasoning="high", timeout=71.25,
            protocol="openai", structured_mode="prompt", thinking_budget=2048,
        )
        self.vision = ProviderConfig(
            provider="anthropic", base_url="https://vision.example.invalid/v1", model="claude-sonnet-4-5",
            api_key="fake-vision-secret", reasoning="enabled", timeout=29.5,
            protocol="anthropic", structured_mode="native", thinking_budget=4096,
        )

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.processEvents()

    def keep(self, widget):
        self.widgets.append(widget)
        return widget

    def settings(self, options=None, vision=None, primary=None, config_dir=None):
        return self.keep(SettingsDialog(
            primary or self.primary, vision, options or {}, config_dir or Path(r"E:\synthetic\settings")
        ))

    @staticmethod
    def select(combo, value):
        index = combo.findData(value)
        assert index >= 0, value
        combo.setCurrentIndex(index)

    def source(self, mode):
        dialog = self.keep(SourceDialog())
        self.select(dialog.mode_combo, mode)
        return dialog

    @staticmethod
    def authorize(dialog):
        dialog.authorization_check.setChecked(True)

    def test_restore_every_provider_field_options_and_directory(self):
        options = {"vision_enabled": True, "vision_reuse": False, "auto_refresh": True,
                   "whisper_path": r"E:\synthetic\large-v3-turbo.pt", "request_budget": 23,
                   "unrelated_option": "preserved"}
        original_options = dict(options)
        dialog = self.settings(options, vision=self.vision)
        self.assertEqual(dialog.primary_form.to_config(), self.primary)
        self.assertEqual(dialog.vision_form.to_config(), self.vision)
        self.assertEqual(dialog.primary_form.api_key_edit.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(dialog.vision_form.api_key_edit.echoMode(), QLineEdit.EchoMode.Password)
        self.assertGreaterEqual(dialog.minimumWidth(), 720)
        self.assertEqual(dialog.tabs.count(), 3)
        emitted = []
        dialog.configuration_ready.connect(emitted.append)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        result = dialog.result_data
        self.assertEqual(result["primary"], self.primary)
        self.assertEqual(result["vision"], self.vision)
        self.assertIsNot(result["primary"], self.primary)
        self.assertIsNot(result["vision"], self.vision)
        self.assertEqual(result["options"], options)
        self.assertIsNot(result["options"], options)
        self.assertEqual(options, original_options)
        self.assertEqual(result["directory"], Path(r"E:\synthetic\settings"))
        self.assertEqual(result["save_mode"], "remember")
        self.assertEqual(emitted, [result])
        self.assertIsInstance(result["primary"], ProviderConfig)
        self.assertIsInstance(result["directory"], Path)
        self.assertIs(type(result["primary"].timeout), float)
        self.assertIs(type(result["primary"].thinking_budget), int)
        self.assertIs(type(result["options"]["request_budget"]), int)
        for name in ("vision_enabled", "vision_reuse", "auto_refresh"):
            self.assertIs(type(result["options"][name]), bool)
        self.assertIsInstance(result["options"]["whisper_path"], str)

    def test_default_directory_model_placeholder_and_explicit_save_label(self):
        dialog = self.keep(SettingsDialog(None, None, {}, None))
        self.assertEqual(dialog.directory_edit.text(), str(Path(r"C:\TeachMeChat")))
        self.assertEqual(dialog.primary_form.model_edit.text(), "")
        self.assertTrue(dialog.primary_form.model_edit.placeholderText())
        self.assertEqual(dialog.primary_form.api_key_edit.text(), "")
        self.assertEqual(dialog.save_mode_combo.currentData(), "remember")
        self.assertIn("API Key", dialog.save_button.text())
        self.assertIn("加密", dialog.save_button.text())
        self.assertIn("加密", dialog.save_mode_combo.currentText())
        self.assertIn("DPAPI", dialog.save_mode_hint.text())
        self.assertNotIn("保险库", dialog.save_mode_hint.text())
        self.assertNotIn("保险库", dialog.save_button.text())
        self.assertFalse(dialog.storage_summary.isHidden())
        for text in (r"C:\TeachMeChat", "小型配置", "DPAPI", "点击保存后", "不保存聊天", "隐私"):
            self.assertIn(text, dialog.storage_summary.text())
        self.assertEqual([dialog.tabs.tabText(i) for i in range(dialog.tabs.count())], ["服务", "隐私", "媒体"])
        self.assertEqual(dialog.tabs.currentIndex(), 0)
        self.assertIsNone(dialog.result_data)
        self.assertFalse(dialog.auto_refresh_check.isChecked())
        self.assertEqual(dialog.request_budget_spin.value(), 12)
        self.assertFalse(dialog.vision_enabled_check.isChecked())
        self.assertEqual(dialog.styleSheet(), "")

    def test_provider_advanced_controls_are_collapsed_but_preserve_saved_values(self):
        for config in (None, self.primary, self.vision):
            with self.subTest(provider=config.provider if config else "new"):
                form = self.keep(ProviderForm(config))
                form.show()
                self.app.processEvents()
                self.assertEqual(form.advanced_check.text(), "高级参数")
                self.assertFalse(form.advanced_check.isChecked())
                self.assertTrue(form.advanced_group.isHidden())
                for name in ("provider_combo", "model_edit", "reasoning_combo", "api_key_edit", "models_button"):
                    self.assertTrue(getattr(form, name).isVisible())
                for name in ("base_url_edit", "protocol_combo", "structured_combo", "timeout_spin"):
                    field = getattr(form, name)
                    self.assertTrue(form.advanced_group.isAncestorOf(field))
                    self.assertFalse(field.isVisible())
                    self.assertTrue(field.isEnabled())
                self.assertFalse(form.advanced_group.isAncestorOf(form.reasoning_combo))
                self.assertTrue(form.thinking_budget_spin.isHidden())
                form.advanced_check.click()
                self.app.processEvents()
                self.assertTrue(form.advanced_group.isVisible())
                self.assertTrue(form.timeout_spin.isVisible())
                self.assertFalse(form.thinking_budget_spin.isVisible())
                self.assertFalse(any("tokens" in label.text() for label in form.findChildren(QLabel)))
                if config:
                    self.assertEqual(form.to_config(), config)
                form.timeout_spin.setValue(88.5)
                form.thinking_budget_spin.setValue(8192)
                form.advanced_check.click()
                self.assertTrue(form.advanced_group.isHidden())
                self.assertEqual(form.timeout_spin.value(), 88.5)
                self.assertEqual(form.thinking_budget_spin.value(), 8192)
                if config:
                    self.assertEqual(form.to_config(), replace(config, timeout=88.5, thinking_budget=8192))
                self.assertLess(len(form.model_edit.toolTip()), 80)
                self.assertLess(len(form.thinking_budget_spin.toolTip()), 80)

    def test_collapsed_advanced_values_are_still_validated(self):
        for field, value in (("protocol", "unsupported"), ("structured_mode", "unsupported")):
            with self.subTest(field=field):
                dialog = self.settings(primary=replace(self.primary, **{field: value}))
                self.assertTrue(dialog.primary_form.advanced_group.isHidden())
                dialog.accept()
                self.assertIsNone(dialog.result_data)
                self.assertFalse(dialog.error_label.isHidden())
                self.assertEqual(dialog.tabs.currentIndex(), 0)

    def test_first_setup_summary_tracks_explicit_save_mode_and_directory(self):
        dialog = self.keep(SettingsDialog(None, None, {}, None))
        events = []
        dialog.configuration_ready.connect(events.append)
        dialog.directory_edit.setText(r"E:\synthetic\new-config")
        self.assertIn(r"E:\synthetic\new-config", dialog.storage_summary.text())
        self.assertNotIn(r"C:\TeachMeChat", dialog.storage_summary.text())
        self.select(dialog.save_mode_combo, "public")
        self.assertIn("不保存 API Key", dialog.storage_summary.text())
        self.assertNotIn("DPAPI", dialog.storage_summary.text())
        self.select(dialog.save_mode_combo, "session")
        self.assertIn("不写入", dialog.storage_summary.text())
        self.assertIn("不会自动删除", dialog.storage_summary.text())
        self.assertNotIn(r"E:\synthetic\new-config", dialog.storage_summary.text())
        self.assertIsNone(dialog.result_data)
        self.assertEqual(events, [])
        self.assertTrue(self.settings().storage_summary.isHidden())

    def test_unused_vision_fields_are_hidden_without_losing_configuration(self):
        dialog = self.settings({"vision_enabled": False, "vision_reuse": False}, vision=self.vision)
        for widget in (dialog.vision_reuse_check, dialog.vision_group, dialog.vision_probe_row, dialog.vision_hint):
            self.assertTrue(widget.isHidden())
        dialog.vision_enabled_check.click()
        for widget in (dialog.vision_reuse_check, dialog.vision_group, dialog.vision_probe_row, dialog.vision_hint):
            self.assertFalse(widget.isHidden())
        self.assertTrue(dialog.vision_form.advanced_group.isHidden())
        self.assertEqual(dialog.vision_form.to_config(), self.vision)
        dialog.vision_enabled_check.click()
        self.assertEqual(dialog.vision_form.to_config(), self.vision)

    def test_dialogs_inherit_global_theme_and_fit_a_700_pixel_tall_screen(self):
        for dialog in (self.keep(SettingsDialog(None, None, {}, None)), self.settings(),
                       self.settings({"vision_enabled": True, "vision_reuse": False}, vision=self.vision),
                       self.source("auto")):
            with self.subTest(dialog=type(dialog).__name__):
                dialog.show()
                self.app.processEvents()
                self.assertLessEqual(dialog.frameGeometry().height(), 700)
                self.assertLessEqual(dialog.minimumSizeHint().height(), 640)
                self.assertTrue(dialog.rect().contains(dialog.button_box.geometry()))
                for widget in (dialog, *dialog.findChildren(QWidget)):
                    self.assertEqual(widget.styleSheet(), "")
                if isinstance(dialog, SettingsDialog):
                    scroll = dialog.tabs.widget(0)
                    viewport = scroll.viewport()
                    for name in ("provider_combo", "model_edit", "reasoning_combo", "api_key_edit"):
                        field = getattr(dialog.primary_form, name)
                        self.assertTrue(field.isVisible())
                        self.assertGreaterEqual(field.mapTo(viewport, field.rect().topLeft()).y(), 0)
                        self.assertLess(field.mapTo(viewport, field.rect().bottomRight()).y(), viewport.height())
                    dialog.primary_form.advanced_check.click()
                    dialog.vision_form.advanced_check.click()
                    self.app.processEvents()
                    self.assertLessEqual(dialog.frameGeometry().height(), 700)
                    scroll.ensureWidgetVisible(dialog.primary_form.timeout_spin)
                    self.app.processEvents()
                    self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
                    self.assertTrue(dialog.rect().contains(dialog.button_box.geometry()))
                else:
                    for mode in ("manual", "snapshot", "live-manual"):
                        self.select(dialog.mode_combo, mode)
                        self.app.processEvents()
                        self.assertLessEqual(dialog.frameGeometry().height(), 700)
                        self.assertTrue(dialog.rect().contains(dialog.button_box.geometry()))

    def test_opening_modal_dialogs_and_editing_does_not_probe_or_save(self):
        settings = self.settings()
        source = self.source("auto")
        events = []
        settings.probe_requested.connect(lambda *_args: events.append("probe"))
        settings.models_requested.connect(lambda *_args: events.append("models"))
        settings.configuration_ready.connect(lambda *_args: events.append("save"))
        for dialog in (settings, source):
            QTimer.singleShot(0, dialog.reject)
            self.assertEqual(dialog.exec(), QDialog.DialogCode.Rejected)
        self.assertEqual(events, [])
        self.assertIsNone(settings.result_data)
        self.assertIsNone(source.spec)
        settings.primary_form.advanced_check.click()
        self.select(settings.primary_form.provider_combo, "glm")
        self.select(settings.save_mode_combo, "session")
        self.select(source.mode_combo, "live-manual")
        self.assertEqual(events, [])
        self.assertIsNone(settings.result_data)
        self.assertIsNone(source.spec)

    def test_provider_specs_define_all_choices_and_model_hint_is_never_a_value(self):
        form = self.keep(ProviderForm())
        values = {form.provider_combo.itemData(i) for i in range(form.provider_combo.count())}
        self.assertEqual(values, set(PROVIDERS))
        self.assertTrue({"openai", "gemini", "deepseek", "glm", "anthropic", "kimi", "custom"} <= values)
        self.assertEqual([form.provider_combo.itemData(i) for i in range(form.provider_combo.count())],
                         ["openai", "gemini", "deepseek", "glm", "anthropic", "kimi", "custom"])
        for provider, spec in PROVIDERS.items():
            with self.subTest(provider=provider):
                self.select(form.provider_combo, provider)
                self.assertEqual(form.model_edit.text(), "")
                self.assertEqual(form.base_url_edit.text(), spec.base_url)
                self.assertEqual(form.protocol_combo.currentData(), spec.protocol)
                self.assertEqual(tuple(form.reasoning_combo.itemData(i)
                                       for i in range(form.reasoning_combo.count())), spec.reasoning_options)
                if spec.model_hint:
                    self.assertEqual(form.model_edit.placeholderText(), spec.model_hint)

    def test_legacy_alias_and_default_protocol_restore_without_key_loss(self):
        config = replace(self.primary, provider="openai-compatible", reasoning="default", protocol="")
        form = self.keep(ProviderForm(config))
        self.assertEqual(form.provider_combo.currentData(), "custom")
        self.assertEqual(form.to_config(), config)
        self.assertEqual(form.api_key_edit.text(), config.api_key)

    def test_url_or_provider_change_immediately_clears_key_without_mutating_config(self):
        form = self.keep(ProviderForm(self.primary))
        self.assertEqual(form.api_key_edit.text(), self.primary.api_key)
        form.base_url_edit.setText("https://other.example.invalid/v1")
        self.assertEqual(form.api_key_edit.text(), "")
        # Returning to the old address must not resurrect a saved credential.
        form.base_url_edit.setText(self.primary.base_url)
        self.assertEqual(form.api_key_edit.text(), "")
        form.api_key_edit.setText("replacement-fake-key")
        self.select(form.provider_combo, "deepseek")
        self.assertEqual(form.api_key_edit.text(), "")
        self.assertEqual(form.model_edit.text(), "")
        self.assertEqual(self.primary.api_key, "fake-primary-secret")
        self.assertEqual(self.primary.base_url, "https://primary.example.invalid/v1")
        self.assertEqual(self.primary.provider, "openai")

    def test_same_host_path_change_also_clears_key_but_model_change_does_not(self):
        form = self.keep(ProviderForm(self.primary))
        form.model_edit.setText("other-synthetic-model")
        self.assertEqual(form.api_key_edit.text(), self.primary.api_key)
        form.base_url_edit.setText("https://primary.example.invalid/v2")
        self.assertEqual(form.api_key_edit.text(), "")

    def test_independent_vision_is_disabled_unless_opted_in(self):
        dialog = self.settings({"vision_enabled": False, "vision_reuse": False}, vision=self.vision)
        dialog.vision_form.model_edit.clear()
        dialog.vision_form.api_key_edit.clear()
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog.result_data["vision"])
        self.assertFalse(dialog.result_data["options"]["vision_enabled"])

    def test_reused_vision_is_a_distinct_primary_copy(self):
        dialog = self.settings({"vision_enabled": True, "vision_reuse": True}, vision=self.vision)
        dialog.vision_form.model_edit.clear()
        dialog.vision_form.api_key_edit.clear()
        dialog.accept()
        self.assertEqual(dialog.result_data["vision"], dialog.result_data["primary"])
        self.assertIsNot(dialog.result_data["vision"], dialog.result_data["primary"])
        self.assertTrue(dialog.result_data["options"]["vision_reuse"])

    def test_independent_vision_is_validated_and_toggle_preserves_edits(self):
        dialog = self.settings({"vision_enabled": True, "vision_reuse": False}, vision=self.vision)
        dialog.vision_reuse_check.setChecked(True)
        self.assertFalse(dialog.vision_form.isEnabled())
        dialog.vision_reuse_check.setChecked(False)
        self.assertEqual(dialog.vision_form.to_config(), self.vision)
        dialog.vision_form.model_edit.clear()
        dialog.accept()
        self.assertIsNone(dialog.result_data)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertIn("模型", dialog.error_label.text())

    def test_validation_rejects_missing_model_or_key_and_keeps_dialog_open(self):
        for field in ("model_edit", "api_key_edit"):
            with self.subTest(field=field):
                dialog = self.settings()
                getattr(dialog.primary_form, field).clear()
                events = []
                dialog.configuration_ready.connect(events.append)
                dialog.accept()
                self.assertIsNone(dialog.result_data)
                self.assertEqual(events, [])
                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                self.assertFalse(dialog.error_label.isHidden())
                self.assertNotIn(self.primary.api_key, dialog.error_label.text())

    def test_url_errors_are_fixed_plain_text_and_never_echo_credentials(self):
        dialog = self.settings()
        dialog.primary_form.base_url_edit.setText("https://private-user:secret@host.invalid/v1")
        dialog.primary_form.api_key_edit.setText("fake-secret")
        dialog.accept()
        self.assertIsNone(dialog.result_data)
        self.assertIn("API 地址", dialog.error_label.text())
        for secret in ("private-user", "secret@", "fake-secret"):
            self.assertNotIn(secret, dialog.error_label.text())
        self.assertEqual(dialog.error_label.textFormat(), Qt.TextFormat.PlainText)
        dialog.primary_form.base_url_edit.setText("http://remote.example.invalid/v1")
        dialog.primary_form.api_key_edit.setText("fake-secret")
        dialog.accept()
        self.assertIsNone(dialog.result_data)
        dialog.primary_form.base_url_edit.setText("http://localhost:8080/v1/")
        dialog.primary_form.api_key_edit.setText("fake-secret")
        dialog.accept()
        self.assertEqual(dialog.result_data["primary"].base_url, "http://localhost:8080/v1")

    def test_save_modes_collect_only_and_do_not_strip_session_credentials(self):
        for mode, caption in (("remember", "API Key"), ("public", "不含 Key"), ("session", "本次会话")):
            with self.subTest(mode=mode):
                dialog = self.settings({"save_mode": "remember"})
                self.select(dialog.save_mode_combo, mode)
                self.assertIn(caption, dialog.save_button.text())
                dialog.save_button.click()
                self.assertEqual(dialog.result_data["save_mode"], mode)
                self.assertEqual(dialog.result_data["options"]["save_mode"], mode)
                self.assertEqual(dialog.result_data["primary"].api_key, self.primary.api_key)

    def test_cancel_has_no_result_or_configuration_signal_and_does_not_mutate_inputs(self):
        options = {"auto_refresh": False, "request_budget": 12}
        dialog = self.settings(options, vision=self.vision)
        events = []
        dialog.configuration_ready.connect(events.append)
        dialog.primary_form.model_edit.setText("unsaved-model")
        dialog.auto_refresh_check.setChecked(True)
        dialog.request_budget_spin.setValue(50)
        dialog.button_box.button(QDialogButtonBox.StandardButton.Cancel).click()
        self.assertIsNone(dialog.result_data)
        self.assertEqual(events, [])
        self.assertEqual(self.primary.model, "gpt-5")
        self.assertEqual(options, {"auto_refresh": False, "request_budget": 12})

    def test_browse_is_mocked_and_picker_cancel_preserves_current_fields(self):
        dialog = self.settings()
        with patch("teachmechat.desktop.dialogs.QFileDialog.getExistingDirectory",
                   return_value=r"E:\synthetic\new-settings") as choose:
            dialog.directory_browse_button.click()
            choose.assert_called_once()
        self.assertEqual(dialog.directory_edit.text(), r"E:\synthetic\new-settings")
        with patch("teachmechat.desktop.dialogs.QFileDialog.getExistingDirectory", return_value=""):
            dialog.directory_browse_button.click()
        self.assertEqual(dialog.directory_edit.text(), r"E:\synthetic\new-settings")
        with patch("teachmechat.desktop.dialogs.QFileDialog.getOpenFileName",
                   return_value=(r"E:\synthetic\turbo.pt", "")) as choose:
            dialog.whisper_browse_button.click()
            choose.assert_called_once()
        self.assertEqual(dialog.whisper_path_edit.text(), r"E:\synthetic\turbo.pt")
        with patch("teachmechat.desktop.dialogs.QFileDialog.getOpenFileName", return_value=("", "")):
            dialog.whisper_browse_button.click()
        dialog.accept()
        self.assertEqual(dialog.result_data["options"]["whisper_path"], r"E:\synthetic\turbo.pt")
        self.assertEqual(dialog.result_data["directory"], Path(r"E:\synthetic\new-settings"))

    def test_media_requires_local_absolute_path_but_never_checks_file_existence(self):
        for value in ("turbo", "E:turbo.pt", r"\\server\share\turbo.pt", "//server/share/turbo.pt"):
            with self.subTest(value=value):
                dialog = self.settings()
                dialog.whisper_path_edit.setText(value)
                dialog.accept()
                self.assertIsNone(dialog.result_data)
                self.assertEqual(dialog.tabs.currentIndex(), 2)
                self.assertIn("绝对路径", dialog.error_label.text())
                self.assertIn("网络路径", dialog.error_label.text())
        for value in (r"C:\synthetic\turbo.pt", r"E:\does-not-exist\turbo.pt"):
            with self.subTest(value=value):
                dialog = self.settings()
                dialog.whisper_path_edit.setText(value)
                dialog.accept()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                self.assertEqual(dialog.result_data["options"]["whisper_path"], value)

    def test_empty_storage_directory_is_a_local_validation_error(self):
        dialog = self.settings()
        dialog.directory_edit.clear()
        dialog.accept()
        self.assertIsNone(dialog.result_data)
        self.assertEqual(dialog.tabs.currentIndex(), 1)
        self.assertIn("配置目录", dialog.error_label.text())

    def test_probe_emits_typed_copies_only_and_does_not_accept_or_block(self):
        dialog = self.settings({"vision_enabled": True, "vision_reuse": False}, vision=self.vision)
        requests = []
        dialog.probe_requested.connect(lambda config, kind: requests.append((config, kind)))
        for kind in ("text", "structured", "vision"):
            dialog.probe_buttons[kind].click()
            self.assertFalse(dialog.probe_buttons[kind].isEnabled())
            dialog.probe_buttons[kind].click()
            self.assertEqual(len(requests), ("text", "structured", "vision").index(kind) + 1)
        self.assertEqual([kind for _, kind in requests], ["text", "structured", "vision"])
        for config, kind in requests:
            self.assertIsInstance(config, ProviderConfig)
            expected = self.vision if kind == "vision" else self.primary
            self.assertEqual(config, expected)
            self.assertIsNot(config, expected)
            dialog.set_probe_result(kind, "synthetic success", True)
            self.assertTrue(dialog.probe_buttons[kind].isEnabled())
            self.assertIn("探测成功", dialog.probe_labels[kind].text())
        self.assertIsNone(dialog.result_data)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_probe_can_use_independent_vision_without_valid_primary(self):
        dialog = self.settings({"vision_enabled": True, "vision_reuse": False}, vision=self.vision)
        dialog.primary_form.model_edit.clear()
        requests = []
        dialog.probe_requested.connect(lambda config, kind: requests.append((config, kind)))
        dialog.probe_buttons["text"].click()
        self.assertEqual(requests, [])
        self.assertTrue(dialog.probe_buttons["text"].isEnabled())
        dialog.probe_buttons["vision"].click()
        self.assertEqual(requests, [(self.vision, "vision")])

    def test_visual_probe_reuse_and_disabled_states(self):
        dialog = self.settings({"vision_enabled": False, "vision_reuse": True})
        requests = []
        dialog.probe_requested.connect(lambda config, kind: requests.append((config, kind)))
        self.assertFalse(dialog.probe_buttons["vision"].isEnabled())
        dialog.probe_buttons["vision"].click()
        self.assertEqual(requests, [])
        dialog.vision_enabled_check.setChecked(True)
        dialog.probe_buttons["vision"].click()
        self.assertEqual(requests, [(self.primary, "vision")])
        dialog.vision_enabled_check.setChecked(False)
        dialog.set_probe_result("vision", "completed", True)
        self.assertFalse(dialog.probe_buttons["vision"].isEnabled())

    def test_probe_result_is_plain_text_bounded_and_redacts_old_and_current_keys(self):
        dialog = self.settings()
        dialog.probe_buttons["text"].click()
        dialog.primary_form.base_url_edit.setText("https://changed.example.invalid/v1")
        dialog.primary_form.api_key_edit.setText("new-synthetic-secret")
        dialog.set_probe_result("text", "<b>" + self.primary.api_key + " new-synthetic-secret\x00" + "x" * 1000, False)
        label = dialog.probe_labels["text"]
        self.assertEqual(label.textFormat(), Qt.TextFormat.PlainText)
        self.assertNotIn(self.primary.api_key, label.text())
        self.assertNotIn("new-synthetic-secret", label.text())
        self.assertNotIn("\x00", label.text())
        self.assertIn("[凭据已隐藏]", label.text())
        self.assertLess(len(label.text()), 620)
        self.assertTrue(dialog.probe_buttons["text"].isEnabled())
        dialog.set_probe_result("unknown", "ignored", False)

    def test_provider_parameter_types_and_safe_invalid_values(self):
        config = replace(self.primary, reasoning="unsupported-secret-option")
        form = self.keep(ProviderForm(config))
        self.assertEqual(form.reasoning_combo.currentData(), "default")
        self.assertIn("已选默认", form.reasoning_hint.text())
        self.assertNotIn("unsupported-secret-option", form.reasoning_hint.text())
        self.assertEqual(form.to_config().reasoning, "default")
        form.reasoning_combo.addItem("invalid", "unsupported-secret-option")
        form.reasoning_combo.setCurrentIndex(form.reasoning_combo.count() - 1)
        with self.assertRaises(TeachMeChatError) as result:
            form.to_config()
        self.assertNotIn("unsupported-secret-option", str(result.exception))
        self.select(form.reasoning_combo, "default")
        form.api_key_edit.setText("key with spaces")
        with self.assertRaises(TeachMeChatError) as result:
            form.to_config()
        self.assertNotIn("key with spaces", str(result.exception))

    def test_model_combo_keeps_text_api_and_suggestions_without_auto_selection(self):
        form = self.keep(ProviderForm())
        combo = form.model_edit
        self.assertIsInstance(combo, (ModelCombo, QComboBox))
        self.assertTrue(combo.isEditable())
        self.assertEqual(combo.text(), "")
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], model_catalog.suggested_models("openai"))
        changes = []
        combo.textChanged.connect(changes.append)
        combo.setText("third-party/alias")
        self.assertEqual(combo.text(), "third-party/alias")
        self.assertEqual(changes[-1], "third-party/alias")
        count = combo.count()
        combo.clear()
        self.assertEqual(combo.text(), "")
        self.assertEqual(combo.count(), count)
        combo.setCurrentIndex(0)
        self.assertEqual(combo.text(), combo.itemText(0))

    def test_reasoning_matches_exact_model_and_updates_on_model_protocol_provider(self):
        form = self.keep(ProviderForm(self.primary))
        for provider in PROVIDERS:
            self.select(form.provider_combo, provider)
            for model in model_catalog.suggested_models(provider) + ["third-party/unknown"]:
                form.model_edit.setText(model)
                self.assertEqual(
                    [(form.reasoning_combo.itemText(i), form.reasoning_combo.itemData(i))
                     for i in range(form.reasoning_combo.count())],
                    model_catalog.get_model_options(provider, model, form.protocol_combo.currentData()),
                )
        self.select(form.provider_combo, "openai")
        form.model_edit.setText("gpt-5")
        self.select(form.reasoning_combo, "minimal")
        form.model_edit.setText("gpt-5.1")
        self.assertEqual(form.reasoning_combo.currentData(), "default")
        self.assertIn("已选默认", form.reasoning_hint.text())
        self.select(form.reasoning_combo, "high")
        self.select(form.protocol_combo, "anthropic")
        self.assertEqual(form.reasoning_combo.currentData(), "default")
        self.assertIn("已选默认", form.reasoning_hint.text())
        self.select(form.protocol_combo, "openai")
        self.select(form.reasoning_combo, "high")
        self.select(form.provider_combo, "glm")
        self.assertEqual(form.reasoning_combo.currentData(), "default")
        self.assertIn("已选默认", form.reasoning_hint.text())

    def test_restored_reasoning_keeps_only_model_supported_options(self):
        for config in (self.primary, self.vision,
                       replace(self.vision, model="claude-opus-4-6", reasoning="max")):
            form = self.keep(ProviderForm(config))
            self.assertEqual(form.to_config(), config)
        for config in (replace(self.primary, model="unknown-alias"),
                       replace(self.primary, model="gpt-5.1", reasoning="minimal"),
                       replace(self.vision, model="claude-opus-4-6", reasoning="enabled")):
            form = self.keep(ProviderForm(config))
            self.assertEqual(form.to_config(), replace(config, reasoning="default"))
            self.assertIn("已选默认", form.reasoning_hint.text())
            self.assertEqual(form.thinking_budget_spin.value(), config.thinking_budget)

    def test_custom_model_selection_preserves_endpoint_protocol_key_and_saved_budget(self):
        config = replace(self.vision, provider="custom", model="claude-opus-4-6", reasoning="high")
        form = self.keep(ProviderForm(config))
        self.assertTrue(form.advanced_check.isChecked())
        self.assertFalse(form.advanced_group.isHidden())
        form.model_edit.setText("third-party/private-alias")
        self.assertEqual(form.to_config(), replace(config, model="third-party/private-alias", reasoning="default"))
        form.model_edit.setText("claude-opus-4-6")
        self.select(form.reasoning_combo, "max")
        self.assertEqual(form.to_config(), replace(config, reasoning="max"))

    def test_models_request_allows_empty_model_and_runs_independently_from_probe(self):
        dialog = self.settings({"vision_enabled": True, "vision_reuse": False}, vision=self.vision)
        requests, probes = [], []
        dialog.models_requested.connect(lambda config, target: requests.append((config, target)))
        dialog.probe_requested.connect(lambda config, kind: probes.append((config, kind)))
        dialog.probe_buttons["text"].click()
        dialog.primary_form.model_edit.clear()
        dialog.primary_form.models_button.click()
        dialog.primary_form.models_button.click()
        dialog.vision_form.models_button.click()
        self.assertEqual([target for _, target in requests], ["primary", "vision"])
        self.assertEqual(requests[0][0], replace(self.primary, model="", reasoning="default"))
        self.assertEqual(requests[1][0], self.vision)
        self.assertIsNot(requests[1][0], self.vision)
        self.assertEqual(probes, [(self.primary, "text")])
        self.assertFalse(dialog.probe_buttons["text"].isEnabled())
        self.assertFalse(dialog.primary_form.models_button.isEnabled())
        self.assertFalse(dialog.vision_form.models_button.isEnabled())
        dialog.set_models(["gpt-5", "account-only"], target="primary")
        dialog.set_models(["claude-opus-4-6"], target="vision")
        self.assertEqual(dialog.primary_form.model_edit.text(), "")
        self.assertEqual(dialog.vision_form.model_edit.text(), self.vision.model)
        self.assertEqual(dialog.vision_form.api_key_edit.text(), self.vision.api_key)
        self.assertTrue(dialog.primary_form.models_button.isEnabled())
        self.assertTrue(dialog.vision_form.models_button.isEnabled())
        self.assertFalse(dialog.probe_buttons["text"].isEnabled())
        self.assertIsNone(dialog.result_data)

    def test_models_results_ignore_configuration_changes_even_if_restored(self):
        changes = {
            "model": lambda f: (f.model_edit.setText("changed"), f.model_edit.setText(self.primary.model)),
            "key": lambda f: (f.api_key_edit.setText("different"), f.api_key_edit.setText(self.primary.api_key)),
            "url": lambda f: f.base_url_edit.setText("https://new.example.invalid/v1"),
            "provider": lambda f: self.select(f.provider_combo, "glm"),
            "protocol": lambda f: self.select(f.protocol_combo, "anthropic"),
            "reasoning": lambda f: self.select(f.reasoning_combo, "low"),
            "structured": lambda f: self.select(f.structured_combo, "native"),
            "timeout": lambda f: f.timeout_spin.setValue(99),
            "budget": lambda f: f.thinking_budget_spin.setValue(8192),
        }
        for name, change in changes.items():
            with self.subTest(field=name):
                dialog = self.settings()
                form = dialog.primary_form
                form.models_button.click()
                change(form)
                self.assertTrue(form.models_button.isEnabled())
                before = [form.model_edit.itemText(i) for i in range(form.model_edit.count())]
                dialog.set_models(["stale-result"], target="primary")
                self.assertEqual([form.model_edit.itemText(i) for i in range(form.model_edit.count())], before)
                self.assertIn("配置已变更", form.models_label.text())
        dialog = self.settings()
        dialog.set_models(["unsolicited"], target="primary")
        dialog.set_models(["ignored"], target="unknown")
        self.assertEqual(dialog.primary_form.model_edit.findText("unsolicited"), -1)

    def test_models_results_sanitize_dedupe_keep_custom_text_and_do_not_leak_keys(self):
        dialog = self.settings({"vision_enabled": True, "vision_reuse": False}, vision=self.vision)
        form = dialog.primary_form
        form.model_edit.setText("private/custom-id")
        form.models_button.click()
        dialog.set_models(["server-model", "server-model", " second ", "", None, "bad\x00id",
                           "x" * 257, self.primary.api_key, "prefix-" + self.vision.api_key])
        self.assertEqual([form.model_edit.itemText(i) for i in range(form.model_edit.count())],
                         ["server-model", "second"])
        self.assertEqual(form.model_edit.text(), "private/custom-id")
        self.assertEqual(form.api_key_edit.text(), self.primary.api_key)
        self.assertEqual(form.base_url_edit.text(), self.primary.base_url)
        self.assertEqual(form.protocol_combo.currentData(), self.primary.protocol)
        form.models_button.click()
        dialog.set_models([], error="<b>" + self.primary.api_key + " " + self.vision.api_key + "\x00" + "x" * 500)
        self.assertEqual(form.models_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertNotIn(self.primary.api_key, form.models_label.text())
        self.assertNotIn(self.vision.api_key, form.models_label.text())
        self.assertNotIn("\x00", form.models_label.text())
        self.assertIn("[凭据已隐藏]", form.models_label.text())
        self.assertLess(len(form.models_label.text()), 320)
        self.assertTrue(form.models_button.isEnabled())
        self.assertEqual(form.model_edit.text(), "private/custom-id")
        form.models_button.click()
        dialog.set_models([])
        self.assertIn("可手输", form.models_label.text())
        self.assertEqual(form.model_edit.count(), 2)
        form.models_button.click()
        dialog.set_models(["retried"])
        self.assertEqual(form.model_edit.itemText(0), "retried")

    def test_models_request_still_validates_key_url_protocol_without_network(self):
        for field, value in (("api_key_edit", ""), ("api_key_edit", "bad key"),
                             ("base_url_edit", "https://user:secret@example.invalid/v1")):
            dialog = self.settings()
            form = dialog.primary_form
            form.model_edit.clear()
            getattr(form, field).setText(value)
            requests = []
            dialog.models_requested.connect(lambda *args: requests.append(args))
            form.models_button.click()
            self.assertEqual(requests, [])
            self.assertTrue(form.models_button.isEnabled())
            self.assertNotIn("user:secret", form.models_label.text())

    def test_source_manual_requires_explicit_readonly_authorization_and_background(self):
        dialog = self.source("manual")
        self.assertGreaterEqual(dialog.minimumWidth(), 720)
        self.assertIs(dialog.authorization_check, dialog.readonly_check)
        self.assertEqual(dialog.findChildren(QCheckBox), [dialog.authorization_check])
        self.assertIn("有权访问", dialog.authorization_check.text())
        self.assertIn("只读", dialog.authorization_check.toolTip())
        self.assertIn("不授权外发", dialog.authorization_check.toolTip())
        dialog.background_edit.setPlainText("synthetic background")
        dialog.accept()
        self.assertIsNone(dialog.spec)
        dialog.authorization_check.setChecked(True)
        dialog.readonly_check.setChecked(False)
        dialog.accept()
        self.assertIsNone(dialog.spec)
        dialog.authorization_check.setChecked(True)
        dialog.background_edit.clear()
        dialog.accept()
        self.assertIsNone(dialog.spec)
        dialog.background_edit.setPlainText("  synthetic background  ")
        dialog.accept()
        self.assertEqual(dialog.spec, {"mode": "manual", "background": "synthetic background"})
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_source_defaults_to_recommended_auto_without_authorization(self):
        dialog = self.keep(SourceDialog())
        self.assertEqual(dialog.mode_combo.currentData(), "auto")
        self.assertEqual(dialog.mode_combo.currentIndex(), 0)
        self.assertEqual(dialog.mode_combo.currentText(), "连接当前微信（推荐）")
        self.assertEqual(dialog.pages.currentIndex(), 1)
        self.assertEqual({dialog.mode_combo.itemData(i) for i in range(dialog.mode_combo.count())},
                         {"auto", "manual", "snapshot", "live-manual"})
        self.assertTrue(dialog.key_edit.isHidden())
        self.assertFalse(dialog.authorization_check.isChecked())
        self.assertFalse(dialog.readonly_check.isChecked())
        dialog.accept()
        self.assertIsNone(dialog.spec)
        self.assertIn("授权", dialog.error_label.text())
        self.authorize(dialog)
        dialog.accept()
        self.assertEqual(dialog.spec, {"mode": "auto"})

    def test_each_source_mode_requires_explicit_authorization(self):
        for mode in ("auto", "manual", "snapshot", "live-manual"):
            with self.subTest(mode=mode):
                dialog = self.source(mode)
                dialog.background_edit.setPlainText("synthetic background")
                dialog.root_edit.setText(r"E:\synthetic\snapshot")
                dialog.key_edit.setText("a" * 64)
                dialog.accept()
                self.assertIsNone(dialog.spec)
                self.assertIn("授权", dialog.error_label.text())
                self.assertNotIn("a" * 64, dialog.error_label.text())
                self.authorize(dialog)
                dialog.accept()
                self.assertEqual(dialog.spec["mode"], mode)

    def test_auto_source_returns_no_paths_or_credentials_and_does_not_scan(self):
        dialog = self.source("auto")
        self.authorize(dialog)
        dialog.root_edit.setText(r"E:\synthetic\ignored")
        dialog.background_edit.setPlainText("ignored background")
        dialog.accept()
        self.assertEqual(dialog.spec, {"mode": "auto"})

    def test_snapshot_source_types_and_mocked_directory_browse(self):
        dialog = self.source("snapshot")
        self.authorize(dialog)
        dialog.accept()
        self.assertIsNone(dialog.spec)
        with patch("teachmechat.desktop.dialogs.QFileDialog.getExistingDirectory",
                   side_effect=[r"E:\synthetic\snapshot", r"E:\synthetic\media"]):
            dialog.root_browse_button.click()
            dialog.media_browse_button.click()
        self.select(dialog.version_combo, 3)
        dialog.account_id_edit.setText("synthetic-owner")
        dialog.key_edit.setText("ignored-key")
        dialog.accept()
        self.assertEqual(dialog.spec, {"mode": "snapshot", "root": r"E:\synthetic\snapshot", "version": 3,
                                      "media_root": r"E:\synthetic\media", "account_id": "synthetic-owner", "key": ""})
        self.assertIs(type(dialog.spec["version"]), int)
        self.assertTrue(all(isinstance(value, str) for key, value in dialog.spec.items() if key != "version"))
        self.assertTrue(dialog.key_edit.isHidden())

    def test_live_manual_masks_and_requires_key_and_cancel_leaves_no_spec(self):
        dialog = self.source("live-manual")
        self.authorize(dialog)
        dialog.root_edit.setText(r"E:\synthetic\db_storage")
        self.assertEqual(dialog.key_edit.echoMode(), QLineEdit.EchoMode.Password)
        self.assertFalse(dialog.key_edit.isHidden())
        dialog.accept()
        self.assertIsNone(dialog.spec)
        dialog.key_edit.setText("a" * 64)
        dialog.accept()
        self.assertEqual(dialog.spec["mode"], "live-manual")
        self.assertEqual(dialog.spec["key"], "a" * 64)
        self.assertEqual(dialog.spec["version"], 4)
        self.assertEqual(dialog.spec["media_root"], "")
        self.assertEqual(dialog.spec["account_id"], "")
        cancelled = self.source("live-manual")
        self.authorize(cancelled)
        cancelled.key_edit.setText("b" * 64)
        cancelled.button_box.button(QDialogButtonBox.StandardButton.Cancel).click()
        self.assertIsNone(cancelled.spec)
        self.assertEqual(cancelled.key_edit.text(), "")

    def test_leaving_manual_live_mode_clears_database_key(self):
        dialog = self.source("live-manual")
        dialog.key_edit.setText("a" * 64)
        self.select(dialog.mode_combo, "snapshot")
        self.assertEqual(dialog.key_edit.text(), "")
        self.assertTrue(dialog.key_edit.isHidden())
        self.select(dialog.mode_combo, "live-manual")
        self.assertEqual(dialog.key_edit.text(), "")


if __name__ == "__main__":
    unittest.main()
