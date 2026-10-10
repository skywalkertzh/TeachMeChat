"""Conservative provider defaults for clients and configuration UIs.

Provider-wide reasoning_options is retained for compatibility, but is default
only: selectable API levels live in model_catalog's exact-ID/protocol registry.
"""

from dataclasses import dataclass

from .models import TeachMeChatError


@dataclass(frozen=True)
class ProviderSpec:
    label: str
    base_url: str
    protocol: str
    reasoning_options: tuple[str, ...] = ("default",)
    model_hint: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    "glm": ProviderSpec("GLM", "https://open.bigmodel.cn/api/paas/v4", "openai"),
    "kimi": ProviderSpec("Kimi", "https://api.moonshot.cn/v1", "openai"),
    "openai": ProviderSpec("OpenAI", "https://api.openai.com/v1", "openai"),
    "gemini": ProviderSpec("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "openai"),
    "deepseek": ProviderSpec("DeepSeek", "https://api.deepseek.com/v1", "openai"),
    "anthropic": ProviderSpec("Anthropic", "https://api.anthropic.com/v1", "anthropic"),
    "custom": ProviderSpec("自定义 / OpenAI 兼容", "", "openai"),
}


def get_spec(id: str) -> ProviderSpec:
    """Resolve a provider, including the legacy openai-compatible identifier."""
    if not isinstance(id, str):
        raise TeachMeChatError("不支持该供应商；请从供应商列表选择。")
    if id == "openai-compatible":
        id = "custom"
    try:
        return PROVIDERS[id]
    except KeyError:
        raise TeachMeChatError("不支持该供应商；请从供应商列表选择。") from None
