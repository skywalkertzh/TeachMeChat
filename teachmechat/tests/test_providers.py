import base64
import io
import json
import threading
import unittest
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from teachmechat.models import ProviderConfig, TeachMeChatError
from teachmechat.providers import ADVICE_SCHEMA, LLMClient, MAX_IMAGE_BYTES, MAX_RESPONSE_BYTES, validate_base_url


SECRET = "unit-test-secret"
PRIVATE = "synthetic-private-message"


def response_body(content="OK", **choice):
    return json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop", **choice}]}).encode()


class Response(io.BytesIO):
    def __init__(self, body, url="https://example.invalid/v1/chat/completions", headers=None):
        super().__init__(body)
        self.url = url
        self.headers = headers or {}

    def geturl(self):
        return self.url

    def getcode(self):
        return 200


class Transport:
    def __init__(self, *results):
        self.results = list(results)
        self.requests = []

    def open(self, req, timeout):
        self.requests.append((req, timeout))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def config(**kwargs):
    fields = dict(base_url="https://example.invalid/v1", model="arbitrary-model", api_key=SECRET)
    fields.update(kwargs)
    return ProviderConfig(**fields)


def failure(code):
    return HTTPError("https://example.invalid/" + SECRET, code, PRIVATE, {}, io.BytesIO((SECRET + PRIVATE).encode()))


