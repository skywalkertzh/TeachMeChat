import json
import unittest
from dataclasses import asdict
from unittest.mock import patch

from teachmechat.model_catalog import (
    MODEL_CAPABILITIES, MODEL_CATALOG, ModelCapability, get_model_options, get_model_explanation,
    get_model_capability, get_model_control_label, suggested_models, reasoning_parameters,
)
from teachmechat.models import TeachMeChatError
from teachmechat.providers import (
    LLMClient, MAX_MODEL_IDS, MAX_MODEL_PAGES, MAX_RESPONSE_BYTES, discover_models,
)
from teachmechat.tests.test_providers import (
    PRIVATE, SECRET, Response, Transport, anthropic_response, config, failure, response_body,
)


MODEL_URL = "https://example.invalid/v1/models"


def model_response(ids=(), *, native=False, cursor=None, **fields):
    data = {"data": [{"id": model} for model in ids], **fields}
    url = MODEL_URL
    if native:
        from urllib.parse import urlencode
        params = {"limit": 100}
        if cursor is not None:
            params["after_id"] = cursor
        url += "?" + urlencode(params)
    return Response(json.dumps(data).encode(), url=url)


class CatalogTests(unittest.TestCase):
    def values(self, provider, model, protocol=""):
        return [value for _, value in get_model_options(provider, model, protocol)]

    def test_reference_names_are_not_inferred_capabilities(self):
        # The only remaining unverified reference is the free legacy GLM model.
        self.assertEqual(self.values("glm", "glm-4.7-flash"), ["default"])
        cap = get_model_capability("glm", "glm-4.7-flash")
        self.assertEqual(cap.parameter, "default_only")
        self.assertEqual(cap.evidence_level, "name_only")
        self.assertIn("档位未核实", cap.explanation)
        for mode in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "disabled", "enabled"):
            with self.assertRaises(TeachMeChatError):
                reasoning_parameters("glm", "glm-4.7-flash", "", mode, 1024)
        # Responses-only, retired and offline IDs are deliberately absent.
        for model in ("gpt-5.5-pro", "gpt-5.6-cyber", "claude-opus-4-1", "kimi-k2.5", "kimi-latest",
                      "moonshot-v1-8k", "gemini-3-pro", "gemini-3-flash"):
            with self.subTest(model=model):
                self.assertNotIn(model, MODEL_CAPABILITIES)
                self.assertNotIn(model, {m for names in MODEL_CATALOG.values() for m in names})
                self.assertEqual(self.values("openai", model), ["default"])
        for model in ("glm-5.3-flash-alias", "claude-opus-5-5-alias", "deepseek-v4-pro-custom", "gemini-3.8-flash-alias"):
            self.assertEqual(self.values("custom", model), ["default"])
        self.assertEqual(suggested_models("openai")[:4], ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna"])
        self.assertEqual(suggested_models("openai")[-3:], ["gpt-5-nano", "o3", "o4-mini"])
        self.assertEqual(suggested_models("anthropic")[:2], ["claude-fable-5-1", "claude-mythos-5-1"])
        self.assertEqual(suggested_models("anthropic")[-2:], ["claude-sonnet-4-5", "claude-haiku-4-5"])
        self.assertEqual(suggested_models("glm")[:4], ["glm-5.3", "glm-5.3-flash", "glm-5.3-flashx", "glm-5.2"])
        self.assertEqual(suggested_models("glm")[-1], "glm-4.7-flash")
        self.assertEqual(suggested_models("kimi")[-1], "kimi-k2.6")
        self.assertEqual(suggested_models("gemini"), ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
                                                      "gemini-3.1-pro-preview", "gemini-3-flash-preview"])
        self.assertEqual({m for names in MODEL_CATALOG.values() for m in names}, set(MODEL_CAPABILITIES))
        options = get_model_options("deepseek", "deepseek-flash")
        options.clear()
        self.assertEqual(len(get_model_options("deepseek", "deepseek-flash")), 5)

    def test_per_model_defaults_and_control_labels(self):
        # New metadata remains optional for callers constructing old records.
        self.assertEqual(ModelCapability("custom", "openai", "default_only", (), "test").default_effort, "")
        for provider, model, effort, label in (
            ("openai", "gpt-6.1-sol", "medium", "推理强度"),
            ("openai", "gpt-6-astra", "", "推理强度"),
            ("openai", "gpt-6-sol", "medium", "推理强度"),
            ("openai", "gpt-5.6-luna", "medium", "推理强度"),
            ("openai", "gpt-5.5", "medium", "推理强度"),
            ("openai", "gpt-5.1", "", "推理强度"),
            ("openai", "gpt-5", "", "推理强度"),
            ("openai", "o4-mini", "", "推理强度"),
            ("anthropic", "claude-fable-5-1", "high", "推理强度"),
            ("anthropic", "claude-mythos-5-1", "high", "推理强度"),
            ("anthropic", "claude-opus-5-5", "medium", "推理强度"),
            ("anthropic", "claude-sonnet-5-5", "high", "推理强度"),
            ("anthropic", "claude-haiku-5-5", "medium", "推理强度"),
            ("anthropic", "claude-opus-5", "high", "推理强度"),
            ("anthropic", "claude-sonnet-5", "high", "推理强度"),
            ("anthropic", "claude-opus-4-8", "high", "推理强度"),
            ("anthropic", "claude-opus-4-7", "high", "推理强度"),
            ("anthropic", "claude-opus-4-6", "high", "推理强度"),
            ("anthropic", "claude-opus-4-5", "", "推理强度"),
            ("anthropic", "claude-haiku-4-5", "", "思考开关"),
            ("glm", "glm-5.3", "max", "推理强度"),
            ("glm", "glm-5.3-flash", "max", "推理强度"),
            ("glm", "glm-5.2", "max", "推理强度"),
            ("glm", "glm-5.1", "", "思考开关"),
            ("glm", "glm-5-turbo", "", "思考开关"),
            ("glm", "glm-4.7", "", "思考开关"),
            ("glm", "glm-4.7-flash", "", "推理设置"),
            ("kimi", "kimi-k3", "max", "推理强度"),
            ("kimi", "kimi-k2.7-code", "", "思考开关"),
            ("kimi", "kimi-k2.7-code-highspeed", "", "思考开关"),
            ("kimi", "kimi-k2.6", "", "思考开关"),
            ("deepseek", "deepseek-v4-pro", "high", "推理强度"),
            ("gemini", "gemini-3.8-flash", "medium", "推理强度"),
            ("gemini", "gemini-3.6-flash", "medium", "推理强度"),
            ("gemini", "gemini-3.5-flash-lite", "minimal", "推理强度"),
            ("gemini", "gemini-3.1-pro-preview", "high", "推理强度"),
            ("gemini", "gemini-3-flash-preview", "high", "推理强度"),
        ):
            with self.subTest(model=model):
                cap = get_model_capability(provider, model)
                self.assertEqual(cap.default_effort, effort)
                self.assertTrue(cap.source_urls)
                self.assertEqual(get_model_control_label(provider, model), label)
                self.assertEqual(get_model_control_label("custom", model, cap.protocol), label)
                self.assertEqual(reasoning_parameters(provider, model, "", "default", 1024), {})
        self.assertEqual(get_model_control_label("custom", "private-alias"), "推理设置")

    def test_deepseek_canonical_and_saved_legacy_modes(self):
        for model in ("deepseek-flash", "deepseek-v4-pro"):
            self.assertEqual(self.values("deepseek", model), ["default", "none", "low", "high", "max"])
            for provider in ("deepseek", "custom", "openai-compatible"):
                for mode in ("none", "low", "high", "max"):
                    self.assertEqual(reasoning_parameters(provider, model, "openai", mode, 1024),
                                     {"thinking": {"type": "disabled" if mode == "none" else "enabled"}, "reasoning_effort": mode})
                for mode in ("enabled", "disabled"):
                    self.assertEqual(reasoning_parameters(provider, model, "openai", mode, 1024), {"thinking": {"type": mode}})

    def test_glm_and_kimi_new_exact_specs(self):
        for model in ("glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"):
            self.assertEqual(self.values("glm", model), ["default", "low", "high", "max"])
            for mode in ("low", "high", "max"):
                self.assertEqual(reasoning_parameters("glm", model, "", mode, 1024),
                                 {"thinking": {"type": "enabled"}, "reasoning_effort": mode})
            self.assertIn("不支持关闭思考", get_model_explanation("glm", model))
        self.assertEqual(self.values("glm", "glm-5.2"),
                         ["default", "disabled", "none", "minimal", "low", "medium", "high", "xhigh", "max"])
        self.assertEqual(reasoning_parameters("glm", "glm-5.2", "", "disabled", 1024), {"thinking": {"type": "disabled"}})
        for mode in ("none", "minimal"):
            self.assertEqual(reasoning_parameters("glm", "glm-5.2", "", mode, 1024),
                             {"thinking": {"type": "disabled"}, "reasoning_effort": mode})
        for mode in ("low", "medium", "high", "xhigh", "max"):
            self.assertEqual(reasoning_parameters("glm", "glm-5.2", "", mode, 1024),
                             {"thinking": {"type": "enabled"}, "reasoning_effort": mode})
        self.assertIn("图片/视频输入", get_model_explanation("glm", "glm-5.3-flash"))
        for mode in ("low", "high", "max"):
            self.assertEqual(reasoning_parameters("kimi", "kimi-k3", "", mode, 1024), {"reasoning_effort": mode})
        for model in ("kimi-k2.7-code", "kimi-k2.7-code-highspeed"):
            self.assertEqual(self.values("kimi", model), ["default", "enabled"])
            self.assertEqual(reasoning_parameters("kimi", model, "", "enabled", 1024),
                             {"thinking": {"type": "enabled", "keep": "all"}})
            self.assertIn("keep", get_model_explanation("kimi", model))
        for provider, model, bad in (
            ("glm", "glm-5.3", ("none", "disabled", "enabled", "medium", "xhigh")),
            ("glm", "glm-5.3-flash", ("none", "disabled", "enabled", "medium", "xhigh")),
            ("glm", "glm-5.2", ("enabled",)),
            ("kimi", "kimi-k3", ("none", "disabled", "enabled", "medium", "xhigh")),
            ("kimi", "kimi-k2.7-code", ("none", "disabled", "medium", "low", "high", "max")),
            ("kimi", "kimi-k2.7-code-highspeed", ("none", "disabled", "medium")),
        ):
            for mode in bad:
                with self.subTest(model=model, mode=mode), self.assertRaises(TeachMeChatError):
                    reasoning_parameters(provider, model, "", mode, 1024)

    def test_anthropic_five_efforts_and_budget_boundaries(self):
        five = ["low", "medium", "high", "xhigh", "max"]
        for model in ("claude-fable-5-1", "claude-mythos-5-1", "claude-opus-5-5", "claude-sonnet-5-5",
                      "claude-haiku-5-5", "claude-opus-5", "claude-sonnet-5", "claude-opus-4-7", "claude-opus-4-8"):
            allowed_off = model in ("claude-sonnet-5", "claude-opus-4-7", "claude-opus-4-8")
            self.assertEqual(self.values("anthropic", model), ["default"] + (["disabled"] if allowed_off else []) + five)
            for mode in five:
                self.assertEqual(reasoning_parameters("anthropic", model, "", mode, 4096),
                                 {"thinking": {"type": "adaptive"}, "output_config": {"effort": mode}})
            for mode in (["enabled"] if allowed_off else ["enabled", "disabled"]):
                with self.subTest(model=model, mode=mode), self.assertRaises(TeachMeChatError):
                    reasoning_parameters("anthropic", model, "", mode, 4096)
        self.assertIn("返回 400", get_model_explanation("anthropic", "claude-fable-5-1"))
        self.assertEqual(self.values("anthropic", "claude-opus-4-5"), ["default", "low", "medium", "high"])
        for mode in ("low", "medium", "high"):
            self.assertEqual(reasoning_parameters("anthropic", "claude-opus-4-5", "", mode, 4096),
                             {"thinking": {"type": "adaptive"}, "output_config": {"effort": mode}})
        for mode in ("xhigh", "max"):
            with self.subTest(mode=mode), self.assertRaises(TeachMeChatError):
                reasoning_parameters("anthropic", "claude-opus-4-5", "", mode, 4096)
        for model in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5", "private-legacy-alias"):
            self.assertEqual(reasoning_parameters("anthropic", model, "", "enabled", 4096),
                             {"thinking": {"type": "enabled", "budget_tokens": 4096}})
            self.assertEqual(reasoning_parameters("custom", model, "anthropic", "disabled", 4096), {"thinking": {"type": "disabled"}})
        self.assertIn("2026-09-30", get_model_explanation("anthropic", "claude-sonnet-4-5"))
        for model in ("gpt-5", "gpt-5.5", "gpt-6-astra", "glm-5.3", "kimi-k3", "deepseek-v4-pro", "gemini-3.8-flash"):
            for mode in ("enabled", "disabled"):
                with self.assertRaises(TeachMeChatError):
                    reasoning_parameters("custom", model, "anthropic", mode, 4096)
        for budget in (True, 1023, 16384, "2048"):
            with self.assertRaises(TeachMeChatError):
                reasoning_parameters("anthropic", "private-legacy-alias", "", "enabled", budget)

    def test_exact_openai_levels(self):
        for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano"):
            self.assertEqual(self.values("openai", model), ["default", "minimal", "low", "medium", "high"])
            self.assertIn("退役", get_model_explanation("openai", model))
        self.assertEqual(self.values("openai", "gpt-5.1"), ["default", "none", "low", "medium", "high"])
        for model in ("o3", "o4-mini"):
            self.assertEqual(self.values("openai", model), ["default", "low", "medium", "high"])
            self.assertIn("退役", get_model_explanation("openai", model))
        self.assertEqual(self.values("openai", "gpt-5.5"), ["default", "none", "low", "medium", "high", "xhigh"])
        for model in ("gpt-6-astra", "gpt-6.1-sol"):
            self.assertEqual(self.values("openai", model), ["default", "low", "medium", "high", "xhigh", "max"])
        for model in ("gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
            self.assertEqual(self.values("openai", model), ["default", "none", "low", "medium", "high", "xhigh", "max"])
        for model in ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.5"):
            for _, mode in get_model_options("openai", model):
                if mode != "default":
                    self.assertEqual(reasoning_parameters("openai", model, "", mode, 1024), {"reasoning_effort": mode})
        self.assertIn("默认档位官方未核实", get_model_explanation("openai", "gpt-6-astra"))
        for model in MODEL_CATALOG["openai"]:
            self.assertEqual(MODEL_CAPABILITIES[model].completion_token_field, "max_completion_tokens")
        for model, mode in (("gpt-5.5", "max"), ("gpt-6-astra", "none"), ("gpt-6.1-sol", "none"),
                            ("gpt-6.1-sol", "minimal"), ("gpt-5", "none"), ("gpt-5.1", "minimal")):
            with self.subTest(model=model, mode=mode), self.assertRaises(TeachMeChatError):
                reasoning_parameters("openai", model, "", mode, 1024)

    def test_gemini_exact_specs(self):
        for model, default in (("gemini-3.8-flash", "medium"), ("gemini-3.6-flash", "medium"),
                               ("gemini-3.5-flash-lite", "minimal"), ("gemini-3.1-pro-preview", "high"),
                               ("gemini-3-flash-preview", "high")):
            with self.subTest(model=model):
                cap = get_model_capability("gemini", model)
                self.assertEqual((cap.provider, cap.protocol, cap.parameter), ("gemini", "openai", "reasoning_effort"))
                self.assertEqual(cap.default_effort, default)
                self.assertEqual(cap.completion_token_field, "max_tokens")
                self.assertTrue(cap.source_urls)
                self.assertIn("仅限既往使用者", get_model_explanation("gemini", model))
        self.assertEqual(self.values("gemini", "gemini-3.8-flash"), ["default", "low", "medium", "high"])
        self.assertEqual(self.values("gemini", "gemini-3.1-pro-preview"), ["default", "low", "medium", "high"])
        for model in ("gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"):
            self.assertEqual(self.values("gemini", model), ["default", "minimal", "low", "medium", "high"])
        for mode in ("low", "medium", "high"):
            self.assertEqual(reasoning_parameters("gemini", "gemini-3.8-flash", "", mode, 1024), {"reasoning_effort": mode})
        self.assertIn("json_object", get_model_explanation("gemini", "gemini-3.8-flash"))
        for model, mode in (("gemini-3.8-flash", "minimal"), ("gemini-3.8-flash", "none"), ("gemini-3.8-flash", "max"),
                            ("gemini-3.1-pro-preview", "minimal"), ("gemini-3-flash-preview", "max")):
            with self.subTest(model=model, mode=mode), self.assertRaises(TeachMeChatError):
                reasoning_parameters("gemini", model, "", mode, 1024)

    def test_native_adaptive_and_legacy_choices(self):
        for model in ("claude-opus-4-6", "claude-sonnet-4-6"):
            self.assertEqual(self.values("anthropic", model), ["default", "disabled", "low", "medium", "high", "max"])
        self.assertEqual(self.values("anthropic", "claude-sonnet-4-5"), ["default", "disabled", "enabled"])

    def test_glm_kimi_have_real_choices(self):
        for model in ("glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7", "glm-4.7-flashx"):
            self.assertEqual(self.values("glm", model), ["default", "disabled", "enabled"])
        self.assertEqual(self.values("kimi", "kimi-k2.6"), ["default", "disabled", "enabled"])
        self.assertEqual(self.values("kimi", "kimi-k3"), ["default", "low", "high", "max"])

    def test_unknown_alias_never_inferred_from_substrings(self):
        for model in ("", "Gpt-5", "gpt-5-thinking", "my-gpt-5", "gpt-5-2099-01-01", "gpt-5 ", "glm-4.7-custom",
                      "kimi-k3-alias", "claude-opus-4-6-proxy", "gemini-3-flash", "gemini-3.8-flash-preview", None):
            for provider in ("openai", "glm", "kimi", "anthropic", "custom", "gemini"):
                self.assertEqual(self.values(provider, model), ["default"])
        self.assertEqual(self.values("kimi", "gpt-5"), ["default"])
        self.assertEqual(self.values("custom", "claude-opus-4-6", "openai"), ["default"])
        self.assertEqual(self.values("openai", "gpt-5", "anthropic"), ["default"])

    def test_third_party_exact_id_uses_protocol_not_credentials(self):
        for model, capability in MODEL_CAPABILITIES.items():
            for provider in ("custom", "openai-compatible"):
                self.assertEqual(self.values(provider, model, capability.protocol), self.values(capability.provider, model))
        for model, protocol in (("gpt-5", "openai"), ("claude-opus-4-6", "anthropic"), ("unknown", "openai")):
            explanation = get_model_explanation("custom", model, protocol)
            self.assertIn("第三方代理可能不支持", explanation)
            self.assertIn("default", explanation)
            self.assertIn("地址和凭据保持不变", explanation)
        self.assertIn("output_config.effort", get_model_explanation("anthropic", "claude-opus-4-6"))
        self.assertIn("preview", get_model_explanation("gemini", "gemini-3-flash-preview"))
        self.assertIn("未登记", get_model_explanation("custom", "alias"))

    def test_recommendations_and_helpers_are_offline_and_return_fresh_lists(self):
        with patch("teachmechat.providers.request.build_opener", side_effect=AssertionError("network")):
            for provider in ("openai", "anthropic", "glm", "kimi", "deepseek", "gemini"):
                models = suggested_models(provider)
                self.assertTrue(models)
                self.assertTrue(all(MODEL_CAPABILITIES[m].provider == provider for m in models))
                models.clear()
                self.assertTrue(suggested_models(provider))
                self.values(provider, "unknown")
        self.assertEqual(suggested_models("custom"), [])
        self.assertEqual(suggested_models("openai-compatible"), [])
        with self.assertRaises(TeachMeChatError):
            get_model_options("custom", "gpt-5", "wrong")

    def test_every_option_produces_expected_payload_offline(self):
        for model, capability in MODEL_CAPABILITIES.items():
            for _, mode in get_model_options(capability.provider, model):
                with self.subTest(model=model, mode=mode):
                    native = capability.protocol == "anthropic"
                    transport = Transport(anthropic_response() if native else Response(response_body()))
                    conf = config(provider="custom", model=model, protocol=capability.protocol, reasoning=mode)
                    before = asdict(conf)
                    client = LLMClient(conf, transport=transport)
                    client.complete([{"role": "user", "content": "synthetic"}], structured=True)
                    req = transport.requests[0][0]
                    body = json.loads(req.data)
                    self.assertEqual(asdict(conf), before)
                    self.assertTrue(req.full_url.startswith("https://example.invalid/v1/"))
                    self.assertEqual(req.get_header("X-api-key" if native else "Authorization"), SECRET if native else "Bearer " + SECRET)
                    expected = reasoning_parameters("custom", model, capability.protocol, mode, 1024)
                    for key, value in expected.items():
                        if key == "output_config":
                            self.assertEqual(body[key]["effort"], value["effort"])
                            self.assertIn("format", body[key])
                        else:
                            self.assertEqual(body[key], value)
                    if mode == "default":
                        self.assertNotIn("thinking", body)
                        self.assertNotIn("reasoning_effort", body)
                    if capability.provider == "openai":
                        self.assertIn("max_completion_tokens", body)
                        self.assertNotIn("max_tokens", body)
                    if capability.provider == "gemini":
                        self.assertIn("max_tokens", body)
                        self.assertNotIn("max_completion_tokens", body)

    def test_bad_levels_fail_before_network_not_silently_downgraded(self):
        for provider, model, mode in (("openai", "gpt-5", "none"), ("openai", "gpt-5.1", "minimal"),
                                      ("openai", "o3", "minimal"), ("openai", "gpt-6-astra", "none"),
                                      ("openai", "gpt-5.5", "max"), ("kimi", "kimi-k3", "medium"),
                                      ("kimi", "kimi-k2.7-code", "disabled"), ("anthropic", "claude-opus-4-6", "xhigh"),
                                      ("anthropic", "claude-fable-5-1", "disabled"), ("gemini", "gemini-3.8-flash", "minimal"),
                                      ("glm", "glm-5.2", "enabled"), ("custom", "alias", "high")):
            transport = Transport()
            with self.subTest(model=model), self.assertRaises(TeachMeChatError):
                LLMClient(config(provider=provider, model=model, reasoning=mode), transport=transport)
            self.assertEqual(transport.requests, [])

    def test_probe_unknown_alias_has_allowance_and_length_is_not_network_error(self):
        for native in (False, True):
            transport = Transport(anthropic_response(stop_reason="max_tokens") if native else Response(response_body(finish_reason="length")))
            client = LLMClient(config(provider="custom", protocol="anthropic" if native else "openai"), transport=transport)
            with self.assertRaisesRegex(TeachMeChatError, "不代表网络不通"):
                client.probe()
            self.assertEqual(json.loads(transport.requests[0][0].data)["max_tokens"], 1024)
            self.assertEqual(len(transport.requests), 1)

    def test_anthropic_adaptive_schema_merge_prompt_and_legacy(self):
        for structured_mode in ("native", "prompt"):
            for model in ("claude-opus-4-6", "claude-sonnet-4-6"):
                transport = Transport(anthropic_response(), anthropic_response())
                client = LLMClient(config(provider="anthropic", model=model, reasoning="low", structured_mode=structured_mode), transport=transport)
                for structured in (True, False):
                    client.complete([{"role": "user", "content": "synthetic"}], structured=structured)
                    body = json.loads(transport.requests[-1][0].data)
                    self.assertEqual(body["thinking"], {"type": "adaptive"})
                    self.assertEqual(body["output_config"]["effort"], "low")
                    self.assertEqual("format" in body["output_config"], structured and structured_mode == "native")
                    self.assertEqual(body["max_tokens"], 2048)
        for model in ("claude-opus-4-6", "claude-opus-4-5", "old-private-alias"):
            transport = Transport(anthropic_response())
            LLMClient(config(provider="anthropic", model=model, reasoning="enabled", thinking_budget=3072), transport=transport).complete([{"role": "user", "content": "x"}], max_tokens=512)
            body = json.loads(transport.requests[0][0].data)
            self.assertEqual(body["thinking"], {"type": "enabled", "budget_tokens": 3072})
            self.assertEqual(body["max_tokens"], 3584)


class DiscoveryTests(unittest.TestCase):
    def test_empty_model_get_only_no_config_mutation(self):
        conf = config(model="", reasoning="not-used", thinking_budget=0, structured_mode="not-used", timeout=12)
        before = asdict(conf)
        transport = Transport(model_response(["z", "a", "z"]))
        self.assertEqual(discover_models(conf, transport=transport), ["z", "a"])
        self.assertEqual(asdict(conf), before)
        req, timeout = transport.requests[0]
        self.assertEqual(req.full_url, MODEL_URL)
        self.assertEqual(req.method, "GET")
        self.assertIsNone(req.data)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + SECRET)
        self.assertIsNone(req.get_header("X-api-key"))
        self.assertEqual(timeout, 12)
        with self.assertRaises(TeachMeChatError):
            LLMClient(config(model=""), transport=Transport())

    def test_existing_client_and_empty_catalog(self):
        transport = Transport(model_response())
        client = LLMClient(config(), transport=transport)
        self.assertEqual(client.request_count, 0)
        self.assertEqual(client.list_models(), [])
        self.assertEqual(client.request_count, 1)

    def test_native_pagination_and_encoded_cursor(self):
        cursor = "claude/safe?next=elsewhere&x=1"
        transport = Transport(model_response([cursor], native=True, has_more=True, last_id=cursor), model_response([cursor, "last"], native=True, cursor=cursor, has_more=False))
        conf = config(provider="custom", protocol="anthropic", model="")
        self.assertEqual(discover_models(conf, transport=transport), [cursor, "last"])
        for req, _ in transport.requests:
            self.assertEqual(req.method, "GET")
            self.assertIsNone(req.data)
            self.assertEqual(req.get_header("X-api-key"), SECRET)
            self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
            self.assertIsNone(req.get_header("Authorization"))
            self.assertTrue(req.full_url.startswith(MODEL_URL + "?limit=100"))
        self.assertIn("after_id=claude%2Fsafe%3Fnext%3Delsewhere%26x%3D1", transport.requests[1][0].full_url)

    def test_current_endpoint_no_provider_default_fallback(self):
        for provider, protocol, base in (("openai", "", "https://example.invalid/v1/chat/completions/"), ("anthropic", "", "https://example.invalid/v1/messages"), ("custom", "openai", "https://example.invalid/v1/models/")):
            native = provider == "anthropic"
            transport = Transport(model_response(["alias"], native=native))
            self.assertEqual(discover_models(config(provider=provider, protocol=protocol, base_url=base, model=""), transport=transport), ["alias"])
            self.assertTrue(transport.requests[0][0].full_url.startswith(MODEL_URL))

    def test_invalid_connection_rejected_without_io(self):
        for change in ({"base_url": "http://remote.invalid/v1"}, {"base_url": "https://u:p@example.invalid"}, {"base_url": "https://example.invalid?q=x"}, {"api_key": ""}, {"api_key": "a\nb"}, {"api_key": "a b"}, {"timeout": 0}, {"timeout": float("inf")}, {"timeout": True}, {"timeout": 301}, {"protocol": "bad"}, {"provider": "unknown"}):
            transport = Transport()
            with self.subTest(change=change), self.assertRaises(TeachMeChatError):
                discover_models(config(model="", **change), transport=transport)
            self.assertEqual(transport.requests, [])
        with self.assertRaises(TeachMeChatError):
            discover_models(config(model=""), transport=Transport(), request_guard=False)

    def test_malformed_lists_and_ids_are_safe_errors(self):
        bodies = [b"not-json " + SECRET.encode(), b"[]", b"{}", b'{"data":NaN}', b'{"data":{}}']
        for value in ([{}], [None], [{"id": ""}], [{"id": "bad\nline"}], [{"id": "\x7f"}], [{"id": "a\u202eb"}], [{"id": "x" * 257}], [{"id": 1}], [{"id": " trailing "}]):
            bodies.append(json.dumps({"data": value}).encode())
        for raw in bodies:
            with self.subTest(raw=raw), self.assertRaises(TeachMeChatError) as caught:
                discover_models(config(model=""), transport=Transport(Response(raw, url=MODEL_URL)))
            self.assertNotIn(SECRET, str(caught.exception))
        with self.assertRaises(TeachMeChatError):
            discover_models(config(model=""), transport=Transport(model_response(["x"] * (MAX_MODEL_IDS + 1))))

    def test_native_invalid_or_repeated_cursor_fails(self):
        for fields in ({"has_more": True}, {"has_more": "true"}, {"has_more": True, "last_id": "not-last"}, {"has_more": True, "last_id": "\n"}):
            with self.subTest(fields=fields), self.assertRaises(TeachMeChatError):
                discover_models(config(provider="anthropic", model=""), transport=Transport(model_response(["x"], native=True, **fields)))
        transport = Transport(model_response(["x"], native=True, has_more=True, last_id="x"), model_response(["x"], native=True, cursor="x", has_more=True, last_id="x"))
        with self.assertRaises(TeachMeChatError):
            discover_models(config(provider="anthropic", model=""), transport=transport)
        self.assertEqual(len(transport.requests), 2)
        with self.assertRaises(TeachMeChatError):
            discover_models(config(model=""), transport=Transport(model_response(["x"], has_more=True, next="https://elsewhere.invalid")))

    def test_pagination_limit_and_total_response_limit(self):
        pages = [model_response([str(i)], native=True, cursor=str(i - 1) if i else None, has_more=True, last_id=str(i)) for i in range(MAX_MODEL_PAGES)]
        transport = Transport(*pages)
        with self.assertRaisesRegex(TeachMeChatError, "分页上限"):
            discover_models(config(provider="anthropic", model=""), transport=transport)
        self.assertEqual(len(transport.requests), MAX_MODEL_PAGES)
        pages = [model_response([str(i)], native=True, cursor=str(i - 1) if i else None, has_more=not i, last_id=str(i), padding="x" * (MAX_RESPONSE_BYTES // 2)) for i in range(2)]
        with self.assertRaisesRegex(TeachMeChatError, "总响应"):
            discover_models(config(provider="anthropic", model=""), transport=Transport(*pages))

    def test_same_transport_limits_redirect_auth_retry_guard(self):
        for result in (failure(302), failure(401), failure(403), failure(404), Response(b"{}", url="https://elsewhere.invalid/models"), Response(b"x" * (MAX_RESPONSE_BYTES + 1), url=MODEL_URL), Response(b"", url=MODEL_URL, headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}), Response(b"", url=MODEL_URL, headers={"Content-Length": "bad"}), Response(b"", url=MODEL_URL, headers={"Content-Encoding": "gzip"})):
            transport = Transport(result)
            with self.subTest(result=type(result).__name__), self.assertRaises(TeachMeChatError) as caught:
                discover_models(config(model=""), transport=transport)
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertNotIn(PRIVATE, str(caught.exception))
            self.assertEqual(len(transport.requests), 1)
        events = []
        class Ordered(Transport):
            def open(self, req, timeout):
                events.append("get")
                return super().open(req, timeout)
        transport = Ordered(failure(429), failure(503), model_response(["x"]))
        result = discover_models(config(model=""), transport=transport, sleep=lambda _: events.append("sleep"), request_guard=lambda: events.append("guard"))
        self.assertEqual(result, ["x"])
        self.assertEqual(events, ["guard", "get", "sleep", "guard", "get", "sleep", "guard", "get"])

    def test_guard_can_deny_first_page_retry_or_next_page(self):
        for first in (None, failure(429), model_response(["x"], native=True, has_more=True, last_id="x")):
            transport = Transport(*([] if first is None else [first]))
            calls = []
            def guard():
                calls.append(1)
                if first is None or len(calls) > 1:
                    raise TeachMeChatError("synthetic denial")
            with self.assertRaisesRegex(TeachMeChatError, "synthetic denial"):
                discover_models(config(provider="anthropic", model=""), transport=transport, sleep=lambda _: None, request_guard=guard)
            self.assertEqual(len(transport.requests), 0 if first is None else 1)

    def test_default_transport_disables_proxy_and_redirects(self):
        transport = Transport(model_response())
        with patch("teachmechat.providers.request.build_opener", return_value=transport) as build:
            discover_models(config(model=""))
        handlers = build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsNone(handlers[1].redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid"))


if __name__ == "__main__":
    unittest.main()
