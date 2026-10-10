from dataclasses import fields
from pathlib import Path
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget, QMenu, QSizePolicy, QGridLayout,
                               QComboBox, QSpinBox)

from ..models import Advice, ChatMessage, ProviderConfig, TeachMeChatError
from ..scheduler import fingerprint
from .theme import ASCII_MARK
from .chrome import FramelessWindow, TitleBar
from .refresh_controls import RefreshSwitch, RefreshButton, REFRESH_INTERVAL_SECONDS


def label(text, name="", parent=None):
    widget = QLabel(text, parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


class MainWindow(FramelessWindow):
    def __init__(self, runtime, config_dir=None, *, demo=False):
        super().__init__()
        self.runtime = Path(runtime)
        self.explicit_config_dir = config_dir
        self.config_dir = Path(config_dir) if config_dir else Path(r"C:\TeachMeChat")
        self.primary = None
        self.vision = None
        self.options = {"auto_refresh": True, "request_budget": 12, "context_limit": 100}
        self._save_mode = "session"
        self.wechat_connected = False
        self._reload_source_spec = None
        self.source_actor = None
        self.analysis_actor = None
        self.probe_actor = None
        self.model_actors = {}
        self.actors = []
        self.epoch = 0
        self.active_epoch = 0
        self.last_hash = ""
        self.active_hash = ""
        self.success_hash = ""
        self.messages = []
        self.selected_id = ""
        self.source_ready = False
        self.source_valid = False
        self.manual = False
        self.consent = False
        self.pending_read = False
        self.regenerate = False
        self.paused = False
        self.next_refresh = 0.0
        self.requests = 0
        self.latest_message_time = "—"
        self.last_checked_time = "—"
        self._window_closing = False
        self.demo = demo
        self.setWindowTitle("交我聊 · TeachMeChat")
        self.setMinimumSize(960, 680)
        self.resize(1360, 860)
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(250)
        if demo:
            self._demo()
        else:
            QTimer.singleShot(0, self._load_configuration)

    def _build(self):
        from .chat_view import ChatView
        root = QWidget()
        root.setObjectName("canvas")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 10, 20, 12)
        outer.setSpacing(12)
        self.titlebar = TitleBar(self, title="交我聊")
        self.settings_button = button("设置", self.open_settings)
        self.settings_button.setObjectName("quiet")
        self.titlebar.add_action(self.settings_button)
        more = button("更多", lambda: None)
        more.setObjectName("quiet")
        menu = QMenu(more)
        menu.addAction("其他导入方式…", self.open_source)
        menu.addAction("关于交我聊", self.about)
        more.setMenu(menu)
        self.titlebar.add_action(more)
        outer.addWidget(self.titlebar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(12)
        outer.addWidget(self.splitter, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(260)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 20, 14, 16)
        side.setSpacing(12)
        side.addWidget(label("最近聊天", "section"))
        from .connect_button import ConnectButton
        self.connect_button = ConnectButton(self.quick_connect)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索联系人")
        self.search.textChanged.connect(self._filter)
        side.addWidget(self.search)
        self.conversations = QListWidget()
        self.conversations.currentItemChanged.connect(self._select_chat)
        side.addWidget(self.conversations, 1)
        side.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignHCenter)
        manual = button("手动输入", self.manual_context)
        manual.setObjectName("quiet")
        side.addWidget(manual)
        self.splitter.addWidget(sidebar)

        center = QFrame()
        center.setObjectName("surface")
        middle = QVBoxLayout(center)
        middle.setContentsMargins(20, 20, 20, 18)
        middle.setSpacing(12)
        chat_header = QHBoxLayout()
        chat_header.setSpacing(12)
        self.avatar = label("聊", "avatar")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setFixedSize(38, 38)
        chat_header.addWidget(self.avatar)
        self.chat_title = label("想聊点什么？", "section")
        chat_header.addWidget(self.chat_title, 1)
        self.auto = RefreshSwitch()
        self.auto.setChecked(True)
        chat_header.addWidget(self.auto)
        self.refresh_button = RefreshButton(self.refresh)
        chat_header.addWidget(self.refresh_button)
        middle.addLayout(chat_header)
        context_row = QHBoxLayout()
        context_row.addWidget(label("上下文", "muted"))
        self.context_limit_combo = QComboBox()
        for amount in (100, 200, 500, 1000):
            self.context_limit_combo.addItem(f"{amount} 条", amount)
        self.context_limit_combo.addItem("自定义", None)
        self.context_limit_combo.setToolTip("读取的最近消息数量；较长内容仍可能按模型输入预算裁剪。")
        self.context_custom = QSpinBox()
        self.context_custom.setRange(1, 5000)
        self.context_custom.setValue(100)
        self.context_custom.setSuffix(" 条")
        self.context_custom.setKeyboardTracking(False)
        self.context_custom.hide()
        context_row.addWidget(self.context_limit_combo)
        context_row.addWidget(self.context_custom)
        context_row.addStretch()
        middle.addLayout(context_row)
        self.context_limit_combo.currentIndexChanged.connect(self._context_limit_changed)
        self.context_custom.valueChanged.connect(self._context_limit_changed)
        self.context = ChatView()
        middle.addWidget(self.context, 1)
        self.background_toggle = button("补充要求", self.toggle_background)
        self.background_toggle.setObjectName("raised")
        middle.addWidget(self.background_toggle)
        self.background = QPlainTextEdit()
        self.background.setPlaceholderText("例如：希望自然接续话题，简短一点，不要太正式。")
        self.background.setFixedHeight(88)
        self.background.hide()
        middle.addWidget(self.background)
        self.splitter.addWidget(center)

        right = QFrame()
        right.setObjectName("surface")
        right.setMinimumWidth(310)
        content = QVBoxLayout(right)
        content.setContentsMargins(20, 22, 20, 18)
        content.setSpacing(10)
        reply_header = QHBoxLayout()
        reply_header.addWidget(label("回复", "section"))
        reply_header.addStretch()
        self.generate_button = button("生成", self.generate, True)
        reply_header.addWidget(self.generate_button)
        content.addLayout(reply_header)
        self.tabs = QTabWidget()
        content.addWidget(self.tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("scrollCanvas")
        cards = QVBoxLayout(container)
        cards.setContentsMargins(0, 14, 0, 4)
        cards.setSpacing(14)
        self.reply_labels, self.copy_buttons, self.reply_cards = [], [], []
        self.reply_empty = label("想好怎么回，我来帮你。\n选一段聊天，再点“生成”。", "muted")
        self.reply_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cards.addWidget(self.reply_empty)
        for index in range(3):
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 15, 18, 17)
            card_layout.setSpacing(13)
            top = QHBoxLayout()
            top.addWidget(label(f"{index + 1:02d}", "eyebrow"))
            top.addStretch()
            copy = button("复制", lambda checked=False, i=index: self.copy_reply(i))
            copy.setObjectName("copy")
            copy.setEnabled(False)
            top.addWidget(copy)
            card_layout.addLayout(top)
            reply = label("", "replyText")
            reply.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            reply.setMinimumHeight(54)
            reply.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            card_layout.addWidget(reply)
            self.reply_labels.append(reply)
            self.copy_buttons.append(copy)
            self.reply_cards.append(card)
            cards.addWidget(card)
            card.hide()
        cards.addStretch()
        scroll.setWidget(container)
        self.tabs.addTab(scroll, "建议")
        from .advice_view import AdviceAnalysis
        self.analysis = AdviceAnalysis()
        self.tabs.addTab(self.analysis, "分析")
        self.splitter.addWidget(right)
        self.splitter.setSizes([215, 500, 435])
        for index in range(3):
            self.splitter.setCollapsible(index, False)
        from .status_robot import RobotStatus
        footer = QGridLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setHorizontalSpacing(12)
        footer.setColumnStretch(0, 1)
        footer.setColumnStretch(2, 1)
        footer.addWidget(QWidget(), 0, 0)
        self.status = RobotStatus()
        footer.addWidget(self.status, 0, 1, Qt.AlignmentFlag.AlignCenter)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.pause_button = button("暂停", self.toggle_pause)
        self.pause_button.setObjectName("quiet")
        controls.addWidget(self.pause_button)
        control_widget = QWidget()
        control_widget.setLayout(controls)
        side_width = control_widget.sizeHint().width()
        footer.setColumnMinimumWidth(0, side_width)
        footer.setColumnMinimumWidth(2, side_width)
        control_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(control_widget, 0, 2, Qt.AlignmentFlag.AlignRight)
        outer.addLayout(footer)
        self.setCentralWidget(root)
        self.generate_button.setEnabled(False)

    def _restore_context_limit(self):
        from PySide6.QtCore import QSignalBlocker
        from ..context_options import validate_context_limit
        value = validate_context_limit(self.options.get("context_limit", 100))
        with QSignalBlocker(self.context_limit_combo), QSignalBlocker(self.context_custom):
            index = self.context_limit_combo.findData(value)
            self.context_limit_combo.setCurrentIndex(index if index >= 0 else 4)
            self.context_custom.setValue(value)
            self.context_custom.setVisible(index < 0)

    def _context_limit_changed(self, *_):
        from ..context_options import validate_context_limit
        selected = self.context_limit_combo.currentData()
        self.context_custom.setVisible(selected is None)
        value = validate_context_limit(self.context_custom.value() if selected is None else selected)
        if value == self.options.get("context_limit", 100):
            return
        previous = dict(self.options)
        self.options["context_limit"] = value
        try:
            if self._save_mode != "session" and self.primary:
                from ..settings import Settings
                Settings(self.config_dir).save_profiles(self.primary, self.vision,
                    remember_keys=self._save_mode == "remember", options=self.options)
        except TeachMeChatError as error:
            self.options = previous
            self._restore_context_limit()
            self._error(str(error))
            return
        self._invalidate("上下文范围已更改，请重新确认发送范围。")
        self.messages = []
        self.last_hash = self.success_hash = ""
        self.context.clear()
        # Drop any old read before accepting a result under a new message limit.
        if not self.manual and self._reload_source_spec is not None:
            if self.source_actor:
                self.source_actor.stop()
            self.source_actor = None
            from .workers import source_worker
            actor = self._actor(source_worker, 180)
            self.source_actor = actor
            actor.received.connect(lambda event, payload: self._source_event(actor, event, payload))
            actor.failed.connect(lambda message: self._source_failed(actor, message))
            self.source_ready = False
            self._restore_chat_id = self.selected_id
            self.conversations.clear()
            actor.submit("open", dict(self._reload_source_spec))
        elif self.manual:
            self.refresh()
        self._show_robot("busy" if not self.manual else "ready", f"读取范围：{value} 条")

    def _show_robot(self, state, text):
        detail = ""
        if self.selected_id and self.last_checked_time != "—":
            detail = f"最新消息 {self.latest_message_time} · 检查 {self.last_checked_time}"
        self.status.set_state(state, text, detail, connected=self.wechat_connected)

    def toggle_background(self):
        expanded = not self.background.isVisible()
        self.background.setVisible(expanded)
        self.background_toggle.setText("收起要求" if expanded else "补充要求")
        if expanded:
            self.background.setFocus()

    def quick_connect(self):
        if self.source_actor and not self.source_ready:
            self._invalidate("已取消连接。", disconnect=True)
            self.connect_button.setText("连接微信")
            return
        answer = QMessageBox.question(self, "连接你的微信", "仅在本机读取你有权访问的会话。\n选好聊天后，生成建议前会再确认发送范围。\n\n是否连接当前微信？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.connect_source({"mode": "auto"})

    def _load_configuration(self):
        from ..settings import Settings, config_directory
        try:
            self.config_dir = config_directory(self.runtime, self.explicit_config_dir)
            self.primary, self.vision, self.options = Settings(self.config_dir).load_profiles()
            self.options = self.options or {"auto_refresh": True, "request_budget": 12}
            self.auto.setChecked(self.options.get("auto_refresh", True))
            self._save_mode = self.options.get("credential_mode", "public")
            self._restore_context_limit()
            self._service_status()
        except TeachMeChatError as error:
            try:
                public = Settings(self.config_dir).load()
                allowed = {field.name for field in fields(ProviderConfig)} - {"api_key"}
                for name, target in (("provider", "primary"), ("vision", "vision")):
                    if isinstance(public.get(name), dict):
                        setattr(self, target, ProviderConfig(**{key: value for key, value in public[name].items() if key in allowed}))
            except TeachMeChatError:
                pass
            self._error(str(error))
            return
        if not self.primary or not self.primary.api_key:
            self.open_settings()

    def _service_status(self):
        from ..provider_specs import get_spec
        if self.primary:
            name = get_spec(self.primary.provider).label
            self.settings_button.setToolTip(f"{name} / {self.primary.model}\n{self.primary.base_url}")
        else:
            self.settings_button.setToolTip("配置 AI 服务")

    def _actor(self, target, deadline=180):
        from .tasks import ProcessActor
        actor = ProcessActor(target, self.runtime, self, deadline=deadline)
        self.actors.append(actor)
        return actor

    def _stop_analysis(self):
        if self.analysis_actor:
            self.analysis_actor.stop()
            self.analysis_actor = None
        self.active_hash = ""

    def _invalidate(self, message, *, disconnect=False):
        self.epoch += 1
        self.consent = False
        self.source_valid = False
        self.pending_read = False
        self._stop_analysis()
        if disconnect and self.source_actor:
            self.source_actor.stop()
            self.source_actor = None
            self.source_ready = False
        if disconnect:
            self.wechat_connected = False
        self._show_robot("idle", message)
        self.reply_empty.show()
        for card in self.reply_cards:
            card.hide()
        self.generate_button.setText("生成")
        self.generate_button.setEnabled(self.source_ready)
        for text in self.reply_labels:
            text.clear()
        self.analysis.clear()
        for copy in self.copy_buttons:
            copy.setEnabled(False)

    def open_settings(self):
        from .dialogs import SettingsDialog
        was_paused = self.paused
        self.paused = True
        self.pause_button.setText("继续")
        self._stop_analysis()
        dialog = SettingsDialog(self.primary, self.vision, self.options, self.config_dir, self)
        dialog.probe_requested.connect(lambda config, kind: self._probe(dialog, config, kind))
        dialog.models_requested.connect(lambda config, target: self._fetch_models(dialog, config, target))
        tools = QHBoxLayout()
        tools.addWidget(button("导入旧版公开设置…", lambda: self._import_legacy(dialog)))
        tools.addWidget(button("删除已保存的 API Key", self._forget_keys))
        tools.addStretch()
        dialog.layout().insertLayout(dialog.layout().count() - 1, tools)
        accepted = dialog.exec()
        for actor in self.model_actors.values():
            actor.stop()
        self.model_actors.clear()
        if self.probe_actor:
            self.probe_actor.stop()
            self.probe_actor = None
        if not accepted:
            self.paused = was_paused
            self.pause_button.setText("继续" if self.paused else "暂停")
            return False
        data = dialog.result_data
        from ..settings import Settings, remember_config_directory
        try:
            if data["save_mode"] != "session":
                Settings(data["directory"]).save_profiles(data["primary"], data["vision"],
                    remember_keys=data["save_mode"] == "remember", options=data["options"])
                remember_config_directory(self.runtime, data["directory"])
        except TeachMeChatError as error:
            self._error(str(error))
            return
        self._invalidate("服务设置已更新。生成前将重新确认发送范围。")
        self.primary, self.vision = data["primary"], data["vision"]
        self.options, self.config_dir = data["options"], data["directory"]
        self._save_mode = data["save_mode"]
        self._restore_context_limit()
        self.auto.setChecked(self.options.get("auto_refresh", True))
        self._service_status()
        self.paused = was_paused
        self.pause_button.setText("继续" if self.paused else "暂停")
        return True

    def _forget_keys(self):
        from ..settings import Settings
        if QMessageBox.question(self, "删除保存的凭据", "只删除所选配置目录中的API凭据，公开配置保留。是否继续？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            Settings(self.config_dir).forget_credentials()
            self._invalidate("已删除保存的API凭据。下次启动需要重新填写。")
        except TeachMeChatError as error:
            self._error(str(error))

    def _import_legacy(self, dialog):
        from PySide6.QtWidgets import QFileDialog
        from ..settings import load_legacy_settings
        selected, _ = QFileDialog.getOpenFileName(self, "选择旧版公开配置", str(self.runtime), "JSON (*.json)")
        if not selected:
            return
        try:
            public = load_legacy_settings(Path(selected))
            config = public.get("provider", {})
            form = dialog.primary_form
            index = form.provider_combo.findData("custom" if config.get("provider") == "openai-compatible" else config.get("provider"))
            if index >= 0:
                form.provider_combo.setCurrentIndex(index)
            form.base_url_edit.setText(config.get("base_url", ""))
            form.model_edit.setText(config.get("model", ""))
            form.api_key_edit.clear()
            form.timeout_spin.setValue(config.get("timeout", 45.0))
            index = form.reasoning_combo.findData(config.get("reasoning", "default"))
            if index >= 0:
                form.reasoning_combo.setCurrentIndex(index)
            dialog.whisper_path_edit.setText(public.get("whisper_path", ""))
            dialog.auto_refresh_check.setChecked(public.get("auto_refresh", True))
        except TeachMeChatError as error:
            self._error(str(error))

    def _fetch_models(self, dialog, config, target):
        from .workers import analysis_worker
        previous = self.model_actors.get(target)
        if previous:
            previous.stop()
        actor = self._actor(analysis_worker, 90)
        self.model_actors[target] = actor
        def finished(event, payload):
            if self.model_actors.get(target) is not actor:
                return
            if event == "models":
                dialog.set_models(payload, target=target)
            elif event == "error":
                dialog.set_models([], error=payload[0], target=target)
            else:
                return
            actor.stop()
            self.model_actors.pop(target, None)
        def failed(message):
            if self.model_actors.get(target) is actor:
                dialog.set_models([], error=message, target=target)
                actor.stop()
                self.model_actors.pop(target, None)
        actor.received.connect(finished)
        actor.failed.connect(failed)
        actor.submit("models", {"primary": config, "limit": 6})

    def _probe(self, dialog, config, kind):
        from .workers import analysis_worker
        if self.probe_actor:
            self.probe_actor.stop()
        actor = self._actor(analysis_worker, 120)
        self.probe_actor = actor
        dialog.probe_labels[kind].setText("正在验证合成请求，不包含聊天内容……")
        def received(event, result):
            if actor is not self.probe_actor:
                return
            if event == "probe":
                dialog.set_probe_result(kind, result[1], True)
            elif event == "error":
                dialog.set_probe_result(kind, result[0], False)
            actor.stop()
        actor.received.connect(received)
        actor.failed.connect(lambda message: dialog.set_probe_result(kind, message, False) if actor is self.probe_actor else None)
        actor.submit("probe", {"primary": config, "kind": kind, "limit": 3})

    def open_source(self):
        from .dialogs import SourceDialog
        dialog = SourceDialog(self)
        if not dialog.exec():
            return
        self.connect_source(dialog.spec)

    def connect_source(self, spec):
        from .workers import source_worker
        self.wechat_connected = False
        self._reload_source_spec = dict(spec)
        self._restore_chat_id = ""
        self._invalidate("正在连接本地数据源……", disconnect=True)
        self.messages = []
        self.success_hash = ""
        self.selected_id = ""
        self.latest_message_time = self.last_checked_time = "—"
        self.context.clear()
        self.conversations.clear()
        self.manual = spec["mode"] == "manual"
        self.generate_button.setEnabled(self.manual)
        self.connect_button.setText("取消连接" if not self.manual else "连接微信")
        self.paused = False
        self.pause_button.setText("暂停")
        if self.manual:
            self.background.setPlainText(spec.get("background", ""))
            self.source_ready = self.source_valid = True
            self.chat_title.setText("直接写背景")
            self.avatar.setText("写")
            self.chat_title.setToolTip("只分析手动输入的内容")
            self.context.show_empty("想回复什么？", "在下方写下对方的话、你们的关系，\n或你希望表达的意思。")
            self.background.show()
            self.background_toggle.setText("收起要求")
            self._show_robot("ready", "背景已就绪")
            return
        self._show_robot("busy", "正在连接微信…")
        actor = self._actor(source_worker, 180)
        self.source_actor = actor
        actor.received.connect(lambda event, payload: self._source_event(actor, event, payload))
        actor.failed.connect(lambda message: self._source_failed(actor, message))
        actor.submit("open", spec)

    def manual_context(self):
        self.connect_source({"mode": "manual", "background": self.background.toPlainText()})
        self.background.setFocus()

    def _source_failed(self, actor, message):
        if actor is self.source_actor:
            self.wechat_connected = False
            self._invalidate(message + " 请重新连接。", disconnect=True)
            self.connect_button.setText("重新连接微信")
            self._show_robot("error", message)

    def _source_event(self, actor, event, payload):
        if actor is not self.source_actor:
            return
        if event == "progress":
            self._show_robot("busy", payload)
            actor.started = time.monotonic()
        elif event == "error":
            self._source_failed(actor, payload)
        elif event == "opened":
            conversations, source_label = payload
            self.source_ready = True
            self.wechat_connected = bool(self._reload_source_spec and self._reload_source_spec["mode"] in {"auto", "live", "live-manual"})
            self.connect_button.setText("重新连接")
            self.chat_title.setToolTip(source_label)
            self.conversations.blockSignals(True)
            for conversation in conversations:
                item = QListWidgetItem(conversation.name)
                item.setData(Qt.ItemDataRole.UserRole, conversation.id)
                item.setToolTip(conversation.id)
                self.conversations.addItem(item)
            self.conversations.blockSignals(False)
            self._show_robot("ready", "已连接 · 请选择聊天")
            restore_id = getattr(self, "_restore_chat_id", "")
            self._restore_chat_id = ""
            if restore_id:
                for index in range(self.conversations.count()):
                    item = self.conversations.item(index)
                    if item.data(Qt.ItemDataRole.UserRole) == restore_id:
                        self.conversations.setCurrentItem(item)
                        break
        elif event == "messages":
            conversation_id, payload = payload
            if conversation_id != self.selected_id:
                self._dispatch_read()
                return
            self.source_valid = True
            previous_hash = self.last_hash
            self.messages = payload
            self.last_hash = fingerprint(self.messages, self.background.toPlainText())
            if self.last_hash != previous_hash or not self.context.toPlainText():
                self._render_context(self.messages)
            self.generate_button.setEnabled(not (self.analysis_actor and self.analysis_actor.busy))
            self.chat_title.setToolTip(f"最近 {len(payload)} 条 · 本机预览")
            try:
                latest = time.strftime("%H:%M", time.localtime(max(m.timestamp for m in payload))) if payload else "—"
            except (ValueError, OSError, OverflowError):
                latest = "—"
            self.latest_message_time = latest
            self.last_checked_time = time.strftime("%H:%M:%S")
            self.refresh_button.setToolTip(f"最新消息 {latest}")
            if not (self.analysis_actor and self.analysis_actor.busy) and not self.paused:
                answered = bool(self.success_hash and self.success_hash == self.last_hash)
                self._show_robot("answered" if answered else "ready", "回答已生成" if answered else "已同步")
            elif self.paused:
                self._show_robot("paused", "已暂停")
            else:
                self._show_robot("generating", "正在生成建议…")
            if self.consent and not self.paused:
                self._analyze_if_needed()

    def _select_chat(self, current, previous):
        if current is None:
            return
        self._invalidate("已切换会话；读取预览中。")
        self.messages = []
        self.success_hash = ""
        self.context.clear()
        self.selected_id = current.data(Qt.ItemDataRole.UserRole)
        self.latest_message_time = self.last_checked_time = "—"
        self.chat_title.setText(current.text())
        self.avatar.setText(current.text()[:1] or "聊")
        self._show_robot("busy", "正在读取聊天…")
        self.generate_button.setEnabled(False)
        self.refresh()

    def _filter(self, text):
        for i in range(self.conversations.count()):
            item = self.conversations.item(i)
            needle = text.casefold()
            item.setHidden(needle not in item.text().casefold() and needle not in str(item.data(Qt.ItemDataRole.UserRole)).casefold())

    def refresh(self):
        if self.manual:
            self.source_valid = True
            self.messages = []
            self.last_hash = fingerprint([], self.background.toPlainText())
            if self.consent and not self.paused:
                self._analyze_if_needed()
            return
        if not self.source_ready or not self.selected_id or not self.source_actor:
            self.status.setText("请先连接并选择会话，或使用手动背景。")
            return
        self.pending_read = True
        self._dispatch_read()

    def _dispatch_read(self):
        if self.source_actor and not self.source_actor.busy and self.pending_read:
            self.pending_read = False
            self.source_actor.submit("recent", {"conversation_id": self.selected_id, "limit": self.options.get("context_limit", 100)})
            if not (self.analysis_actor and self.analysis_actor.busy) and not self.paused:
                self._show_robot("busy", "正在检查更新…")
            self.next_refresh = time.monotonic() + REFRESH_INTERVAL_SECONDS

    def generate(self):
        if self.demo:
            return
        if not self.source_ready or (not self.manual and not self.selected_id):
            self.status.setText("先选一个联系人，或点击左下角直接写背景。")
            return
        if not self.primary or not self.primary.api_key:
            if not self.open_settings() or not self.primary or not self.primary.api_key:
                return
        if self.manual and not self.background.toPlainText().strip():
            self.status.setText("请先写下背景或想回复的内容。")
            self.background.setFocus()
            return
        if not self.consent:
            recipient = f"{self.primary.provider}\n{self.primary.base_url}\n模型：{self.primary.model}"
            if self.vision:
                recipient += f"\n视觉：{self.vision.base_url} / {self.vision.model}"
            dialog = QMessageBox(self)
            dialog.setWindowTitle("允许 AI 帮你起草吗？")
            count = self.options.get("context_limit", 100)
            dialog.setText(f"将“{self.chat_title.text()}”的最近最多 {count} 条消息\n和补充背景发送给 {self.primary.provider}。")
            dialog.setInformativeText("只生成建议，不发送微信。较长上下文会按模型输入预算裁剪。\n自动更新开启时，新消息也会参与分析，可能产生 API 费用。")
            dialog.setDetailedText(recipient + "\n\n范围包括已启用的图片描述及语音转写；不发送微信数据库密钥或其他会话。")
            allow = dialog.addButton("允许并生成", QMessageBox.ButtonRole.AcceptRole)
            cancel = dialog.addButton("暂不发送", QMessageBox.ButtonRole.RejectRole)
            dialog.setDefaultButton(cancel)
            dialog.exec()
            if dialog.clickedButton() is not allow:
                return
            self.consent = True
        self.paused = False
        self.pause_button.setText("暂停")
        self.regenerate = True
        self.refresh()

    def _analyze_if_needed(self):
        if not self.consent or self.paused or not self.source_valid or not self.primary:
            return
        if self.pending_read or (self.source_actor and self.source_actor.busy):
            return
        if self.analysis_actor and self.analysis_actor.busy:
            return
        self.last_hash = fingerprint(self.messages, self.background.toPlainText())
        if self.last_hash == self.success_hash and not self.regenerate:
            return
        from .workers import analysis_worker
        if self.analysis_actor is None or self.analysis_actor.stopping:
            actor = self._actor(analysis_worker, 180)
            self.analysis_actor = actor
            actor.received.connect(lambda event, payload: self._analysis_event(actor, event, payload))
            actor.failed.connect(lambda message: self._analysis_failed(actor, message))
        self.regenerate = False
        self.active_hash, self.active_epoch = self.last_hash, self.epoch
        payload = {"primary": self.primary, "vision": self.vision, "options": self.options,
                   "messages": self.messages, "background": self.background.toPlainText(),
                   "limit": self.options.get("request_budget", 12)}
        self.analysis_actor.submit("analyze", payload)
        self.generate_button.setText("生成中…")
        self.generate_button.setEnabled(False)
        self._show_robot("generating", "正在生成建议…")

    def _analysis_failed(self, actor, message):
        if actor is self.analysis_actor:
            self.paused = True
            self.pause_button.setText("继续")
            self._stop_analysis()
            self.generate_button.setText("重试生成")
            self.generate_button.setEnabled(self.source_valid)
            self._show_robot("error", message + " 自动分析已暂停。")

    def _analysis_event(self, actor, event, payload):
        if actor is not self.analysis_actor:
            return
        if event == "error":
            self.requests += payload[1]
            self._analysis_failed(actor, payload[0])
        elif event == "advice":
            advice, enriched, requests = payload
            self.requests += requests
            if self.active_epoch != self.epoch or not self.source_valid or self.paused:
                return
            current = self.active_hash == fingerprint(self.messages, self.background.toPlainText())
            self.success_hash = self.active_hash
            self.display_advice(advice)
            if current:
                self._render_context(enriched)
            self._show_robot("answered" if current else "busy", "回答已生成" if current else "旧结果，正在更新…")
            self.generate_button.setToolTip(f"本次会话已发起 {self.requests} 次 API 请求")
            self._analyze_if_needed()

    def display_advice(self, advice):
        self.generate_button.setText("换一组")
        self.generate_button.setEnabled(True)
        self.reply_empty.hide()
        for card in self.reply_cards:
            card.show()
        for text, copy, reply in zip(self.reply_labels, self.copy_buttons, advice.replies):
            text.setText(reply)
            copy.setEnabled(True)
        self.analysis.show_advice(advice)

    def _render_context(self, messages):
        self.context.set_messages(messages, self.chat_title.text(), self.selected_id)

    def copy_reply(self, index):
        if self.copy_buttons[index].isEnabled():
            QApplication.clipboard().setText(self.reply_labels[index].text())
            self.copy_buttons[index].setText("已复制")
            QTimer.singleShot(1800, lambda: self.copy_buttons[index].setText("复制"))

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_button.setText("继续" if self.paused else "暂停")
        if self.paused:
            self.epoch += 1
            self._stop_analysis()
            self.generate_button.setEnabled(self.source_ready)
            self.generate_button.setText("生成")
            self._show_robot("paused", "已暂停")
            self.pause_button.setToolTip("已发出的 API 请求不能保证撤回。")
        else:
            self.refresh()

    def _tick(self):
        if self.demo:
            return
        self.actors = [actor for actor in self.actors if not actor.disposed]
        if self.paused:
            return
        if self.pending_read:
            self._dispatch_read()
        if self.auto.isChecked() and self.source_ready and not self.manual and time.monotonic() >= self.next_refresh:
            self.refresh()

    def about(self):
        try:
            from .. import __version__ as version
        except ImportError:  # 防御性回退：不影响关于对话框
            version = "dev"
        QMessageBox.information(self, "关于交我聊", f"TeachMeChat {version} · 桌面预览版\n\n" + ASCII_MARK +
                                "\n\n只为表达提供参考，不替你判断关系，也不自动发送消息。"
                                "\n本地读取 / 自选模型 / 可暂停\n配置与密钥保护说明见使用文档。")

    def _error(self, message):
        self._show_robot("error", message)
        QMessageBox.warning(self, "需要处理", message)

    def closeEvent(self, event: QCloseEvent):
        self._window_closing = True
        self.timer.stop()
        self.epoch += 1
        for actor in self.actors:
            actor.stop()
        for actor in self.actors:
            actor.dispose()
        event.accept()

    def _demo(self):
        self.primary = ProviderConfig(provider="glm", base_url="https://open.bigmodel.cn/api/paas/v4", model="已配置的聊天模型", api_key="synthetic")
        self._service_status()
        self.conversations.blockSignals(True)
        for name in ("林夏", "设计讨论小组", "陈一", "周末计划"):
            self.conversations.addItem(name)
        self.conversations.setCurrentRow(0)
        self.conversations.blockSignals(False)
        self.chat_title.setText("林夏")
        self.avatar.setText("林")
        self.selected_id = "wxid_synthetic_friend"
        self.connect_button.setText("已连接微信")
        self.chat_title.setToolTip("最近 100 条 · 本机预览")
        now = int(time.time())
        self._render_context([
            ChatMessage("0", now - 900, "wxid_synthetic_friend", "<msg><appmsg><title>周末，在城市里慢下来</title><des>散步、咖啡和几处值得停留的小地方。</des><type>5</type><url>https://example.com/article?private=not-displayed</url><sourcedisplayname>生活手记</sourcedisplayname></appmsg></msg>", kind="other"),
            ChatMessage("1", now - 600, "wxid_synthetic_friend", "这周终于把手上的项目做完了，感觉整个人轻松了不少。"),
            ChatMessage("2", now - 500, "我", "辛苦啦！忙了这么久，周末准备怎么放松？", outgoing=True),
            ChatMessage("3", now - 400, "林夏", "还没想好，可能去河边走走，也想找家安静的咖啡店。"),
        ])
        self.background.setPlainText("朋友之间自然接续话题，语气轻松，不要显得刻意。")
        self.display_advice(Advice([
            "河边散步听起来就很舒服。找家有窗边座位的咖啡店，发会儿呆也挺好。",
            "终于可以歇一歇了！我知道一家挺安静的小店，要不要把位置发你参考？",
            "这安排不错，慢慢走、慢慢喝。你更想一个人放空，还是约人一起聊聊天？",
        ], "已知事实：对方分享了项目结束后的轻松感，并提出两种休息想法。\n\n可能解释：可以顺着具体活动继续聊，但不能据此确定对方是否期待邀约。",
           "不需要急着给出完美回复。关注自己舒适的交流节奏，也给对方选择空间。", ["此页面全部为合成示例，不涉及真实联系人。", "态势解释不是心理诊断。"] ))
        self.latest_message_time = time.strftime("%H:%M", time.localtime(now - 400))
        self.last_checked_time = time.strftime("%H:%M:%S")
        self.wechat_connected = True
        self._show_robot("answered", "回答已生成 · 示例")


def launch(runtime, config_dir=None, *, demo=False):
    from .theme import apply_theme
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("TeachMeChat")
    application.setOrganizationName("TeachMeChat")
    apply_theme(application)
    window = MainWindow(runtime, config_dir, demo=demo)
    window.show()
    return application.exec()
