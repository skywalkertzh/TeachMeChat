import unittest
from unittest.mock import patch, MagicMock

from teachmechat.discovery import BoundLiveSource, acquire
from teachmechat.models import TeachMeChatError


class DiscoveryTests(unittest.TestCase):
    @patch("teachmechat.discovery.subprocess.Popen")
    def test_worker_secret_not_passed_on_command_line(self, popen):
        child = popen.return_value
        child.communicate.return_value = ('{"ok":true,"key":"fake-secret"}', None)
        child.returncode = 0
        child.poll.return_value = 0
        result = acquire({"pid": 100, "version": 3})
        self.assertEqual(result["key"], "fake-secret")
        self.assertNotIn("fake-secret", str(popen.call_args))

    @patch("teachmechat.discovery.processes")
    def test_process_restart_invalidates_source(self, processes):
        processes.return_value = [{"pid": 1, "started": 2}]
        source = MagicMock()
        bound = BoundLiveSource(source, {"pid": 1, "started": 1})
        with self.assertRaises(TeachMeChatError):
            bound.recent("fake")
        source.recent.assert_not_called()

    @patch("teachmechat.discovery.subprocess.Popen")
    def test_raw_worker_output_not_in_error(self, popen):
        child = popen.return_value
        child.communicate.return_value = ("fake-secret broken json", None)
        child.returncode = 0
        child.poll.return_value = 0
        with self.assertRaises(TeachMeChatError) as error:
            acquire({"pid": 1, "version": 4})
        self.assertNotIn("fake-secret", str(error.exception))
