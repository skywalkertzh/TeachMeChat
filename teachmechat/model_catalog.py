"""Offline exact-ID model references and separately verified API capabilities.

Evidence supplied from official documents, checked 2026-10-09. Suggestions are
not account availability or a claim of latest production status. No I/O here.
"""

from dataclasses import dataclass

from .models import TeachMeChatError
from .provider_specs import get_spec


@dataclass(frozen=True)
class ModelCapability:
    provider: str
    protocol: str
    parameter: str
    values: tuple[str, ...]
    explanation: str
    default_effort: str = ""
    source_urls: tuple[str, ...] = ()
    evidence_level: str = "official"
    legacy_budget: bool = False
    completion_token_field: str = "max_tokens"


_OPENAI_SOURCES = (
    "https://raw.githubusercontent.com/openai/openai-python/v2.8.1/src/openai/types/chat/completion_create_params.py",
    "https://raw.githubusercontent.com/openai/openai-python/v1.75.0/src/openai/types/chat/completion_create_params.py",
    "https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/gpt-5/gpt-5_new_params_and_tools.ipynb",
)
_ANTHROPIC_SOURCES = (
    "https://raw.githubusercontent.com/anthropics/skills/main/skills/claude-api/SKILL.md",
)
_KIMI_SOURCES = ("https://platform.kimi.com/docs/api/chat",)
_GLM_SOURCES = ("https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3.md",)
_GLM52_SOURCES = ("https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2.md",)
_GLM_LEGACY_SOURCES = ("https://docs.bigmodel.cn/cn/guide/models/text/glm-4.7",)
_GEMINI_SOURCES = (
    "https://ai.google.dev/gemini-api/docs/openai",
    "https://ai.google.dev/gemini-api/docs/models",
    "https://ai.google.dev/gemini-api/docs/thinking",
)
_FIVE_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# OpenAI 2026-10 目录（Chat Completions，顶层 reasoning_effort）。
# gpt-5.5-pro 与 gpt-5.6-cyber 仅通过 Responses API 提供，本应用只支持
# Chat Completions，故不收录。gpt-5 / gpt-5-mini / gpt-5-nano / gpt-5.1 / o3 /
# o4-mini 保留供过渡，官方已列入退役计划。
_GPT55 = ModelCapability("openai", "openai", "reasoning_effort", ("none", "low", "medium", "high", "xhigh"),
    "reasoning_effort 支持 none/low/medium/high/xhigh，默认 medium；不支持 max。",
    default_effort="medium", source_urls=_OPENAI_SOURCES, completion_token_field="max_completion_tokens")
_GPT6_ASTRA = ModelCapability("openai", "openai", "reasoning_effort", ("low", "medium", "high", "xhigh", "max"),
    "reasoning_effort 支持 low/medium/high/xhigh/max；none 会返回 400。默认档位官方未核实。",
    source_urls=_OPENAI_SOURCES, completion_token_field="max_completion_tokens")
_GPT61_SOL = ModelCapability("openai", "openai", "reasoning_effort", ("low", "medium", "high", "xhigh", "max"),
    "reasoning_effort 支持 low/medium/high/xhigh/max，默认 medium；none 与 minimal 会返回 400。",
    default_effort="medium", source_urls=_OPENAI_SOURCES, completion_token_field="max_completion_tokens")
_GPT_EFFORT_FULL = ModelCapability("openai", "openai", "reasoning_effort",
    ("none", "low", "medium", "high", "xhigh", "max"),
    "reasoning_effort 支持 none/low/medium/high/xhigh/max，默认 medium。",
    default_effort="medium", source_urls=_OPENAI_SOURCES, completion_token_field="max_completion_tokens")
_GPT5 = ModelCapability("openai", "openai", "reasoning_effort", ("minimal", "low", "medium", "high"),
    "reasoning_effort 支持 minimal/low/medium/high；不支持 none。官方已列入退役计划。",
    source_urls=_OPENAI_SOURCES, completion_token_field="max_completion_tokens")
