"""Native configuration dialogs: collect values only, never read settings or call APIs."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .. import model_catalog
from ..models import ProviderConfig, TeachMeChatError
from ..provider_specs import PROVIDERS
from ..providers import validate_base_url


DEFAULT_DIRECTORY = Path(r"C:\TeachMeChat")
_PROVIDER_ORDER = ("openai", "gemini", "deepseek", "glm", "anthropic", "kimi", "custom")


def _label(text: str, name: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _select(combo: QComboBox, value, label: str | None = None) -> None:
    index = combo.findData(value)
    if index < 0:
        combo.addItem(label or str(value), value)
        index = combo.count() - 1
    combo.setCurrentIndex(index)


def _form() -> QFormLayout:
    layout = QFormLayout()
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    layout.setHorizontalSpacing(18)
    layout.setVerticalSpacing(12)
    return layout


def _scroll(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


def _browse_row(edit: QWidget, button: QPushButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    button.setAutoDefault(False)
    return row


def _plain_path(value: str, message: str) -> str:
    value = value.strip()
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise TeachMeChatError(message)
    return value


class ModelCombo(QComboBox):
    """Editable suggestions with the former QLineEdit's public text interface."""

    textChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(16)
        self.lineEdit().setClearButtonEnabled(True)
        self.editTextChanged.connect(self.textChanged.emit)

    def text(self) -> str:
        return self.currentText()

    def setText(self, text: str) -> None:
        self.setEditText(text)

    def clear(self) -> None:
        # Existing imports/tests use clear() to empty the value, not the choices.
        self.setEditText("")

    def setPlaceholderText(self, text: str) -> None:
        self.lineEdit().setPlaceholderText(text)

    def placeholderText(self) -> str:
        return self.lineEdit().placeholderText()

    def set_models(self, model_ids: list[str]) -> None:
        current = self.text()
        with QSignalBlocker(self):
            super().clear()
            self.addItems(model_ids)
            self.setCurrentIndex(-1)
            self.setEditText(current)


