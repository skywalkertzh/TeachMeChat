"""Synthetic worker protocol tests; no chat databases, processes or APIs."""

from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from teachmechat.context_options import (
    DEFAULT, DEFAULT_CONTEXT_MESSAGES, MAX_CONTEXT_MESSAGES, validate_context_limit,
)
from teachmechat.desktop.workers import source_worker
from teachmechat.models import TeachMeChatError
from teachmechat.runtime import configure_runtime

_RUNTIME = None


def setUpModule():
    global _RUNTIME
    _RUNTIME = configure_runtime(Path(__file__).resolve().parents[2] / ".teachmechat-runtime")


class FakePipe:
    def __init__(self, requests):
        self.requests = iter(requests)
        self.sent = []
        self.closed = False

    def poll(self, timeout):
        return True

    def recv(self):
        try:
            return next(self.requests)
        except StopIteration:
            raise EOFError from None

    def send(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True


class ContextLimitTests(unittest.TestCase):
    def test_presets_custom_and_boundaries(self):
        self.assertEqual(DEFAULT, 100)
        self.assertEqual(DEFAULT_CONTEXT_MESSAGES, 100)
        self.assertEqual(MAX_CONTEXT_MESSAGES, 5000)
        for value in (1, 100, 200, 500, 1000, 1234, 5000):
            with self.subTest(value=value):
                self.assertEqual(validate_context_limit(value), value)

    def test_invalid_limits_are_safe_errors_and_never_coerced(self):
        for value in (True, False, 0, -1, 5001, 100.0, 1.5, float("nan"),
                      float("inf"), "private-value-canary", "100", None, [], {}):
            with self.subTest(value=value), self.assertRaises(TeachMeChatError) as caught:
                validate_context_limit(value)
            self.assertNotIn("private-value-canary", str(caught.exception))

    def run_worker(self, payloads, *, source_available=True, failure=None):
        source = Mock()
        source.list_conversations.return_value = []
        source.status_label = "synthetic source"
        source.recent.side_effect = failure or (
            lambda conversation_id, limit: [f"synthetic-{index}" for index in range(limit)]
        )
        pipe = FakePipe([("open", {"mode": "synthetic"})]
                        + [("recent", payload) for payload in payloads]
                        + [("stop", None)])
        with patch("teachmechat.desktop.workers._source",
                   return_value=source if source_available else None):
            source_worker(pipe, threading.Event(), _RUNTIME)
        self.assertTrue(pipe.closed)
        if source_available:
            source.close.assert_called_once_with()
        return source, pipe.sent[1:]  # Skip the opened notification.

    def test_recent_passes_each_requested_limit_to_source_and_preserves_reply(self):
        limits = (1, 100, 200, 500, 1000, 1234, 5000)
        source, replies = self.run_worker([
            {"conversation_id": "synthetic-conversation", "limit": limit} for limit in limits
        ])
        self.assertEqual(len(replies), len(limits))
        for call, reply, limit in zip(source.recent.call_args_list, replies, limits):
            self.assertEqual(call.args, ("synthetic-conversation",))
            self.assertEqual(call.kwargs, {"limit": limit})
            kind, (conversation_id, messages) = reply
            self.assertEqual(kind, "messages")
            self.assertEqual(conversation_id, "synthetic-conversation")
            self.assertEqual(len(messages), limit)
            self.assertEqual(messages[-1], f"synthetic-{limit - 1}")

    def test_old_string_payload_retains_default_100(self):
        source, replies = self.run_worker(["synthetic-old-conversation"])
        source.recent.assert_called_once_with("synthetic-old-conversation", limit=100)
        self.assertEqual(replies[0][0], "messages")
        self.assertEqual(replies[0][1][0], "synthetic-old-conversation")
        self.assertEqual(len(replies[0][1][1]), 100)

    def test_invalid_payloads_do_not_reach_source_and_worker_recovers(self):
        invalid = [
            {"conversation_id": "private-id-canary", "limit": value}
            for value in (True, False, 0, -1, 5001, 1.5, 100.0, "100", None, [], {})
        ] + [None, True, 1, [], {}, "", "  ",
             {"conversation_id": "private-id-canary"},
             {"limit": 100}, {"conversation_id": None, "limit": 100},
             {"conversation_id": True, "limit": 100},
             {"conversation_id": "", "limit": 100},
             {"conversation_id": "private-id-canary", "limit": 100, "extra": "private-value-canary"}]
        source, replies = self.run_worker(invalid + ["synthetic-recovery"])
        source.recent.assert_called_once_with("synthetic-recovery", limit=100)
        for kind, error in replies[:-1]:
            self.assertEqual(kind, "error")
            self.assertIsInstance(error, str)
            self.assertNotIn("private-id-canary", error)
            self.assertNotIn("private-value-canary", error)
        self.assertEqual(len(replies), len(invalid) + 1)
        self.assertEqual(replies[-1][0], "messages")

    def test_manual_mode_still_validates_payload_and_returns_same_reply_shape(self):
        source, replies = self.run_worker([
            {"conversation_id": "synthetic-manual", "limit": 5000},
            {"conversation_id": "synthetic-manual", "limit": True},
            "synthetic-old",
        ], source_available=False)
        source.recent.assert_not_called()
        self.assertEqual(replies[0], ("messages", ("synthetic-manual", [])))
        self.assertEqual(replies[1][0], "error")
        self.assertEqual(replies[2], ("messages", ("synthetic-old", [])))

    def test_unexpected_source_error_is_sanitized(self):
        _, replies = self.run_worker([{"conversation_id": "synthetic", "limit": 1000}],
                                     failure=RuntimeError("private-source-canary"))
        self.assertEqual(replies[0][0], "error")
        self.assertNotIn("private-source-canary", replies[0][1])


if __name__ == "__main__":
    unittest.main()