_GPT51 = ModelCapability("openai", "openai", "reasoning_effort", ("none", "low", "medium", "high"),
    "reasoning_effort 支持 none/low/medium/high；none 关闭推理，不支持 minimal。官方已列入退役计划。",
    source_urls=_OPENAI_SOURCES, completion_token_field="max_completion_tokens")
_O3 = ModelCapability("openai", "openai", "reasoning_effort", ("low", "medium", "high"),
    "reasoning_effort 支持 low/medium/high；不支持 none/minimal。官方已列入退役计划。",
    source_urls=_OPENAI_SOURCES, completion_token_field="max_completion_tokens")

# Anthropic 2026-10 目录（Messages，effort 走 output_config.effort，adaptive =
# thinking.type=adaptive）。claude-opus-4-1 已退役，不再收录。
_CLAUDE_FABLE = ModelCapability("anthropic", "anthropic", "adaptive", _FIVE_EFFORTS,
    "思考必须开启且使用 adaptive；low/medium/high/xhigh/max 发送 thinking.type=adaptive 与 "
    "output_config.effort，默认 high；disabled 与手动预算（budget_tokens）都会返回 400。",
    default_effort="high", source_urls=_ANTHROPIC_SOURCES)
_CLAUDE_OPUS55 = ModelCapability("anthropic", "anthropic", "adaptive", _FIVE_EFFORTS,
    "思考始终开启；支持 adaptive 或省略 thinking。low/medium/high/xhigh/max 发送 "
    "thinking.type=adaptive 与 output_config.effort，默认 medium；不支持关闭或手动预算。",
    default_effort="medium", source_urls=_ANTHROPIC_SOURCES)
_CLAUDE_SONNET55 = ModelCapability("anthropic", "anthropic", "adaptive", _FIVE_EFFORTS,
    "思考使用 adaptive；low/medium/high/xhigh/max 发送 thinking.type=adaptive 与 "
    "output_config.effort，默认 high。关闭需要额外 between_tools 条件及 effort<=high，"
    "本客户端保守不提供关闭；不支持手动预算。",
    default_effort="high", source_urls=_ANTHROPIC_SOURCES)
_CLAUDE_HAIKU55 = ModelCapability("anthropic", "anthropic", "adaptive", _FIVE_EFFORTS,
    "默认 adaptive；low/medium/high/xhigh/max 发送 thinking.type=adaptive 与 "
    "output_config.effort，默认 medium。关闭仅在 effort<=high 时允许，"
    "本客户端保守不提供关闭；不支持手动预算。",
    default_effort="medium", source_urls=_ANTHROPIC_SOURCES)
_CLAUDE_OPUS5 = ModelCapability("anthropic", "anthropic", "adaptive", _FIVE_EFFORTS,
    "思考使用 adaptive；low/medium/high/xhigh/max 发送 thinking.type=adaptive 与 "
    "output_config.effort，默认 high；本客户端保守不提供关闭（disabled），不支持手动预算。",
    default_effort="high", source_urls=_ANTHROPIC_SOURCES)
_CLAUDE_ADAPTIVE5 = ModelCapability("anthropic", "anthropic", "adaptive", ("disabled",) + _FIVE_EFFORTS,
    "low/medium/high/xhigh/max 显式发送 thinking.type=adaptive 与 output_config.effort；"
    "默认 high。disabled 关闭思考；不支持 enabled 或手动预算。",
    default_effort="high", source_urls=_ANTHROPIC_SOURCES)
_CLAUDE_ADAPTIVE = ModelCapability("anthropic", "anthropic", "adaptive", ("disabled", "low", "medium", "high", "max"),
    "low/medium/high/max 发送 thinking.type=adaptive 与 output_config.effort，默认 high；"
    "disabled 发送 thinking.type=disabled。不支持 xhigh。"
    "旧 enabled + thinking_budget 配置仍兼容（官方已弃用手动预算）。",
    default_effort="high", source_urls=_ANTHROPIC_SOURCES, legacy_budget=True)
