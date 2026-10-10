import time
import unittest
from unittest.mock import patch

from teachmechat.console import choose


import io
import os
from contextlib import redirect_stdout
from teachmechat.console import panel, display_width, wrap_lines, terminal_theme, show_advice
from teachmechat.models import Advice


class LayoutTests(unittest.TestCase):
    def test_chinese_panels_align_at_narrow_width(self):
        stream = io.StringIO()
        with patch("teachmechat.console.line_width", return_value=32), redirect_stdout(stream):
            panel("聊天态势", "你好，世界！" * 15 + "\nABC")
        lines = stream.getvalue().splitlines()
        self.assertTrue(all(display_width(line) == 32 for line in lines))
        self.assertNotIn("\x1b", stream.getvalue())

    def test_long_reply_is_preserved(self):
        text = "回复文字" * 60
        self.assertEqual("".join(wrap_lines(text, 19)), text)

    def test_advice_sections_and_warning_are_preserved(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            show_advice(Advice(["first", "second", "third"], "事实分析", "健康建议", ["缺失图片"]), False)
        output = stream.getvalue()
        for label in ("first", "second", "third", "ANALYSIS", "WELLBEING", "NOTES", "上一批上下文"):
            self.assertIn(label, output)

    def test_theme_non_tty_is_plain_and_restores_state(self):
        from teachmechat import console
        stream = io.StringIO()
        with redirect_stdout(stream):
            with self.assertRaises(RuntimeError):
                with terminal_theme():
                    console.say("plain")
                    raise RuntimeError("test")
        self.assertEqual(stream.getvalue(), "plain\n")
        self.assertFalse(console._THEME)

    def test_active_theme_restored_even_on_error(self):
        from teachmechat import console
        stream = io.StringIO()
        with redirect_stdout(stream), patch.object(stream, "isatty", return_value=True), patch("teachmechat.console.os.name", "posix"):
            with self.assertRaises(RuntimeError):
                with terminal_theme():
                    console.status("checking")
                    raise RuntimeError("test")
        self.assertIn("\x1b[97;40m", stream.getvalue())
        self.assertTrue(stream.getvalue().endswith("\x1b[0m"))
        self.assertFalse(console._THEME)
        self.assertFalse(console._STATUS)


class MenuTests(unittest.TestCase):
    def test_down_enter_selects_second_without_space(self):
        try:
            from prompt_toolkit.application import create_app_session
            from prompt_toolkit.input import create_pipe_input
            from prompt_toolkit.output import DummyOutput
        except ImportError:
            self.skipTest("prompt_toolkit unavailable")
        with create_pipe_input() as pipe:
            with create_app_session(input=pipe, output=DummyOutput()):
                with patch("sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True):
                    pipe.send_text("\x1b[B\r")
                    selected = choose("synthetic menu", [("one", 1), ("two", 2)])
                    self.assertEqual(selected, 2)
