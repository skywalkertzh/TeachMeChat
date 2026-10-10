import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from teachmechat.console import safe_text
from teachmechat.models import Advice, ChatMessage, ProviderConfig, TeachMeChatError
from teachmechat.runtime import configure_runtime
from teachmechat.scheduler import Scheduler, fingerprint
from teachmechat.settings import Settings


# Configure before any TemporaryDirectory, including unittest discovery/import.
configure_runtime()


class RuntimeTests(unittest.TestCase):
    def test_runtime_caches_in_project_local_runtime(self):
        project = Path(__file__).resolve().parents[2]
        root = configure_runtime()
        # 默认运行目录与项目同盘，仍位于项目内的 .teachmechat-runtime（本机绝对路径）。
        self.assertTrue(root.is_absolute())
        self.assertEqual(root, (project / ".teachmechat-runtime").resolve())
        self.assertTrue(root.is_relative_to(project))
        self.assertEqual(root.drive, project.drive)
        for name in ("TEMP", "TMP", "TMPDIR", "PIP_CACHE_DIR", "HF_HOME", "TORCH_HOME"):
            self.assertTrue(Path(os.environ[name]).is_relative_to(root))
        self.assertEqual(Path(tempfile.gettempdir()), root / "tmp")

    def test_runtime_rejects_relative_and_unc_paths(self):
        for value in ("relative-runtime", "E:relative-runtime",
                      r"\\server\share\runtime", "//server/share/runtime"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                configure_runtime(value)

    def test_optional_required_drive_is_enforced(self):
        runtime = configure_runtime()
        wrong = "Z:" if runtime.drive.upper() != "Z:" else "Y:"
        with patch.dict(os.environ, {"TEACHMECHAT_REQUIRE_DRIVE": wrong}):
            with self.assertRaises(ValueError) as raised:
                configure_runtime(runtime)
            self.assertIn(wrong, str(raised.exception))
            self.assertIn("TEACHMECHAT_REQUIRE_DRIVE", str(raised.exception))
        # 未设置或与本机盘符一致时不改变默认行为（本机盘符为空时仅跳过限制）。
        with patch.dict(os.environ, {"TEACHMECHAT_REQUIRE_DRIVE": runtime.drive}):
            self.assertEqual(configure_runtime(runtime), runtime)
        self.assertNotIn("TEACHMECHAT_REQUIRE_DRIVE", os.environ)

    def test_no_secret_in_saved_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp))
            settings.save(ProviderConfig(api_key="secret-api-canary", protocol="openai"), background="private-canary")
            text = settings.path.read_text(encoding="utf-8")
            self.assertNotIn("secret-api-canary", text)
            self.assertNotIn("private-canary", text)
            self.assertNotIn("api_key", text)

    def test_terminal_control_sequences_removed(self):
        self.assertEqual(safe_text("\x1b[31mhello\x1b[0m\x00"), "hello")
        self.assertNotIn("\x1b", safe_text("\x1b]52;c;payload\x07safe"))