_CLAUDE_OPUS45 = ModelCapability("anthropic", "anthropic", "adaptive", ("low", "medium", "high"),
    "low/medium/high 发送 thinking.type=adaptive 与 output_config.effort；可与已保存的 "
    "thinking_budget 并存（旧 enabled + thinking_budget 配置仍兼容）。不支持 xhigh/max。",
    source_urls=_ANTHROPIC_SOURCES, legacy_budget=True)
_CLAUDE_BUDGET = ModelCapability("anthropic", "anthropic", "budget", ("disabled", "enabled"),
    "仅支持 thinking.type=enabled/disabled，不支持 effort。enabled 使用已保存的 thinking_budget"
    "（默认 1024 tokens），无需在界面手输预算。",
    source_urls=_ANTHROPIC_SOURCES, legacy_budget=True)
_CLAUDE_BUDGET_DEPRECATED = ModelCapability("anthropic", "anthropic", "budget", ("disabled", "enabled"),
    "仅支持 thinking.type=enabled/disabled，不支持 effort。enabled 使用已保存的 thinking_budget"
    "（默认 1024 tokens），无需在界面手输预算。官方已于 2026-09-30 弃用该型号。",
    source_urls=_ANTHROPIC_SOURCES, legacy_budget=True)

# 智谱 GLM 2026-10 目录。
_GLM53 = ModelCapability("glm", "openai", "thinking_effort", ("low", "high", "max"),
    "仅支持 thinking.type=enabled；reasoning_effort 支持 low/high/max，默认 max；不支持关闭思考。",
    default_effort="max", source_urls=_GLM_SOURCES)
_GLM53_FLASH = ModelCapability("glm", "openai", "thinking_effort", ("low", "high", "max"),
    "仅支持 thinking.type=enabled；reasoning_effort 支持 low/high/max，默认 max；不支持关闭思考。"
    "支持图片/视频输入。",
    default_effort="max", source_urls=_GLM_SOURCES)
_GLM52 = ModelCapability("glm", "openai", "thinking_effort",
    ("disabled", "none", "minimal", "low", "medium", "high", "xhigh", "max"),
    "thinking.type 支持 enabled（默认）/disabled；reasoning_effort 支持 "
    "none/minimal/low/medium/high/xhigh/max 全档，默认 max；none 与 minimal 等于放弃思考。",
    default_effort="max", source_urls=_GLM52_SOURCES)
_GLM_TOGGLE = ModelCapability("glm", "openai", "thinking", ("disabled", "enabled"),
    "thinking.type 支持 enabled（默认）/disabled（开启/关闭思考）；未登记 effort 档位。",
    source_urls=_GLM_SOURCES)
_GLM_LEGACY_TOGGLE = ModelCapability("glm", "openai", "thinking", ("disabled", "enabled"),
    "thinking.type 支持 enabled/disabled（轮级思考可关）；未登记 effort 档位。该型号为旧型号。",
    source_urls=_GLM_LEGACY_SOURCES)
_GLM_REFERENCE = ModelCapability("glm", "openai", "default_only", (),
    "免费型号；ChatCompletions 具体档位未核实；仅提供 default，不按名称猜测。",
    source_urls=_GLM_LEGACY_SOURCES, evidence_level="name_only")

# Kimi 2026-10 目录。kimi-k2.5、moonshot-v1 系列、kimi-latest 与 kimi-k2 系列均已下线，不收录。
_KIMI_TOGGLE = ModelCapability("kimi", "openai", "thinking", ("disabled", "enabled"),
    "thinking.type 支持 enabled/disabled（开启/关闭思考）；未登记 effort 档位。",
    source_urls=_KIMI_SOURCES)
_KIMI_KEEP = ModelCapability("kimi", "openai", "thinking_keep", ("enabled",),
    "思考始终开启、不可关闭；thinking 仅允许 {\"type\":\"enabled\",\"keep\":\"all\"}；"
    "无 effort 档位。生成长度沿用 max_tokens。",
    source_urls=_KIMI_SOURCES)
