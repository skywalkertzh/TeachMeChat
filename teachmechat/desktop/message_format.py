"""Bounded, side-effect-free presentation of chat messages.

All returned strings are plain text, never HTML. UI callers must explicitly use
plain-text widgets and must not enable automatic/external link opening. This
module never reads media, contacts, databases or network resources, and never
modifies the source ChatMessage.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from ..models import ChatMessage


MAX_XML_BYTES = 128 * 1024
MAX_TEXT_CHARS = 8000
MAX_TITLE_CHARS = 140
MAX_DESCRIPTION_CHARS = 220
_TRUNCATED = "内容过长，已截断显示。"
_XML_MARKER = re.compile(
    r"<\s*(?:\?xml\b|!DOCTYPE\b|!ENTITY\b|/?(?:msg|appmsg|image|"
    r"videomsg|voicemsg|voice|emoji|sticker|location|sysmsg)(?=[\s/>]|$))",
    re.IGNORECASE,
)
_FORBIDDEN_XML = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_WECHAT_MEDIA = re.compile(
    r"<(?:img|video)\b[^>]*\b(?:aeskey|cdnthumburl|cdnmidimgurl|cdnbigimgurl|"
    r"cdnvideourl|cdnthumbaeskey|md5|encryver|length|playlength)\s*=",
    re.IGNORECASE,
)
_MEDIA = {
    "image": ("图片", "[图片]"),
    "video": ("视频", "[视频]"),
    "voice": ("语音", "[语音消息]"),
    "sticker": ("表情", "[表情消息]"),
    "location": ("位置", "[位置消息]"),
    "system": ("系统消息", "[系统通知]"),
}
_KIND_ALIASES = {
    "img": "image", "photo": "image", "audio": "voice", "emoji": "sticker",
    "emoticon": "sticker", "shortvideo": "video", "sysmsg": "system",
    "3": "image", "34": "voice", "43": "video", "62": "video",
    "47": "sticker", "48": "location", "10000": "system", "10002": "system",
    "1": "text", "49": "other",
}
_XML_MEDIA = {
    "img": "image", "image": "image", "videomsg": "video", "video": "video",
    "voicemsg": "voice", "voice": "voice", "emoji": "sticker",
    "sticker": "sticker", "location": "location", "sysmsg": "system",
}


@dataclass(frozen=True)
class DisplayMessage:
    kind: str
    title: str
    body: str
    detail: str = ""
    speaker: str = ""
    outgoing: bool = False
    timestamp: int = 0


def _clean(text: str, *, multiline: bool = True) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not multiline:
        text = text.replace("\n", " ").replace("\t", " ")
    text = "".join(
        char for char in text
        if (multiline and char in "\n\t")
        or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )
    return text if multiline else " ".join(text.split())


def _bounded(text: str, limit: int, *, multiline: bool = True) -> tuple[str, bool]:
    # Bound the work even for a very large value consisting mostly of controls.
    prefix = text[:MAX_XML_BYTES]
    clean = _clean(prefix, multiline=multiline)
    truncated = len(text) > len(prefix) or len(clean) > limit
    if truncated:
        clean = clean[:limit - 1] + "…"
    return clean, truncated


def _card_text(text: str, limit: int, *, multiline: bool = True) -> tuple[str, bool]:
    clean, truncated = _bounded(text, limit, multiline=multiline)
    # CDATA and escaped reference content can themselves contain WeChat XML.
    # Never place that payload into a title, description or diagnostic detail.
    if _XML_MARKER.search(clean) or _FORBIDDEN_XML.search(clean) or _WECHAT_MEDIA.search(clean):
        return "[结构化内容已隐藏]", truncated
    return clean.strip(), truncated


def _name(text: str) -> str:
    return _card_text(text, MAX_TITLE_CHARS, multiline=False)[0]


def _is_wxid(text: str) -> bool:
    return text.casefold().startswith("wxid_")


def _speaker(message: ChatMessage, conversation_name: str, conversation_id: str,
             member_names: dict | None) -> tuple[str, bool]:
    metadata = message.metadata or {}
    if metadata.get("outgoing_unknown") or metadata.get("direction_unknown"):
        return "方向未确认", False
    if message.outgoing:
        return "我", True
    sender = _name(message.sender or "")
    conversation = _name(conversation_name or "")
    is_group = conversation_id.endswith("@chatroom") or conversation_name.endswith("@chatroom")
    if is_group:
        mapped = (member_names or {}).get(message.sender, "")
        mapped = _name(mapped) if isinstance(mapped, str) else ""
        if mapped and not _is_wxid(mapped) and not mapped.endswith("@chatroom"):
            return mapped, False
        if sender and not _is_wxid(sender) and not sender.endswith("@chatroom"):
            return sender, False
        if sender:
            # Unlike hash(), this anonymous label is stable across sessions and
            # distinguishes IDs with the same suffix without exposing that ID.
            digest = sha256((message.sender or "").encode("utf-8", errors="replace")).hexdigest()[:6].upper()
            return f"群成员 · {digest}", False
        return "群成员", False
    if not sender or message.sender == conversation_id or _is_wxid(sender):
        if not conversation or _is_wxid(conversation) or conversation.endswith("@chatroom"):
            conversation = "对方"
        return conversation, False
    return sender, False


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1].lower() if isinstance(node.tag, str) else ""


def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in node if _tag(child) == name), None)


def _field(node: ET.Element, name: str) -> str:
    child = _child(node, name)
    return (child.text or "") if child is not None else ""


def _domain(url: str) -> str:
    """Return only a validated hostname, never credentials/path/query/fragment."""
    url = url.strip()
    if not url or len(url) > MAX_XML_BYTES or "\\" in url or _clean(url) != url or any(char.isspace() for char in url):
        return ""
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return ""
        host = parts.hostname.encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError):
        return ""
    if len(host) > 253 or not re.fullmatch(r"[a-z0-9.:-]+", host):
        return ""
    return host


def _xml_candidate(text: str) -> bool:
    # A BOM and leading invisible controls must not turn XML into visible text.
    start = _clean(text[:MAX_XML_BYTES]).lstrip()
    return bool(_XML_MARKER.match(start) or _FORBIDDEN_XML.match(start) or _WECHAT_MEDIA.match(start)
                or (start.startswith("<") and _XML_MARKER.search(start)))


def _media_enrichment(message: ChatMessage, kind: str) -> tuple[str, str] | None:
    metadata = message.metadata or {}
    status = metadata.get("media_status")
    if kind not in {"image", "voice"} or status not in {"success", "missing", "unsupported", "temporary"}:
        return None
    # MediaProcessor appends recognition after the original text (often XML).
    # Only take its latest labelled addition, never the raw media prefix.
    text = message.text or ""
    labels = ("[图片识别", "[Whisper turbo", "[微信已有") if status == "success" else ("[媒体未识别]",)
    markers = [text.rfind(label) for label in labels]
    start = max(markers)
    addition = text[start:] if start >= 0 else ("" if _xml_candidate(text) else text)
    body, truncated = _card_text(addition, MAX_TEXT_CHARS)
    if status == "success":
        source = {
            "vision": "图片识别", "wechat": "微信已有语音转写（非 Whisper turbo）",
            "whisper-turbo-local": "Whisper turbo 本地语音转写",
        }.get(metadata.get("media_source"), "媒体识别（来源未确认）")
        detail = "来源：" + source
        if metadata.get("media_degraded"):
            detail += " · 降级结果，信息可能不完整"
        if metadata.get("media_cached"):
            detail += " · 已缓存"
    else:
        detail = {
            "missing": "媒体未识别：数据或识别服务不可用。",
            "unsupported": "媒体未识别：当前未启用或不支持。",
            "temporary": "媒体处理暂时失败，可重试。",
        }[status]
        if not body:
            explanation, explanation_cut = _card_text(str(metadata.get("media_detail") or ""), MAX_DESCRIPTION_CHARS)
            body = explanation
            truncated = truncated or explanation_cut
    if truncated:
        detail += "\n" + _TRUNCATED
    return body or _MEDIA[kind][1], detail


def format_message(message: ChatMessage, conversation_name: str = "",
                   conversation_id: str = "", member_names: dict | None = None) -> DisplayMessage:
    """Build a display-only summary without mutating or resolving source data.

    Kinds include text, link, file, reply, payment, image, video, voice, sticker,
    location, system and unknown. ``detail`` carries safe source/quote summaries
    and truncation notices only, never parser errors or original XML. Unknown
    direction deliberately overrides the outgoing flag for presentation.
    """
    speaker, outgoing = _speaker(message, conversation_name, conversation_id, member_names)
    kind = _KIND_ALIASES.get(str(message.kind).lower(), str(message.kind).lower())
    text = message.text or ""

    def result(display_kind: str, title: str, body: str, detail: str = "") -> DisplayMessage:
        return DisplayMessage(display_kind, title, body, detail, speaker, outgoing, message.timestamp)

    def placeholder(detail: str = "") -> DisplayMessage:
        display_kind = kind if kind in _MEDIA else "unknown"
        title, body = _MEDIA.get(display_kind, ("结构化消息", "[消息内容暂无法预览]"))
        return result(display_kind, title, body, detail)

    enrichment = _media_enrichment(message, kind)
    if enrichment is not None:
        body, detail = enrichment
        return result(kind, _MEDIA[kind][0], body, detail)

    if (message.metadata or {}).get("content_omitted"):
        return placeholder("原消息内容过大，已省略预览。")

    if not _xml_candidate(text):
        if kind in _MEDIA and kind != "system":
            return placeholder()
        if kind in {"text", "system", ""}:
            body, truncated = _bounded(text, MAX_TEXT_CHARS)
            return result(kind or "text", "系统消息" if kind == "system" else "", body,
                          _TRUNCATED if truncated else "")
        if kind == "file":
            title, truncated = _card_text(text, MAX_TITLE_CHARS, multiline=False)
            return result("file", title or "文件", "[文件消息]", _TRUNCATED if truncated else "")
        body, truncated = _bounded(text, MAX_TEXT_CHARS)
        return result("unknown", "其他消息", body or "[此类消息暂不支持预览]",
                      _TRUNCATED if truncated else "")

    if len(text) > MAX_XML_BYTES or len(text.encode("utf-8", errors="replace")) > MAX_XML_BYTES:
        return placeholder("结构化消息超过 128 KiB，已省略预览。")
    if _FORBIDDEN_XML.search(text):
        return placeholder("结构化消息包含不允许的声明，已隐藏原始内容。")
    try:
        root = ET.fromstring(text.lstrip("\ufeff \t\r\n"))
    except (ET.ParseError, ValueError, UnicodeError):
        return placeholder("结构化消息解析失败，已隐藏原始内容。")

    if kind in _MEDIA:
        return placeholder()
    app = next((node for node in root.iter() if _tag(node) == "appmsg"), None)
    if app is None:
        for node in root.iter():
            media_kind = _XML_MEDIA.get(_tag(node))
            if media_kind:
                title, body = _MEDIA[media_kind]
                return result(media_kind, title, body)
        return placeholder()

    app_type = _field(app, "type").strip()
    if app_type in {"2000", "2001"} or _child(app, "wcpayinfo") is not None:
        return result("payment", "转账消息" if app_type == "2000" else "支付消息",
                      "[支付类消息] 金额与付款状态未在此处确认，请在微信中查看。")

    title, title_cut = _card_text(_field(app, "title"), MAX_TITLE_CHARS, multiline=False)
    description, description_cut = _card_text(_field(app, "des"), MAX_DESCRIPTION_CHARS)
    truncated = title_cut or description_cut
    if app_type == "57":
        reply, reply_cut = _card_text(_field(app, "title"), MAX_DESCRIPTION_CHARS)
        truncated = reply_cut
        reference = _child(app, "refermsg")
        detail = ""
        if reference is not None:
            ref_kind = _KIND_ALIASES.get(_field(reference, "type").strip(), "")
            if ref_kind in _MEDIA:
                quoted = _MEDIA[ref_kind][1]
            else:
                if _field(reference, "type").strip() not in {"", "1"}:
                    quoted = "[引用消息暂无法预览]"
                else:
                    quoted, quote_cut = _card_text(_field(reference, "content"), MAX_DESCRIPTION_CHARS)
                    truncated = truncated or quote_cut
            author = _name(_field(reference, "displayname"))
            if _is_wxid(author):
                author = "群成员" if conversation_id.endswith("@chatroom") else "对方"
            detail = "引用：" + " · ".join(part for part in (author, quoted) if part)
        if truncated:
            detail = "\n".join(part for part in (detail, _TRUNCATED) if part)
        return result("reply", "引用回复", reply or "[引用了一条消息]", detail)

    if app_type == "6":
        return result("file", title or "文件", description or "[文件消息]",
                      _TRUNCATED if truncated else "")

    source_raw = _field(app, "sourcedisplayname") or _field(app, "appname")
    if not source_raw:
        appinfo = _child(root, "appinfo")
        source_raw = _field(appinfo, "appname") if appinfo is not None else ""
    source, source_cut = _card_text(source_raw, MAX_TITLE_CHARS, multiline=False)
    domain = _domain(_field(app, "url"))
    detail = " · ".join(part for part in (source, domain) if part)
    if truncated or source_cut:
        detail = "\n".join(part for part in (detail, _TRUNCATED) if part)
    return result("link" if app_type == "5" else "unknown", title or "分享消息",
                  description or ("[链接分享]" if app_type == "5" else "[分享消息]"), detail)
