"""Cancelable, budgeted boundaries shared by the CLI and desktop workers."""
from threading import Event, Lock

from .models import TeachMeChatError


class OperationCancelled(TeachMeChatError):
    retryable = False


class RequestBudget:
    def __init__(self, cancelled=None, limit=12):
        self.cancelled = cancelled if cancelled is not None else Event()
        self.limit = max(1, int(limit))
        self.count = 0
        self._lock = Lock()

    def check(self):
        if self.cancelled.is_set():
            raise OperationCancelled("操作已停止，未开始后续请求。")

    def before_request(self):
        with self._lock:
            self.check()
            if self.count >= self.limit:
                error = TeachMeChatError("本轮请求预算已用完。请检查媒体数量或在设置中调整预算。")
                error.retryable = False
                raise error
            self.count += 1


def analyze_context(client, processor, messages, background, budget):
    from .coach import generate_advice
    budget.check()
    enriched = processor.process(messages)
    budget.check()
    advice = generate_advice(client, enriched, background)
    budget.check()
    return advice, enriched