_KIMI_EFFORT = ModelCapability("kimi", "openai", "reasoning_effort", ("low", "high", "max"),
    "思考始终开启；reasoning_effort 支持 low/high/max，默认 max；不发送 thinking，"
    "不支持关闭或 medium。生成长度使用 max_completion_tokens。",
    default_effort="max", source_urls=_KIMI_SOURCES, completion_token_field="max_completion_tokens")

# DeepSeek 保持既有经核验档位。
_DEEPSEEK = ModelCapability("deepseek", "openai", "thinking_effort", ("none", "low", "high", "max"),
    "reasoning_effort 支持 none/low/high/max，默认 high；thinking 默认 enabled。"
    "none 同时发送 thinking.type=disabled 与 reasoning_effort=none；其他档位开启思考。"
    "已保存的 enabled/disabled 保留旧 wire 兼容，不重复显示在列表。",
    default_effort="high", source_urls=("https://api-docs.deepseek.com/api/create-chat-completion",))

# Google Gemini：OpenAI 兼容端点（Bearer 鉴权），档位同样走顶层 reasoning_effort。
# 官方已无裸 gemini-3-pro / gemini-3-flash，仅有 preview 变体；2.5 系列仅限既往使用者。
_GEMINI_NOTE = ("兼容端点支持 response_format（schema 形式）结构化输出；native 模式发送的 "
                "json_object 形式尚未核验，建议使用 prompt 模式。官方已无裸 gemini-3-pro / "
                "gemini-3-flash，仅有 preview 变体；2.5 系列仅限既往使用者。")
_GEMINI38 = ModelCapability("gemini", "openai", "reasoning_effort", ("low", "medium", "high"),
    "reasoning_effort 支持 low/medium/high，默认 medium；minimal 会返回 400。" + _GEMINI_NOTE,
    default_effort="medium", source_urls=_GEMINI_SOURCES)
_GEMINI36 = ModelCapability("gemini", "openai", "reasoning_effort", ("minimal", "low", "medium", "high"),
    "reasoning_effort 支持 minimal/low/medium/high，默认 medium。" + _GEMINI_NOTE,
    default_effort="medium", source_urls=_GEMINI_SOURCES)
_GEMINI35 = ModelCapability("gemini", "openai", "reasoning_effort", ("minimal", "low", "medium", "high"),
    "reasoning_effort 支持 minimal/low/medium/high，默认 minimal。" + _GEMINI_NOTE,
    default_effort="minimal", source_urls=_GEMINI_SOURCES)
_GEMINI31_PRO = ModelCapability("gemini", "openai", "reasoning_effort", ("low", "medium", "high"),
    "Preview 状态；reasoning_effort 支持 low/medium/high（无 minimal），默认 high。" + _GEMINI_NOTE,
    default_effort="high", source_urls=_GEMINI_SOURCES)
_GEMINI3_FLASH = ModelCapability("gemini", "openai", "reasoning_effort", ("minimal", "low", "medium", "high"),
    "Preview 状态；reasoning_effort 支持 minimal/low/medium/high，默认 high。" + _GEMINI_NOTE,
    default_effort="high", source_urls=_GEMINI_SOURCES)

