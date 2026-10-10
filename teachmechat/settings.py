"""Versioned small configuration, opt-in DPAPI keys, and a local runtime pointer.

Constructing Settings or resolving a directory never creates it. Legacy imports
are explicit and read-only; runtime caches/models never move with configuration.
"""

from dataclasses import fields, replace
import json
import math
import os
from pathlib import Path, PureWindowsPath
import tempfile

from .context_options import DEFAULT_CONTEXT_MESSAGES, validate_context_limit
from .credentials import (
    assert_owned, current_owner, private_directory, protect_key, unprotect_key,
    validate_envelope, validate_key,
)
from .models import ProviderConfig, TeachMeChatError
from .providers import validate_base_url

SCHEMA_VERSION = 1
DEFAULT_CONFIG_DIRECTORY = Path(r"C:\TeachMeChat")
POINTER_FILENAME = "config-directory.json"
MARKER_FILENAME = ".teachmechat-config.json"
MAX_CONFIG_BYTES = 256 * 1024
_MAX_POINTER_BYTES = 8192
_OPTIONS = {"vision_enabled", "vision_reuse", "auto_refresh", "whisper_path", "request_budget", "remember_keys", "credential_mode", "context_limit"}
_BOOL_OPTIONS = {"vision_enabled", "vision_reuse", "auto_refresh", "remember_keys"}
_INVALID = "配置格式、版本或字段无效；原文件未更改。请检查配置或选择新的空目录。"
_STORAGE_ERROR = "无法安全读写配置；原配置不会被静默重置。请检查当前用户权限或选择新的空目录。"
_MARKER_ERROR = "配置目录不属于本程序或标记无效；请选择当前用户拥有的空目录，不会覆盖现有内容。"


