"""Shared bounds for local conversation retrieval, not the model character budget."""

from .models import TeachMeChatError

DEFAULT_CONTEXT_MESSAGES = 100
DEFAULT = DEFAULT_CONTEXT_MESSAGES
MAX_CONTEXT_MESSAGES = 5000


def validate_context_limit(value) -> int:
    """Accept an integer count only; never coerce booleans, strings or floats."""
    if type(value) is not int or not 1 <= value <= MAX_CONTEXT_MESSAGES:
        raise TeachMeChatError(f"上下文条数必须是 1–{MAX_CONTEXT_MESSAGES} 之间的整数。")
    return value
