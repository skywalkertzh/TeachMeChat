"""Synthetic display tests only: no databases, contacts, settings or keys."""
from copy import deepcopy
from dataclasses import asdict
import unittest
from unittest.mock import patch

from teachmechat.desktop.message_format import (
    DisplayMessage,
    MAX_DESCRIPTION_CHARS,
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    MAX_XML_BYTES,
    format_message,
)
from teachmechat.models import ChatMessage


def message(text="合成消息", **kwargs):
    values = {"id": "synthetic", "timestamp": 123456, "sender": "wxid_synthetic", "text": text}
    values.update(kwargs)
    return ChatMessage(**values)


def app_message(body, app_type="5"):
    return f"<msg><appmsg><type>{app_type}</type>{body}</appmsg></msg>"


def displayed(display):
    return "\n".join((display.title, display.body, display.detail, display.speaker))


class MessageFormatTests(unittest.TestCase):
    def test_public_dataclass_defaults(self):
        self.assertEqual(asdict(DisplayMessage("text", "", "内容")), {
            "kind": "text", "title": "", "body": "内容", "detail": "",
            "speaker": "", "outgoing": False, "timestamp": 0,
        })

    def test_share_xml_cdata_ampersand_and_safe_domain(self):
        raw = '<?xml version="1.0"?>' + app_message(
            "<title><![CDATA[合成分享 & 示例]]></title>"
            "<des>第一行 &amp; 第二行\n第三行</des>"
            "<sourcedisplayname>演示来源</sourcedisplayname>"
            "<url>https://user:synthetic-password@example.test/private/path?token=SYNTHETIC_TOKEN&amp;k=1#secret</url>"
        )
        with patch("urllib.request.urlopen") as urlopen, patch("webbrowser.open") as browser_open:
            result = format_message(message(raw))
        self.assertEqual(result.kind, "link")
        self.assertEqual(result.title, "合成分享 & 示例")
        self.assertEqual(result.body, "第一行 & 第二行\n第三行")
        self.assertEqual(result.detail, "演示来源 · example.test")
        self.assertEqual(result.timestamp, 123456)
        for hidden in ("<msg", "<appmsg", "SYNTHETIC_TOKEN", "synthetic-password", "/private", "#secret", "https://"):
            self.assertNotIn(hidden, displayed(result))
        urlopen.assert_not_called()
        browser_open.assert_not_called()

    def test_appmsg_root_and_appname_fallbacks(self):
        cases = (
            ("<appmsg><type>5</type><title>卡片</title><appname>应用名称</appname></appmsg>", "应用名称"),
            ("<msg><appmsg><type>5</type></appmsg><appinfo><appname>外层应用</appname></appinfo></msg>", "外层应用"),
        )
        for raw, source in cases:
            with self.subTest(raw=raw):
                result = format_message(message(raw, kind="other"))
                self.assertEqual(result.kind, "link")
                self.assertEqual(result.detail, source)

    def test_file_card_keeps_filename_not_attachment_payload(self):
        result = format_message(message(app_message(
            "<title>合成资料.txt</title><des>文件说明</des>"
            "<appattach><attachid>SYNTHETIC_ATTACHMENT_TOKEN</attachid><totallen>4096</totallen></appattach>", "6"
        )))
        self.assertEqual(result.kind, "file")
        self.assertEqual(result.title, "合成资料.txt")
        self.assertEqual(result.body, "文件说明")
        self.assertNotIn("SYNTHETIC_ATTACHMENT_TOKEN", displayed(result))

    def test_reply_card_shows_plain_quote(self):
        result = format_message(message(app_message(
            "<title>合成回复\n保留换行</title><refermsg><type>1</type>"
            "<displayname>示例成员</displayname><content>合成引用 &amp; 文字</content>"
            "<svrid>SYNTHETIC_INTERNAL_ID</svrid></refermsg>", "57"
        )))
        self.assertEqual(result.kind, "reply")
        self.assertEqual(result.title, "引用回复")
        self.assertEqual(result.body, "合成回复\n保留换行")
        self.assertEqual(result.detail, "引用：示例成员 · 合成引用 & 文字")
        self.assertNotIn("SYNTHETIC_INTERNAL_ID", displayed(result))

    def test_reply_body_uses_description_limit_not_title_limit(self):
        result = format_message(message(app_message(f'<title>{"合" * 180}</title>', "57")))
        self.assertEqual(len(result.body), 180)
        self.assertEqual(result.detail, "")

    def test_reply_xml_cdata_is_hidden_not_dumped_into_detail(self):
        for quote in (
            "<![CDATA[<msg><appmsg><title>SYNTHETIC_NESTED_SECRET</title></appmsg></msg>]]>",
            "&lt;msg&gt;&lt;img token=\"SYNTHETIC_NESTED_SECRET\"/&gt;&lt;/msg&gt;",
        ):
            with self.subTest(quote=quote):
                result = format_message(message(app_message(
                    f"<title>合成回复</title><refermsg><type>1</type><displayname>wxid_quote</displayname>"
                    f"<content>{quote}</content></refermsg>", "57"
                )))
                self.assertEqual(result.kind, "reply")
                self.assertNotIn("<msg", result.detail)
                self.assertNotIn("SYNTHETIC_NESTED_SECRET", result.detail)
                self.assertNotIn("wxid_", result.detail)
                self.assertIn("结构化内容已隐藏", result.detail)

    def test_reply_media_and_missing_reference(self):
        result = format_message(message(app_message(
            "<title>合成回复</title><refermsg><type>3</type><content>opaque-synthetic-image-data</content></refermsg>", "57"
        )))
        self.assertIn("[图片]", result.detail)
        self.assertNotIn("opaque", result.detail)
        missing = format_message(message(app_message("", "57")))
        self.assertEqual(missing.kind, "reply")
        self.assertEqual(missing.detail, "")

    def test_payment_never_guesses_amount_or_paid_state(self):
        for app_type in ("2000", "2001"):
            with self.subTest(app_type=app_type):
                result = format_message(message(app_message(
                    "<title>已支付 SYNTHETIC_AMOUNT</title><des>已收款 SYNTHETIC_STATE</des>"
                    "<wcpayinfo><feedesc>SYNTHETIC_AMOUNT</feedesc><paysubtype>3</paysubtype>"
                    "<transcationid>SYNTHETIC_TRANSACTION_ID</transcationid></wcpayinfo>", app_type
                )))
                self.assertEqual(result.kind, "payment")
                self.assertIn("未在此处确认", result.body)
                for hidden in ("SYNTHETIC_AMOUNT", "SYNTHETIC_STATE", "SYNTHETIC_TRANSACTION_ID", "已支付", "已收款"):
                    self.assertNotIn(hidden, displayed(result))

    def test_payment_metadata_with_unknown_type_remains_conservative(self):
        result = format_message(message(app_message(
            "<title>SYNTHETIC_UNCONFIRMED_STATE</title><wcpayinfo><feedesc>SYNTHETIC_UNCONFIRMED_AMOUNT</feedesc></wcpayinfo>",
            "9999",
        )))
        self.assertEqual(result.kind, "payment")
        self.assertNotIn("SYNTHETIC_UNCONFIRMED", displayed(result))

    def test_unknown_non_text_reference_never_dumps_payload(self):
        result = format_message(message(app_message(
            "<title>合成回复</title><refermsg><type>49</type><content>SYNTHETIC_OPAQUE_REFERENCE</content></refermsg>", "57"
        )))
        self.assertNotIn("SYNTHETIC_OPAQUE_REFERENCE", result.detail)
        self.assertIn("引用消息暂无法预览", result.detail)

    def test_media_kinds_have_friendly_placeholders(self):
        for kind, title in (("image", "图片"), ("video", "视频"), ("voice", "语音"),
                            ("sticker", "表情"), ("location", "位置"), ("system", "系统消息")):
            with self.subTest(kind=kind):
                result = format_message(message('<msg><opaque secret="SYNTHETIC_MEDIA_TOKEN"/></msg>', kind=kind))
                self.assertEqual(result.kind, kind)
                self.assertEqual(result.title, title)
                self.assertNotIn("SYNTHETIC_MEDIA_TOKEN", displayed(result))
                self.assertNotIn("<msg", displayed(result))

    def test_media_xml_auto_detected_for_text_and_other_kinds(self):
        tags = {"img": "image", "videomsg": "video", "voicemsg": "voice",
                "emoji": "sticker", "location": "location", "sysmsg": "system"}
        for tag, expected in tags.items():
            for kind in ("text", "other"):
                with self.subTest(tag=tag, kind=kind):
                    for raw in (f'<{tag} md5="SYNTHETIC_MEDIA_TOKEN"/>', f'<msg><{tag} token="SYNTHETIC_MEDIA_TOKEN"/></msg>'):
                        result = format_message(message(raw, kind=kind))
                        self.assertEqual(result.kind, expected)
                        self.assertNotIn("SYNTHETIC_MEDIA_TOKEN", displayed(result))

    def test_known_non_xml_media_remains_a_placeholder(self):
        for kind in ("image", "video", "voice", "sticker", "location"):
            with self.subTest(kind=kind):
                result = format_message(message("SYNTHETIC_OPAQUE_MEDIA_DATA", kind=kind))
                self.assertEqual(result.kind, kind)
                self.assertNotIn("SYNTHETIC_OPAQUE_MEDIA_DATA", displayed(result))

    def test_enriched_media_preserves_only_latest_recognition_with_source(self):
        cases = (
            ("image", "vision", "[图片识别] 合成图片说明", "图片识别"),
            ("voice", "whisper-turbo-local", "[Whisper turbo 语音转写] 合成转写\n第二行", "Whisper turbo 本地"),
            ("voice", "wechat", "[微信已有语音转写（非 Whisper turbo）] 合成转写", "非 Whisper turbo"),
        )
        for kind, source, addition, expected_source in cases:
            for prefix in ("[媒体消息]", '<msg><opaque token="SYNTHETIC_RAW_MEDIA_SECRET"/></msg>'):
                with self.subTest(kind=kind, source=source, prefix=prefix):
                    item = message(prefix + "\n" + addition, kind=kind,
                                   metadata={"media_status": "success", "media_source": source})
                    original = deepcopy(item)
                    result = format_message(item)
                    self.assertEqual(result.kind, kind)
                    self.assertEqual(result.body, addition)
                    self.assertIn(expected_source, result.detail)
                    self.assertIn("来源", result.detail)
                    self.assertNotIn("SYNTHETIC_RAW_MEDIA_SECRET", displayed(result))
                    self.assertNotIn("<msg", displayed(result))
                    self.assertEqual(item, original)

    def test_media_enrichment_degraded_and_cached_are_explicit(self):
        result = format_message(message("[图片识别（缩略图，信息可能不完整）] 合成描述", kind="photo", metadata={
            "media_status": "success", "media_source": "vision", "media_degraded": True, "media_cached": True,
        }))
        self.assertEqual(result.kind, "image")
        self.assertIn("合成描述", result.body)
        self.assertIn("降级", result.detail)
        self.assertIn("已缓存", result.detail)

    def test_media_failure_preserves_safe_failure_addition_without_raw_xml(self):
        for status in ("missing", "unsupported", "temporary"):
            with self.subTest(status=status):
                result = format_message(message(
                    '<msg><img md5="SYNTHETIC_RAW_MEDIA_SECRET"/></msg>\n[媒体未识别] 合成失败原因，可重试。',
                    kind="image", metadata={"media_status": status, "media_detail": "合成失败原因，可重试。"},
                ))
                self.assertIn("合成失败原因", result.body)
                self.assertIn("媒体", result.detail)
                self.assertNotIn("<msg", displayed(result))
                self.assertNotIn("SYNTHETIC_RAW_MEDIA_SECRET", displayed(result))

    def test_enrichment_is_bounded_and_nested_xml_is_hidden(self):
        huge = format_message(message("[图片识别] " + "合成" * 6000, kind="image", metadata={"media_status": "success", "media_source": "vision"}))
        self.assertEqual(len(huge.body), MAX_TEXT_CHARS)
        self.assertIn("截断", huge.detail)
        nested = format_message(message('[图片识别] <msg><opaque token="SYNTHETIC_NESTED_RECOGNITION"/></msg>', kind="image",
                                        metadata={"media_status": "success", "media_source": "vision"}))
        self.assertNotIn("SYNTHETIC_NESTED_RECOGNITION", displayed(nested))
        missing_marker = format_message(message('<msg><img md5="SYNTHETIC_RAW_MEDIA_SECRET"/></msg>', kind="image",
                                                metadata={"media_status": "missing", "media_detail": "原始媒体缺失。"}))
        self.assertEqual(missing_marker.body, "原始媒体缺失。")
        self.assertNotIn("SYNTHETIC_RAW_MEDIA_SECRET", displayed(missing_marker))

    def test_non_xml_other_keeps_plain_notice_and_file_keeps_title(self):
        result = format_message(message("合成系统拍一拍通知\n第二行", kind="other"))
        self.assertEqual(result.title, "其他消息")
        self.assertEqual(result.body, "合成系统拍一拍通知\n第二行")
        huge = format_message(message("合成" * MAX_TEXT_CHARS, kind="other"))
        self.assertEqual(len(huge.body), MAX_TEXT_CHARS)
        self.assertIn("截断", huge.detail)
        attachment = format_message(message("合成文件.txt", kind="file"))
        self.assertEqual(attachment.kind, "file")
        self.assertEqual(attachment.title, "合成文件.txt")
        self.assertEqual(attachment.body, "[文件消息]")

    def test_system_plain_text_is_preserved(self):
        result = format_message(message("合成系统通知\n下一行", kind="system"))
        self.assertEqual(result.body, "合成系统通知\n下一行")
        self.assertEqual(result.kind, "system")

    def test_plain_text_html_and_wxid_are_not_interpreted_or_replaced(self):
        text = '第一行\n<b>合成文字</b>\n<script>alert("synthetic")</script>\nwxid_in_body\n<img src="https://example.test/test.png">'
        result = format_message(message(text), conversation_name="演示联系人")
        self.assertEqual(result.kind, "text")
        self.assertEqual(result.body, text)
        self.assertEqual(result.speaker, "演示联系人")
        self.assertEqual(result.detail, "")

    def test_html_at_start_remains_plain_text(self):
        for text in ('<img src="https://example.test/synthetic.png">',
                     '<video src="https://example.test/synthetic.mp4"></video>',
                     '<b>合成文本 &amp; 原样保留</b>', '<script>synthetic()</script>'):
            with self.subTest(text=text):
                result = format_message(message(text))
                self.assertEqual(result.kind, "text")
                self.assertEqual(result.body, text)

    def test_newlines_and_tabs_are_preserved_controls_and_bidi_are_removed(self):
        result = format_message(message("甲\r\n乙\r丙\t丁\x00\x1b\x7f\x85\u202e\u2066\u2069\ud800"))
        self.assertEqual(result.body, "甲\n乙\n丙\t丁")

    def test_control_filter_applies_to_card_fields_and_names(self):
        result = format_message(message(app_message(
            "<title>合成\u202e标题</title><des>说明\u2066正文</des><sourcedisplayname>来\u200f源</sourcedisplayname>"
        ), sender="安全\u202e名称"))
        self.assertEqual(result.title, "合成标题")
        self.assertEqual(result.body, "说明正文")
        self.assertEqual(result.detail, "来源")
        self.assertEqual(result.speaker, "安全名称")

    def test_long_plain_text_is_bounded_and_marked(self):
        original = "合成正文\n" * 10000
        result = format_message(message(original))
        self.assertEqual(len(result.body), MAX_TEXT_CHARS)
        self.assertTrue(result.body.endswith("…"))
        self.assertIn("截断", result.detail)
        exact = format_message(message("甲" * MAX_TEXT_CHARS))
        self.assertEqual(exact.detail, "")
        self.assertEqual(len(exact.body), MAX_TEXT_CHARS)

    def test_long_card_title_description_and_source_are_bounded(self):
        result = format_message(message(app_message(
            f'<title>{"标题" * 1000}</title><des>{"说明" * 1000}</des>'
            f'<sourcedisplayname>{"来源" * 1000}</sourcedisplayname>'
        )))
        self.assertEqual(len(result.title), MAX_TITLE_CHARS)
        self.assertEqual(len(result.body), MAX_DESCRIPTION_CHARS)
        self.assertIn("截断", result.detail)
        self.assertLess(len(result.detail), MAX_TITLE_CHARS + 50)

    def test_huge_xml_is_rejected_before_parsing_by_utf8_byte_length(self):
        for text in ("x" * MAX_XML_BYTES, "汉" * (MAX_XML_BYTES // 3)):
            raw = app_message(f"<title>{text}</title>")
            with self.subTest(length=len(raw)), patch("teachmechat.desktop.message_format.ET.fromstring") as parser:
                result = format_message(message(raw))
            parser.assert_not_called()
            self.assertIn("128 KiB", result.detail)
            self.assertLess(len(displayed(result)), 150)
            self.assertNotIn("<appmsg", displayed(result))

    def test_malformed_xml_is_safe_and_does_not_reveal_parser_input(self):
        for raw in ('<msg><appmsg><title>SYNTHETIC_BROKEN_PAYLOAD',
                    '<?xml version="1.0"?><msg>SYNTHETIC_BROKEN_PAYLOAD&</msg>',
                    '<msg><title>SYNTHETIC_BROKEN_PAYLOAD</msg>',
                    '<msg>SYNTHETIC_BROKEN_PAYLOAD\x00</msg>',
                    '<msg>&unresolved;</msg>', '<msg'):
            with self.subTest(raw=raw):
                result = format_message(message(raw))
                self.assertEqual(result.kind, "unknown")
                self.assertIn("解析失败", result.detail)
                self.assertNotIn("SYNTHETIC_BROKEN_PAYLOAD", displayed(result))
                self.assertNotIn("<msg", displayed(result))

    def test_doctype_and_entities_are_rejected_before_elementtree(self):
        values = (
            '<!DOCTYPE msg [<!ENTITY e "SYNTHETIC_ENTITY_SECRET">]><msg>&e;</msg>',
            '<?xml version="1.0"?><!DOCTYPE msg SYSTEM "file:///synthetic-missing-file"><msg/>',
            '<!ENTITY injected SYSTEM "https://example.test/synthetic-secret"><msg/>',
            '<!doctype msg><msg/>',
            '<msg><![CDATA[<!ENTITY e "SYNTHETIC_ENTITY_SECRET">]]></msg>',
        )
        for raw in values:
            with self.subTest(raw=raw), patch("teachmechat.desktop.message_format.ET.fromstring") as parser:
                result = format_message(message(raw))
            parser.assert_not_called()
            self.assertIn("不允许", result.detail)
            self.assertNotIn("SYNTHETIC_ENTITY_SECRET", displayed(result))
            self.assertNotIn("file://", displayed(result))
            self.assertNotIn("<!", displayed(result))

    def test_unknown_xml_does_not_expose_attributes_or_raw_payload(self):
        for raw in ('<msg><opaque token="SYNTHETIC_UNKNOWN_SECRET"/></msg>',
                    '<?xml version="1.0"?><unknown>SYNTHETIC_UNKNOWN_SECRET</unknown>'):
            result = format_message(message(raw))
            self.assertEqual(result.kind, "unknown")
            self.assertNotIn("SYNTHETIC_UNKNOWN_SECRET", displayed(result))
        app = format_message(message(app_message("<title>未知分享</title><des>合成摘要</des>", "9876")))
        self.assertEqual(app.kind, "unknown")
        self.assertEqual(app.title, "未知分享")
        self.assertEqual(app.body, "合成摘要")

    def test_xml_with_bom_whitespace_or_comment_is_not_rendered_raw(self):
        for prefix in ("\ufeff  \n", " " * 2048, "<!--synthetic-->", "\u202e", "\x00"):
            with self.subTest(prefix=repr(prefix[:20])):
                result = format_message(message(prefix + app_message("<title>合成分享</title>")))
                self.assertNotIn("<msg", displayed(result))
                self.assertNotIn("<appmsg", displayed(result))

    def test_url_domain_rejects_non_web_schemes_and_malformed_hosts(self):
        for url in ("javascript:synthetic()", "file:///synthetic/file", "data:text/plain,synthetic",
                    "https://[invalid", "https://example.test\\@evil.test/path", "https://bad%2fhost.test/",
                    "https://exa\u202emple.test/", "https://example.test/a b"):
            with self.subTest(url=url):
                result = format_message(message(app_message(f"<url>{url}</url>")))
                self.assertEqual(result.detail, "")

    def test_url_domain_is_hostname_only(self):
        for url, host in (("https://Example.TEST:8443/path?token=synthetic#fragment", "example.test"),
                          ("https://[2001:db8::1]:443/path", "2001:db8::1"),
                          ("https://例子.test/", "xn--fsqu00a.test")):
            with self.subTest(url=url):
                result = format_message(message(app_message(f"<url>{url}</url>")))
                self.assertEqual(result.detail, host)

    def test_incoming_one_to_one_name_mapping_and_safe_display_names(self):
        cases = (
            ("contact-key", "contact-key", "演示联系人", "演示联系人"),
            ("wxid_example", "contact-key", "演示联系人", "演示联系人"),
            ("wxid_example", "contact-key", "", "对方"),
            ("wxid_example", "contact-key", "wxid_unreadable", "对方"),
            ("显示昵称", "contact-key", "演示联系人", "显示昵称"),
            ("", "contact-key", "", "对方"),
        )
        for sender, conversation_id, name, expected in cases:
            with self.subTest(sender=sender, name=name):
                result = format_message(message(sender=sender), conversation_name=name, conversation_id=conversation_id)
                self.assertEqual(result.speaker, expected)
                self.assertFalse(result.outgoing)

    def test_outgoing_and_unknown_direction_precedence(self):
        self.assertEqual(format_message(message(outgoing=True)).speaker, "我")
        self.assertTrue(format_message(message(outgoing=True)).outgoing)
        for flag in ("outgoing_unknown", "direction_unknown"):
            for outgoing in (False, True):
                with self.subTest(flag=flag, outgoing=outgoing):
                    result = format_message(message(outgoing=outgoing, metadata={flag: True}), "演示联系人", "wxid_synthetic")
                    self.assertEqual(result.speaker, "方向未确认")
                    self.assertFalse(result.outgoing)

    def test_group_members_are_distinct_stable_anonymous_not_group_name(self):
        names = []
        for sender in ("wxid_first_same", "wxid_second_same"):
            item = message(sender=sender)
            first = format_message(item, "合成讨论群", "synthetic@chatroom")
            second = format_message(item, "合成讨论群", "synthetic@chatroom")
            self.assertEqual(first.speaker, second.speaker)
            self.assertRegex(first.speaker, r"^群成员 · [0-9A-F]{6}$")
            self.assertNotIn(sender, first.speaker)
            self.assertNotEqual(first.speaker, "合成讨论群")
            names.append(first.speaker)
        self.assertNotEqual(names[0], names[1])

    def test_group_member_mapping_and_existing_displayname_are_preserved(self):
        members = {"wxid_first": "合成成员甲"}
        mapped = format_message(message(sender="wxid_first"), "合成讨论群", "synthetic@chatroom", members)
        self.assertEqual(mapped.speaker, "合成成员甲")
        existing = format_message(message(sender="合成成员乙"), "合成讨论群", "synthetic@chatroom", members)
        self.assertEqual(existing.speaker, "合成成员乙")
        group_by_name = format_message(message(sender="wxid_missing"), "synthetic@chatroom", "", members)
        self.assertTrue(group_by_name.speaker.startswith("群成员 · "))
        self.assertEqual(members, {"wxid_first": "合成成员甲"})

    def test_source_omission_metadata_shows_bounded_notice(self):
        result = format_message(message("", metadata={"content_omitted": True}))
        self.assertIn("已省略", result.detail)
        self.assertNotEqual(result.body, "")

    def test_input_message_and_metadata_are_not_mutated(self):
        item = message(app_message("<title>合成标题</title>"), metadata={"nested": {"test": [1, 2, 3]}})
        before = deepcopy(item)
        format_message(item, "合成联系人", "wxid_synthetic", {"wxid_synthetic": "合成昵称"})
        self.assertEqual(item, before)


if __name__ == "__main__":
    unittest.main()