def _path(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip() or "\x00" in str(value):
        raise TeachMeChatError("配置目录必须是有效的本地绝对路径。")
    path = Path(value)
    if not path.is_absolute() or (os.name == "nt" and (not path.drive or path.drive.startswith("\\\\") or ":" in str(path)[2:])):
        raise TeachMeChatError("配置目录必须是有效的本地绝对路径。")
    if ".." in path.parts:
        raise TeachMeChatError("配置目录不能包含父目录跳转。")
    return path


def _exists(path: Path) -> bool:
    # lexists, unlike exists, does not silently accept a dangling link.
    return os.path.lexists(path)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _constant(_):
    raise ValueError()


def _read_json(path: Path, limit: int = MAX_CONFIG_BYTES) -> dict:
    assert_owned(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError()
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeError, RecursionError):
        raise TeachMeChatError(_INVALID) from None
    except OSError:
        raise TeachMeChatError(_STORAGE_ERROR) from None


def _atomic_json(path: Path, data: dict, limit: int = MAX_CONFIG_BYTES) -> None:
    """Same-directory exclusive temporary file, fsync, atomic replacement.

    Callers only supply public metadata or DPAPI ciphertext. Never serializes a
    ProviderConfig or an in-memory plaintext key directly.
    """
    try:
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        if len(payload) > limit:
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise TeachMeChatError(_INVALID) from None
    temporary = None
    descriptor = None
    try:
        assert_owned(path.parent)
        if _exists(path):
            assert_owned(path)
        descriptor, filename = tempfile.mkstemp(prefix=".teachmechat-", suffix=".tmp", dir=path.parent)
        temporary = Path(filename)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Repeat security checks immediately before the only destructive step.
        assert_owned(path.parent)
        assert_owned(temporary)
        if _exists(path):
            assert_owned(path)
        os.replace(temporary, path)
    except OSError:
        raise TeachMeChatError(_STORAGE_ERROR) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None and _exists(temporary):
            try:
                temporary.unlink()
            except OSError:
                pass


def _text(value, maximum=512, *, empty=True) -> str:
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise TeachMeChatError(_INVALID)
    return value


def _provider(value: dict, *, legacy=False) -> dict:
    if not isinstance(value, dict):
        raise TeachMeChatError(_INVALID)
    whitelist = {item.name for item in fields(ProviderConfig)}
    if set(value) - whitelist:
        raise TeachMeChatError(_INVALID)
    if "api_key" in value and not legacy:
        raise TeachMeChatError("发现不应保存的明文凭据字段；请显式导入旧配置或选择新的空目录。")
    public = {key: entry for key, entry in value.items() if key != "api_key"}
    try:
        config = ProviderConfig(**public)
    except (TypeError, ValueError):
        raise TeachMeChatError(_INVALID) from None
    result = {}
    for item in fields(ProviderConfig):
        name = item.name
        if name == "api_key":
            continue
        entry = getattr(config, name)
        if name == "timeout":
            if isinstance(entry, bool) or not isinstance(entry, (int, float)) or not math.isfinite(entry) or not 0 < entry <= 300:
                raise TeachMeChatError(_INVALID)
        elif name == "thinking_budget":
            if entry is not None and (type(entry) is not int or not 0 <= entry <= 1000000):
                raise TeachMeChatError(_INVALID)
        elif name == "base_url":
            _text(entry, 4096, empty=False)
            validate_base_url(entry)
        elif name in {"provider", "protocol", "structured_mode", "reasoning"}:
            _text(entry, 128, empty=name == "protocol")
        elif name == "model":
            _text(entry, 256)
        else:
            # Dataclass-driven allowlist keeps new non-secret fields instead of
            # silently dropping them. Unknown complex types remain fail-closed.
            default = getattr(ProviderConfig(), name)
            if isinstance(default, str):
                _text(entry, 4096)
            elif default is None:
                if entry is not None:
                    raise TeachMeChatError(_INVALID)
            elif type(entry) is not type(default) or not isinstance(entry, (bool, int, float)):
                raise TeachMeChatError(_INVALID)
            elif isinstance(entry, float) and not math.isfinite(entry):
                raise TeachMeChatError(_INVALID)
        result[name] = entry
    return result


def _config_public(config: ProviderConfig) -> dict:
    if not isinstance(config, ProviderConfig):
        raise TeachMeChatError(_INVALID)
    validate_key(config.api_key)
    return _provider({item.name: getattr(config, item.name) for item in fields(ProviderConfig) if item.name != "api_key"})


def _options(value: dict, *, ignore_unknown=False) -> dict:
    if not isinstance(value, dict) or (not ignore_unknown and set(value) - _OPTIONS):
        raise TeachMeChatError(_INVALID)
    result = {"context_limit": DEFAULT_CONTEXT_MESSAGES}
    for key, entry in value.items():
        if key not in _OPTIONS:
            continue
        if key in _BOOL_OPTIONS:
            if type(entry) is not bool:
                raise TeachMeChatError(_INVALID)
        elif key == "whisper_path":
            _text(entry, 4096)
        elif key == "context_limit":
            entry = validate_context_limit(entry)
        elif key == "request_budget":
            if type(entry) is not int or not 1 <= entry <= 10000:
                raise TeachMeChatError(_INVALID)
        elif key == "credential_mode":
            if not isinstance(entry, str) or entry not in {"session", "public", "remember"}:
                raise TeachMeChatError(_INVALID)
        result[key] = entry
    return result


def _document(data: dict, *, legacy=False) -> dict:
    if legacy and "schema_version" not in data:
        if set(data) - ({"provider", "vision"} | _OPTIONS) or "provider" not in data:
            raise TeachMeChatError(_INVALID)
        result = {"schema_version": SCHEMA_VERSION, "provider": _provider(data["provider"], legacy=True), "credentials": {}}
        if data.get("vision") is not None:
            result["vision"] = _provider(data["vision"], legacy=True)
        result.update(_options({key: value for key, value in data.items() if key in _OPTIONS}))
        result.update(remember_keys=False, credential_mode="public")
        return result
    if (type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION
            or set(data) - ({"schema_version", "provider", "vision", "credentials"} | _OPTIONS)
            or "provider" not in data):
        raise TeachMeChatError(_INVALID)
    result = {"schema_version": SCHEMA_VERSION, "provider": _provider(data["provider"])}
    if data.get("vision") is not None:
        result["vision"] = _provider(data["vision"])
    result.update(_options({key: value for key, value in data.items() if key in _OPTIONS}))
    credentials = data.get("credentials", {})
    if not isinstance(credentials, dict) or set(credentials) - {"primary", "vision"}:
        raise TeachMeChatError(_INVALID)
    if "vision" in credentials and "vision" not in result:
        raise TeachMeChatError(_INVALID)
    # Validate envelopes only when decrypting. Public-only recovery and forget
    # must still work when a ciphertext (not the public JSON) is damaged.
    result["credentials"] = credentials
    return result


def _public_document(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != "credentials"}


class Settings:
    def __init__(self, directory: Path):
        self.directory = _path(directory)
        self.path = self.directory / "settings.json"
        self.marker = self.directory / MARKER_FILENAME

    def _directory(self, *, create=False) -> bool:
        try:
            if not _exists(self.directory):
                if not create:
                    return False
                # The parent is deliberately not created/adopted implicitly.
                private_directory(self.directory, create=True)
            assert_owned(self.directory)
            if not self.directory.is_dir():
                raise TeachMeChatError(_MARKER_ERROR)
            if _exists(self.marker):
                marker = _read_json(self.marker, _MAX_POINTER_BYTES)
                expected = {"application": "TeachMeChat", "schema_version": SCHEMA_VERSION, "owner": current_owner()}
                if marker != expected or type(marker.get("schema_version")) is not int:
                    raise TeachMeChatError(_MARKER_ERROR)
                return True
            if any(self.directory.iterdir()):
                raise TeachMeChatError(_MARKER_ERROR)
            if not create:
                return False
            private_directory(self.directory, create=False)
            _atomic_json(self.marker, {"application": "TeachMeChat", "schema_version": SCHEMA_VERSION, "owner": current_owner()}, _MAX_POINTER_BYTES)
            return True
        except OSError:
            raise TeachMeChatError(_STORAGE_ERROR) from None

    def _load_document(self) -> dict:
        if not self._directory() or not _exists(self.path):
            return {}
        return _document(_read_json(self.path))

    def load(self) -> dict:
        """Return public legacy-shaped settings; never decrypt or return a key."""
        return _public_document(self._load_document())

    def load_profiles(self) -> tuple[ProviderConfig | None, ProviderConfig | None, dict]:
        data = self._load_document()
        if not data:
            return None, None, {}
        primary = ProviderConfig(**data["provider"])
        vision = ProviderConfig(**data["vision"]) if "vision" in data else None
        for profile, config in (("primary", primary), ("vision", vision)):
            if profile in data["credentials"]:
                config.api_key = unprotect_key(data["credentials"][profile], provider=config.provider, base_url=config.base_url, profile=profile)
        options = {key: value for key, value in data.items() if key in _OPTIONS}
        options.setdefault("remember_keys", bool(data["credentials"]))
        options.setdefault("credential_mode", "remember" if data["credentials"] else "public")
        return primary, vision, options

    def _save(self, data: dict, *, verify_credentials=True) -> None:
        # Load before touching directories or temp files. Corruption is not reset.
        existing = self._load_document()
        if verify_credentials:
            for profile, envelope in existing.get("credentials", {}).items():
                old = existing["provider" if profile == "primary" else "vision"]
                unprotect_key(envelope, provider=old["provider"], base_url=old["base_url"], profile=profile)
        self._directory(create=True)
        _atomic_json(self.path, data)

    def save(self, config: ProviderConfig, **options) -> None:
        """Legacy save always strips keys, including optional vision dictionaries."""
        public = _config_public(config)
        vision = options.pop("vision", None)
        if isinstance(vision, dict):
            vision_public = _provider(vision, legacy=True)
            vision = ProviderConfig(**vision_public)
        elif vision is not None and not isinstance(vision, ProviderConfig):
            raise TeachMeChatError(_INVALID)
        self.save_profiles(ProviderConfig(**public), replace(vision, api_key="") if vision is not None else None,
                           remember_keys=False, options=_options(options, ignore_unknown=True))

    def save_profiles(self, primary: ProviderConfig, vision: ProviderConfig | None = None, *,
                      remember_keys: bool = False, options: dict | None = None) -> None:
        if type(remember_keys) is not bool:
            raise TeachMeChatError(_INVALID)
        public = _config_public(primary)
        vision_public = _config_public(vision) if vision is not None else None
        safe_options = _options(options if options is not None else {})
        mode = "remember" if remember_keys else safe_options.get("credential_mode", "public")
        if mode == "remember" and not remember_keys:
            mode = "public"
        safe_options.update(remember_keys=remember_keys, credential_mode=mode)
        data = {"schema_version": SCHEMA_VERSION, "provider": public, **safe_options, "credentials": {}}
        if vision_public is not None:
            data["vision"] = vision_public
        # Encrypt before any file creation; plaintext never enters serialization.
        if remember_keys:
            for profile, config in (("primary", primary), ("vision", vision)):
                if config is not None and config.api_key:
                    data["credentials"][profile] = protect_key(config.api_key, provider=config.provider, base_url=config.base_url, profile=profile)
        self._save(data)

    def clear_credentials(self, profile: str | None = None) -> None:
        """Explicitly forget ciphertext, even when DPAPI can no longer decrypt it."""
        if profile not in {None, "primary", "vision"}:
            raise TeachMeChatError(_INVALID)
        data = self._load_document()
        if not data:
            return
        if profile is None:
            data["credentials"] = {}
        else:
            data["credentials"].pop(profile, None)
        for envelope in data["credentials"].values():
            validate_envelope(envelope)
        data.update(remember_keys=bool(data["credentials"]), credential_mode="remember" if data["credentials"] else "public")
        self._save(data, verify_credentials=False)

    forget_credentials = clear_credentials


def load_legacy_settings(path: Path) -> dict:
    """Explicit, read-only import after UI consent. No scanning, writes or keys.

    The caller must provide the exact legacy settings.json path, not a runtime
    root. Nothing in Settings/config_directory calls this helper automatically.
    """
    return _public_document(_document(_read_json(_path(path)), legacy=True))


def _runtime_path(runtime: Path) -> Path:
    """配置目录指针必须保存在本机运行目录：要求本机绝对路径，拒绝 UNC/网络路径。"""
    message = "配置目录指针必须保存在本机运行目录。"
    text = str(runtime).strip() if isinstance(runtime, (str, Path)) else ""
    if (not text or "\x00" in text or text.startswith(("\\\\", "//"))
            or PureWindowsPath(text).drive.startswith("\\\\") or ".." in Path(text).parts
            or (os.name == "nt" and ":" in text[2:])):
        raise TeachMeChatError(message)
    path = Path(text)
    if not path.is_absolute():
        raise TeachMeChatError(message)
    required = os.environ.get("TEACHMECHAT_REQUIRE_DRIVE", "").strip().upper()
    if required:
        if not required.endswith(":"):
            required += ":"
        if path.drive.upper() != required:
            raise TeachMeChatError(f"配置目录指针必须保存在本机运行目录（{required} 盘，由 TEACHMECHAT_REQUIRE_DRIVE 强制）。")
    return path


def _pointer(data: dict) -> Path:
    if (set(data) != {"schema_version", "directory"} or type(data["schema_version"]) is not int
            or data["schema_version"] != SCHEMA_VERSION or not isinstance(data["directory"], str)):
        raise TeachMeChatError(_INVALID)
    return _path(data["directory"])


def config_directory(runtime: Path, explicit: str | Path | None = None) -> Path:
    """Explicit > non-sensitive runtime pointer > default; never mkdir or migrate."""
    if explicit is not None:
        return _path(explicit)
    runtime = _runtime_path(runtime)
    pointer = runtime / POINTER_FILENAME
    if not _exists(pointer):
        return DEFAULT_CONFIG_DIRECTORY
    assert_owned(runtime)
    return _pointer(_read_json(pointer, _MAX_POINTER_BYTES))


def remember_config_directory(runtime: Path, directory: Path) -> None:
    """Write only a schema and path to the existing local runtime directory."""
    runtime = _runtime_path(runtime)
    directory = _path(directory)
    assert_owned(runtime)
    pointer = runtime / POINTER_FILENAME
    if _exists(pointer):
        _pointer(_read_json(pointer, _MAX_POINTER_BYTES))
    _atomic_json(pointer, {"schema_version": SCHEMA_VERSION, "directory": str(directory)}, _MAX_POINTER_BYTES)
