"""Settings tests use only synthetic local tmp data and fake API keys."""

import ctypes
from ctypes import wintypes
from dataclasses import fields, replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from teachmechat.runtime import configure_runtime
from teachmechat.models import ProviderConfig, TeachMeChatError
from teachmechat import credentials
from teachmechat.settings import (
    DEFAULT_CONFIG_DIRECTORY, MARKER_FILENAME, POINTER_FILENAME, SCHEMA_VERSION,
    Settings, config_directory, load_legacy_settings, remember_config_directory,
)

_RUNTIME = None


def setUpModule():
    global _RUNTIME
    # Run before any temporary directory is requested. Never load real settings.
    _RUNTIME = configure_runtime(Path(__file__).resolve().parents[2] / ".teachmechat-runtime")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="settings-test-", dir=_RUNTIME / "tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = Settings(self.root / "configuration")
        self.primary = ProviderConfig(model="synthetic-model", api_key="fake-primary-key-canary")
        self.vision = ProviderConfig(provider="custom", base_url="https://vision.example.test/api", model="synthetic-vision", api_key="fake-vision-key-canary")
        # 运行目录是本机绝对路径；测试数据只落在它下面的 tmp（与运行目录同盘）。
        self.assertTrue(self.root.is_absolute())
        self.assertTrue(self.root.is_relative_to(_RUNTIME))
        self.assertEqual(self.root.drive, _RUNTIME.drive)

    def write_document(self, document):
        self.settings.path.write_text(json.dumps(document), encoding="utf-8")

    def document(self):
        return json.loads(self.settings.path.read_text(encoding="utf-8"))

    def test_missing_load_is_side_effect_free(self):
        self.assertEqual(self.settings.load(), {})
        self.assertEqual(self.settings.load_profiles(), (None, None, {}))
        self.assertFalse(self.settings.directory.exists())

    def test_public_legacy_save_strips_keys_and_unknown_options(self):
        vision = {item.name: getattr(self.vision, item.name) for item in fields(ProviderConfig)}
        self.settings.save(self.primary, vision=vision, background="private-chat-canary", auto_refresh=True)
        text = self.settings.path.read_text(encoding="utf-8")
        for forbidden in (self.primary.api_key, self.vision.api_key, "api_key", "private-chat-canary"):
            self.assertNotIn(forbidden, text)
        loaded = self.settings.load()
        self.assertEqual(loaded["schema_version"], SCHEMA_VERSION)
        self.assertTrue(loaded["auto_refresh"])
        self.assertNotIn("credentials", loaded)
        primary, vision, options = self.settings.load_profiles()
        self.assertEqual(primary.api_key, "")
        self.assertEqual(vision.api_key, "")
        self.assertFalse(options["remember_keys"])

    def test_supported_options_and_all_dataclass_fields_round_trip(self):
        available = {item.name for item in fields(ProviderConfig)}
        extras = {"protocol": "openai", "structured_mode": "prompt", "thinking_budget": 2048}
        configured = replace(self.primary, **{k: v for k, v in extras.items() if k in available})
        options = {"vision_enabled": True, "vision_reuse": False, "auto_refresh": False,
                   "whisper_path": str(self.root / "synthetic-model"), "request_budget": 7,
                   "context_limit": 1000}
        self.settings.save_profiles(configured, self.vision, options=options)
        primary, vision, loaded = self.settings.load_profiles()
        for item in fields(ProviderConfig):
            if item.name != "api_key":
                self.assertEqual(getattr(primary, item.name), getattr(configured, item.name))
        self.assertEqual(vision.model, self.vision.model)
        for key, value in options.items():
            self.assertEqual(loaded[key], value)

    def test_context_limits_round_trip_in_both_save_apis(self):
        for limit in (1, 100, 200, 500, 1000, 1234, 5000):
            for legacy_save in (False, True):
                with self.subTest(limit=limit, legacy_save=legacy_save):
                    options = {"context_limit": limit, "auto_refresh": True,
                               "request_budget": 9, "vision_reuse": False}
                    if legacy_save:
                        self.settings.save(self.primary, vision=self.vision, **options)
                    else:
                        self.settings.save_profiles(self.primary, self.vision, options=options)
                    self.assertEqual(self.document()["context_limit"], limit)
                    self.assertEqual(self.settings.load()["context_limit"], limit)
                    primary, vision, loaded = self.settings.load_profiles()
                    self.assertEqual(primary.model, self.primary.model)
                    self.assertEqual(vision.model, self.vision.model)
                    for key, value in options.items():
                        self.assertEqual(loaded[key], value)

    def test_old_context_default_is_read_only_and_preserves_other_fields(self):
        self.settings.save_profiles(self.primary, self.vision,
                                    options={"auto_refresh": True, "request_budget": 8})
        document = self.document()
        document.pop("context_limit", None)
        self.write_document(document)
        before = self.settings.path.read_bytes()
        loaded = self.settings.load()
        self.assertEqual(loaded["context_limit"], 100)
        primary, vision, options = self.settings.load_profiles()
        self.assertEqual(options["context_limit"], 100)
        self.assertTrue(options["auto_refresh"])
        self.assertEqual(options["request_budget"], 8)
        self.assertEqual(self.settings.path.read_bytes(), before)
        self.settings.save_profiles(primary, vision, options={**options, "context_limit": 5000})
        after = self.document()
        self.assertEqual(after.pop("context_limit"), 5000)
        self.assertEqual(after, document)

    def test_invalid_context_limits_rejected_on_save_and_load_without_rewrite(self):
        self.settings.save_profiles(self.primary, options={"context_limit": 200})
        original = self.document()
        for value in (True, False, 0, -1, 5001, 1.5, 100.0, "100", None, [], {}):
            with self.subTest(value=value):
                self.write_document(original)
                before = self.settings.path.read_bytes()
                with self.assertRaises(TeachMeChatError):
                    self.settings.save_profiles(self.primary, options={"context_limit": value})
                with self.assertRaises(TeachMeChatError):
                    self.settings.save(self.primary, context_limit=value)
                self.assertEqual(self.settings.path.read_bytes(), before)
                self.write_document({**original, "context_limit": value})
                before = self.settings.path.read_bytes()
                for load in (self.settings.load, self.settings.load_profiles):
                    with self.assertRaises(TeachMeChatError):
                        load()
                self.assertEqual(self.settings.path.read_bytes(), before)

    def test_session_and_public_never_persist_keys(self):
        for mode in ("session", "public"):
            with self.subTest(mode=mode):
                self.settings.save_profiles(self.primary, self.vision, options={"credential_mode": mode})
                self.assertEqual(self.document()["credentials"], {})
                self.assertEqual(self.settings.load_profiles()[2]["credential_mode"], mode)
                for path in self.settings.directory.iterdir():
                    self.assertNotIn(self.primary.api_key.encode(), path.read_bytes())
                    self.assertNotIn(self.vision.api_key.encode(), path.read_bytes())

    def test_configuration_types_rejected_without_changing_existing_file(self):
        self.settings.save_profiles(self.primary)
        before = self.settings.path.read_bytes()
        bad_fields = {"provider": None, "base_url": [], "model": {}, "reasoning": True, "timeout": True,
                      "api_key": "fake-key\nheader", "protocol": 3, "structured_mode": False, "thinking_budget": True}
        available = {item.name for item in fields(ProviderConfig)}
        for key, value in bad_fields.items():
            if key not in available:
                continue
            with self.subTest(field=key), self.assertRaises(TeachMeChatError):
                self.settings.save_profiles(replace(self.primary, **{key: value}))
            self.assertEqual(self.settings.path.read_bytes(), before)
        for timeout in (0, -1, float("inf"), float("nan"), 301, "45"):
            with self.subTest(timeout=timeout), self.assertRaises(TeachMeChatError):
                self.settings.save_profiles(replace(self.primary, timeout=timeout))
        for options in ({"vision_enabled": 1}, {"vision_reuse": "true"}, {"auto_refresh": None},
                        {"whisper_path": []}, {"request_budget": True}, {"request_budget": 0},
                        {"remember_keys": "false"}, {"credential_mode": []}, {"credential_mode": "unknown"},
                        {"private_context": "should-not-persist"}):
            with self.subTest(options=options), self.assertRaises(TeachMeChatError):
                self.settings.save_profiles(self.primary, options=options)
            self.assertEqual(self.settings.path.read_bytes(), before)
        with self.assertRaises(TeachMeChatError):
            self.settings.save_profiles(self.primary, remember_keys=1)

    def test_unsafe_urls_rejected(self):
        for url in ("https://user:password@example.test/v1", "https://example.test/?secret=canary",
                    "http://remote.example.test/v1", "https://example.test/#fragment", "file:///E:/tmp"):
            with self.subTest(url=url), self.assertRaises(TeachMeChatError) as caught:
                self.settings.save_profiles(replace(self.primary, base_url=url))
            self.assertNotIn(url, str(caught.exception))
        self.assertFalse(self.settings.directory.exists())

    def test_corrupt_or_unsupported_settings_never_silently_overwritten(self):
        self.settings.save_profiles(self.primary)
        original = self.document()
        invalid_documents = ["{", "[]", "null", "", "{\"schema_version\":1,\"schema_version\":1}",
                             json.dumps({**original, "schema_version": 999}),
                             json.dumps({**original, "schema_version": True}),
                             json.dumps({**original, "provider": []}),
                             json.dumps({**original, "provider": {**original["provider"], "api_key": "fake-plain-secret"}}),
                             json.dumps({**original, "vision": "bad"}),
                             json.dumps({**original, "credentials": []}),
                             json.dumps({**original, "auto_refresh": "yes"}),
                             json.dumps({**original, "unknown": 1}),
                             "{" + "\"deep\":" + "[" * 2000 + "0" + "]" * 2000 + "}",
                             " " * (256 * 1024 + 1)]
        for raw in invalid_documents:
            with self.subTest(raw=raw[:80]):
                self.settings.path.write_text(raw, encoding="utf-8")
                before = self.settings.path.read_bytes()
                with self.assertRaises(TeachMeChatError):
                    self.settings.load()
                with self.assertRaises(TeachMeChatError):
                    self.settings.save_profiles(self.primary)
                self.assertEqual(self.settings.path.read_bytes(), before)

    def test_unmarked_user_directory_is_not_adopted_even_with_legacy_file(self):
        self.settings.directory.mkdir()
        unrelated = self.settings.directory / "user-data.txt"
        unrelated.write_text("synthetic-user-canary", encoding="utf-8")
        for operation in (self.settings.load, lambda: self.settings.save_profiles(self.primary)):
            with self.assertRaises(TeachMeChatError):
                operation()
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "synthetic-user-canary")
        self.assertEqual(list(self.settings.directory.iterdir()), [unrelated])

    def test_empty_owned_directory_can_be_adopted(self):
        self.settings.directory.mkdir()
        self.settings.save_profiles(self.primary)
        marker = json.loads((self.settings.directory / MARKER_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(marker["owner"], credentials.current_owner())
        self.assertEqual(marker["application"], "TeachMeChat")

    def test_foreign_owner_marker_and_corrupt_marker_block_writes(self):
        self.settings.save_profiles(self.primary)
        before = self.settings.path.read_bytes()
        for marker in ({"application": "TeachMeChat", "schema_version": 1, "owner": "foreign-owner"}, {"application": "foreign-app"}):
            self.settings.marker.write_text(json.dumps(marker), encoding="utf-8")
            with self.assertRaises(TeachMeChatError):
                self.settings.save_profiles(self.primary)
            self.assertEqual(self.settings.path.read_bytes(), before)
        self.settings.marker.write_text("{", encoding="utf-8")
        with self.assertRaises(TeachMeChatError):
            self.settings.load()

    def test_actual_owner_check_is_not_skipped(self):
        self.settings.save_profiles(self.primary)
        with patch("teachmechat.credentials.current_owner", return_value="foreign-owner"):
            with self.assertRaises(TeachMeChatError):
                self.settings.load()

    def test_hardlinked_settings_are_rejected(self):
        self.settings.save_profiles(self.primary)
        link = self.root / "linked-settings.json"
        os.link(self.settings.path, link)
        before = link.read_bytes()
        with self.assertRaises(TeachMeChatError):
            self.settings.load()
        with self.assertRaises(TeachMeChatError):
            self.settings.save_profiles(self.primary)
        self.assertEqual(link.read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "Windows junction safety")
    def test_junction_directory_and_parent_are_rejected_before_writes(self):
        target = self.root / "real-target"
        target.mkdir()
        junction = self.root / "junction"
        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.addCleanup(os.rmdir, junction)
        for directory in (junction, junction / "new-child"):
            settings = Settings(directory)
            with self.assertRaises(TeachMeChatError):
                settings.save_profiles(self.primary)
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "real Windows DPAPI")
    def test_dpapi_encrypt_failure_has_no_files_or_plaintext(self):
        with patch("teachmechat.credentials._dpapi", side_effect=TeachMeChatError("synthetic encryption failure")):
            with self.assertRaises(TeachMeChatError):
                self.settings.save_profiles(self.primary, remember_keys=True)
        self.assertFalse(self.settings.directory.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_clearing_one_profile_cannot_rewrite_malformed_other_envelope(self):
        self.settings.save_profiles(self.primary, self.vision)
        document = self.document()
        document["credentials"] = {"vision": {"api_key": "fake-plaintext-canary"}}
        self.write_document(document)
        before = self.settings.path.read_bytes()
        with self.assertRaises(TeachMeChatError):
            self.settings.clear_credentials("primary")
        self.assertEqual(self.settings.path.read_bytes(), before)
        self.settings.forget_credentials()
        self.assertNotIn("fake-plaintext-canary", self.settings.path.read_text(encoding="utf-8"))

    def test_atomic_replace_failure_preserves_original_and_cleans_temp(self):
        self.settings.save_profiles(self.primary)
        before = self.settings.path.read_bytes()
        with patch("teachmechat.settings.os.replace", side_effect=OSError("fake-private-error-canary")):
            with self.assertRaises(TeachMeChatError) as caught:
                self.settings.save_profiles(replace(self.primary, model="changed-model"))
        self.assertNotIn("fake-private-error-canary", str(caught.exception))
        self.assertEqual(self.settings.path.read_bytes(), before)
        self.assertFalse(list(self.settings.directory.glob("*.tmp")))

    def test_fsync_failure_preserves_original_and_cleans_temp(self):
        self.settings.save_profiles(self.primary)
        before = self.settings.path.read_bytes()
        with patch("teachmechat.settings.os.fsync", side_effect=OSError("synthetic-fsync-error")):
            with self.assertRaises(TeachMeChatError):
                self.settings.save_profiles(self.primary)
        self.assertEqual(self.settings.path.read_bytes(), before)
        self.assertFalse(list(self.settings.directory.glob("*.tmp")))

    def test_directory_precedence_and_pointer_only_file_no_default_creation(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        unrelated = runtime / "cache-canary.bin"
        unrelated.write_bytes(b"unchanged-cache")
        with patch("teachmechat.settings.private_directory", side_effect=AssertionError("directory creation forbidden")):
            self.assertEqual(config_directory(runtime), DEFAULT_CONFIG_DIRECTORY)
            selected = self.root / "selected-config"
            remember_config_directory(runtime, selected)
            self.assertEqual(config_directory(runtime), selected)
            explicit = self.root / "explicit-config"
            self.assertEqual(config_directory(runtime, explicit), explicit)
        pointer = json.loads((runtime / POINTER_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(pointer, {"schema_version": 1, "directory": str(selected)})
        self.assertEqual(unrelated.read_bytes(), b"unchanged-cache")
        self.assertFalse(selected.exists())
        self.assertFalse(explicit.exists())
        self.assertEqual(set(p.name for p in runtime.iterdir()), {POINTER_FILENAME, unrelated.name})

    def test_corrupt_pointer_fails_closed_but_explicit_can_bypass(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        pointer = runtime / POINTER_FILENAME
        for data in ("{", "[]", json.dumps({"schema_version": 1, "directory": "relative"}),
                     json.dumps({"schema_version": True, "directory": str(self.root)}),
                     json.dumps({"schema_version": 1, "directory": str(self.root), "api_key": "fake-key"})):
            pointer.write_text(data, encoding="utf-8")
            with self.assertRaises(TeachMeChatError):
                config_directory(runtime)
            with self.assertRaises(TeachMeChatError):
                remember_config_directory(runtime, self.root)
            self.assertEqual(pointer.read_text(encoding="utf-8"), data)
            self.assertEqual(config_directory(runtime, self.root), self.root)

    def test_pointer_requires_local_absolute_runtime_and_target(self):
        for target in ("", "relative", self.root / ".." / "escape"):
            with self.subTest(target=target), self.assertRaises(TeachMeChatError):
                config_directory(self.root, target)
        # 运行目录指针只接受本机绝对路径：相对路径与 UNC/网络路径一律拒绝。
        for runtime in ("relative-runtime", "E:relative-runtime",
                        r"\\server\share\runtime", "//server/share/runtime"):
            with self.subTest(runtime=runtime), self.assertRaises(TeachMeChatError):
                config_directory(runtime)
            with self.subTest(runtime=runtime), self.assertRaises(TeachMeChatError):
                remember_config_directory(runtime, self.root)
        # 本机绝对路径（不同盘符也可）被接受：指针照常写入与读取。
        other = self.root / "other-runtime"
        other.mkdir()
        selected = self.root / "selected-config"
        remember_config_directory(other, selected)
        self.assertEqual(config_directory(other), selected)
        if os.name == "nt":
            with self.assertRaises(TeachMeChatError):
                config_directory(self.root, r"\\server\share\config")

    def test_runtime_pointer_honors_optional_required_drive(self):
        other = "Z:" if self.root.drive.upper() != "Z:" else "Y:"
        with patch.dict(os.environ, {"TEACHMECHAT_REQUIRE_DRIVE": other}):
            with self.assertRaises(TeachMeChatError) as raised:
                config_directory(self.root)
            self.assertIn(other, str(raised.exception))
            self.assertIn("TEACHMECHAT_REQUIRE_DRIVE", str(raised.exception))
        # 与本机盘符一致（或未启用限制）时保持原有解析行为。
        with patch.dict(os.environ, {"TEACHMECHAT_REQUIRE_DRIVE": self.root.drive}):
            self.assertEqual(config_directory(self.root), DEFAULT_CONFIG_DIRECTORY)
        self.assertNotIn("TEACHMECHAT_REQUIRE_DRIVE", os.environ)

    def test_explicit_legacy_import_is_read_only_and_never_imports_keys(self):
        legacy = self.root / "legacy-settings.json"
        data = {"provider": {"model": "legacy-fake", "api_key": "fake-old-primary"},
                "vision": {"model": "legacy-vision", "api_key": "fake-old-vision"}, "auto_refresh": True}
        legacy.write_text(json.dumps(data), encoding="utf-8")
        before = legacy.read_bytes()
        self.assertEqual(self.settings.load(), {})
        imported = load_legacy_settings(legacy)
        self.assertEqual(imported["provider"]["model"], "legacy-fake")
        self.assertNotIn("api_key", imported["provider"])
        self.assertNotIn("api_key", imported["vision"])
        self.assertFalse(imported["remember_keys"])
        self.assertEqual(imported["context_limit"], 100)
        self.assertEqual(legacy.read_bytes(), before)
        self.assertFalse(self.settings.directory.exists())

    def test_runtime_legacy_settings_are_not_scanned(self):
        legacy = self.root / "settings.json"
        legacy.write_text("synthetic corrupt file never read", encoding="utf-8")
        with patch("teachmechat.settings._read_json", side_effect=AssertionError("no automatic reads")):
            self.assertEqual(config_directory(self.root), DEFAULT_CONFIG_DIRECTORY)
            self.assertEqual(self.settings.load(), {})

    @unittest.skipUnless(os.name == "nt", "real Windows DPAPI")
    def test_real_dpapi_primary_and_vision_restore_and_no_plaintext_any_file(self):
        self.settings.save_profiles(self.primary, self.vision, remember_keys=True)
        primary, vision, options = Settings(self.settings.directory).load_profiles()
        self.assertEqual(primary.api_key, self.primary.api_key)
        self.assertEqual(vision.api_key, self.vision.api_key)
        self.assertTrue(options["remember_keys"])
        self.assertEqual(options["credential_mode"], "remember")
        self.assertNotIn(self.primary.api_key, repr(primary))
        self.assertNotIn(self.vision.api_key, repr(vision))
        self.assertNotIn("api_key", repr(self.settings.load()))
        for file in self.settings.directory.iterdir():
            data = file.read_bytes()
            self.assertNotIn(self.primary.api_key.encode(), data)
            self.assertNotIn(self.vision.api_key.encode(), data)

    @unittest.skipUnless(os.name == "nt", "real Windows DPAPI")
    def test_real_dpapi_entropy_prevents_origin_provider_and_profile_tampering(self):
        self.settings.save_profiles(self.primary, self.vision, remember_keys=True)
        original = self.document()
        for updates in ({"base_url": "https://evil.example.test/v1"},
                        {"base_url": "https://api.openai.com:444/v1"},
                        {"provider": "custom"}):
            changed = json.loads(json.dumps(original))
            changed["provider"].update(updates)
            self.write_document(changed)
            before = self.settings.path.read_bytes()
            with self.assertRaises(TeachMeChatError) as caught:
                self.settings.load_profiles()
            self.assertNotIn(self.primary.api_key, str(caught.exception))
            self.assertNotIn("evil.example.test", str(caught.exception))
            with self.assertRaises(TeachMeChatError):
                self.settings.save_profiles(self.primary)
            self.assertEqual(self.settings.path.read_bytes(), before)
            self.assertNotIn("api_key", self.settings.load()["provider"])
        swapped = json.loads(json.dumps(original))
        swapped["vision"] = dict(swapped["provider"])
        swapped["credentials"]["vision"] = swapped["credentials"]["primary"]
        self.write_document(swapped)
        with self.assertRaises(TeachMeChatError):
            self.settings.load_profiles()

    @unittest.skipUnless(os.name == "nt", "real Windows DPAPI")
    def test_origin_binding_normalizes_case_default_port_and_ignores_url_path(self):
        self.settings.save_profiles(self.primary, remember_keys=True)
        data = self.document()
        data["provider"]["base_url"] = "https://API.OPENAI.COM:443/different-path"
        self.write_document(data)
        self.assertEqual(self.settings.load_profiles()[0].api_key, self.primary.api_key)

    @unittest.skipUnless(os.name == "nt", "real Windows DPAPI")
    def test_damaged_ciphertext_public_recovery_and_explicit_forget(self):
        self.settings.save_profiles(self.primary, self.vision, remember_keys=True)
        document = self.document()
        document["credentials"]["primary"]["ciphertext"] = "damaged!fake-ciphertext-canary"
        self.write_document(document)
        before = self.settings.path.read_bytes()
        with self.assertRaises(TeachMeChatError) as caught:
            self.settings.load_profiles()
        self.assertNotIn("fake-ciphertext-canary", str(caught.exception))
        self.assertEqual(self.settings.path.read_bytes(), before)
        self.assertEqual(self.settings.load()["provider"]["model"], self.primary.model)
        with self.assertRaises(TeachMeChatError):
            self.settings.save_profiles(self.primary)
        self.settings.forget_credentials("primary")
        primary, vision, options = self.settings.load_profiles()
        self.assertEqual(primary.api_key, "")
        self.assertEqual(vision.api_key, self.vision.api_key)
        self.assertTrue(options["remember_keys"])
        self.settings.clear_credentials()
        primary, vision, options = self.settings.load_profiles()
        self.assertEqual(vision.api_key, "")
        self.assertFalse(options["remember_keys"])
        self.assertEqual(primary.model, self.primary.model)

    @unittest.skipUnless(os.name == "nt", "real Windows DPAPI")
    def test_atomic_remember_tmp_contains_only_ciphertext(self):
        self.settings.save_profiles(self.primary)
        actual_replace = os.replace
        calls = []
        def observe(source, target):
            source = Path(source)
            payload = source.read_bytes()
            self.assertEqual(source.parent, self.settings.directory)
            self.assertNotIn(self.primary.api_key.encode(), payload)
            self.assertNotIn(self.vision.api_key.encode(), payload)
            calls.append(json.loads(payload))
            actual_replace(source, target)
        with patch("teachmechat.settings.os.replace", side_effect=observe):
            self.settings.save_profiles(self.primary, self.vision, remember_keys=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0]["credentials"]), {"primary", "vision"})

    @unittest.skipUnless(os.name == "nt", "real Windows ACL")
    def test_new_directory_has_current_user_only_protected_dacl(self):
        self.settings.save_profiles(self.primary, remember_keys=True)
        kernel, advapi, _ = credentials._windows()
        pointer = ctypes.c_void_p
        descriptor, dacl, owner = pointer(), pointer(), pointer()
        advapi.GetSecurityDescriptorControl.argtypes = [pointer, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
        advapi.GetAclInformation.argtypes = [pointer, pointer, wintypes.DWORD, ctypes.c_int]
        advapi.GetAce.argtypes = [pointer, wintypes.DWORD, ctypes.POINTER(pointer)]
        class AclSize(ctypes.Structure):
            _fields_ = [("count", wintypes.DWORD), ("used", wintypes.DWORD), ("free", wintypes.DWORD)]
        for path in (self.settings.directory, self.settings.path, self.settings.marker):
            result = advapi.GetNamedSecurityInfoW(str(path), 1, 0x1 | 0x4, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
            self.assertEqual(result, 0)
            try:
                self.assertEqual(credentials._sid_string(owner), credentials.current_owner())
                control, revision = wintypes.WORD(), wintypes.DWORD()
                self.assertTrue(advapi.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)))
                if path == self.settings.directory:
                    self.assertTrue(control.value & 0x1000)  # SE_DACL_PROTECTED
                self.assertTrue(dacl.value)
                size = AclSize()
                self.assertTrue(advapi.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2))
                self.assertEqual(size.count, 1)
                ace = pointer()
                self.assertTrue(advapi.GetAce(dacl, 0, ctypes.byref(ace)))
                self.assertEqual(ctypes.c_ubyte.from_address(ace.value).value, 0)  # ACCESS_ALLOWED_ACE
                self.assertEqual(credentials._sid_string(pointer(ace.value + 8)), credentials.current_owner())
            finally:
                kernel.LocalFree(descriptor)


if __name__ == "__main__":
    configure_runtime()
    unittest.main()