class ProviderForm(QWidget):
    """Editable copy; API access is requested explicitly and performed by the caller."""

    models_requested = Signal(object)

    def __init__(self, config: ProviderConfig | None = None, parent=None):
        super().__init__(parent)
        self._original = replace(config) if config is not None else None
        self._provider_changed = False
        self._config_version = 0
        self._models_version: int | None = None
        self._secrets = {config.api_key} if config and config.api_key else set()
        self.provider_combo = QComboBox()
        for provider in _PROVIDER_ORDER:
            if provider in PROVIDERS:
                self.provider_combo.addItem(PROVIDERS[provider].label, provider)
        for provider, spec in PROVIDERS.items():
            if provider not in _PROVIDER_ORDER:
                self.provider_combo.addItem(spec.label, provider)
        provider = config.provider if config is not None else "openai"
        selected_provider = "custom" if provider == "openai-compatible" else provider
        _select(self.provider_combo, selected_provider)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("服务商提供的 API 地址")
        self.base_url_edit.setToolTip("使用 HTTPS；本机接口可使用 HTTP。更换地址会清空 Key。")
        self.model_edit = ModelCombo()
        self.model_edit.setToolTip("可选择建议模型或手输第三方模型 ID；建议不保证当前账号可用。")
        self.models_button = QPushButton("获取模型")
        self.models_button.setToolTip("仅点击后从当前 API 地址获取模型列表，不发送聊天内容。")
        self.models_label = _label("内置参考；账号实际可用模型请点“获取模型”")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("输入当前服务地址对应的 API Key")
        self.api_key_edit.setClearButtonEnabled(True)
        self.protocol_combo = QComboBox()
        for label, value in (("服务商默认", ""), ("OpenAI Chat Completions", "openai"),
                             ("Anthropic Messages", "anthropic")):
            self.protocol_combo.addItem(label, value)
        self.reasoning_combo = QComboBox()
        self.reasoning_hint = _label("")
        self.structured_combo = QComboBox()
        self.structured_combo.addItem("原生 JSON", "native")
        self.structured_combo.addItem("提示词 JSON", "prompt")
        self.structured_combo.setToolTip("按服务商支持情况选择，不会自动切换。")
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.1, 300.0)
        self.timeout_spin.setDecimals(2)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setValue(45.0)
        # Preserve legacy values for serialization; never expose a token-budget UI.
        self.thinking_budget_spin = QSpinBox(self)
        self.thinking_budget_spin.setRange(1024, 16383)
        self.thinking_budget_spin.setSingleStep(256)
        self.thinking_budget_spin.setValue(1024)
        self.thinking_budget_spin.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = _form()
        form.addRow("服务商", self.provider_combo)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("模型", _browse_row(self.model_edit, self.models_button))
        form.addRow("", self.models_label)
        self.reasoning_label = _label("推理设置")
        form.addRow(self.reasoning_label, self.reasoning_combo)
        form.addRow("", self.reasoning_hint)
        layout.addLayout(form)
        self.advanced_check = QCheckBox("高级参数")
        self.advanced_check.setToolTip("自定义 API 地址、接口协议、JSON 模式与超时。更换服务商或地址需重填 Key。")
        layout.addWidget(self.advanced_check)
        self.advanced_group = QWidget()
        advanced = _form()
        self.advanced_group.setLayout(advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.addRow("API 地址", self.base_url_edit)
        advanced.addRow("协议", self.protocol_combo)
        advanced.addRow("JSON 模式", self.structured_combo)
        advanced.addRow("请求超时", self.timeout_spin)
        advanced.addRow("", _label("更换服务商或地址后，请重新填写 Key。"))
        layout.addWidget(self.advanced_group)
        self.advanced_group.hide()
        self.advanced_check.toggled.connect(self.advanced_group.setVisible)
        self.advanced_check.setChecked(selected_provider == "custom")

        self._load_spec(reset_address=config is None)
        if config is not None:
            self.base_url_edit.setText(config.base_url)
            self.model_edit.setText(config.model)
            self.api_key_edit.setText(config.api_key)
            _select(self.protocol_combo, config.protocol)
            _select(self.structured_combo, config.structured_mode)
            self.timeout_spin.setValue(config.timeout)
            self.thinking_budget_spin.setValue(config.thinking_budget)
        self._update_reasoning(config.reasoning if config else "default")
        # Connect only after restoration, so an untouched saved key is retained.
        self.provider_combo.currentIndexChanged.connect(self._change_provider)
        self.base_url_edit.textChanged.connect(self._clear_key)
        self.model_edit.textChanged.connect(lambda *_: self._update_reasoning())
        self.protocol_combo.currentIndexChanged.connect(lambda *_: self._update_reasoning())
        for signal in (self.provider_combo.currentIndexChanged, self.base_url_edit.textChanged,
                       self.model_edit.textChanged, self.api_key_edit.textChanged,
                       self.protocol_combo.currentIndexChanged, self.reasoning_combo.currentIndexChanged,
                       self.structured_combo.currentIndexChanged, self.timeout_spin.valueChanged,
                       self.thinking_budget_spin.valueChanged):
            signal.connect(self._configuration_changed)
        self.models_button.clicked.connect(self._request_models)

    def _model_options(self) -> list[tuple[str, str]]:
        try:
            return model_catalog.get_model_options(
                self.provider_combo.currentData(), self.model_edit.text().strip(),
                self.protocol_combo.currentData(),
            )
        except TeachMeChatError:
            # Unsupported restored protocol/provider stays invalid for to_config().
            return [("默认（不发送思考参数）", "default")]

    def _update_reasoning(self, previous: str | None = None) -> None:
        previous = previous if previous is not None else self.reasoning_combo.currentData() or "default"
        options = self._model_options()
        valid = previous in {value for _, value in options}
        with QSignalBlocker(self.reasoning_combo):
            self.reasoning_combo.clear()
            for label, value in options:
                self.reasoning_combo.addItem(label, value)
            self.reasoning_combo.setCurrentIndex(self.reasoning_combo.findData(previous if valid else "default"))
        try:
            control = model_catalog.get_model_control_label(
                self.provider_combo.currentData(), self.model_edit.text().strip(),
                self.protocol_combo.currentData(),
            )
        except TeachMeChatError:
            control = "推理设置"
        self.reasoning_label.setText(control)
        self.reasoning_hint.setText(
            "原档位不可用，已选默认。" if not valid else
            "默认不发送推理参数，不等于关闭思考。" if len(options) > 1 else
            "未登记档位，可用默认。"
        )
        try:
            explanation = model_catalog.get_model_explanation(
                self.provider_combo.currentData(), self.model_edit.text().strip(),
                self.protocol_combo.currentData(),
            )
        except TeachMeChatError:
            explanation = "请在高级参数中选择有效协议。"
        self.reasoning_combo.setToolTip(explanation)
        self.reasoning_hint.setToolTip(explanation)

    def _suggest_models(self) -> None:
        try:
            suggestions = model_catalog.suggested_models(self.provider_combo.currentData())
        except TeachMeChatError:
            suggestions = []
        self.model_edit.set_models(suggestions)

    def _load_spec(self, *, reset_address: bool) -> None:
        spec = PROVIDERS.get(self.provider_combo.currentData())
        self.model_edit.setPlaceholderText(
            (spec.model_hint if spec is not None else "") or "选择模型或输入第三方模型 ID"
        )
        self._suggest_models()
        if reset_address:
            self.base_url_edit.setText(spec.base_url if spec is not None else "")
            _select(self.protocol_combo, spec.protocol if spec is not None else "")

    def _clear_key(self, *_args) -> None:
        if self.api_key_edit.text():
            self._secrets.add(self.api_key_edit.text())
        self.api_key_edit.clear()
        self._suggest_models()

    def _change_provider(self, *_args) -> None:
        self._provider_changed = True
        previous = self.reasoning_combo.currentData()
        self._clear_key()
        self._load_spec(reset_address=True)
        # A model identifier on one service is not evidence it exists on another.
        self.model_edit.clear()
        self._update_reasoning(previous)
        if self.provider_combo.currentData() == "custom":
            self.advanced_check.setChecked(True)

    def _configuration_changed(self, *_args) -> None:
        self._config_version += 1
        if self._models_version is not None:
            self.models_label.setText("配置已变更，请重新获取模型。")
        self._models_version = None
        self.models_button.setEnabled(True)

    def _request_models(self) -> None:
        if self._models_version is not None:
            return
        try:
            config = self.to_config(allow_empty_model=True)
        except TeachMeChatError as exc:
            self.models_label.setText(str(exc))
            return
        self._secrets.add(config.api_key)
        self._models_version = self._config_version
        self.models_button.setEnabled(False)
        self.models_label.setText("正在获取模型… 可继续编辑或测试连接")
        self.models_requested.emit(config)

    def set_models(self, model_ids, error: str = "") -> None:
        """Apply only the pending snapshot; caller additionally guards request generations."""
        if self._models_version is None or self._models_version != self._config_version:
            return
        self._models_version = None
        self.models_button.setEnabled(True)
        if error:
            text = str(error)
            for secret in sorted(filter(None, self._secrets), key=len, reverse=True):
                text = text.replace(secret, "[凭据已隐藏]")
            text = "".join(char for char in text if ord(char) >= 32 and not 127 <= ord(char) < 160)
            self.models_label.setText("获取失败 · " + text[:300])
            return
        ids = []
        seen = set()
        for model in model_ids if isinstance(model_ids, (list, tuple)) else ():
            if (not isinstance(model, str) or not model.strip() or len(model) > 256
                    or any(ord(char) < 32 or 127 <= ord(char) < 160 for char in model)
                    or any(secret in model for secret in self._secrets if secret)):
                continue
            model = model.strip()
            if model not in seen:
                seen.add(model)
                ids.append(model)
            if len(ids) >= 1000:
                break
        if not ids:
            self.models_label.setText("未返回可用模型，可手输模型 ID 或稍后重试。")
            return
        self.model_edit.set_models(ids)
        self.models_label.setText(f"已加载 {len(ids)} 个")

    def to_config(self, *, allow_empty_model: bool = False) -> ProviderConfig:
        """Validate locally without instantiating a client or touching the network."""
        provider = self.provider_combo.currentData()
        spec = PROVIDERS.get(provider)
        if spec is None:
            raise TeachMeChatError("请选择受支持的服务商。")
        try:
            base_url = validate_base_url(self.base_url_edit.text().strip())
        except (TeachMeChatError, ValueError, TypeError):
            raise TeachMeChatError("API 地址无效：请使用 HTTPS（本机回环可用 HTTP），勿包含凭据、查询或片段。") from None
        model = self.model_edit.text().strip()
        if ((not model and not allow_empty_model) or len(model) > 256
                or any(ord(char) < 32 or ord(char) == 127 for char in model)):
            raise TeachMeChatError("请填写有效模型标识；占位提示不是已配置的模型。")
        key = self.api_key_edit.text()
        if not key or not key.isascii() or any(ord(char) < 33 or ord(char) == 127 for char in key):
            raise TeachMeChatError("请填写有效 API Key；凭据不能包含空格或控制字符。")
        protocol = self.protocol_combo.currentData()
        if protocol not in ("", "openai", "anthropic"):
            raise TeachMeChatError("请选择受支持的接口协议。")
        reasoning = self.reasoning_combo.currentData()
        if reasoning not in {value for _, value in self._model_options()}:
            raise TeachMeChatError("当前模型或协议不支持所选推理档位，请重新选择。")
        structured = self.structured_combo.currentData()
        if structured not in ("native", "prompt"):
            raise TeachMeChatError("请选择原生或提示词结构化输出模式。")
        if (not self._provider_changed and self._original is not None
                and self._original.provider == "openai-compatible"):
            provider = "openai-compatible"
        return ProviderConfig(
            provider=provider, base_url=base_url, model=model, api_key=key,
            reasoning=reasoning, timeout=float(self.timeout_spin.value()),
            protocol=protocol, structured_mode=structured,
            thinking_budget=int(self.thinking_budget_spin.value()),
        )


class SettingsDialog(QDialog):
    """The caller owns persistence and asynchronous execution of all probes.

    ``probe_requested`` kinds are text/structured/vision. The vision request must
    use a synthetic image, not user media. ``result_data`` exists only on accept.
    """

    probe_requested = Signal(object, str)
    models_requested = Signal(object, str)
    configuration_ready = Signal(object)

    def __init__(self, primary: ProviderConfig | None, vision: ProviderConfig | None,
                 options: dict, config_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置 · TeachMeChat")
        self.setMinimumWidth(720)
        self.resize(840, 640)
        self.setSizeGripEnabled(True)
        self.result_data: dict | None = None
        self._options = dict(options or {})
        self._probe_secrets = {config.api_key for config in (primary, vision) if config and config.api_key}
        self._pending_probes: set[str] = set()
        self.probe_buttons: dict[str, QPushButton] = {}
        self.probe_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        layout.addWidget(_label("连接模型服务" if primary is None else "设置", "hero"))
        layout.addWidget(_label("选择或手输模型并填写 Key。仅点击获取模型或测试才联网，不发送聊天内容。"))
        self.storage_summary = _label("", "section")
        self.storage_summary.setAccessibleName("保存与隐私摘要")
        self.storage_summary.setVisible(primary is None)
        layout.addWidget(self.storage_summary)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_models(primary, vision)
        self._build_storage(config_dir)
        self._build_media()
        self.error_label = _label("", "error")
        self.error_label.setAccessibleName("设置校验提示")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setObjectName("primary")
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        self.save_mode_combo.currentIndexChanged.connect(self._update_save_mode)
        self.directory_edit.textChanged.connect(self._update_save_mode)
        self._update_save_mode()
        self._update_vision()

    def _build_models(self, primary, vision) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        primary_group = QGroupBox()
        primary_group.setObjectName("modelCard")
        primary_layout = QVBoxLayout(primary_group)
        primary_layout.setContentsMargins(18, 18, 18, 16)
        primary_layout.setSpacing(12)
        primary_layout.addWidget(_label("聊天模型", "section"))
        self.primary_form = ProviderForm(primary)
        primary_layout.addWidget(self.primary_form)
        primary_layout.addWidget(self._probe_row("text", "测试连接"))
        primary_layout.addWidget(self._probe_row("structured", "测试 JSON"))
        layout.addWidget(primary_group)
        self.vision_enabled_check = QCheckBox("启用视觉模型 · 识别图片内容")
        self.vision_enabled_check.setChecked(bool(self._options.get("vision_enabled", vision is not None)))
        self.vision_reuse_check = QCheckBox("视觉请求复用主模型配置")
        self.vision_reuse_check.setChecked(bool(self._options.get("vision_reuse", vision is None or vision == primary)))
        layout.addWidget(self.vision_enabled_check)
        layout.addWidget(self.vision_reuse_check)
        self.vision_group = QGroupBox()
        self.vision_group.setObjectName("modelCard")
        vision_layout = QVBoxLayout(self.vision_group)
        vision_layout.setContentsMargins(18, 18, 18, 16)
        vision_layout.setSpacing(12)
        vision_layout.addWidget(_label("图片模型", "section"))
        self.vision_form = ProviderForm(vision)
        for target, form in (("primary", self.primary_form), ("vision", self.vision_form)):
            form.models_requested.connect(lambda config, t=target: self.models_requested.emit(config, t))
        vision_layout.addWidget(self.vision_form)
        layout.addWidget(self.vision_group)
        self.vision_probe_row = self._probe_row("vision", "测试图片")
        layout.addWidget(self.vision_probe_row)
        self.vision_hint = _label("测试只用示例图片；发送聊天图片仍需另行确认。")
        layout.addWidget(self.vision_hint)
        layout.addStretch()
        self.tabs.addTab(_scroll(page), "服务")
        self.vision_enabled_check.toggled.connect(self._update_vision)
        self.vision_reuse_check.toggled.connect(self._update_vision)

    def _probe_row(self, kind: str, title: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 0)
        button = QPushButton(title)
        button.setAutoDefault(False)
        button.clicked.connect(lambda _checked=False, k=kind: self._request_probe(k))
        label = _label("尚未探测")
        self.probe_buttons[kind] = button
        self.probe_labels[kind] = label
        layout.addWidget(button)
        layout.addWidget(label, 1)
        return row

    def _build_storage(self, config_dir: Path) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)
        layout.addWidget(_label("存储与凭据", "section"))
        self.directory_edit = QLineEdit(str(config_dir or DEFAULT_DIRECTORY))
        self.directory_browse_button = QPushButton("选择目录…")
        self.directory_browse_button.clicked.connect(self._browse_directory)
        form = _form()
        form.addRow("配置目录", _browse_row(self.directory_edit, self.directory_browse_button))
        self.save_mode_combo = QComboBox()
        self.save_mode_combo.addItem("保存配置与加密 API Key", "remember")
        self.save_mode_combo.addItem("仅保存公开配置 · 不保存 API Key", "public")
        self.save_mode_combo.addItem("仅本次会话 · 不写入设置", "session")
        mode = self._options.get("credential_mode", self._options.get("save_mode", "remember"))
        _select(self.save_mode_combo, mode if mode in ("remember", "public", "session") else "remember")
        form.addRow("保存方式", self.save_mode_combo)
        layout.addLayout(form)
        self.save_mode_hint = _label("")
        layout.addWidget(self.save_mode_hint)
        layout.addWidget(_label("隐私边界", "section"))
        layout.addWidget(_label(
            "• 默认 C:\\TeachMeChat 只放小型配置，不复制聊天或媒体。\n"
            "• 只有点击保存才写入配置；可改为仅本次会话。\n"
            "• 数据库路径、数据库密钥、聊天内容与来源授权不保存。\n"
            "• 测试不含聊天内容；分析前仍需确认外发范围。"
        ))
        layout.addStretch()
        self.tabs.addTab(_scroll(page), "隐私")

    def _build_media(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)
        layout.addWidget(_label("本地语音转写", "section"))
        self.whisper_path_edit = QLineEdit(str(self._options.get("whisper_path", "") or ""))
        self.whisper_path_edit.setPlaceholderText(r"<本地路径>\large-v3-turbo.pt（可留空）")
        self.whisper_browse_button = QPushButton("选择权重…")
        self.whisper_browse_button.clicked.connect(self._browse_whisper)
        form = _form()
        form.addRow("Whisper turbo", _browse_row(self.whisper_path_edit, self.whisper_browse_button))
        layout.addLayout(form)
        layout.addWidget(_label("仅使用本机本地 turbo 权重，不下载模型、不安装依赖。留空则不加载本地转写；模型文件与架构由后台校验。"))
        layout.addWidget(_label("刷新与请求预算", "section"))
        self.auto_refresh_check = QCheckBox("自动刷新（每 5 秒）")
        self.auto_refresh_check.setChecked(bool(self._options.get("auto_refresh", False)))
        layout.addWidget(self.auto_refresh_check)
        layout.addWidget(_label("自动检查更新不等于自动外发或自动发送回复；外发授权与任务取消由主窗口管理。"))
        self.request_budget_spin = QSpinBox()
        self.request_budget_spin.setRange(1, 100)
        budget = self._options.get("request_budget", 12)
        self.request_budget_spin.setValue(budget if type(budget) is int else 12)
        self.request_budget_spin.setSuffix(" 次 / 轮")
        budget_form = _form()
        budget_form.addRow("单轮 API 请求上限", self.request_budget_spin)
        layout.addLayout(budget_form)
        layout.addWidget(_label("文本与媒体请求共享单轮预算；达到上限后停止后续请求，避免无界消耗。"))
        layout.addStretch()
        self.tabs.addTab(_scroll(page), "媒体")

    def _update_vision(self, *_args) -> None:
        enabled = self.vision_enabled_check.isChecked()
        reuse = self.vision_reuse_check.isChecked()
        self.vision_reuse_check.setEnabled(enabled)
        self.vision_reuse_check.setVisible(enabled)
        self.vision_probe_row.setVisible(enabled)
        self.vision_hint.setVisible(enabled)
        self.vision_group.setVisible(enabled and not reuse)
        self.vision_form.setEnabled(enabled and not reuse)
        self.probe_buttons["vision"].setEnabled(enabled and "vision" not in self._pending_probes)

    def _update_save_mode(self, *_args) -> None:
        mode = self.save_mode_combo.currentData()
        captions = {
            "remember": ("加密保存设置与 API Key", "API Key 使用 Windows DPAPI 绑定当前用户加密保存，配置目录限制为当前用户访问。下次启动可直接恢复；更换 Windows 用户或机器后需要重新输入 Key。"),
            "public": ("保存公开配置（不含 Key）", "只持久化非敏感配置；API Key 仅供当前会话使用，下次需要重新输入。"),
            "session": ("应用到本次会话", "仅应用当前会话，不请求写入设置文件；已有保存文件不会因本次选择自动删除。"),
        }
        caption, hint = captions[mode]
        self.save_button.setText(caption)
        self.save_mode_hint.setText(hint)
        directory = self.directory_edit.text().strip() or "（请选择配置目录）"
        summaries = {
            "remember": f"点击保存后：{directory} 仅存小型配置；API Key 由 Windows DPAPI 加密。\n不保存聊天或来源授权；保存方式可在「隐私」中更改。",
            "public": f"点击保存后：{directory} 仅存公开配置，不保存 API Key、聊天或来源授权。",
            "session": "仅本次会话：不写入设置或 API Key；已有保存文件不会自动删除。",
        }
        self.storage_summary.setText(summaries[mode])

    def _browse_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择配置目录", self.directory_edit.text())
        if selected:
            self.directory_edit.setText(selected)

    def _browse_whisper(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self, "选择本地 Whisper turbo 权重", self.whisper_path_edit.text() or str(Path.home()),
            "PyTorch 权重 (*.pt *.pth);;所有文件 (*)",
        )
        if selected:
            self.whisper_path_edit.setText(selected)

    def _visual_config(self, primary: ProviderConfig | None = None) -> ProviderConfig | None:
        if not self.vision_enabled_check.isChecked():
            return None
        if self.vision_reuse_check.isChecked():
            return replace(primary if primary is not None else self.primary_form.to_config())
        return self.vision_form.to_config()

    def _request_probe(self, kind: str) -> None:
        if kind in self._pending_probes:
            return
        try:
            config = self._visual_config() if kind == "vision" else self.primary_form.to_config()
            if config is None:
                raise TeachMeChatError("请先启用视觉模型。")
        except TeachMeChatError as exc:
            self.probe_labels[kind].setText(str(exc))
            return
        self._probe_secrets.add(config.api_key)
        self._pending_probes.add(kind)
        self.probe_buttons[kind].setEnabled(False)
        self.probe_labels[kind].setText("后台探测中… 可继续编辑或取消")
        self.probe_requested.emit(config, kind)

    def set_models(self, model_ids, error: str = "", target: str = "primary") -> None:
        """GUI-thread model-discovery result; the main window guards actor generations."""
        form = {"primary": self.primary_form, "vision": self.vision_form}.get(target)
        if form is not None:
            # Never display credentials from either form in endpoint-supplied data.
            form._secrets.update(self._probe_secrets | self.primary_form._secrets | self.vision_form._secrets
                                 | {self.primary_form.api_key_edit.text(), self.vision_form.api_key_edit.text()})
            form.set_models(model_ids, error)

    def set_probe_result(self, kind: str, text: str, success: bool) -> None:
        """Called by the GUI-thread receiver after the worker returns a safe result."""
        if kind not in self.probe_labels:
            return
        self._pending_probes.discard(kind)
        self.probe_buttons[kind].setEnabled(kind != "vision" or self.vision_enabled_check.isChecked())
        text = str(text)
        secrets = self._probe_secrets | {self.primary_form.api_key_edit.text(), self.vision_form.api_key_edit.text()}
        for secret in sorted(filter(None, secrets), key=len, reverse=True):
            text = text.replace(secret, "[凭据已隐藏]")
        text = "".join(char for char in text if char in "\n\t" or (ord(char) >= 32 and not 127 <= ord(char) < 160))
        self.probe_labels[kind].setText(("探测成功 · " if success else "探测失败 · ") + text[:600])
        self.probe_labels[kind].setProperty("success", bool(success))

    def accept(self) -> None:
        self.error_label.hide()
        try:
            primary = self.primary_form.to_config()
            vision = self._visual_config(primary)
        except TeachMeChatError as exc:
            self.tabs.setCurrentIndex(0)
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        try:
            directory = Path(_plain_path(self.directory_edit.text(), "请选择有效的配置目录。"))
        except TeachMeChatError as exc:
            self.tabs.setCurrentIndex(1)
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        whisper_path = self.whisper_path_edit.text().strip()
        if whisper_path:
            path = PureWindowsPath(whisper_path)
            if (not path.is_absolute() or path.drive.startswith("\\\\")
                    or whisper_path.startswith(("\\\\", "//"))
                    or any(ord(char) < 32 or ord(char) == 127 for char in whisper_path)):
                self.tabs.setCurrentIndex(2)
                self.error_label.setText("Whisper turbo 权重须使用本机绝对路径（不支持网络路径）；也可留空禁用本地转写。")
                self.error_label.show()
                return
        options = dict(self._options)
        options.update(
            vision_enabled=bool(self.vision_enabled_check.isChecked()),
            vision_reuse=bool(self.vision_reuse_check.isChecked()),
            auto_refresh=bool(self.auto_refresh_check.isChecked()),
            whisper_path=whisper_path, request_budget=int(self.request_budget_spin.value()),
        )
        mode = self.save_mode_combo.currentData()
        if "save_mode" in options:
            options["save_mode"] = mode
        self.result_data = {"primary": primary, "vision": vision, "options": options,
                            "directory": directory, "save_mode": mode}
        self.configuration_ready.emit(self.result_data)
        super().accept()

    def reject(self) -> None:
        self.result_data = None
        super().reject()


class SourceDialog(QDialog):
    """Collect explicit read-only authorization; source values never become settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("其他导入方式 · TeachMeChat")
        self.setMinimumWidth(720)
        self.resize(780, 620)
        self.setSizeGripEnabled(True)
        self.spec: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        layout.addWidget(_label("其他导入方式", "hero"))
        layout.addWidget(_label("仅本地只读，不修改微信或发送消息。向模型发送内容仍需另行确认。"))
        self.mode_combo = QComboBox()
        for title, mode in (("连接当前微信（推荐）", "auto"),
                            ("手动填写背景", "manual"),
                            ("导入明文快照（高级）", "snapshot"),
                            ("手动连接数据库（高级）", "live-manual")):
            self.mode_combo.addItem(title, mode)
        mode_form = _form()
        mode_form.addRow("数据来源", self.mode_combo)
        layout.addLayout(mode_form)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)

        manual = QWidget()
        manual_layout = QVBoxLayout(manual)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.addWidget(_label("手动输入背景", "section"))
        manual_layout.addWidget(_label("描述聊天背景或粘贴必要片段。内容仅保留于本次会话，分析时再确认是否外发。"))
        self.background_edit = QPlainTextEdit()
        self.background_edit.setPlaceholderText("例如：我想礼貌地确认约定时间，又不想显得催促……")
        self.background_edit.setMinimumHeight(120)
        manual_layout.addWidget(self.background_edit, 1)
        self.pages.addWidget(manual)
        auto = QWidget()
        auto_layout = QVBoxLayout(auto)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.addWidget(_label("连接已登录的微信", "section"))
        auto_layout.addWidget(_label("请先在电脑上登录微信。确认授权后才会在后台连接；尚未登录时会等待，可随时在主窗口停止。"))
        auto_layout.addStretch()
        self.pages.addWidget(auto)

        file_page = QWidget()
        file_layout = QVBoxLayout(file_page)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.source_hint = _label("")
        file_layout.addWidget(self.source_hint)
        form = _form()
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("账号根目录、Msg / db_storage 或明文快照目录")
        self.root_browse_button = QPushButton("选择目录…")
        self.root_browse_button.clicked.connect(lambda: self._browse_source(self.root_edit, "选择数据目录"))
        form.addRow("数据目录", _browse_row(self.root_edit, self.root_browse_button))
        self.version_combo = QComboBox()
        self.version_combo.addItem("微信 4.x", 4)
        self.version_combo.addItem("微信 3.x", 3)
        form.addRow("数据库版本", self.version_combo)
        self.media_root_edit = QLineEdit()
        self.media_root_edit.setPlaceholderText("可选：经授权的独立媒体目录")
        self.media_browse_button = QPushButton("选择目录…")
        self.media_browse_button.clicked.connect(lambda: self._browse_source(self.media_root_edit, "选择媒体目录"))
        form.addRow("媒体目录", _browse_row(self.media_root_edit, self.media_browse_button))
        self.account_id_edit = QLineEdit()
        self.account_id_edit.setPlaceholderText("可选：本人准确微信 ID，用于识别消息方向")
        form.addRow("本人微信 ID", self.account_id_edit)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("本人授权取得的数据库密钥，仅用于本次会话")
        self.key_label = QLabel("数据库密钥")
        form.addRow(self.key_label, self.key_edit)
        file_layout.addLayout(form)
        file_layout.addWidget(_label("目录与密钥仅本次使用，不写入设置。"))
        file_layout.addStretch()
        self.pages.addWidget(_scroll(file_page))

        self.authorization_check = QCheckBox("我确认只读取本人有权访问的聊天")
        self.authorization_check.setToolTip("仅本人数据或所有者明确授权的数据；仅本地只读，不授权外发。")
        # One explicit opt-in covers ownership/access rights and local read-only use.
        # Keep the legacy attribute so callers cannot bypass either boundary.
        self.readonly_check = self.authorization_check
        layout.addWidget(self.authorization_check)
        self.error_label = _label("", "error")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("确认来源 · 仅只读")
        self.confirm_button.setObjectName("primary")
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        self.mode_combo.currentIndexChanged.connect(self._update_mode)
        self._update_mode()

    def _browse_source(self, edit: QLineEdit, title: str) -> None:
        path = QFileDialog.getExistingDirectory(self, title, edit.text())
        if path:
            edit.setText(path)

    def _update_mode(self, *_args) -> None:
        mode = self.mode_combo.currentData()
        self.pages.setCurrentIndex(0 if mode == "manual" else 1 if mode == "auto" else 2)
        live = mode == "live-manual"
        self.key_label.setVisible(live)
        self.key_edit.setVisible(live)
        self.key_edit.setEnabled(live)
        if not live:
            self.key_edit.clear()
        self.source_hint.setText("读取本人授权的实时数据库；密钥以隐藏输入提供。" if live else "读取已有明文快照，不修改原数据库。")
        self.error_label.hide()

    def accept(self) -> None:
        self.error_label.hide()
        try:
            if not self.authorization_check.isChecked() or not self.readonly_check.isChecked():
                raise TeachMeChatError("请确认数据授权与本地只读边界；此确认不包含外发授权。")
            mode = self.mode_combo.currentData()
            if mode == "manual":
                background = self.background_edit.toPlainText().strip()
                if not background:
                    raise TeachMeChatError("请填写手动背景，或选择其他数据来源。")
                spec = {"mode": "manual", "background": background}
            elif mode == "auto":
                spec = {"mode": "auto"}
            else:
                root = _plain_path(self.root_edit.text(), "请选择有效的数据目录。")
                media_root = self.media_root_edit.text().strip()
                if media_root:
                    media_root = _plain_path(media_root, "请填写有效的媒体目录，或留空。")
                key = self.key_edit.text() if mode == "live-manual" else ""
                if mode == "live-manual" and (not key or any(char.isspace() or ord(char) < 32 for char in key)):
                    raise TeachMeChatError("请填写有效的本人授权数据库密钥；密钥不会被显示或保存。")
                spec = {"mode": mode, "root": root, "version": int(self.version_combo.currentData()),
                        "media_root": media_root, "account_id": self.account_id_edit.text().strip(), "key": key}
        except TeachMeChatError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.spec = spec
        super().accept()

    def reject(self) -> None:
        self.spec = None
        self.key_edit.clear()
        super().reject()
