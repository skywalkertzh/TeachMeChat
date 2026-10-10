import unittest
from dataclasses import asdict, fields

from teachmechat.models import ProviderConfig, TeachMeChatError
from teachmechat.provider_specs import PROVIDERS, ProviderSpec, get_spec


class ProviderSpecTests(unittest.TestCase):
    def test_public_registry_and_ui_fields(self):
        self.assertIsInstance(PROVIDERS, dict)
        self.assertEqual(set(PROVIDERS), {"glm", "kimi", "openai", "gemini", "deepseek", "anthropic", "custom"})
        self.assertEqual({f.name for f in fields(ProviderSpec)}, {
            "label", "base_url", "protocol", "reasoning_options", "model_hint",
        })
        for key, spec in PROVIDERS.items():
            with self.subTest(provider=key):
                self.assertIs(get_spec(key), spec)
                self.assertTrue(spec.label)
                self.assertIn(spec.protocol, ("openai", "anthropic"))
                self.assertIsInstance(spec.reasoning_options, tuple)
                self.assertEqual(spec.reasoning_options[0], "default")
                self.assertEqual(spec.model_hint, "")

    def test_official_urls_and_conservative_reasoning(self):
        self.assertEqual(get_spec("glm").base_url, "https://open.bigmodel.cn/api/paas/v4")
        self.assertEqual(get_spec("kimi").base_url, "https://api.moonshot.cn/v1")
        self.assertEqual(get_spec("openai").base_url, "https://api.openai.com/v1")
        self.assertEqual(get_spec("deepseek").base_url, "https://api.deepseek.com/v1")
        self.assertEqual(get_spec("anthropic").base_url, "https://api.anthropic.com/v1")
        self.assertEqual(get_spec("anthropic").protocol, "anthropic")
        for key in PROVIDERS:
            self.assertEqual(get_spec(key).reasoning_options, ("default",))
        self.assertEqual(get_spec("custom").base_url, "")

    def test_gemini_openai_compatible_endpoint(self):
        spec = get_spec("gemini")
        self.assertEqual(spec.label, "Google Gemini")
        self.assertEqual(spec.base_url, "https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(spec.protocol, "openai")
        self.assertEqual(spec.reasoning_options, ("default",))
        self.assertEqual(spec.model_hint, "")

    def test_legacy_alias_and_safe_unknown_errors(self):
        self.assertIs(get_spec("openai-compatible"), get_spec("custom"))
        for value in ("unknown-private-id", "", None, [], {}):
            with self.subTest(value=value), self.assertRaises(TeachMeChatError) as caught:
                get_spec(value)
            self.assertNotIn("unknown-private-id", str(caught.exception))

    def test_config_defaults_and_legacy_positional_arguments(self):
        config = ProviderConfig("custom", "https://example.invalid", "model", "test-key", "default", 30)
        self.assertEqual(config.protocol, "")
        self.assertEqual(config.structured_mode, "native")
        self.assertEqual(config.thinking_budget, 1024)
        self.assertEqual(config.timeout, 30)
        self.assertNotIn("test-key", repr(config))
        self.assertEqual(ProviderConfig(**asdict(config)), config)


if __name__ == "__main__":
    unittest.main()
