from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    id: str
    timestamp: int
    sender: str
    text: str
    kind: str = "text"
    outgoing: bool = False
    media_path: str = ""
    media_bytes: bytes = field(default=b"", repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Conversation:
    id: str
    name: str
    timestamp: int = 0


@dataclass
class Advice:
    replies: list[str]
    analysis: str
    wellbeing: str
    limitations: list[str] = field(default_factory=list)


@dataclass
class ProviderConfig:
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    api_key: str = field(default="", repr=False)
    reasoning: str = "default"
    timeout: float = 45.0
    protocol: str = ""
    structured_mode: str = "native"
    thinking_budget: int = 1024


class TeachMeChatError(Exception):
    """An actionable error safe to display without private request details."""
