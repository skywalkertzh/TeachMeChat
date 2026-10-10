"""Synthetic command-line acceptance checks; no private data or network access."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import unittest

from teachmechat import app
from teachmechat.models import ProviderConfig, Advice, TeachMeChatError


class AppFlowTests(unittest.TestCase):
    @patch("teachmechat.app.choose")
    @patch("teachmechat.app.ask")
    def test_provider_configuration_probes_before_return(self, ask, choose):
        from teachmechat.providers import LLMClient
        choose.side_effect = ["openai-compatible", "default"]
        ask.side_effect = ["https://example.invalid/v1", "fake-model", "fake-key"]
        with patch.object(LLMClient, "probe", return_value="ok") as probe:
            config, client = app.configure_provider()
        self.assertEqual(config.model, "fake-model")
        probe.assert_called_once()

    @patch("teachmechat.app.select_source", return_value=(None, None, "manual"))
    @patch("teachmechat.app.configure_provider")
    @patch("teachmechat.app.confirm", return_value=False)
    @patch("teachmechat.app.ask", return_value="synthetic private context")
    def test_no_generation_without_external_consent(self, ask, confirm, configure, source):
        configure.return_value = (ProviderConfig(model="fake"), MagicMock())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TeachMeChatError):
                app.run(Path(tmp))
        configure.return_value[1].complete.assert_not_called()

    @patch("teachmechat.app.select_source", return_value=(None, None, "manual"))
    @patch("teachmechat.app.configure_provider")
    @patch("teachmechat.app.confirm", side_effect=[True, False])
    @patch("teachmechat.app.ask", return_value="synthetic context")
    def test_manual_mode_generates_three_replies_and_exits(self, ask, confirm, configure, source):
        from teachmechat.models import Advice
        client = MagicMock()
        configure.return_value = (ProviderConfig(model="fake", api_key="fake-key"), client)
        result = Advice(["a", "b", "c"], "facts", "boundaries")
        with patch("teachmechat.coach.generate_advice", return_value=result) as generate:
            with patch("teachmechat.app.show_advice") as show:
                with patch("teachmechat.app.keyboard_action", side_effect=lambda: "q" if show.called else ""):
                    with tempfile.TemporaryDirectory() as tmp:
                        app.run(Path(tmp))
                generate.assert_called_once()
                show.assert_called_once()
                self.assertEqual(show.call_args.args[0].replies, ["a", "b", "c"])
