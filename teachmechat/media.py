"""Optional media enrichment, with local-only scratch space and no downloads.

The caller selects the conversation/window. Only supplied messages are processed.
No wxManager/exporter package is imported and no raw media is changed.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
import hashlib
import importlib
import importlib.util
import io
import os
from pathlib import Path, PureWindowsPath
import shutil
import tempfile
import threading
import warnings
import wave

from .models import ChatMessage, TeachMeChatError


class _Unavailable(Exception):
    def __init__(self, status: str, detail: str):
        self.status, self.detail = status, detail


class MediaProcessor:
    """Enrich copies of messages; failures remain visible and retryable.

    metadata inputs: xor_key (0..255), thumbnail_path, wechat_transcript (or
    audio_text). Outputs: media_status, media_source, media_detail,
    media_degraded, media_cached. Statuses are success/missing/unsupported/
    temporary. Recognition text is untrusted message content, not instructions.
    """

    VERSION = "media-v1"
    MAX_BYTES = 25 * 1024 * 1024
    MAX_PIXELS = 20_000_000
    MAX_AUDIO_SECONDS = 300
    CACHE_ENTRIES = 128
    MAX_TEXT = 16_000

    def __init__(self, runtime_root: Path, vision_client=None,
                 whisper_path: str = "", enabled: bool = True):
        root = self._local_path(runtime_root)
        self.runtime_root = root
        (self.runtime_root / "tmp").mkdir(parents=True, exist_ok=True)
        self.vision_client = vision_client
        self.whisper_path = whisper_path
        self.enabled = enabled
        self._cache: OrderedDict[tuple, str] = OrderedDict()
        self._model = None
        self._model_identity = None
        self._closed = False
        self._cancelled = threading.Event()
        self._lock = threading.RLock()
        self._scratch = Path(tempfile.mkdtemp(prefix="media-", dir=self.runtime_root / "tmp"))
        self._decrypt = None

    @staticmethod
    def _local_path(value) -> Path:
        """本机绝对路径校验：拒绝相对路径、UNC/网络路径；可选强制盘符。"""
        message = "模型、缓存和临时目录必须使用本机绝对路径（不支持网络路径）。"
        text = str(value).strip()
        if not text or "\x00" in text or text.startswith(("\\\\", "//")):
            raise TeachMeChatError(message)
        if PureWindowsPath(text).drive.startswith("\\\\"):
            raise TeachMeChatError(message)
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise TeachMeChatError(message)
        path = path.resolve()
        # 解析后复核：符号链接/联接点不能把本机路径变成 UNC 或移除盘符。
        if PureWindowsPath(str(path)).drive.startswith("\\\\") or (os.name == "nt" and not path.drive):
            raise TeachMeChatError(message)
        required = os.environ.get("TEACHMECHAT_REQUIRE_DRIVE", "").strip().upper()
        if required:
            if not required.endswith(":"):
                required += ":"
            if path.drive.upper() != required:
                raise TeachMeChatError(f"模型、缓存和临时目录必须位于 {required} 盘（由 TEACHMECHAT_REQUIRE_DRIVE 强制）。")
        return path

    def cancel(self):
        """Stop between media operations; an active local inference must finish.

        Cancellation is permanent for this processor. The caller should create a
        new processor for a subsequent session. No worker files are deleted here.
        """
        self._cancelled.set()

    def close(self):
        self.cancel()
        # Serialize cleanup with process: never remove an active decoder's files.
        with self._lock:
            self._cache.clear()
            self._model = None
            self._model_identity = None
            shutil.rmtree(self._scratch, ignore_errors=True)
            self._closed = True

    def _check_cancelled(self):
        if self._cancelled.is_set():
            raise _Unavailable("temporary", "媒体识别已取消，未开始后续识别。")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def process(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        with self._lock:
            return self._process(messages)

    def _process(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        if self._closed:
            raise TeachMeChatError("媒体处理器已关闭。")
        results = []
        for original in messages:
            message = replace(original, metadata=dict(original.metadata))
            if message.kind not in {"image", "photo", "voice", "audio"}:
                results.append(message)
                continue
            metadata = message.metadata
            metadata.update(media_cached=False, media_degraded=False, media_source="",
                            media_detail="")
            metadata.pop("media_fallback_reason", None)
            # Clear stale statuses on each attempt, so failures can be retried.
            try:
                self._check_cancelled()
                if not self.enabled:
                    raise _Unavailable("unsupported", "媒体识别已关闭。")
                if message.kind in {"image", "photo"}:
                    text, source, degraded, cached = self._image(message)
                    label = "图片识别（缩略图，信息可能不完整）" if degraded else "图片识别"
                else:
                    text, source, degraded, cached = self._audio(message)
                    label = "微信已有语音转写（非 Whisper turbo）" if source == "wechat" else "Whisper turbo 语音转写"
                metadata.update(media_status="success", media_source=source,
                                media_detail=metadata.get("media_fallback_reason", ""),
                                media_degraded=degraded, media_cached=cached)
                addition = f"[{label}] {text}"
            except _Unavailable as exc:
                metadata.update(media_status=exc.status, media_detail=exc.detail)
                addition = f"[媒体未识别] {exc.detail}"
            except TeachMeChatError:
                metadata.update(media_status="unsupported", media_detail="模型、缓存和临时目录必须使用本机绝对路径（不支持网络路径）。")
                addition = "[媒体未识别] 模型、缓存和临时目录必须使用本机绝对路径（不支持网络路径）。"
            except Exception:
                # Never expose exceptions containing file paths, media, requests or keys.
                metadata.update(media_status="temporary", media_detail="媒体处理暂时失败，可重试。")
                addition = "[媒体未识别] 媒体处理暂时失败，可重试。"
            message.text = f"{message.text}\n{addition}".strip()
            results.append(message)
        return results

    def _read_path(self, value) -> bytes:
        # Source media may live on any local drive; open read-only. Decoded
        # output always goes to our separately validated local scratch space.
        path = Path(value).expanduser()
        try:
            if not path.is_file():
                raise _Unavailable("missing", "原始媒体文件缺失，请提供本地文件。")
            if path.stat().st_size > self.MAX_BYTES:
                raise _Unavailable("unsupported", "媒体文件超出大小限制。")
            with path.open("rb") as stream:
                data = stream.read(self.MAX_BYTES + 1)
        except OSError:
            raise _Unavailable("temporary", "媒体文件暂时无法读取，可重试。") from None
        return self._check_bytes(data)

    def _check_bytes(self, data) -> bytes:
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise _Unavailable("missing", "没有可用的媒体数据。")
        if len(data) > self.MAX_BYTES:
            raise _Unavailable("unsupported", "媒体文件超出大小限制。")
        return bytes(data)

    def _data(self, message):
        if message.media_bytes:
            return self._check_bytes(message.media_bytes)
        if message.media_path:
            return self._read_path(message.media_path)
        raise _Unavailable("missing", "原始媒体文件缺失，请提供本地文件。")

    def _cached(self, key, produce):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key], True
        text = produce()
        if not isinstance(text, str) or not text.strip():
            raise _Unavailable("temporary", "识别服务未返回文字，可重试。")
        text = text.strip()[:self.MAX_TEXT]
        self._cache[key] = text
        while len(self._cache) > self.CACHE_ENTRIES:
            self._cache.popitem(last=False)
        return text, False

    def _image(self, message):
        degraded = False
        try:
            data = self._data(message)
        except _Unavailable as exc:
            if exc.status != "missing" or not message.metadata.get("thumbnail_path"):
                raise
            data = self._read_path(message.metadata["thumbnail_path"])
            degraded = True
        if self.vision_client is None:
            raise _Unavailable("missing", "未配置图片识别服务，图片尚未转文字。")
        key = (self.VERSION, "image", hashlib.sha256(data).digest(),
               str(message.metadata.get("xor_key", "")), id(self.vision_client),
               str(getattr(self.vision_client, "model", "")))

        def describe():
            with tempfile.TemporaryDirectory(prefix="image-", dir=self._scratch) as temp:
                decoded = self._decode_image(data, message.metadata.get("xor_key"), Path(temp))
                clean, mime = self._sanitize_image(decoded)
                # Only sanitized re-encoded pixels leave this process.
                self._check_cancelled()
                return self.vision_client.describe_image(clean, mime)

        text, cached = self._cached(key, describe)
        return text, "vision", degraded, cached

    def _decrypt_helpers(self):
        if self._decrypt is None:
            # Audited standalone file: stdlib, aiofiles, Crypto only. Do not import
            # wxManager.__init__, which configures privacy-sensitive logging.
            source = Path(__file__).resolve().parent.parent / "wxManager" / "decrypt" / "decrypt_dat.py"
            spec = importlib.util.spec_from_file_location("_teachmechat_dat_helpers", source)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except ImportError:
                raise _Unavailable("unsupported", "缺少本地图片解密依赖；未安装任何依赖。") from None
            self._decrypt = module
        return self._decrypt

    def _decode_image(self, data: bytes, xor_key, temp: Path) -> bytes:
        if xor_key is not None and (type(xor_key) is not int or not 0 <= xor_key <= 255):
            raise _Unavailable("unsupported", "图片 XOR 密钥必须为 0 到 255 的整数。")
        if data.startswith(b"\x07\x08"):
            helpers = self._decrypt_helpers()
            if not helpers.is_v4_image(data):
                raise _Unavailable("unsupported", "不支持此微信 4.x 图片加密版本。")
            if xor_key is None:
                raise _Unavailable("missing", "微信 4.x 图片需要提供 XOR 密钥，不能假定为零。")
            if len(data) < 31:
                raise _Unavailable("unsupported", "加密图片数据不完整。")
            source = temp / "input.dat"
            source.write_bytes(data)
            # Only this synchronous helper is used. It has no print/log calls;
            # never call get_decode_code_v4 (scans private directories) or async helpers.
            output = helpers.decode_dat_v4(xor_key, str(source), str(temp), "decoded")
            if not output:
                raise _Unavailable("unsupported", "此图片无法解密；不保证所有 4.x 图片可用。")
            return self._read_path(output)
        signatures = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM", b"II*\0", b"MM\0*", b"RIFF")
        if data.startswith(signatures):
            return data
        if xor_key is None:
            # Legacy WeChat uses a single XOR byte; require agreement of both
            # leading signature bytes. Pillow validates the full result below.
            for header in (b"\xff\xd8", b"\x89P", b"GI"):
                if len(data) >= 2 and data[0] ^ header[0] == data[1] ^ header[1]:
                    xor_key = data[0] ^ header[0]
                    break
        if xor_key is None:
            raise _Unavailable("unsupported", "未知图片格式或不支持的加密方式。")
        decoded = bytes(value ^ xor_key for value in data)
        (temp / "decoded.image").write_bytes(decoded)
        return decoded

    def _sanitize_image(self, data):
        try:
            from PIL import Image, ImageOps
        except ImportError:
            raise _Unavailable("unsupported", "缺少 Pillow，无法安全验证图片；未安装依赖。") from None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in {"JPEG", "PNG", "GIF", "WEBP", "BMP", "TIFF"}:
                        raise ValueError("format")
                    if image.width * image.height > self.MAX_PIXELS:
                        raise ValueError("pixels")
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    image.seek(0)
                    oriented = ImageOps.exif_transpose(image)
                    oriented.thumbnail((2048, 2048))
                    # Fresh image strips EXIF, comments, ICC and other source metadata.
                    rgb = oriented.convert("RGB")
                    clean = Image.new("RGB", rgb.size)
                    clean.paste(rgb)
                    output = io.BytesIO()
                    clean.save(output, format="JPEG", quality=88)
                    return output.getvalue(), "image/jpeg"
        except Exception:
            raise _Unavailable("unsupported", "图片损坏、尺寸过大或格式不可支持。") from None

    def _audio(self, message):
        existing = message.metadata.get("wechat_transcript") or message.metadata.get("audio_text")
        existing = existing.strip()[:self.MAX_TEXT] if isinstance(existing, str) else ""
        try:
            # A configured turbo model takes priority even when WeChat already
            # supplied text. Missing/failed turbo is never cached as a success.
            identity = self._whisper_identity()
            data = self._data(message)
            key = (self.VERSION, "audio", hashlib.sha256(data).digest(), identity)
            text, cached = self._cached(key, lambda: self._transcribe(data, identity))
            return text, "whisper-turbo-local", False, cached
        except Exception as exc:
            # Cancellation must not be hidden by a successful fallback result.
            self._check_cancelled()
            if not existing:
                raise
            reason = exc.detail if isinstance(exc, _Unavailable) else "Whisper turbo 处理暂时失败，可重试。"
            message.metadata["media_fallback_reason"] = reason
            return existing, "wechat", True, False

    def _whisper_identity(self):
        if not self.whisper_path:
            raise _Unavailable("missing", "未提供本地 Whisper turbo 模型；不会下载模型。")
        try:
            path = self._local_path(self.whisper_path)
        except TeachMeChatError:
            raise _Unavailable("unsupported", "Whisper 模型必须是本机绝对路径下的现有文件，不接受模型别名。") from None
        if not path.is_file():
            raise _Unavailable("missing", "本地 Whisper turbo 模型文件不存在；不会下载模型。")
        stat = path.stat()
        return str(path), stat.st_size, stat.st_mtime_ns

    def _load_whisper(self, identity):
        if self._model is not None and self._model_identity == identity:
            return self._model
        try:
            torch = importlib.import_module("torch")
            model_api = importlib.import_module("whisper.model")
        except ImportError:
            raise _Unavailable("unsupported", "缺少本地 Whisper/PyTorch 依赖；未安装依赖。") from None
        try:
            # Avoid whisper.load_model aliases and its pickle-based loader.
            # Older PyTorch without weights_only must degrade, never unsafe fallback.
            checkpoint = torch.load(identity[0], map_location="cpu", weights_only=True)
            dims = checkpoint["dims"]
            expected = {"n_mels": 128, "n_audio_ctx": 1500, "n_audio_state": 1280,
                        "n_audio_head": 20, "n_audio_layer": 32, "n_text_ctx": 448,
                        "n_text_state": 1280, "n_text_head": 20, "n_text_layer": 4,
                        "n_vocab": 51866}
            if any(dims.get(name) != value for name, value in expected.items()):
                raise _Unavailable("unsupported", "无法验证为 large-v3-turbo 架构，未将此模型冒称 turbo。")
            model = model_api.Whisper(model_api.ModelDimensions(**dims))
            model.load_state_dict(checkpoint["model_state_dict"], strict=True)
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = model.to(device)
            model.eval()
        except _Unavailable:
            raise
        except Exception:
            raise _Unavailable("unsupported", "本地 turbo 权重无法安全加载或验证；需要支持 weights_only 的 PyTorch 和兼容权重。") from None
        self._model, self._model_identity = model, identity
        return model

    def _pcm(self, data):
        if data.startswith(b"RIFF"):
            try:
                with wave.open(io.BytesIO(data), "rb") as audio:
                    if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                        raise ValueError("format")
                    if audio.getnframes() > 16000 * self.MAX_AUDIO_SECONDS:
                        raise ValueError("duration")
                    return audio.readframes(audio.getnframes())
            except Exception:
                raise _Unavailable("unsupported", "WAV 必须为 16kHz 单声道 16 位 PCM，且不超过五分钟。") from None
        if not data.startswith((b"#!SILK_V3", b"\x02#!SILK_V3")):
            raise _Unavailable("unsupported", "不支持此语音格式；需要微信 SILK 或 16kHz PCM WAV。")
        try:
            pysilk = importlib.import_module("pysilk")
        except ImportError:
            raise _Unavailable("unsupported", "缺少本地 pysilk 解码依赖；未安装依赖。") from None
        try:
            pcm = pysilk.decode(data, to_wav=False, sample_rate=16000)
        except Exception:
            raise _Unavailable("unsupported", "SILK 语音解码失败或数据损坏。") from None
        return pcm

    def _transcribe(self, data, identity):
        self._check_cancelled()
        pcm = self._pcm(data)
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 32000 * self.MAX_AUDIO_SECONDS:
            raise _Unavailable("unsupported", "语音 PCM 数据无效或时长超过五分钟。")
        try:
            numpy = importlib.import_module("numpy")
        except ImportError:
            raise _Unavailable("unsupported", "缺少本地 NumPy 音频依赖；未安装依赖。") from None
        self._check_cancelled()
        model = self._load_whisper(identity)
        self._check_cancelled()
        audio = numpy.frombuffer(pcm, dtype="<i2").astype(numpy.float32) / 32768.0
        # ndarray avoids ffmpeg and any implicit audio scratch files. verbose=None
        # suppresses both transcript printing and progress bars in openai-whisper.
        result = model.transcribe(audio, fp16=str(model.device).startswith("cuda"), verbose=None)
        return result.get("text", "")
