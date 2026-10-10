import hashlib
import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from .models import ChatMessage, TeachMeChatError


def fingerprint(messages: list[ChatMessage], background: str) -> str:
    payload = [(m.id, m.timestamp, m.sender, m.text, m.kind, m.outgoing,
                m.media_path, hashlib.sha256(m.media_bytes).hexdigest(), m.metadata)
               for m in messages]
    return hashlib.sha256(json.dumps([background, payload], ensure_ascii=False,
                                     sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class Event:
    kind: str
    value: object = None
    generation: int | None = None
    version: int | None = None
    stale: bool = False


class Scheduler:
    """Single-owner-thread scheduler; fetch/analyze run on separate workers.

    generation advances on read failure, pause and close. version advances on
    each changed successful snapshot (including recovery with the same hash).
    Event values remain compatible: messages is a list, advice is (result,
    current), and errors are safe strings. Metadata also identifies stale errors.

    on_invalidate runs synchronously on read failure, pause and close, after
    invalidation and before more scheduling. It must be fast and non-reentrant;
    the caller owns request-guard cancellation and rearming for new work. Python
    futures cannot interrupt an already-running fetch/analyze or network request.
    """

    MAX_ANALYSIS_ATTEMPTS = 3

    def __init__(self, fetch: Callable, analyze: Callable, background: str = "",
                 automatic: bool = True, interval: float = 10.0,
                 clock: Callable = time.monotonic,
                 on_invalidate: Callable[[], None] | None = None):
        self.fetch, self.analyze = fetch, analyze
        self.background, self.automatic = background, automatic
        self.interval, self.clock = interval, clock
        self.on_invalidate = on_invalidate
        self.reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tmc-read")
        self.model = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tmc-model")
        self.read_future: Future | None = None
        self.analysis_future: Future | None = None
        self.next_read = clock()
        self.pending_read = True
        self.latest: list[ChatMessage] | None = None
        self.latest_hash = ""
        self.success_hash = ""
        self.active_hash = ""
        self.generation = 0
        self.version = 0
        self._read_generation = 0
        self.active_generation = -1
        self.active_version = -1
        self.success_version = -1
        self.force = False
        self.next_analysis = 0.0
        self.closed = False
        self.paused = False
        self.last_read_error = ""
        self.last_analysis_error = ""
        self.analysis_failures = 0
        self.failed_hash = ""
        self._retryable = True

    @property
    def idle(self) -> bool:
        """No worker is in flight; completed, unconsumed futures count as idle."""
        return all(future is None or future.done()
                   for future in (self.read_future, self.analysis_future))

    def request(self, regenerate: bool = False):
        """Coalesce refreshes; force waits for all pending reads, then runs once.

        A request during a read queues at most one additional read, so an R
        never uses a snapshot whose read started before that request. Requests
        while paused/closed are ignored. R renews the analysis failure budget.
        """
        if self.closed or self.paused:
            return
        self.pending_read = True
        self.force |= regenerate

    def set_automatic(self, enabled: bool):
        """Only toggle periodic reads; explicit work/retries are not cancelled.

        Enabling checks on the next unpaused tick. Disabling is NOT pause and
        does not cancel an in-flight read or an explicit pending request.
        """
        if self.closed:
            return
        enabled = bool(enabled)
        if enabled and not self.automatic:
            self.next_read = self.clock()
        self.automatic = enabled

    def _reset_failures(self):
        self.analysis_failures = 0
        self.failed_hash = ""
        self.next_analysis = 0.0
        self._retryable = True
        self.last_analysis_error = ""

    def _invalidate(self):
        self.generation += 1
        self.latest = None
        self.latest_hash = ""
        self.success_hash = ""
        self.success_version = -1
        self.force = False
        self._reset_failures()
        if self.analysis_future is not None:
            self.analysis_future.cancel()
        if self.on_invalidate is not None:
            try:
                self.on_invalidate()
            except Exception:
                # A broken cancellation hook must not allow further dispatch or
                # expose potentially private exception details.
                self.paused = True
                self.pending_read = False
                raise TeachMeChatError("取消回调失败；调度已暂停。") from None

    def pause(self):
        """Invalidate all context and discard queued work, without waiting.

        tick may drain late results (as stale), but never dispatches while
        paused. resume requires a fresh successful read, even for the same hash.
        """
        if self.closed or self.paused:
            return
        self.paused = True
        self.pending_read = False
        if self.read_future is not None:
            self.read_future.cancel()
        self._invalidate()

    def resume(self):
        """Leave pause and queue one fresh read; never resurrect a closed scheduler."""
        if self.closed or not self.paused:
            return
        self.paused = False
        self.pending_read = True
        self.next_read = self.clock()

    def tick(self) -> list[Event]:
        if self.closed:
            return []
        now = self.clock()
        events = []
        if self.read_future is not None and self.read_future.done():
            future, self.read_future = self.read_future, None
            if not future.cancelled() and self._read_generation == self.generation:
                # Do not turn a slow read into a backlog of automatic refreshes.
                self.next_read = now + self.interval
                try:
                    latest = future.result()
                    latest_hash = fingerprint(latest, self.background)
                except Exception as error:
                    self.last_read_error = str(error) if isinstance(error, TeachMeChatError) else "读取组件失败，未显示私人错误详情。"
                    self._invalidate()
                    events.append(Event("read_error", self.last_read_error,
                                        self.generation, self.version))
                else:
                    if self.latest is None or latest_hash != self.latest_hash:
                        self.version += 1
                        self._reset_failures()
                    self.latest, self.latest_hash = latest, latest_hash
                    self.last_read_error = ""
                    events.append(Event("messages", self.latest,
                                        self.generation, self.version))
        if self.analysis_future is not None and self.analysis_future.done():
            future, self.analysis_future = self.analysis_future, None
            current = (not self.paused and self.latest is not None
                       and self.active_generation == self.generation
                       and self.active_version == self.version
                       and self.active_hash == self.latest_hash)
            if not future.cancelled():
                try:
                    result = future.result()
                except Exception as error:
                    message = str(error) if isinstance(error, TeachMeChatError) else "分析组件失败，未显示私人错误详情。"
                    if current:
                        self.analysis_failures += 1
                        self.failed_hash = self.active_hash
                        self._retryable = not (isinstance(error, TeachMeChatError)
                                               and getattr(error, "retryable", None) is False)
                        self.next_analysis = now + min(60.0, 15.0 * self.analysis_failures)
                        self.last_analysis_error = message
                    events.append(Event("analysis_error", message, self.active_generation,
                                        self.active_version, stale=not current))
                else:
                    if current:
                        self.success_hash = self.active_hash
                        self.success_version = self.active_version
                        self._reset_failures()
                    events.append(Event("advice", (result, current), self.active_generation,
                                        self.active_version, stale=not current))
        if self.paused:
            return events
        if self.automatic and now >= self.next_read and self.read_future is None:
            self.pending_read = True
        if self.pending_read and self.read_future is None:
            self.pending_read = False
            self.next_read = now + self.interval
            self._read_generation = self.generation
            self.read_future = self.reader.submit(self.fetch)
            events.append(Event("reading", generation=self.generation, version=self.version))
        # Reads are a barrier for BOTH forced work and pending/retry work. Never
        # send an older context while a refresh may replace or invalidate it.
        if (self.latest is not None and self.analysis_future is None
                and self.read_future is None and not self.pending_read
                and (self.force or (now >= self.next_analysis and self._retryable
                                    and self.analysis_failures < self.MAX_ANALYSIS_ATTEMPTS
                                    and self.version != self.success_version))):
            if self.force:
                self._reset_failures()
            self.force = False
            self.active_hash = self.latest_hash
            self.active_generation = self.generation
            self.active_version = self.version
            self.analysis_future = self.model.submit(self.analyze, list(self.latest), self.background)
            events.append(Event("analyzing", generation=self.generation, version=self.version))
        return events

    def close(self, wait: bool = True):
        """Permanently stop dispatch. CLI waits by default; UI may use wait=False.

        wait=False does not terminate running threads; hard cancellation requires
        the caller's request guard/process isolation. Repeated close(wait=True)
        can join work left by an earlier non-waiting close.
        """
        try:
            if not self.closed:
                self.closed = True
                self.pending_read = False
                if self.read_future is not None:
                    self.read_future.cancel()
                self._invalidate()
        finally:
            self.reader.shutdown(wait=wait, cancel_futures=True)
            self.model.shutdown(wait=wait, cancel_futures=True)
