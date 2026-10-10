"""Synthetic media tests only: no chat databases/media or real model imports."""
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import MagicMock, Mock, patch
import wave

from teachmechat.media import MediaProcessor, _Unavailable
from teachmechat.models import ChatMessage, TeachMeChatError


ROOT = Path(__file__).resolve().parents[2] / ".teachmechat-runtime"


class MediaTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="media-test-", dir=ROOT / "tmp")
        self.root = Path(self.temp.name)
        self.vision = Mock()
        self.vision.describe_image.return_value = "一只合成的小猫"
        self.processor = MediaProcessor(self.root, self.vision)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.processor.close)

    def message(self, kind="image", **kwargs):
        return ChatMessage("synthetic", 0, "fake", "原始文字", kind=kind, **kwargs)

    def image(self, metadata=False):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed; no dependency is installed by tests")
        buffer = io.BytesIO()
        image = Image.new("RGB", (16, 16), "red")
        if metadata:
            exif = Image.Exif()
            exif[270] = "private synthetic description"
            image.save(buffer, format="JPEG", exif=exif)
        else:
            image.save(buffer, format="PNG")
        return buffer.getvalue()

    def wav(self):
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 160)
        return output.getvalue()

    def test_image_copy_deduplicate_and_strip_exif(self):
        data = self.image(metadata=True)
        original = self.message(media_bytes=data, metadata={"keep": "value"})
        copies = self.processor.process([original, original])
        self.assertEqual(self.vision.describe_image.call_count, 1)
        self.assertEqual(original.text, "原始文字")
        self.assertEqual(original.metadata, {"keep": "value"})
        self.assertIsNot(copies[0], original)
        self.assertEqual(copies[0].metadata["media_status"], "success")
        self.assertTrue(copies[1].metadata["media_cached"])
        sanitized, mime = self.vision.describe_image.call_args.args
        from PIL import Image
        with Image.open(io.BytesIO(sanitized)) as image:
            self.assertEqual(dict(image.getexif()), {})
        self.assertNotIn(b"private synthetic", sanitized)
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(list(self.processor._scratch.iterdir()), [])

    def test_legacy_xor_explicit_and_detected_key(self):
        data = self.image()
        encrypted = bytes(byte ^ 93 for byte in data)
        for metadata in ({"xor_key": 93}, {}):
            result = self.processor.process([self.message(media_bytes=encrypted, metadata=metadata)])[0]
            self.assertEqual(result.metadata["media_status"], "success")
        bad = self.processor.process([self.message(media_bytes=encrypted, metadata={"xor_key": 21})])[0]
        self.assertEqual(bad.metadata["media_status"], "unsupported")

    def test_thumbnail_missing_original_is_marked_degraded(self):
        thumb = self.root / "thumbnail.png"
        thumb.write_bytes(self.image())
        message = self.message(media_path=str(self.root / "missing.dat"),
                               metadata={"thumbnail_path": str(thumb)})
        result = self.processor.process([message])[0]
        self.assertTrue(result.metadata["media_degraded"])
        self.assertIn("缩略图", result.text)

    def test_missing_file_not_permanently_cached(self):
        path = self.root / "later.png"
        message = self.message(media_path=str(path))
        first = self.processor.process([message])[0]
        self.assertEqual(first.metadata["media_status"], "missing")
        path.write_bytes(self.image())
        self.assertEqual(self.processor.process([message])[0].metadata["media_status"], "success")

    def test_failed_vision_retries_without_private_error(self):
        self.vision.describe_image.side_effect = [RuntimeError("SECRET PRIVATE FILE"), "ok"]
        message = self.message(media_bytes=self.image())
        first = self.processor.process([message])[0]
        self.assertEqual(first.metadata["media_status"], "temporary")
        self.assertNotIn("SECRET", first.text)
        self.assertEqual(self.processor.process([message])[0].metadata["media_status"], "success")
        self.assertEqual(self.vision.describe_image.call_count, 2)

    def test_corrupt_oversized_and_pixel_limit(self):
        for data in (b"not an image", b"\x89PNG\r\n\x1a\ninvalid"):
            result = self.processor.process([self.message(media_bytes=data)])[0]
            self.assertEqual(result.metadata["media_status"], "unsupported")
        self.processor.MAX_BYTES = 8
        result = self.processor.process([self.message(media_bytes=b"x" * 9)])[0]
        self.assertEqual(result.metadata["media_status"], "unsupported")
        self.processor.MAX_BYTES = 25 * 1024 * 1024
        self.processor.MAX_PIXELS = 10
        result = self.processor.process([self.message(media_bytes=self.image())])[0]
        self.assertEqual(result.metadata["media_status"], "unsupported")
        self.vision.describe_image.assert_not_called()

    def test_v4_key_required_and_unknown_version(self):
        helper = types.SimpleNamespace(is_v4_image=lambda value: value.startswith(b"\x07\x08V1\x08\x07"))
        self.processor._decrypt = helper
        known = self.message(media_bytes=b"\x07\x08V1\x08\x07" + b"0" * 40)
        unknown = self.message(media_bytes=b"\x07\x08V9\x08\x07" + b"0" * 40)
        self.assertEqual(self.processor.process([known])[0].metadata["media_status"], "missing")
        self.assertEqual(self.processor.process([unknown])[0].metadata["media_status"], "unsupported")

    def test_v4_fake_helper_uses_only_scratch_and_respects_key(self):
        data = self.image()
        calls = []
        def decode(key, source, directory, name):
            calls.append(key)
            self.assertTrue(Path(source).is_relative_to(self.processor._scratch))
            target = Path(directory) / (name + ".png")
            target.write_bytes(data)
            return str(target)
        self.processor._decrypt = types.SimpleNamespace(is_v4_image=lambda value: True, decode_dat_v4=decode)
        message = self.message(media_bytes=b"\x07\x08V1\x08\x07" + b"0" * 40, metadata={"xor_key": 77})
        self.assertEqual(self.processor.process([message])[0].metadata["media_status"], "success")
        self.assertEqual(calls, [77])
        self.assertEqual(list(self.processor._scratch.iterdir()), [])

    def test_wechat_transcript_fallback_when_no_model_configured(self):
        message = self.message("voice", metadata={"wechat_transcript": "微信已有转写"})
        with patch.object(self.processor, "_load_whisper", side_effect=AssertionError("no model")):
            result = self.processor.process([message])[0]
        self.assertEqual(result.metadata["media_source"], "wechat")
        self.assertIn("非 Whisper turbo", result.text)
        self.assertTrue(result.metadata["media_degraded"])
        self.assertIn("未提供", result.metadata["media_fallback_reason"])

    def test_turbo_preferred_over_wechat_and_failed_attempt_retries(self):
        model_file = self.root / "synthetic-turbo.pt"
        model_file.write_bytes(b"fake, never deserialized")
        self.processor.whisper_path = str(model_file)
        message = self.message("voice", media_bytes=self.wav(),
                               metadata={"wechat_transcript": "微信旧转写"})
        with patch.object(self.processor, "_transcribe", side_effect=[RuntimeError("PRIVATE"), "turbo新转写"]) as transcribe:
            first = self.processor.process([message])[0]
            second = self.processor.process([message])[0]
        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(first.metadata["media_source"], "wechat")
        self.assertTrue(first.metadata["media_degraded"])
        self.assertIn("非 Whisper turbo", first.text)
        self.assertNotIn("PRIVATE", str(first.metadata))
        self.assertEqual(second.metadata["media_source"], "whisper-turbo-local")
        self.assertFalse(second.metadata["media_degraded"])
        self.assertNotIn("media_fallback_reason", second.metadata)
        self.assertIn("turbo新转写", second.text)
        self.assertNotIn("微信旧转写", second.text)
        self.assertNotIn("media_fallback_reason", message.metadata)

    def test_invalid_turbo_path_falls_back_but_cancellation_does_not(self):
        message = self.message("voice", metadata={"audio_text": "微信已有转写"})
        for path in (str(self.root / "missing.pt"), "C:/synthetic-model.pt",
                     r"\\server\share\model.pt", "//server/share/model.pt", "relative-model.pt"):
            self.processor.whisper_path = path
            result = self.processor.process([message])[0]
            self.assertEqual(result.metadata["media_source"], "wechat")
            self.assertTrue(result.metadata["media_degraded"])
            self.assertTrue(result.metadata["media_fallback_reason"])
        self.processor.cancel()
        result = self.processor.process([message])[0]
        self.assertEqual(result.metadata["media_status"], "temporary")
        self.assertEqual(result.metadata["media_source"], "")

    def test_missing_model_and_alias_do_not_import_whisper(self):
        message = self.message("voice", media_bytes=self.wav())
        with patch("teachmechat.media.importlib.import_module", side_effect=AssertionError("no imports")):
            result = self.processor.process([message])[0]
            self.assertEqual(result.metadata["media_status"], "missing")
            self.processor.whisper_path = str(self.root / "turbo")
            result = self.processor.process([message])[0]
            self.assertEqual(result.metadata["media_status"], "missing")

    def test_fake_silk_transcription_and_dedup(self):
        model_file = self.root / "synthetic-turbo.pt"
        model_file.write_bytes(b"fake checkpoint, never deserialized")
        self.processor.whisper_path = str(model_file)
        model = Mock(device="cpu")
        model.transcribe.return_value = {"text": "合成音频转写"}
        silk = types.SimpleNamespace(decode=Mock(return_value=b"\0\0" * 160))
        message = self.message("voice", media_bytes=b"\x02#!SILK_V3" + b"synthetic")
        numpy = types.SimpleNamespace(frombuffer=Mock(return_value=MagicMock()), float32="float32")
        with patch.dict(sys.modules, {"pysilk": silk, "numpy": numpy}), patch.object(self.processor, "_load_whisper", return_value=model):
            results = self.processor.process([message, message])
        self.assertEqual(results[0].metadata["media_source"], "whisper-turbo-local")
        self.assertEqual(results[0].metadata["media_status"], "success")
        self.assertTrue(results[1].metadata["media_cached"])
        silk.decode.assert_called_once_with(message.media_bytes, to_wav=False, sample_rate=16000)
        self.assertEqual(model.transcribe.call_count, 1)
        self.assertIsNone(model.transcribe.call_args.kwargs["verbose"])
        self.assertFalse(model.transcribe.call_args.kwargs["fp16"])

    def test_model_architecture_verified_with_fake_torch(self):
        good_dims = dict(n_mels=128, n_audio_ctx=1500, n_audio_state=1280,
                         n_audio_head=20, n_audio_layer=32, n_text_ctx=448,
                         n_text_state=1280, n_text_head=20, n_text_layer=4, n_vocab=51866)
        model = Mock()
        model.to.return_value = model
        api = types.SimpleNamespace(Whisper=Mock(return_value=model), ModelDimensions=lambda **kw: kw)
        torch = types.SimpleNamespace(load=Mock(return_value={"dims": good_dims, "model_state_dict": {}}),
                                      cuda=types.SimpleNamespace(is_available=lambda: False))
        identity = (str(self.root / "fake.pt"), 1, 1)
        with patch("teachmechat.media.importlib.import_module", side_effect=lambda name: {"torch": torch, "whisper.model": api}[name]):
            self.processor._load_whisper(identity)
            torch.load.assert_called_once_with(identity[0], map_location="cpu", weights_only=True)
            model.to.assert_called_once_with("cpu")
            model.load_state_dict.assert_called_once_with({}, strict=True)
            self.processor._model = None
            good_dims["n_text_layer"] = 32
            with self.assertRaises(_Unavailable) as error:
                self.processor._load_whisper(identity)
            self.assertIn("无法验证", error.exception.detail)

    def test_missing_optional_dependencies_degrade(self):
        self.processor.whisper_path = str(self.root / "fake.pt")
        Path(self.processor.whisper_path).write_bytes(b"fake")
        message = self.message("voice", media_bytes=b"#!SILK_V3synthetic")
        with patch("teachmechat.media.importlib.import_module", side_effect=ImportError("fake dependency")):
            result = self.processor.process([message])[0]
        self.assertEqual(result.metadata["media_status"], "unsupported")
        self.assertNotIn("fake dependency", result.text)

    def test_bounded_cache_and_model_change_key(self):
        self.processor.CACHE_ENTRIES = 2
        for value in range(4):
            self.processor._cached((value,), lambda: "synthetic")
        self.assertEqual(len(self.processor._cache), 2)
        model = self.root / "fake.pt"
        model.write_bytes(b"first")
        self.processor.whisper_path = str(model)
        before = self.processor._whisper_identity()
        model.write_bytes(b"second version")
        self.assertNotEqual(before, self.processor._whisper_identity())

    def test_constructor_preserves_global_temp_directory(self):
        before = tempfile.tempdir
        with MediaProcessor(self.root / "nested"):
            self.assertEqual(tempfile.tempdir, before)
        self.assertEqual(tempfile.tempdir, before)

    def test_cancel_stops_next_media_and_close_waits_for_active_media(self):
        entered = threading.Event()
        release = threading.Event()
        closed = threading.Event()
        captured = []
        def describe(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            self.assertTrue(self.processor._scratch.exists())
            return "synthetic"
        self.vision.describe_image.side_effect = describe
        message = self.message(media_bytes=self.image())
        worker = threading.Thread(target=lambda: captured.extend(self.processor.process([message, message])))
        def close():
            self.processor.close()
            closed.set()
        closer = threading.Thread(target=close)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.processor.cancel()
            closer.start()
            self.assertFalse(closed.wait(0.05))
        finally:
            release.set()
            worker.join(5)
            if closer.ident is not None:
                closer.join(5)
        self.assertTrue(closed.is_set())
        self.assertEqual(self.vision.describe_image.call_count, 1)
        self.assertEqual(captured[1].metadata["media_status"], "temporary")
        self.assertIn("取消", captured[1].text)
        self.assertFalse(self.processor._scratch.exists())

    def test_disabled_close_and_local_path_enforcement(self):
        self.processor.enabled = False
        result = self.processor.process([self.message(media_bytes=b"fake")])[0]
        self.assertEqual(result.metadata["media_status"], "unsupported")
        text = self.message("text")
        self.assertEqual(self.processor.process([text])[0].text, text.text)
        self.processor.close()
        self.assertFalse(self.processor._scratch.exists())
        with self.assertRaises(TeachMeChatError):
            self.processor.process([])
        # 相对路径与 UNC/网络路径被拒绝；本机绝对路径（任意盘符）是允许的。
        for value in ("relative-media-runtime", r"\\server\share\media", "//server/share/media"):
            with self.subTest(value=value), self.assertRaises(TeachMeChatError):
                MediaProcessor(value)
        for path in (r"\\server\share\model.pt", "//server/share/model.pt", "relative-model.pt"):
            with self.subTest(path=path):
                self.processor.whisper_path = path
                with self.assertRaises(_Unavailable) as error:
                    self.processor._whisper_identity()
                self.assertEqual(error.exception.status, "unsupported")
        if os.name == "nt":
            # C: 盘的本机绝对路径不再被拒绝；只有文件不存在时才是缺失。
            self.processor.whisper_path = "C:/forbidden-model.pt"
            with self.assertRaises(_Unavailable) as error:
                self.processor._whisper_identity()
            self.assertEqual(error.exception.status, "missing")

    def test_local_absolute_runtime_accepted_and_scratch_stays_under_runtime(self):
        nested = self.root / "other-runtime"
        processor = MediaProcessor(nested, self.vision)
        self.addCleanup(processor.close)
        self.assertEqual(processor.runtime_root, nested.resolve())
        self.assertTrue(processor._scratch.is_absolute())
        self.assertTrue(processor._scratch.is_relative_to(processor.runtime_root))
        self.assertEqual(processor._scratch.drive, processor.runtime_root.drive)
        if os.name == "nt":
            # 任意本机盘符（含 C:）都接受；只做校验，不创建目录。
            self.assertEqual(MediaProcessor._local_path("C:/synthetic/media-runtime").drive.upper(), "C:")
        # 可选 TEACHMECHAT_REQUIRE_DRIVE：盘符不符时同样拒绝本机绝对路径。
        required = "Z:" if nested.drive.upper() != "Z:" else "Y:"
        with patch.dict(os.environ, {"TEACHMECHAT_REQUIRE_DRIVE": required}):
            with self.assertRaises(TeachMeChatError):
                MediaProcessor(nested / "enforced")
        self.assertFalse((nested / "enforced").exists())
        self.assertNotIn("TEACHMECHAT_REQUIRE_DRIVE", os.environ)

    def test_c_drive_source_is_read_only_without_actual_c_drive_access(self):
        # Fake only the specified source file. All real scratch operations still
        # run under the local runtime directory, and no actual C-drive file is
        # read or created by this test.
        source = Path("C:/synthetic-only/source.dat")
        original_open = Path.open
        original_stat = Path.stat
        original_is_file = Path.is_file
        data = self.image()
        encrypted = bytes(value ^ 93 for value in data)
        modes = []
        def open_file(path, mode="r", *args, **kwargs):
            if path == source:
                modes.append(mode)
                self.assertEqual(mode, "rb")
                return io.BytesIO(encrypted)
            # 源文件之外只允许本机 runtime 下的绝对路径，绝不写源目录。
            self.assertTrue(Path(path).is_absolute())
            self.assertTrue(Path(path).is_relative_to(self.processor.runtime_root))
            return original_open(path, mode, *args, **kwargs)
        def stat_file(path, *args, **kwargs):
            if path == source:
                return types.SimpleNamespace(st_size=len(encrypted))
            return original_stat(path, *args, **kwargs)
        def is_file(path):
            return True if path == source else original_is_file(path)
        message = self.message(media_path=str(source), metadata={"xor_key": 93})
        with patch.object(Path, "open", open_file), patch.object(Path, "stat", stat_file), patch.object(Path, "is_file", is_file):
            result = self.processor.process([message])[0]
        self.assertEqual(result.metadata["media_status"], "success")
        self.assertEqual(modes, ["rb"])
        # scratch 始终是本机绝对路径，并与 runtime_root 同盘、位于其下。
        self.assertTrue(self.processor._scratch.is_absolute())
        self.assertTrue(self.processor._scratch.is_relative_to(self.processor.runtime_root))
        self.assertEqual(self.processor._scratch.drive, self.processor.runtime_root.drive)
        self.assertEqual(list(self.processor._scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