# Names and their display ordering are independent from capability inference.
# Every entry is an exact ID; no prefix, substring, case or date fallback.
# Newer exact IDs first; legacy/retiring IDs last.
MODEL_CATALOG: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna",
               "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5",
               "gpt-5.1", "gpt-5", "gpt-5-mini", "gpt-5-nano", "o3", "o4-mini"),
    "anthropic": ("claude-fable-5-1", "claude-mythos-5-1", "claude-opus-5-5", "claude-sonnet-5-5",
                  "claude-haiku-5-5", "claude-opus-5", "claude-sonnet-5", "claude-opus-4-8",
                  "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6",
                  "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"),
    "glm": ("glm-5.3", "glm-5.3-flash", "glm-5.3-flashx", "glm-5.2", "glm-5.1", "glm-5", "glm-5-turbo",
            "glm-4.7", "glm-4.7-flashx", "glm-4.7-flash"),
    "kimi": ("kimi-k3", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"),
    "deepseek": ("deepseek-v4-pro", "deepseek-flash"),
    "gemini": ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
               "gemini-3.1-pro-preview", "gemini-3-flash-preview"),
}
MODEL_CAPABILITIES: dict[str, ModelCapability] = {
    "gpt-6.1-sol": _GPT61_SOL,
    "gpt-6-astra": _GPT6_ASTRA,
    "gpt-6-sol": _GPT_EFFORT_FULL,
    "gpt-6-luna": _GPT_EFFORT_FULL,
    "gpt-5.6-sol": _GPT_EFFORT_FULL,
    "gpt-5.6-terra": _GPT_EFFORT_FULL,
    "gpt-5.6-luna": _GPT_EFFORT_FULL,
    "gpt-5.5": _GPT55,
    "gpt-5": _GPT5,
    "gpt-5-mini": _GPT5,
    "gpt-5-nano": _GPT5,
    "gpt-5.1": _GPT51,
    "o3": _O3,
    "o4-mini": _O3,
    "claude-fable-5-1": _CLAUDE_FABLE,
    "claude-mythos-5-1": _CLAUDE_FABLE,
    "claude-opus-5-5": _CLAUDE_OPUS55,
    "claude-sonnet-5-5": _CLAUDE_SONNET55,
    "claude-haiku-5-5": _CLAUDE_HAIKU55,
    "claude-opus-5": _CLAUDE_OPUS5,
    "claude-sonnet-5": _CLAUDE_ADAPTIVE5,
    "claude-opus-4-8": _CLAUDE_ADAPTIVE5,
    "claude-opus-4-7": _CLAUDE_ADAPTIVE5,
    "claude-opus-4-6": _CLAUDE_ADAPTIVE,
    "claude-sonnet-4-6": _CLAUDE_ADAPTIVE,
    "claude-opus-4-5": _CLAUDE_OPUS45,
    "claude-sonnet-4-5": _CLAUDE_BUDGET_DEPRECATED,
    "claude-haiku-4-5": _CLAUDE_BUDGET,
    "glm-5.3": _GLM53,
    "glm-5.3-flash": _GLM53_FLASH,
    "glm-5.3-flashx": _GLM53_FLASH,
    "glm-5.2": _GLM52,
    "glm-5.1": _GLM_TOGGLE,
    "glm-5": _GLM_TOGGLE,
    "glm-5-turbo": _GLM_TOGGLE,
    "glm-4.7": _GLM_LEGACY_TOGGLE,
    "glm-4.7-flashx": _GLM_LEGACY_TOGGLE,
    "glm-4.7-flash": _GLM_REFERENCE,
    "kimi-k2.6": _KIMI_TOGGLE,
    "kimi-k2.7-code": _KIMI_KEEP,
    "kimi-k2.7-code-highspeed": _KIMI_KEEP,
    "kimi-k3": _KIMI_EFFORT,
    "deepseek-flash": _DEEPSEEK,
    "deepseek-v4-pro": _DEEPSEEK,
    "gemini-3.8-flash": _GEMINI38,
    "gemini-3.6-flash": _GEMINI36,
    "gemini-3.5-flash-lite": _GEMINI35,
    "gemini-3.1-pro-preview": _GEMINI31_PRO,
    "gemini-3-flash-preview": _GEMINI3_FLASH,
}

_LABELS = {
    "default": "默认（不发送思考参数）", "none": "关闭推理（none）",
    "minimal": "最低（minimal）", "low": "低（low）", "medium": "中（medium）",
    "high": "高（high）", "xhigh": "超高（xhigh）", "max": "最高（max）",
    "disabled": "关闭思考（disabled）", "enabled": "开启思考（enabled）",
}


def get_model_capability(provider: str, model: str, protocol: str = "") -> ModelCapability | None:
    spec = get_spec(provider)
    if protocol not in ("", "openai", "anthropic"):
        raise TeachMeChatError("API 协议必须为 openai 或 anthropic；留空时按供应商选择。")
    if not isinstance(model, str):
        return None
    capability = MODEL_CAPABILITIES.get(model)
    if capability is None or capability.protocol != (protocol or spec.protocol):
        return None
    if provider not in ("custom", "openai-compatible", capability.provider):
        return None
    return capability


