"""Bounded, side-effect-free message decoding; never imports wxManager."""
from __future__ import annotations

import io
from pathlib import Path
from xml.etree import ElementTree as ET

from ..models import TeachMeChatError

MAX_CONTENT = 8 * 1024 * 1024


def decode_content(content, compressed, version: int) -> str:
    value = content if content not in (None, '', b'') else compressed
    if value is None:
        return ''
    if isinstance(value, str):
        return value[:MAX_CONTENT].replace('\x00', '')
    data = bytes(value)
    if len(data) > MAX_CONTENT:
        raise TeachMeChatError('消息内容超过安全解析大小。')
    is_compressed = value is compressed and bool(compressed)
    if version == 4 and (data.startswith(b'\x28\xb5\x2f\xfd') or is_compressed):
        try:
            import zstandard
        except ImportError:
            raise TeachMeChatError('读取 V4 压缩消息需要 zstandard，请配置已有依赖环境。') from None
        try:
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as reader:
                data = reader.read(MAX_CONTENT + 1)
            if len(data) > MAX_CONTENT:
                raise ValueError('size')
        except Exception:
            raise TeachMeChatError('V4 消息解压失败或内容过大。') from None
    elif version == 3 and is_compressed:
        try:
            import lz4.block
        except ImportError:
            raise TeachMeChatError('读取 V3 压缩消息需要 lz4，请配置已有依赖环境。') from None
        try:
            data = lz4.block.decompress(data, uncompressed_size=min(MAX_CONTENT, max(1, len(data)) << 10))
        except Exception:
            raise TeachMeChatError('V3 消息解压失败。') from None
    return data.decode('utf-8', errors='replace').replace('\x00', '')


def safe_media_path(root: Path | None, value: str) -> str:
    """Only expose files inside the explicitly authorized media root."""
    if root is None or not value or '://' in value:
        return ''
    value = value.replace('\\', '/')
    if value.startswith('wxid_') and '/' in value:
        value = value.split('/', 1)[1]
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate = candidate.resolve()
        candidate.relative_to(root)
        return str(candidate) if candidate.is_file() else ''
    except (OSError, ValueError):
        return ''


def _fields(data: bytes):
    """Minimal bounded protobuf wire reader for existing MessageBytesExtra."""
    pos = 0
    def varint():
        nonlocal pos
        result = 0
        for shift in range(0, 70, 7):
            if pos >= len(data):
                raise ValueError('truncated')
            byte = data[pos]
            pos += 1
            result |= (byte & 127) << shift
            if not byte & 128:
                return result
        raise ValueError('varint')
    while pos < len(data):
        tag = varint()
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            yield field, varint()
        elif wire == 2:
            size = varint()
            if size > len(data) - pos:
                raise ValueError('length')
            value = data[pos:pos + size]
            pos += size
            yield field, value
        elif wire in (1, 5):
            pos += 8 if wire == 1 else 4
            if pos > len(data):
                raise ValueError('fixed')
        else:
            raise ValueError('wire')


def v3_extra(data) -> dict[int, str]:
    result = {}
    if not isinstance(data, bytes) or len(data) > MAX_CONTENT:
        return result
    try:
        for field, value in _fields(data):
            if field == 3 and isinstance(value, bytes):
                child = dict(_fields(value))
                if isinstance(child.get(2), bytes):
                    result[int(child.get(1, 0))] = child[2].decode('utf-8', errors='replace')
    except (ValueError, TypeError):
        pass
    return result


def v4_packed(data) -> dict[str, str]:
    """Wire fields from repository packed_info_data{,_img,_img2}.proto."""
    result = {}
    if not isinstance(data, bytes) or len(data) > MAX_CONTENT:
        return result
    try:
        fields = dict(_fields(data))
        image = fields.get(3)
        if isinstance(image, bytes):
            try:
                filename = dict(_fields(image)).get(4, b'')
            except ValueError:
                filename = b''
            if not filename:
                filename = image  # older V4 stores filename directly at field 3
            if isinstance(filename, bytes):
                decoded = filename.decode('utf-8').strip().strip('"').strip()
                if decoded and not any(ord(char) < 32 for char in decoded):
                    result['filename'] = decoded
        audio = fields.get(5)
        if isinstance(audio, bytes):
            transcript = dict(_fields(audio)).get(2)
            if isinstance(transcript, bytes):
                result['wechat_transcript'] = transcript.decode('utf-8')
    except (ValueError, TypeError, UnicodeError):
        pass
    return result


def parse_media(text: str, kind: str, root: Path | None, extra=None):
    metadata = {}
    media_path = ''
    extra_fields = v3_extra(extra)
    if extra_fields.get(4):
        media_path = safe_media_path(root, extra_fields[4])
    thumbnail = safe_media_path(root, extra_fields.get(3, ''))
    if thumbnail:
        metadata['thumbnail_path'] = thumbnail
    xml = text[text.find('<'):] if '<' in text else ''
    if not xml or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        return media_path, metadata
    try:
        node = ET.fromstring(xml)
    except (ET.ParseError, ValueError):
        return media_path, metadata
    for element in node.iter():
        if element.tag in ('voicetrans', 'transcribe'):
            transcript = element.get('transtext') or element.get('text') or element.text
            if transcript:
                metadata['wechat_transcript'] = transcript
        if element.tag in ('img', 'voicemsg'):
            attrs = element.attrib
            for key in ('md5', 'voicelength', 'length', 'voiceformat'):
                if key in attrs:
                    metadata[key] = attrs[key]
            for key in ('path', 'localpath', 'filepath', 'hdpath'):
                media_path = media_path or safe_media_path(root, attrs.get(key, ''))
            thumb = safe_media_path(root, attrs.get('thumbpath', ''))
            if thumb:
                metadata['thumbnail_path'] = thumb
            try:
                xor_key = int(attrs.get('xor_key', '-1'), 0)
                if 0 <= xor_key <= 255:
                    metadata['xor_key'] = xor_key
            except ValueError:
                pass
    return media_path, metadata
