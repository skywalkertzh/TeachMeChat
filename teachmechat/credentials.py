"""Current-user credentials and local filesystem safety; no plaintext key files."""

import base64
import ctypes
from ctypes import wintypes
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit

from .models import TeachMeChatError
from .providers import validate_base_url

_CREDENTIAL_ERROR = "无法恢复保存的 API Key：当前 Windows 用户或供应商/地址/配置绑定不匹配，或凭据已损坏。请重新输入或忘记凭据；原配置未更改。"
_DIRECTORY_ERROR = "配置目录或文件不安全：请选择当前用户拥有、非链接的空目录或本程序已标记目录。不会自动提权或覆盖其他内容。"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


@lru_cache(maxsize=1)
def _windows():
    if os.name != "nt":
        raise TeachMeChatError("记住 API Key 仅支持 Windows 当前用户 DPAPI；请使用仅本次会话模式。")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    pointer = ctypes.c_void_p
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, pointer]
    kernel.CreateDirectoryW.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, pointer, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(pointer)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(pointer), ctypes.POINTER(wintypes.DWORD)]
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(pointer), pointer, pointer, pointer, ctypes.POINTER(pointer)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, pointer]
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), pointer, pointer, wintypes.DWORD, ctypes.POINTER(_Blob)]
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), pointer, ctypes.POINTER(_Blob), pointer, pointer, wintypes.DWORD, ctypes.POINTER(_Blob)]
    return kernel, advapi, crypt


def _sid_string(pointer) -> str:
    kernel, advapi, _ = _windows()
    text = ctypes.c_void_p()
    if not advapi.ConvertSidToStringSidW(pointer, ctypes.byref(text)):
        raise TeachMeChatError(_DIRECTORY_ERROR)
    try:
        return ctypes.wstring_at(text)
    finally:
        kernel.LocalFree(text)


def current_owner() -> str:
    if os.name != "nt":
        return str(os.getuid())
    kernel, advapi, _ = _windows()
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise TeachMeChatError(_DIRECTORY_ERROR)
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            raise TeachMeChatError(_DIRECTORY_ERROR)
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise TeachMeChatError(_DIRECTORY_ERROR)
        return _sid_string(ctypes.c_void_p.from_buffer(buffer))
    finally:
        kernel.CloseHandle(token)


def _assert_no_links(path: Path) -> None:
    try:
        for part in (path, *path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise TeachMeChatError(_DIRECTORY_ERROR)
    except OSError:
        raise TeachMeChatError(_DIRECTORY_ERROR) from None


def assert_owned(path: Path) -> None:
    """Reject links/junctions (including parents), hardlinked files and foreign owners."""
    try:
        _assert_no_links(path)
        info = path.stat()
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise TeachMeChatError(_DIRECTORY_ERROR)
        if os.name != "nt":
            if str(info.st_uid) != current_owner():
                raise TeachMeChatError(_DIRECTORY_ERROR)
            return
        kernel, advapi, _ = _windows()
        owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
        result = advapi.GetNamedSecurityInfoW(str(path), 1, 0x00000001, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor))
        try:
            if result or not owner.value or _sid_string(owner) != current_owner():
                raise TeachMeChatError(_DIRECTORY_ERROR)
        finally:
            if descriptor.value:
                kernel.LocalFree(descriptor)
    except OSError:
        raise TeachMeChatError(_DIRECTORY_ERROR) from None


