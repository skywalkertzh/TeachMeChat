import getpass
import os
import re
import shutil
import sys
from contextlib import contextmanager

_THEME = False
_STATUS = False
ANSI_WHITE_BLACK = "\x1b[97;40m"


def safe_text(value: object) -> str:
    text = str(value)
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "".join(c for c in text if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) < 160))


def display_width(text):
    from wcwidth import wcswidth
    return max(0, wcswidth(text))


def line_width():
    return max(12, min(88, shutil.get_terminal_size((88, 24)).columns - 2))


def wrap_lines(value, width):
    text = safe_text(value).expandtabs(4)
    lines = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            if current and display_width(current + char) > width:
                lines.append(current)
                current = ""
            current += char
        lines.append(current)
    return lines


def _clear_status():
    global _STATUS
    if _STATUS:
        sys.stdout.write("\r\x1b[2K")
        _STATUS = False


@contextmanager
def terminal_theme():
    """Keep styling process-local and restore console attributes on exit."""
    global _THEME
    previous = _THEME
    restore = None
    active = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    if active and os.name == "nt":
        import ctypes
        from ctypes import wintypes
        class Coord(ctypes.Structure):
            _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]
        class SmallRect(ctypes.Structure):
            _fields_ = [(name, wintypes.SHORT) for name in ("Left", "Top", "Right", "Bottom")]
        class BufferInfo(ctypes.Structure):
            _fields_ = [("size", Coord), ("cursor", Coord),
                        ("attributes", wintypes.WORD), ("window", SmallRect),
                        ("maximum", Coord)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.GetConsoleScreenBufferInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(BufferInfo)]
        kernel.SetConsoleTextAttribute.argtypes = [wintypes.HANDLE, wintypes.WORD]
        handle = kernel.GetStdHandle(-11)
        mode = wintypes.DWORD()
        info = BufferInfo()
        active = bool(kernel.GetConsoleMode(handle, ctypes.byref(mode))
                      and kernel.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)))
        if active:
            kernel.SetConsoleTextAttribute(handle, 15)
            active = bool(kernel.SetConsoleMode(handle, mode.value | 4))
            def restore():
                kernel.SetConsoleTextAttribute(handle, info.attributes)
                kernel.SetConsoleMode(handle, mode.value)
    try:
        _THEME = bool(active)
        if _THEME:
            sys.stdout.write(ANSI_WHITE_BLACK + "\x1b[0J")
            sys.stdout.flush()
        yield
    finally:
        _clear_status()
        if _THEME:
            sys.stdout.write("\x1b[0m")
            sys.stdout.flush()
        if restore is not None:
            restore()
        _THEME = previous


def say(value=""):
    _clear_status()
    text = safe_text(value)
    if _THEME:
        text = ANSI_WHITE_BLACK + text.replace("\n", "\x1b[K\n" + ANSI_WHITE_BLACK) + "\x1b[K"
    print(text, flush=True)


def status(value):
    global _STATUS
    text = wrap_lines(value, line_width())[0]
    if _THEME:
        sys.stdout.write("\r" + ANSI_WHITE_BLACK + "\x1b[2K" + text)
        sys.stdout.flush()
        _STATUS = True
    else:
        say(value)


def panel(title, body):
    width = line_width()
    inner = width - 4
    border = "+" + "-" * (width - 2) + "+"
    say(border)
    for content in (title, "", body):
        for line in wrap_lines(content, inner):
            say("| " + line + " " * max(0, inner - display_width(line)) + " |")
    say(border)


def show_banner(runtime):
    say()
    art = " .-----------------.\n |  TeachMeChat    |\n '------------.----'\n              '"
    if line_width() >= 30:
        say(art)
    panel("TEACH ME CHAT  /  交我聊", "聊天补全 · 更从容地表达\n\n只生成草稿，不自动发送。\n应用数据与缓存在项目运行目录。")
    say("  01 配置服务   /   02 选择聊天   /   03 获取建议")
    say()
    for line in wrap_lines(f"运行目录：{runtime}", line_width() - 2):
        say("  " + line)
    say()


def ask(label: str, default: str = "", secret: bool = False) -> str:
    hint = f" [{default}]" if default and not secret else ""
    _clear_status()
    say()
    for line in wrap_lines(label + hint, line_width() - 2):
        say("  " + line)
    prompt = "  > "
    try:
        value = getpass.getpass(prompt) if secret else input(prompt)
    except EOFError:
        raise KeyboardInterrupt from None
    return value.strip() or default


def confirm(label: str, default: bool = False) -> bool:
    answer = ask(label + (" (Y/n)" if default else " (y/N)"), "y" if default else "n")
    return answer.lower() in {"y", "yes", "是"}


def choose(title: str, options: list[tuple[str, object]]):
    if not options:
        raise ValueError("没有可选项目")
    _clear_status()
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ImportError
        from prompt_toolkit import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, HSplit
        from prompt_toolkit.styles import Style
        from prompt_toolkit.widgets import Frame, RadioList, Label, Box
        items = RadioList([(i, safe_text(label)) for i, (label, _) in enumerate(options)])
        bindings = KeyBindings()

        @bindings.add("enter", eager=True)
        def accept(event):
            event.app.exit(result=items.values[items._selected_index][0])

        @bindings.add("escape", eager=True)
        @bindings.add("c-c", eager=True)
        def cancel(event):
            event.app.exit(result=None)

        style = Style.from_dict({
            "": "bg:#000000 #ffffff",
            "frame.border": "bg:#000000 #ffffff",
            "frame.label": "bg:#000000 #ffffff bold",
            "radio-list": "bg:#000000 #ffffff",
            "radio-selected": "bg:#000000 #ffffff bold underline",
            "radio-checked": "bg:#000000 #ffffff",
            "label": "bg:#000000 #ffffff",
        })
        content = HSplit([Box(items, padding=1), Label("  [Up/Down] 选择   [Enter] 确认   [Esc] 返回")])
        application = Application(layout=Layout(Frame(content, title=safe_text(title))),
                                  key_bindings=bindings, full_screen=False,
                                  style=style, include_default_pygments_style=False)
        result = application.run()
        if result is None:
            raise KeyboardInterrupt
        return options[result][1]
    except ImportError:
        panel(title, "\n".join(f"[{i}] {label}" for i, (label, _) in enumerate(options, 1)))
        while True:
            value = ask("输入编号", "1")
            if value.isdigit() and 1 <= int(value) <= len(options):
                return options[int(value) - 1][1]


def show_advice(advice, current: bool = True):
    say("\n")
    panel("CHAT COMPLETION  /  聊天补全", "三个表达方向，选择适合你的那一个。\n回复均为草稿，请自行检查；不会自动发送。")
    if not current:
        say()
        panel("[!] 上下文已更新", "分析期间出现更新，此结果对应上一批上下文。")
    for i, reply in enumerate(advice.replies, 1):
        say()
        panel(f"0{i}  /  备选回复", reply)
    say()
    panel("ANALYSIS  /  聊天态势", advice.analysis)
    say()
    panel("WELLBEING  /  心理健康与沟通建议（非诊断）", advice.wellbeing)
    if advice.limitations:
        say()
        panel("NOTES  /  信息与能力边界", "\n\n".join("- " + item for item in advice.limitations))
    say()
    for line in wrap_lines("[Enter] 检查更新   [R] 重新生成   [Q / Ctrl+C] 退出", line_width() - 2):
        say("  " + line)
    say()
