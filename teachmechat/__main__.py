import argparse
import importlib.util
from pathlib import Path
import sys

from .runtime import configure_runtime


def main():
    parser = argparse.ArgumentParser(description="TeachMeChat · 交我聊（只生成建议，不发送消息）")
    parser.add_argument("--diagnostics", action="store_true", help="仅检查环境，不访问微信或外部API")
    parser.add_argument("--test", action="store_true", help="只运行合成数据和模拟API测试")
    parser.add_argument("--release-check", action="store_true", help="运行发布门禁，关键测试不允许跳过")
    parser.add_argument("--cli", action="store_true", help="使用传统终端界面")
    parser.add_argument("--demo", action="store_true", help="桌面合成数据预览，不读配置或连接服务")
    parser.add_argument("--config-dir", help="配置目录；首次默认 C:\\TeachMeChat，缓存与模型在项目运行目录")
    args = parser.parse_args()
    runtime = configure_runtime()
    if args.test or args.release_check:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import unittest
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / "tests"))
        count = suite.countTestCases()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if args.release_check and (count < 73 or result.skipped):
            print("Release check failed: missing or skipped coverage.")
            return 1
        return 0 if result.wasSuccessful() and count > 0 else 1
    if args.diagnostics:
        print(f"Python: {sys.version.split()[0]}")
        print(f"Executable: {sys.executable}")
        print(f"Runtime: {runtime}")
        for name in ("prompt_toolkit", "psutil", "sqlcipher3", "PIL", "pysilk", "whisper", "torch"):
            print(f"{name}: {'available' if importlib.util.find_spec(name) else 'not installed'}")
        print("No WeChat data, credentials, models or external APIs were accessed.")
        return 0
    if not args.cli:
        try:
            from .desktop.window import launch
            return launch(runtime, args.config_dir, demo=args.demo)
        except ImportError:
            print("Desktop dependencies missing. Run Start-TeachMeChat.ps1 -Install, or use --cli.")
            return 1
    from .app import run
    from .console import say, terminal_theme
    from .models import TeachMeChatError
    try:
        with terminal_theme():
            run(runtime)
        return 0
    except KeyboardInterrupt:
        say("\n已退出交我聊，微信未被关闭。")
        return 130
    except TeachMeChatError as error:
        say(f"无法继续：{error}")
        return 1
    except Exception:
        say("运行失败；为保护聊天和密钥，不输出原始异常。请检查依赖及输入配置，或运行 --diagnostics。")
        return 1


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