def private_directory(path: Path, *, create: bool) -> None:
    """Create atomically with protected, current-user-only inheritable DACL.

    An existing directory may only be restricted after the caller established it
    is empty. No ownership changes, privilege enablement or UAC are attempted.
    """
    if create:
        _assert_no_links(path.parent)
    if os.name != "nt":
        try:
            if create:
                path.mkdir(mode=0o700)
            else:
                assert_owned(path)
                path.chmod(0o700)
        except OSError:
            raise TeachMeChatError(_DIRECTORY_ERROR) from None
        return
    kernel, advapi, _ = _windows()
    descriptor = ctypes.c_void_p()
    sid = current_owner()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"O:{sid}D:P(A;OICI;FA;;;{sid})", 1, ctypes.byref(descriptor), None):
        raise TeachMeChatError(_DIRECTORY_ERROR)
    try:
        if create:
            class SecurityAttributes(ctypes.Structure):
                _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wintypes.BOOL)]
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            success = kernel.CreateDirectoryW(str(path), ctypes.byref(attributes))
        else:
            assert_owned(path)
            success = advapi.SetFileSecurityW(str(path), 0x00000004 | 0x80000000, descriptor)
        if not success:
            raise TeachMeChatError(_DIRECTORY_ERROR)
    finally:
        kernel.LocalFree(descriptor)
    assert_owned(path)


def credential_binding(provider: str, base_url: str, profile: str) -> bytes:
    if profile not in {"primary", "vision"} or not isinstance(provider, str) or not provider:
        raise TeachMeChatError(_CREDENTIAL_ERROR)
    parts = urlsplit(validate_base_url(base_url))
    host = parts.hostname.lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    # Paths intentionally do not participate: this binding is an origin, not a URL.
    material = ["TeachMeChat.credentials", 1, provider, parts.scheme.lower(), host, port, profile]
    return hashlib.sha256(json.dumps(material, ensure_ascii=True, separators=(",", ":")).encode("ascii")).digest()


def validate_key(key: str) -> None:
    if not isinstance(key, str) or len(key) > 16384 or (key and (not key.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in key))):
        raise TeachMeChatError("API Key 格式无效；凭据内容不会显示。")


def _dpapi(data: bytes, entropy: bytes, *, decrypt: bool) -> bytes:
    kernel, _, crypt = _windows()
    source_buffer = ctypes.create_string_buffer(data)
    entropy_buffer = ctypes.create_string_buffer(entropy)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    extra = _Blob(len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    try:
        if decrypt:
            success = crypt.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(extra), None, None, 0x1, ctypes.byref(output))
        else:
            # CRYPTPROTECT_UI_FORBIDDEN only; never CRYPTPROTECT_LOCAL_MACHINE.
            success = crypt.CryptProtectData(ctypes.byref(source), "TeachMeChat API credential", ctypes.byref(extra), None, None, 0x1, ctypes.byref(output))
        if not success:
            raise TeachMeChatError(_CREDENTIAL_ERROR)
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.memset(source_buffer, 0, len(source_buffer))
        if output.pbData:
            ctypes.memset(output.pbData, 0, output.cbData)
            kernel.LocalFree(output.pbData)


def validate_envelope(envelope: dict) -> None:
    if (not isinstance(envelope, dict) or set(envelope) != {"version", "scheme", "ciphertext"}
            or type(envelope["version"]) is not int or envelope["version"] != 1
            or envelope["scheme"] != "dpapi-current-user"
            or not isinstance(envelope["ciphertext"], str) or not 1 <= len(envelope["ciphertext"]) <= 65536):
        raise TeachMeChatError(_CREDENTIAL_ERROR)
    try:
        if not base64.b64decode(envelope["ciphertext"], validate=True):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise TeachMeChatError(_CREDENTIAL_ERROR) from None


def protect_key(key: str, *, provider: str, base_url: str, profile: str) -> dict:
    validate_key(key)
    if not key:
        raise TeachMeChatError("不能记住空 API Key。")
    encrypted = _dpapi(key.encode("ascii"), credential_binding(provider, base_url, profile), decrypt=False)
    return {"version": 1, "scheme": "dpapi-current-user", "ciphertext": base64.b64encode(encrypted).decode("ascii")}


def unprotect_key(envelope: dict, *, provider: str, base_url: str, profile: str) -> str:
    validate_envelope(envelope)
    try:
        result = _dpapi(base64.b64decode(envelope["ciphertext"], validate=True), credential_binding(provider, base_url, profile), decrypt=True).decode("ascii")
        validate_key(result)
        if not result:
            raise ValueError()
        return result
    except (ValueError, UnicodeError):
        raise TeachMeChatError(_CREDENTIAL_ERROR) from None