class SchedulerTests(unittest.TestCase):
    def message(self, value="hello"):
        return ChatMessage("1", 100, "friend", value)

    def pump(self, scheduler, predicate, seconds=2):
        deadline = time.monotonic() + seconds
        events = []
        while time.monotonic() < deadline:
            events.extend(scheduler.tick())
            if predicate(events):
                return events
            time.sleep(.005)
        self.fail("scheduler condition timed out")

    def test_unchanged_content_not_analyzed_twice_and_regenerate(self):
        calls = []
        scheduler = Scheduler(lambda: [self.message()], lambda m, b: calls.append(m) or "ok", automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
            self.assertEqual(len(calls), 1)
            scheduler.request(regenerate=True)
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual(len(calls), 2)
        finally:
            scheduler.close()

    def test_reader_requests_coalesce_while_busy(self):
        release = threading.Event()
        calls = []
        def fetch():
            calls.append(1)
            release.wait(2)
            return [self.message()]
        scheduler = Scheduler(fetch, lambda m, b: "ok", automatic=False)
        try:
            scheduler.tick()
            for _ in range(20):
                scheduler.request()
                scheduler.tick()
            self.assertLessEqual(len(calls), 1)
            release.set()
            self.pump(scheduler, lambda e: sum(x.kind == "messages" for x in e) >= 2)
            self.assertEqual(len(calls), 2)
        finally:
            release.set()
            scheduler.close()

    def test_changed_same_id_changes_fingerprint(self):
        self.assertNotEqual(fingerprint([self.message("old")], ""),
                            fingerprint([self.message("new")], ""))

    def test_analysis_failure_retry_is_bounded(self):
        clock = [0.0]
        calls = []
        def fail(messages, background):
            calls.append(1)
            raise RuntimeError("private-error-canary")
        scheduler = Scheduler(lambda: [self.message()], fail, automatic=False, clock=lambda: clock[0])
        try:
            for _ in range(3):
                events = self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
                self.assertNotIn("private-error-canary", str(events))
                clock[0] += 100
            for _ in range(5):
                scheduler.tick()
            self.assertEqual(len(calls), 3)
            scheduler.request(regenerate=True)
            self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
            self.assertEqual(len(calls), 4)
        finally:
            scheduler.close()

    def test_automatic_ten_seconds(self):
        clock = [0.0]
        scheduler = Scheduler(lambda: [], lambda m, b: "ok", clock=lambda: clock[0])
        try:
            self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
            clock[0] = 9.9
            self.assertFalse(any(e.kind == "reading" for e in scheduler.tick()))
            clock[0] = 10
            self.assertTrue(any(e.kind == "reading" for e in scheduler.tick()))
        finally:
            scheduler.close()

    def test_regenerate_waits_for_blocked_read_and_uses_new_content_once(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []
        advice = Advice(["synthetic reply"], "synthetic analysis", "synthetic wellbeing")

        def fetch():
            reads.append(1)
            if len(reads) > 1:
                entered.set()
                release.wait(5)
                return [self.message("new")]
            return [self.message("old")]

        scheduler = Scheduler(fetch, lambda m, b: calls.append(m[0].text) or advice,
                              automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            for _ in range(20):
                scheduler.request(regenerate=True)
            events = scheduler.tick()
            self.assertTrue(entered.wait(2))
            for _ in range(20):
                events.extend(scheduler.tick())
            self.assertNotIn("analyzing", [x.kind for x in events])
            self.assertEqual(calls, ["old"])
            release.set()
            events = self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            result = next(x for x in events if x.kind == "advice")
            self.assertEqual(result.value, (advice, True))
            self.assertFalse(result.stale)
            self.assertEqual(result.version, scheduler.version)
            self.assertEqual(result.generation, scheduler.generation)
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(calls, ["old", "new"])
            self.assertEqual(len(reads), 2)
        finally:
            release.set()
            scheduler.close()

    def test_force_and_pending_reads_merge_without_intermediate_analysis(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 2:
                entered.set()
                release.wait(5)
                return [self.message("intermediate")]
            return [self.message("old" if len(reads) == 1 else "new")]

        scheduler = Scheduler(fetch, lambda m, b: calls.append(m[0].text) or "ok",
                              automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            scheduler.request()
            scheduler.tick()
            self.assertTrue(entered.wait(2))
            for _ in range(20):
                scheduler.request(regenerate=True)
                scheduler.tick()
            self.assertEqual(calls, ["old"])
            release.set()
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(len(reads), 3)
            self.assertEqual(calls, ["old", "new"])
            self.assertFalse(scheduler.force)
        finally:
            release.set()
            scheduler.close()

    def test_read_invalidation_prevents_pending_stale_calls_and_marks_late_result(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls, invalidations = [], [], []

        def fetch():
            reads.append(1)
            if len(reads) == 3:
                raise RuntimeError("private-read-canary")
            return [self.message("old" if len(reads) == 1 else "new")]

        def analyze(messages, background):
            calls.append(messages[0].text)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
            return calls[-1]

        scheduler = Scheduler(fetch, analyze, automatic=False,
                              on_invalidate=lambda: invalidations.append(scheduler.generation))
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            original_generation = scheduler.generation
            original_version = scheduler.version
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
            self.assertEqual(scheduler.latest[0].text, "new")
            scheduler.request(regenerate=True)
            events = self.pump(scheduler, lambda e: any(x.kind == "read_error" for x in e))
            self.assertNotIn("private-read-canary", str(events))
            self.assertIsNone(scheduler.latest)
            self.assertEqual(scheduler.latest_hash, "")
            self.assertFalse(scheduler.force)
            self.assertEqual(scheduler.generation, original_generation + 1)
            self.assertEqual(invalidations, [scheduler.generation])
            release.set()
            events = self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            late = next(x for x in events if x.kind == "advice")
            self.assertEqual(late.value, ("old", False))
            self.assertTrue(late.stale)
            self.assertEqual((late.generation, late.version),
                             (original_generation, original_version))
            self.assertEqual(scheduler.success_hash, "")
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(calls, ["old"])
            scheduler.request()
            events = self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual(calls, ["old", "new"])
            self.assertTrue(next(x.value[1] for x in events if x.kind == "advice"))
        finally:
            release.set()
            scheduler.close()

    def test_late_failure_does_not_retry_or_poison_recovered_same_hash(self):
        release = threading.Event()
        entered = threading.Event()
        clock = [0.0]
        reads, calls = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 2:
                raise TeachMeChatError("synthetic read failure")
            return [self.message()]

        def analyze(messages, background):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
                raise RuntimeError("private-analysis-canary")
            return "recovered"

        scheduler = Scheduler(fetch, analyze, automatic=False, clock=lambda: clock[0])
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "read_error" for x in e))
            release.set()
            events = self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
            self.assertTrue(next(x.stale for x in events if x.kind == "analysis_error"))
            self.assertNotIn("private-analysis-canary", str(events))
            self.assertEqual(scheduler.analysis_failures, 0)
            self.assertEqual(scheduler.last_analysis_error, "")
            clock[0] = 1000
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(len(calls), 1)
            scheduler.request()
            events = self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual(next(x.value for x in events if x.kind == "advice"),
                             ("recovered", True))
            self.assertEqual(len(calls), 2)
        finally:
            release.set()
            scheduler.close()

    def test_recovery_before_old_success_finishes_still_marks_it_stale(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 2:
                raise TeachMeChatError("synthetic read failure")
            return [self.message()]

        def analyze(messages, background):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
            return "ok"

        scheduler = Scheduler(fetch, analyze, automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            old_version = scheduler.version
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "read_error" for x in e))
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
            self.assertGreater(scheduler.version, old_version)
            release.set()
            events = self.pump(scheduler, lambda e: sum(x.kind == "advice" for x in e) == 2)
            self.assertEqual([x.value[1] for x in events if x.kind == "advice"], [False, True])
            self.assertEqual(len(calls), 2)
        finally:
            release.set()
            scheduler.close()

    def test_read_failure_wins_when_read_and_analysis_finish_in_same_tick(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 2:
                raise TeachMeChatError("synthetic read failure")
            return [self.message()]

        def analyze(messages, background):
            calls.append(1)
            entered.set()
            release.wait(5)
            return "late"

        scheduler = Scheduler(fetch, analyze, automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            scheduler.request(regenerate=True)
            scheduler.tick()
            with self.assertRaises(TeachMeChatError):
                scheduler.read_future.result(timeout=2)
            release.set()
            scheduler.analysis_future.result(timeout=2)
            events = scheduler.tick()
            self.assertEqual([x.kind for x in events], ["read_error", "advice"])
            self.assertEqual(events[1].value, ("late", False))
            self.assertTrue(events[1].stale)
            self.assertIsNone(scheduler.latest)
            self.assertEqual(scheduler.success_hash, "")
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            scheduler.close()

    def test_force_while_model_busy_merges_into_one_latest_analysis(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []

        def fetch():
            reads.append(1)
            return [self.message("old" if len(reads) == 1 else "new")]

        def analyze(messages, background):
            calls.append(messages[0].text)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
            return "ok"

        scheduler = Scheduler(fetch, analyze, automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            for _ in range(20):
                scheduler.request(regenerate=True)
            self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
            self.assertEqual(calls, ["old"])
            self.assertTrue(scheduler.force)
            release.set()
            events = self.pump(scheduler, lambda e: sum(x.kind == "advice" for x in e) == 2)
            self.assertEqual([x.value[1] for x in events if x.kind == "advice"], [False, True])
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(calls, ["old", "new"])
            self.assertFalse(scheduler.force)
        finally:
            release.set()
            scheduler.close()

    def test_invalidation_hook_can_cancel_synthetic_outbound_guard(self):
        release = threading.Event()
        entered = threading.Event()
        cancelled = threading.Event()
        reads, outbound = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 2:
                raise TeachMeChatError("synthetic read failure")
            return [self.message()]

        def analyze(messages, background):
            entered.set()
            release.wait(5)
            if cancelled.is_set():
                error = TeachMeChatError("synthetic guard cancellation")
                error.retryable = False
                raise error
            outbound.append(1)
            return "ok"

        scheduler = Scheduler(fetch, analyze, automatic=False, on_invalidate=cancelled.set)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "read_error" for x in e))
            self.assertTrue(cancelled.is_set())
            release.set()
            events = self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
            self.assertTrue(next(x.stale for x in events if x.kind == "analysis_error"))
            self.assertEqual(outbound, [])
            self.assertEqual(scheduler.analysis_failures, 0)
        finally:
            release.set()
            scheduler.close()

    def test_successful_same_hash_is_analyzed_again_after_read_failure(self):
        reads, calls = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 2:
                raise TeachMeChatError("synthetic read failure")
            return [self.message()]

        scheduler = Scheduler(fetch, lambda m, b: calls.append(1) or "ok", automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            original_hash, original_version = scheduler.success_hash, scheduler.version
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "read_error" for x in e))
            self.assertIsNone(scheduler.latest)
            self.assertEqual(scheduler.success_hash, "")
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(len(calls), 1)
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual(scheduler.success_hash, original_hash)
            self.assertGreater(scheduler.version, original_version)
            self.assertEqual(len(calls), 2)
            self.assertEqual(scheduler.last_read_error, "")
        finally:
            scheduler.close()

    def test_retry_waits_for_read_and_read_failure_cancels_retry(self):
        release = threading.Event()
        entered = threading.Event()
        clock = [0.0]
        reads, calls = [], []

        def fetch():
            reads.append(1)
            if len(reads) > 1:
                entered.set()
                release.wait(5)
                raise TeachMeChatError("synthetic read failure")
            return [self.message()]

        def analyze(messages, background):
            calls.append(1)
            raise RuntimeError("synthetic analysis failure")

        scheduler = Scheduler(fetch, analyze, automatic=False, clock=lambda: clock[0])
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
            clock[0] = 100
            scheduler.request()
            scheduler.tick()
            self.assertTrue(entered.wait(2))
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(len(calls), 1)
            release.set()
            self.pump(scheduler, lambda e: any(x.kind == "read_error" for x in e))
            clock[0] = 1000
            for _ in range(20):
                scheduler.tick()
            self.assertEqual(len(calls), 1)
        finally:
            release.set()
            scheduler.close()

    def test_context_version_prevents_aba_result_becoming_current(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []

        def fetch():
            reads.append(1)
            return [self.message("b" if len(reads) == 2 else "a")]

        def analyze(messages, background):
            calls.append(messages[0].text)
            if len(calls) == 1:
                entered.set()
                release.wait(5)
            return "ok"

        scheduler = Scheduler(fetch, analyze, automatic=False)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            for _ in range(2):
                scheduler.request()
                self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
            self.assertEqual(scheduler.active_hash, scheduler.latest_hash)
            release.set()
            events = self.pump(scheduler, lambda e: sum(x.kind == "advice" for x in e) == 2)
            self.assertEqual([x.value[1] for x in events if x.kind == "advice"], [False, True])
            self.assertEqual(calls, ["a", "a"])
        finally:
            release.set()
            scheduler.close()

    def test_pause_no_tasks_and_resume_requires_fresh_read(self):
        reads, calls, invalidations = [], [], []
        scheduler = Scheduler(lambda: reads.append(1) or [self.message()],
                              lambda m, b: calls.append(1) or "ok", automatic=False,
                              on_invalidate=lambda: invalidations.append(1))
        try:
            scheduler.pause()
            scheduler.pause()
            generation = scheduler.generation
            for _ in range(20):
                scheduler.request(regenerate=True)
                self.assertEqual(scheduler.tick(), [])
            self.assertTrue(scheduler.idle)
            self.assertFalse(scheduler.pending_read)
            self.assertFalse(scheduler.force)
            self.assertEqual((reads, calls, invalidations), ([], [], [1]))
            scheduler.resume()
            scheduler.resume()
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual((len(reads), len(calls)), (1, 1))
            self.assertEqual(scheduler.generation, generation)
            scheduler.pause()
            scheduler.resume()
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual((len(reads), len(calls)), (2, 2))
        finally:
            scheduler.close()

    def test_pause_discards_inflight_read_even_after_resume(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 1:
                entered.set()
                release.wait(5)
                return [self.message("stale")]
            return [self.message("fresh")]

        scheduler = Scheduler(fetch, lambda m, b: calls.append(m[0].text) or "ok",
                              automatic=False)
        try:
            scheduler.tick()
            self.assertTrue(entered.wait(2))
            scheduler.pause()
            self.assertFalse(scheduler.idle)
            for _ in range(20):
                self.assertEqual(scheduler.tick(), [])
            scheduler.resume()
            release.set()
            events = self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual([x.value[0].text for x in events if x.kind == "messages"], ["fresh"])
            self.assertEqual(calls, ["fresh"])
        finally:
            release.set()
            scheduler.close()

    def test_pause_drains_late_advice_as_stale_without_scheduling(self):
        release = threading.Event()
        entered = threading.Event()
        reads, calls = [], []

        def analyze(messages, background):
            calls.append(1)
            entered.set()
            release.wait(5)
            return "late"

        scheduler = Scheduler(lambda: reads.append(1) or [self.message()], analyze)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analyzing" for x in e))
            self.assertTrue(entered.wait(2))
            scheduler.request(regenerate=True)
            scheduler.pause()
            release.set()
            events = self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual(next(x.value for x in events if x.kind == "advice"), ("late", False))
            self.assertTrue(next(x.stale for x in events if x.kind == "advice"))
            self.assertNotIn("reading", [x.kind for x in events])
            self.assertNotIn("analyzing", [x.kind for x in events])
            self.assertEqual((len(reads), len(calls)), (1, 1))
            self.assertTrue(scheduler.idle)
        finally:
            release.set()
            scheduler.close()

    def test_set_automatic_is_not_pause_and_preserves_explicit_requests(self):
        clock = [0.0]
        reads, calls = [], []
        scheduler = Scheduler(lambda: reads.append(1) or [self.message()],
                              lambda m, b: calls.append(1) or "ok", clock=lambda: clock[0])
        try:
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            scheduler.set_automatic(False)
            clock[0] = 100
            self.assertEqual(scheduler.tick(), [])
            scheduler.request(regenerate=True)
            scheduler.set_automatic(False)
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual((len(reads), len(calls)), (2, 2))
            scheduler.set_automatic(True)
            self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
            self.assertEqual(len(reads), 3)
            self.assertEqual(len(calls), 2)
            scheduler.pause()
            scheduler.set_automatic(False)
            scheduler.set_automatic(True)
            clock[0] = 1000
            for _ in range(20):
                self.assertEqual(scheduler.tick(), [])
            self.assertEqual(len(reads), 3)
            scheduler.resume()
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual((len(reads), len(calls)), (4, 3))
        finally:
            scheduler.close()

    def test_close_prevents_all_future_scheduling_and_is_idempotent(self):
        calls, invalidations = [], []
        scheduler = Scheduler(lambda: calls.append("read") or [],
                              lambda m, b: calls.append("analyze"),
                              on_invalidate=lambda: invalidations.append(1))
        scheduler.request(regenerate=True)
        scheduler.close()
        generation = scheduler.generation
        scheduler.close(wait=False)
        scheduler.request(regenerate=True)
        scheduler.pause()
        scheduler.resume()
        scheduler.set_automatic(False)
        for _ in range(20):
            self.assertEqual(scheduler.tick(), [])
        self.assertEqual(calls, [])
        self.assertEqual(invalidations, [1])
        self.assertEqual(scheduler.generation, generation)
        self.assertFalse(scheduler.pending_read)
        self.assertFalse(scheduler.force)
        self.assertTrue(scheduler.idle)

    def test_close_wait_false_returns_with_workers_inflight(self):
        for stage in ("read", "analyze"):
            with self.subTest(stage=stage):
                release = threading.Event()
                entered = threading.Event()
                calls = []

                def fetch():
                    calls.append("read")
                    if stage == "read":
                        entered.set()
                        release.wait(5)
                    return [self.message()]

                def analyze(messages, background):
                    calls.append("analyze")
                    entered.set()
                    release.wait(5)
                    return "ok"

                scheduler = Scheduler(fetch, analyze, automatic=False)
                try:
                    self.pump(scheduler, lambda e: any(x.kind == ("reading" if stage == "read" else "analyzing") for x in e))
                    self.assertTrue(entered.wait(2))
                    future = scheduler.read_future if stage == "read" else scheduler.analysis_future
                    self.assertFalse(scheduler.idle)
                    started = time.monotonic()
                    scheduler.close(wait=False)
                    self.assertLess(time.monotonic() - started, 1)
                    self.assertFalse(scheduler.idle)
                    scheduler.request(regenerate=True)
                    scheduler.resume()
                    self.assertEqual(scheduler.tick(), [])
                    release.set()
                    future.result(timeout=2)
                    self.assertTrue(scheduler.idle)
                    self.assertEqual(scheduler.tick(), [])
                    self.assertEqual(calls, ["read"] if stage == "read" else ["read", "analyze"])
                finally:
                    release.set()
                    scheduler.close()

    def test_idle_counts_done_unconsumed_futures_as_idle(self):
        release = threading.Event()
        entered = threading.Event()

        def fetch():
            entered.set()
            release.wait(5)
            return [self.message()]

        scheduler = Scheduler(fetch, lambda m, b: "ok", automatic=False)
        try:
            self.assertTrue(scheduler.idle)
            scheduler.tick()
            self.assertTrue(entered.wait(2))
            self.assertFalse(scheduler.idle)
            release.set()
            scheduler.read_future.result(timeout=2)
            self.assertTrue(scheduler.idle)
            scheduler.tick()
            scheduler.analysis_future.result(timeout=2)
            self.assertTrue(scheduler.idle)
        finally:
            release.set()
            scheduler.close()

    def test_teachmechat_error_retryable_contract_and_force_renews_budget(self):
        for retryable in (False, True, None):
            with self.subTest(retryable=retryable):
                calls = []
                clock = [0.0]

                def fail(messages, background):
                    calls.append(1)
                    error = TeachMeChatError("synthetic safe failure")
                    if retryable is not None:
                        error.retryable = retryable
                    raise error

                scheduler = Scheduler(lambda: [self.message()], fail,
                                      automatic=False, clock=lambda: clock[0])
                try:
                    attempts = 1 if retryable is False else 3
                    for _ in range(attempts):
                        self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
                        clock[0] += 100
                    scheduler.request()
                    self.pump(scheduler, lambda e: any(x.kind == "messages" for x in e))
                    for _ in range(20):
                        scheduler.tick()
                    self.assertEqual(len(calls), attempts)
                    self.assertEqual(scheduler.analysis_failures, attempts)
                    scheduler.request(regenerate=True)
                    self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
                    self.assertEqual(len(calls), attempts + 1)
                    self.assertEqual(scheduler.analysis_failures, 1)
                finally:
                    scheduler.close()

    def test_new_content_resets_failure_backoff_immediately(self):
        text = ["old"]
        calls = []

        def analyze(messages, background):
            calls.append(messages[0].text)
            if messages[0].text == "old":
                raise RuntimeError("synthetic failure")
            return "ok"

        scheduler = Scheduler(lambda: [self.message(text[0])], analyze,
                              automatic=False, clock=lambda: 0.0)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "analysis_error" for x in e))
            self.assertGreater(scheduler.next_analysis, 0)
            text[0] = "new"
            scheduler.request()
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            self.assertEqual(calls, ["old", "new"])
            self.assertEqual(scheduler.analysis_failures, 0)
        finally:
            scheduler.close()

    def test_invalidation_callback_observes_invalidated_state(self):
        reads, seen = [], []

        def fetch():
            reads.append(1)
            if len(reads) == 2:
                raise TeachMeChatError("synthetic read failure")
            return [self.message()]

        def invalidate():
            seen.append((scheduler.generation, scheduler.latest, scheduler.latest_hash,
                         scheduler.success_hash, scheduler.force))

        scheduler = Scheduler(fetch, lambda m, b: "ok", automatic=False,
                              on_invalidate=invalidate)
        try:
            self.pump(scheduler, lambda e: any(x.kind == "advice" for x in e))
            scheduler.request(regenerate=True)
            self.pump(scheduler, lambda e: any(x.kind == "read_error" for x in e))
            scheduler.pause()
            scheduler.close(wait=False)
            self.assertEqual(seen, [(1, None, "", "", False), (2, None, "", "", False),
                                    (3, None, "", "", False)])
        finally:
            scheduler.close()

    def test_failed_invalidation_hook_pauses_without_leaking_private_error(self):
        def invalidate():
            raise RuntimeError("private-hook-canary")

        scheduler = Scheduler(lambda: [], lambda m, b: "ok", on_invalidate=invalidate)
        try:
            with self.assertRaises(TeachMeChatError) as raised:
                scheduler.pause()
            self.assertNotIn("private-hook-canary", str(raised.exception))
            self.assertTrue(scheduler.paused)
            self.assertIsNone(scheduler.latest)
            scheduler.request(regenerate=True)
            self.assertEqual(scheduler.tick(), [])
        finally:
            scheduler.on_invalidate = None
            scheduler.close()


if __name__ == "__main__":
    configure_runtime()
    unittest.main()