class ProviderTests(unittest.TestCase):
    def test_urls(self):
        for url in ("https://example.invalid/v1/", "http://127.0.0.1:1234/v1", "http://[::1]/v1", "http://localhost/v1", "http://127.1.2.3/v1"):
            with self.subTest(url=url):
                self.assertEqual(validate_base_url(url), url.rstrip("/"))
        for url in ("http://example.invalid", "ftp://localhost", "https://u:p@example.invalid", "https://example.invalid?", "https://example.invalid#", "https://example.invalid/?key=secret", "https://example.invalid/#secret", "https://example.invalid\\@localhost", "https://example.invalid\n", "http://localhost.evil.invalid", "http://2130706433", "https://example.invalid:99999", "http://[::ffff:127.0.0.1]", "http://127.0.0.1%25evil", "https:///path", "https://example.invalid:0"):
            with self.subTest(url=url), self.assertRaises(TeachMeChatError):
                validate_base_url(url)

    def test_request_and_probe(self):
        transport = Transport(Response(response_body("model-text-not-displayed")))
        client = LLMClient(config(), transport=transport)
        result = client.probe()
        self.assertNotIn("model-text", result)
        req, timeout = transport.requests[0]
        self.assertEqual(timeout, 45)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + SECRET)
        body = json.loads(req.data)
        self.assertEqual(body["max_tokens"], 1024)
        self.assertEqual(body["messages"], [{"role": "user", "content": "Reply with OK only."}])
        self.assertNotIn("reasoning_effort", body)
        self.assertNotIn(SECRET, repr(client.config))
        self.assertNotIn(SECRET, repr(client))

    def test_provider_output_budget_and_probe(self):
        for provider, field, budget in (("openai", "max_completion_tokens", 1024), ("deepseek", "max_tokens", 1024), ("custom", "max_tokens", 1024)):
            transport = Transport(Response(response_body()))
            LLMClient(config(provider=provider), transport=transport).probe()
            body = json.loads(transport.requests[0][0].data)
            self.assertEqual(body[field], budget)
            self.assertNotIn("max_tokens" if field == "max_completion_tokens" else "max_completion_tokens", body)

    def test_reasoning_capabilities_not_model_names(self):
        for provider, mode, parameter in (("openai", "low", {"reasoning_effort": "low"}), ("deepseek", "enabled", {"thinking": {"type": "enabled"}}), ("deepseek", "disabled", {"thinking": {"type": "disabled"}}), ("custom", "default", {})):
            with self.subTest(provider=provider, mode=mode):
                transport = Transport(Response(response_body()))
                model = {"openai": "gpt-5", "deepseek": "deepseek-flash"}.get(provider, "arbitrary-model")
                LLMClient(config(provider=provider, model=model, reasoning=mode), transport=transport).complete([{"role": "user", "content": "x"}], structured=True)
                body = json.loads(transport.requests[0][0].data)
                for key, value in parameter.items():
                    self.assertEqual(body[key], value)
                self.assertEqual(body["response_format"], {"type": "json_object"})
        for provider, mode in (("custom", "low"), ("openai-compatible", "enabled"), ("deepseek", "low"), ("openai", "disabled")):
            with self.subTest(provider=provider), self.assertRaises(TeachMeChatError):
                LLMClient(config(provider=provider, reasoning=mode))

    def test_new_model_wire_parameters_and_token_field(self):
        cases = [
            ("deepseek", "deepseek-flash", "none", {"thinking": {"type": "disabled"}, "reasoning_effort": "none"}, "max_tokens"),
            ("deepseek", "deepseek-v4-pro", "max", {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}, "max_tokens"),
            ("deepseek", "deepseek-v4-pro", "disabled", {"thinking": {"type": "disabled"}}, "max_tokens"),
            ("deepseek", "deepseek-v4-pro", "enabled", {"thinking": {"type": "enabled"}}, "max_tokens"),
            ("glm", "glm-5.3", "high", {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}, "max_tokens"),
            ("kimi", "kimi-k3", "max", {"reasoning_effort": "max"}, "max_completion_tokens"),
            ("kimi", "kimi-k3", "default", {}, "max_completion_tokens"),
            ("kimi", "kimi-k2.7-code", "default", {}, "max_tokens"),
            ("kimi", "kimi-k2.7-highspeed", "default", {}, "max_tokens"),
            ("kimi", "kimi-k2.6", "disabled", {"thinking": {"type": "disabled"}}, "max_tokens"),
            ("openai", "gpt-5.5", "default", {}, "max_completion_tokens"),
            ("openai", "gpt-6-astra", "default", {}, "max_completion_tokens"),
        ]
        for original_provider, model, mode, expected, field in cases:
            for provider in (original_provider, "custom", "openai-compatible"):
                with self.subTest(provider=provider, model=model, mode=mode):
                    transport = Transport(Response(response_body()))
                    LLMClient(config(provider=provider, protocol="openai", model=model, reasoning=mode), transport=transport).complete(
                        [{"role": "user", "content": "synthetic"}], max_tokens=987, structured=True)
                    body = json.loads(transport.requests[0][0].data)
                    for key in ("thinking", "reasoning_effort"):
                        self.assertEqual(body.get(key), expected.get(key))
                    self.assertEqual(body[field], 987)
                    self.assertNotIn("max_tokens" if field == "max_completion_tokens" else "max_completion_tokens", body)
                    self.assertEqual(body["response_format"], {"type": "json_object"})
        # An unverified alias keeps the legacy field; no name heuristics.
        transport = Transport(Response(response_body()))
        LLMClient(config(provider="kimi", model="kimi-k3-private"), transport=transport).probe()
        self.assertIn("max_tokens", json.loads(transport.requests[0][0].data))

    def test_new_models_reject_unverified_modes_before_network(self):
        invalid = [
            ("glm", "glm-5.3", "disabled"), ("glm", "glm-5.3", "none"),
            ("kimi", "kimi-k3", "disabled"), ("kimi", "kimi-k3", "enabled"),
            ("kimi", "kimi-k2.7-code", "high"), ("kimi", "kimi-k2.7-highspeed", "disabled"),
            ("deepseek", "deepseek-v4-pro", "medium"),
            ("openai", "gpt-5.5", "max"), ("openai", "gpt-6-astra", "none"),
        ]
        for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-4-7", "claude-opus-4-8"):
            invalid.append(("anthropic", model, "enabled"))
            if model.endswith("5-5"):
                invalid.append(("anthropic", model, "disabled"))
        for model in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5"):
            invalid.append(("anthropic", model, "xhigh"))
        for original_provider, model, mode in invalid:
            for provider in (original_provider, "custom", "openai-compatible"):
                transport = Transport()
                protocol = "anthropic" if original_provider == "anthropic" else "openai"
                with self.subTest(provider=provider, model=model, mode=mode), self.assertRaises(TeachMeChatError):
                    LLMClient(config(provider=provider, protocol=protocol, model=model, reasoning=mode, thinking_budget=4096), transport=transport)
                self.assertEqual(transport.requests, [])

    def test_unsupported_parameters_not_silently_dropped(self):
        transport = Transport(failure(400), Response(response_body()))
        with self.assertRaisesRegex(TeachMeChatError, "参数不会被静默移除"):
            LLMClient(config(provider="deepseek", model="deepseek-flash", reasoning="enabled"), transport=transport).probe()
        self.assertEqual(len(transport.requests), 1)

    def test_bounded_retry(self):
        sleeps = []
        transport = Transport(failure(429), failure(503), Response(response_body()))
        self.assertTrue(LLMClient(config(), transport=transport, sleep=sleeps.append).probe())
        self.assertEqual(sleeps, [0.25, 0.5])
        transport = Transport(failure(500), failure(502), failure(503))
        with self.assertRaises(TeachMeChatError):
            LLMClient(config(), transport=transport, sleep=lambda _: None).probe()
        self.assertEqual(len(transport.requests), 3)

    def test_errors_private_and_not_retried(self):
        for exc in (failure(401), failure(403), failure(302), failure(422), URLError(SECRET + PRIVATE), TimeoutError(SECRET + PRIVATE), IncompleteRead((SECRET + PRIVATE).encode())):
            with self.subTest(error_type=type(exc).__name__):
                transport = Transport(exc)
                with self.assertRaises(TeachMeChatError) as caught:
                    LLMClient(config(), transport=transport).complete([{"role": "user", "content": PRIVATE}])
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertNotIn(PRIVATE, str(caught.exception))
                self.assertEqual(len(transport.requests), 1)

    def test_response_limits_and_malformed(self):
        bodies = [b"not-json " + SECRET.encode(), b"[]", b'{}', response_body(""), response_body("partial", finish_reason="length"), response_body([], finish_reason="stop"), b'{"choices":NaN}', response_body("x", message={"content": "x", "refusal": "no"}), response_body("x", message={"content": "x", "tool_calls": [{}]})]
        for body in bodies:
            with self.subTest(body_size=len(body)), self.assertRaises(TeachMeChatError) as caught:
                LLMClient(config(), transport=Transport(Response(body))).probe()
            self.assertNotIn(SECRET, str(caught.exception))
        for response in (Response(b"x" * (MAX_RESPONSE_BYTES + 1)), Response(b"", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}), Response(b"", headers={"Content-Length": "bad"}), Response(b"", headers={"Content-Encoding": "gzip"})):
            with self.assertRaises(TeachMeChatError):
                LLMClient(config(), transport=Transport(response)).probe()

    def test_image_data_uri_and_validation(self):
        transport = Transport(Response(response_body("visible description")))
        client = LLMClient(config(), transport=transport)
        self.assertEqual(client.describe_image(b"\x89PNG\r\n\x1a\nsynthetic", "image/png"), "visible description")
        body = json.loads(transport.requests[0][0].data)
        uri = body["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        for data, mime in ((b"", "image/png"), (b"fake", "image/png"), (b"fake", "image/svg+xml"), (b"x" * (MAX_IMAGE_BYTES + 1), "image/jpeg")):
            with self.assertRaises(TeachMeChatError):
                client.describe_image(data, mime)
        self.assertEqual(len(transport.requests), 1)

    def test_invalid_config(self):
        for change in ({"timeout": 0}, {"timeout": float("nan")}, {"timeout": 301}, {"timeout": True}, {"api_key": "a\r\nb"}, {"api_key": ""}, {"model": ""}, {"provider": "unknown"}):
            with self.subTest(change=change), self.assertRaises(TeachMeChatError):
                LLMClient(config(**change))

    def test_local_server_and_cross_host_redirect(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                if self.path.startswith("/redirect"):
                    self.send_response(307)
                    self.send_header("Location", "http://localhost:%s/stolen" % self.server.server_port)
                    self.end_headers()
                else:
                    data = response_body()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = "http://127.0.0.1:%s" % server.server_port
                with patch.dict("os.environ", {"http_proxy": "http://invalid.invalid:1", "HTTP_PROXY": "http://invalid.invalid:1"}):
                    LLMClient(config(base_url=base + "/v1")).probe()
                    with self.assertRaisesRegex(TeachMeChatError, "重定向"):
                        LLMClient(config(base_url=base + "/redirect")).probe()
                self.assertEqual(len(received), 2)
                self.assertEqual(received[0][0], "/v1/chat/completions")
                self.assertEqual(received[0][1], "Bearer " + SECRET)
            finally:
                server.shutdown()
                thread.join(timeout=3)


def anthropic_body(text="OK", **changes):
    data = {"type": "message", "content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
    data.update(changes)
    return json.dumps(data).encode()


def anthropic_response(text="OK", **changes):
    return Response(anthropic_body(text, **changes), url="https://example.invalid/v1/messages")


def advice_text(**changes):
    data = {"replies": ["one", "two", "three"], "analysis": "known and uncertain", "wellbeing": "rest", "limitations": []}
    data.update(changes)
    return json.dumps(data)


class RegistryClientTests(unittest.TestCase):
    def test_glm_kimi_use_chat_completions_without_guessing_reasoning(self):
        for provider in ("glm", "kimi"):
            for model in ("arbitrary-model", "name-with-thinking-and-reasoner"):
                with self.subTest(provider=provider, model=model):
                    transport = Transport(Response(response_body()))
                    LLMClient(config(provider=provider, model=model), transport=transport).probe()
                    req = transport.requests[0][0]
                    self.assertTrue(req.full_url.endswith("/chat/completions"))
                    body = json.loads(req.data)
                    self.assertEqual(body["model"], model)
                    self.assertNotIn("thinking", body)
                    self.assertNotIn("reasoning_effort", body)
                    self.assertNotIn("output_config", body)
            for mode in ("enabled", "disabled", "low"):
                with self.subTest(provider=provider, mode=mode), self.assertRaises(TeachMeChatError):
                    LLMClient(config(provider=provider, reasoning=mode))

    def test_explicit_protocol_selects_wire_format(self):
        for provider, protocol, native in (("custom", "anthropic", True), ("openai", "anthropic", True), ("anthropic", "openai", False)):
            with self.subTest(provider=provider, protocol=protocol):
                transport = Transport(anthropic_response() if native else Response(response_body()))
                LLMClient(config(provider=provider, protocol=protocol), transport=transport).probe()
                req = transport.requests[0][0]
                self.assertEqual(req.full_url.rsplit("/", 1)[-1], "messages" if native else "completions")
                self.assertEqual(bool(req.get_header("X-api-key")), native)
                self.assertEqual(bool(req.get_header("Authorization")), not native)
                body = json.loads(req.data)
                self.assertNotIn("max_completion_tokens", body)

    def test_invalid_extended_configuration(self):
        for change in ({"protocol": "unknown"}, {"protocol": None}, {"structured_mode": "invalid"}, {"structured_mode": None}, {"thinking_budget": True}, {"thinking_budget": 1023}, {"thinking_budget": 16384}, {"thinking_budget": 1024.0}, {"thinking_budget": "1024"}):
            with self.subTest(change=change), self.assertRaises(TeachMeChatError):
                LLMClient(config(**change))
        with self.assertRaises(TeachMeChatError):
            LLMClient(config(), request_guard=False)

    def test_prompt_mode_never_sends_structured_parameters(self):
        from teachmechat.coach import generate_advice

        for provider in ("openai", "glm", "kimi", "anthropic", "custom"):
            make_response = anthropic_response if provider == "anthropic" else lambda text: Response(response_body(text))
            with self.subTest(provider=provider):
                transport = Transport(make_response(advice_text(replies=["invalid"])), make_response(advice_text()))
                client = LLMClient(config(provider=provider, structured_mode="prompt"), transport=transport)
                result = generate_advice(client, [], background="synthetic test")
                self.assertEqual(result.replies, ["one", "two", "three"])
                self.assertEqual(client.request_count, 2)
                for req, _ in transport.requests:
                    body = json.loads(req.data)
                    for key in ("response_format", "output_config", "tools", "tool_choice"):
                        self.assertNotIn(key, body)
                transport = Transport(make_response(advice_text(replies=[])), make_response(advice_text(replies=[])))
                with self.assertRaisesRegex(TeachMeChatError, "严格 JSON 校验"):
                    generate_advice(LLMClient(config(provider=provider, structured_mode="prompt"), transport=transport), [], background="synthetic test")

    def test_structured_probe_has_no_chat_data_and_hides_model_text(self):
        for provider in ("openai", "anthropic"):
            for mode in ("native", "prompt"):
                with self.subTest(provider=provider, mode=mode):
                    content = advice_text(analysis=PRIVATE)
                    response = anthropic_response(content) if provider == "anthropic" else Response(response_body(content))
                    transport = Transport(response)
                    client = LLMClient(config(provider=provider, structured_mode=mode), transport=transport)
                    result = client.probe_structured()
                    self.assertIn("校验", result)
                    self.assertNotIn(PRIVATE, result)
                    self.assertNotIn(PRIVATE, transport.requests[0][0].data.decode())
                    self.assertEqual(client.request_count, 1)


class AnthropicTests(unittest.TestCase):
    def test_new_adaptive_effort_preserves_native_schema(self):
        for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-4-7", "claude-opus-4-8"):
            for mode in ("low", "medium", "high", "xhigh", "max", "default"):
                for structured_mode in ("native", "prompt"):
                    with self.subTest(model=model, mode=mode, structured_mode=structured_mode):
                        transport = Transport(anthropic_response())
                        client = LLMClient(config(provider="custom", protocol="anthropic", model=model, reasoning=mode,
                                                  structured_mode=structured_mode, thinking_budget=8192), transport=transport)
                        client.complete([{"role": "user", "content": "synthetic"}], max_tokens=512, structured=True)
                        body = json.loads(transport.requests[0][0].data)
                        self.assertEqual(body["max_tokens"], 512)
                        self.assertNotIn("budget_tokens", json.dumps(body))
                        if mode == "default":
                            self.assertNotIn("thinking", body)
                            self.assertNotIn("effort", body.get("output_config", {}))
                        else:
                            self.assertEqual(body["thinking"], {"type": "adaptive"})
                            self.assertEqual(body["output_config"]["effort"], mode)
                        if structured_mode == "native":
                            self.assertEqual(body["output_config"]["format"], {"type": "json_schema", "schema": ADVICE_SCHEMA})
                        else:
                            self.assertNotIn("format", body.get("output_config", {}))
        for model in ("claude-opus-4-7", "claude-opus-4-8"):
            transport = Transport(anthropic_response())
            LLMClient(config(provider="anthropic", model=model, reasoning="disabled"), transport=transport).probe()
            body = json.loads(transport.requests[0][0].data)
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertNotIn("output_config", body)

    def test_budget_truncation_is_explicit_not_network_error(self):
        for provider, model, mode, response in (
            ("anthropic", "claude-opus-5-5", "max", anthropic_response(stop_reason="max_tokens")),
            ("anthropic", "claude-sonnet-4-5", "enabled", anthropic_response(stop_reason="max_tokens")),
            ("kimi", "kimi-k3", "max", Response(response_body(finish_reason="length"))),
        ):
            with self.subTest(model=model):
                transport = Transport(response)
                with self.assertRaisesRegex(TeachMeChatError, "输出或思考长度达到上限.*不代表网络不通"):
                    LLMClient(config(provider=provider, model=model, reasoning=mode), transport=transport).probe()
                self.assertEqual(len(transport.requests), 1)

    def test_headers_endpoint_system_and_schema(self):
        for base in ("https://example.invalid/v1", "https://example.invalid/v1/messages/"):
            with self.subTest(base=base):
                transport = Transport(anthropic_response(advice_text()))
                client = LLMClient(config(provider="anthropic", base_url=base), transport=transport)
                messages = [{"role": "system", "content": "first system"}, {"role": "system", "content": [{"type": "text", "text": "second system"}]}, {"role": "user", "content": "synthetic"}]
                before = json.dumps(messages)
                self.assertEqual(client.complete(messages, structured=True), advice_text())
                self.assertEqual(json.dumps(messages), before)
                req, timeout = transport.requests[0]
                self.assertEqual(req.full_url, "https://example.invalid/v1/messages")
                self.assertEqual(req.get_header("X-api-key"), SECRET)
                self.assertEqual(req.get_header("Anthropic-version"), "2023-06-01")
                self.assertIsNone(req.get_header("Authorization"))
                self.assertEqual(timeout, 45)
                body = json.loads(req.data)
                self.assertEqual(body["system"], "first system\n\nsecond system")
                self.assertEqual(body["messages"], [{"role": "user", "content": "synthetic"}])
                self.assertEqual(body["output_config"], {"format": {"type": "json_schema", "schema": ADVICE_SCHEMA}})
                self.assertEqual(set(ADVICE_SCHEMA["properties"]), {"replies", "analysis", "wellbeing", "limitations"})
                self.assertFalse(ADVICE_SCHEMA["additionalProperties"])
                self.assertNotIn("response_format", body)
                self.assertNotIn("thinking", body)
                self.assertEqual(body["max_tokens"], 2048)

    def test_thinking_is_protocol_specific_and_budget_fits(self):
        for mode, expected in (("default", None), ("disabled", {"type": "disabled"}), ("enabled", {"type": "enabled", "budget_tokens": 2048})):
            with self.subTest(mode=mode):
                transport = Transport(anthropic_response())
                client = LLMClient(config(provider="anthropic", reasoning=mode, thinking_budget=2048), transport=transport)
                client.complete([{"role": "user", "content": "x"}], max_tokens=512)
                body = json.loads(transport.requests[0][0].data)
                self.assertEqual(body.get("thinking"), expected)
                self.assertEqual(body["max_tokens"], 2560 if mode == "enabled" else 512)
                self.assertNotIn("reasoning_effort", body)
        transport = Transport(anthropic_response())
        LLMClient(config(provider="anthropic", reasoning="enabled", thinking_budget=16383), transport=transport).probe()
        self.assertEqual(json.loads(transport.requests[0][0].data)["max_tokens"], 16384)
        for change in ({"reasoning": "low"}, {"protocol": "openai", "reasoning": "enabled"}):
            with self.subTest(change=change), self.assertRaises(TeachMeChatError):
                LLMClient(config(provider="anthropic", **change))

    def test_image_uses_native_base64_block(self):
        data = b"\x89PNG\r\n\x1a\nsynthetic"
        transport = Transport(anthropic_response("visible facts"))
        client = LLMClient(config(provider="anthropic"), transport=transport)
        self.assertEqual(client.describe_image(data, "image/png"), "visible facts")
        body = json.loads(transport.requests[0][0].data)
        self.assertIn("system", body)
        self.assertEqual(len(body["messages"]), 1)
        blocks = body["messages"][0]["content"]
        self.assertEqual(blocks[0]["type"], "text")
        self.assertEqual(blocks[1], {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(data).decode()}})
        self.assertNotIn("image_url", json.dumps(body))
        self.assertNotIn("output_config", body)

    def test_invalid_native_input_is_rejected_without_request(self):
        transport = Transport()
        client = LLMClient(config(provider="anthropic"), transport=transport)
        for messages in ([{"role": "system", "content": "only system"}], [{"role": "tool", "content": "tool output"}], [{"role": "user", "content": []}], [{"role": "user", "content": [{"type": "tool_use"}]}], [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.invalid/private.png"}}]}], [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]}]):
            with self.subTest(messages=messages), self.assertRaises(TeachMeChatError):
                client.complete(messages)
        self.assertEqual(client.request_count, 0)
        self.assertEqual(transport.requests, [])

    def test_extract_only_text_not_private_thinking(self):
        content = [{"type": "thinking", "thinking": SECRET}, {"type": "redacted_thinking", "data": PRIVATE}, {"type": "text", "text": " first"}, {"type": "text", "text": " second "}]
        for reason in ("end_turn", "stop_sequence"):
            transport = Transport(anthropic_response(content=content, stop_reason=reason))
            self.assertEqual(LLMClient(config(provider="anthropic"), transport=transport).complete([{"role": "user", "content": "test"}]), "first second")

    def test_stop_reasons_and_invalid_content_are_rejected(self):
        bodies = [anthropic_body(stop_reason=reason) for reason in (None, "max_tokens", "tool_use", "pause_turn", "refusal", "unknown")]
        bodies.extend(anthropic_body(content=content) for content in ([], "text", [{"type": "thinking", "thinking": PRIVATE}], [{"type": "text", "text": " "}], [{"type": "text", "text": 123}], [{"type": "text", "text": "ok"}, {"type": "tool_use", "input": PRIVATE}], [{"type": "refusal", "text": PRIVATE}], [None]))
        bodies.extend((b"not-json " + SECRET.encode(), b"[]", b"{}", b'{"content":NaN}', anthropic_body(type="error")))
        for raw in bodies:
            with self.subTest(raw=raw), self.assertRaises(TeachMeChatError) as caught:
                LLMClient(config(provider="anthropic"), transport=Transport(Response(raw, url="https://example.invalid/v1/messages"))).probe()
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertNotIn(PRIVATE, str(caught.exception))

    def test_shared_safety_retry_and_limits(self):
        sleeps = []
        transport = Transport(failure(429), failure(503), anthropic_response())
        client = LLMClient(config(provider="anthropic"), transport=transport, sleep=sleeps.append)
        client.probe()
        self.assertEqual(client.request_count, 3)
        self.assertEqual(sleeps, [0.25, 0.5])
        for result in (failure(302), failure(401), failure(400), URLError(SECRET + PRIVATE), Response(anthropic_body(), url="https://other.invalid/messages"), Response(b"x" * (MAX_RESPONSE_BYTES + 1), url="https://example.invalid/v1/messages"), Response(b"", url="https://example.invalid/v1/messages", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}), Response(b"", url="https://example.invalid/v1/messages", headers={"Content-Encoding": "gzip"})):
            transport = Transport(result)
            with self.subTest(result=type(result).__name__), self.assertRaises(TeachMeChatError) as caught:
                LLMClient(config(provider="anthropic"), transport=transport).probe()
            self.assertNotIn(SECRET, str(caught.exception))
            self.assertNotIn(PRIVATE, str(caught.exception))
            self.assertEqual(len(transport.requests), 1)

    def test_local_server_native_path_and_redirect_blocked(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append((self.path, self.headers.get("x-api-key"), self.headers.get("anthropic-version"), self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                if self.path.startswith("/redirect"):
                    self.send_response(307)
                    self.send_header("Location", "http://localhost:%s/stolen" % self.server.server_port)
                    self.end_headers()
                else:
                    data = anthropic_body()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = "http://127.0.0.1:%s" % server.server_port
                with patch.dict("os.environ", {"http_proxy": "http://invalid.invalid:1", "HTTP_PROXY": "http://invalid.invalid:1"}):
                    LLMClient(config(provider="anthropic", base_url=base + "/v1")).probe()
                    with self.assertRaisesRegex(TeachMeChatError, "重定向"):
                        LLMClient(config(provider="anthropic", base_url=base + "/redirect")).probe()
                self.assertEqual(len(received), 2)
                self.assertEqual(received[0][:4], ("/v1/messages", SECRET, "2023-06-01", None))
            finally:
                server.shutdown()
                thread.join(timeout=3)


class RequestGuardTests(unittest.TestCase):
    def test_denied_first_attempt_does_not_send_or_increment(self):
        transport = Transport()
        denial = TeachMeChatError("synthetic guard denial")

        def guard():
            raise denial

        client = LLMClient(config(), transport=transport, request_guard=guard)
        self.assertEqual(client.request_count, 0)
        with self.assertRaises(TeachMeChatError) as caught:
            client.probe()
        self.assertIs(caught.exception, denial)
        self.assertEqual(client.request_count, 0)
        self.assertEqual(transport.requests, [])

    def test_guard_immediately_precedes_every_attempt_including_retries(self):
        events = []

        class OrderedTransport(Transport):
            def open(self, req, timeout):
                events.append("http")
                return super().open(req, timeout)

        for provider in ("custom", "anthropic"):
            with self.subTest(provider=provider):
                events.clear()
                transport = OrderedTransport(failure(429), failure(503), anthropic_response() if provider == "anthropic" else Response(response_body()))
                client = LLMClient(config(provider=provider), transport=transport, sleep=lambda _: events.append("sleep"), request_guard=lambda: events.append("guard"))
                client.probe()
                self.assertEqual(events, ["guard", "http", "sleep", "guard", "http", "sleep", "guard", "http"])
                self.assertEqual(client.request_count, 3)

    def test_guard_can_cancel_retry_and_format_repair(self):
        for first in (failure(429), Response(response_body("invalid JSON " + PRIVATE))):
            transport = Transport(first, Response(response_body(advice_text())))
            calls = []

            def guard():
                calls.append(1)
                if len(calls) > 1:
                    raise TeachMeChatError("request budget exhausted")

            client = LLMClient(config(), transport=transport, sleep=lambda _: None, request_guard=guard)
            with self.subTest(first=type(first).__name__), self.assertRaisesRegex(TeachMeChatError, "budget exhausted"):
                client.probe_structured()
            self.assertEqual(len(calls), 2)
            self.assertEqual(client.request_count, 1)
            self.assertEqual(len(transport.requests), 1)

    def test_guard_count_accumulates_across_methods_and_validation_is_free(self):
        calls = []
        transport = Transport(Response(response_body()), Response(response_body("image")), Response(response_body(advice_text())))
        client = LLMClient(config(), transport=transport, request_guard=lambda: calls.append(1))
        client.probe()
        client.describe_image(b"\x89PNG\r\n\x1a\nsynthetic", "image/png")
        client.probe_structured()
        with self.assertRaises(TeachMeChatError):
            client.complete([])
        with self.assertRaises(TeachMeChatError):
            client.complete([{"role": "user", "content": "x" * (8 * 1024 * 1024)}])
        with self.assertRaises(TeachMeChatError):
            client.describe_image(b"bad", "image/png")
        self.assertEqual(len(calls), 3)
        self.assertEqual(client.request_count, 3)


if __name__ == "__main__":
    unittest.main()