def get_model_options(provider: str, model: str, protocol: str = "") -> list[tuple[str, str]]:
    """Fresh UI choices as (human-readable label, ProviderConfig.reasoning value)."""
    capability = get_model_capability(provider, model, protocol)
    values = ("default",) + (capability.values if capability else ())
    return [(_LABELS[value], value) for value in values]


def suggested_models(provider: str) -> list[str]:
    """Fresh offline name references only; discovery remains an explicit action."""
    get_spec(provider)
    return list(MODEL_CATALOG.get(provider, ()))


def get_model_control_label(provider: str, model: str, protocol: str = "") -> str:
    capability = get_model_capability(provider, model, protocol)
    if capability is None or capability.parameter == "default_only":
        return "推理设置"
    if capability.parameter in ("thinking", "thinking_keep", "budget"):
        return "思考开关"
    return "推理强度"


def get_model_explanation(provider: str, model: str, protocol: str = "") -> str:
    capability = get_model_capability(provider, model, protocol)
    if capability is None:
        detail = "此模型 ID / 供应商 / 协议组合未登记已核实能力；仅提供 default，不按名称猜测。可手填模型 ID。"
    else:
        detail = "按精确模型 ID 与协议匹配。" + capability.explanation
    if provider in ("custom", "openai-compatible"):
        detail += " 第三方代理可能不支持原厂参数；可使用 default。地址和凭据保持不变。"
    return detail + " default 不发送思考参数，并不代表关闭思考。离线推荐不保证当前账号或端点可用。"


def reasoning_parameters(provider: str, model: str, protocol: str, mode: str, thinking_budget: int) -> dict:
    """Translate exact capabilities, preserving only documented legacy wire modes."""
    capability = get_model_capability(provider, model, protocol)
    resolved_protocol = protocol or get_spec(provider).protocol
    if mode == "default":
        return {}
    # Unknown private Anthropic aliases retain saved manual budgets. A known ID
    # on a wrong provider/protocol must NOT bypass validation via this escape hatch.
    unknown_alias = isinstance(model, str) and model not in MODEL_CAPABILITIES and not any(
        model in names for names in MODEL_CATALOG.values())
    if resolved_protocol == "anthropic" and mode in ("enabled", "disabled"):
        if unknown_alias or (capability is not None and (
                capability.legacy_budget or (mode == "disabled" and mode in capability.values))):
            thinking = {"type": mode}
            if mode == "enabled":
                if type(thinking_budget) is not int or not 1024 <= thinking_budget < 16384:
                    raise TeachMeChatError("思考预算必须为 1024 到 16383 之间的整数。")
                thinking["budget_tokens"] = thinking_budget
            return {"thinking": thinking}
    # These saved DeepSeek switches predate the canonical effort-only UI.
    if capability is _DEEPSEEK and mode in ("enabled", "disabled"):
        return {"thinking": {"type": mode}}
    if capability is None or mode not in capability.values:
        raise TeachMeChatError("此模型或协议未登记所选思考档位；请使用 default 或该模型列表中的选项。")
    if capability.parameter == "reasoning_effort":
        return {"reasoning_effort": mode}
    if capability.parameter == "thinking":
        return {"thinking": {"type": mode}}
    if capability.parameter == "thinking_keep":
        return {"thinking": {"type": "enabled", "keep": "all"}}
    if capability.parameter == "thinking_effort":
        if mode == "disabled":
            return {"thinking": {"type": "disabled"}}
        quiet = mode in ("none", "minimal")
        return {"thinking": {"type": "disabled" if quiet else "enabled"}, "reasoning_effort": mode}
    if capability.parameter == "adaptive":
        return {"thinking": {"type": "adaptive"}, "output_config": {"effort": mode}}
    raise TeachMeChatError("所选思考参数无法应用；请使用 default。")
