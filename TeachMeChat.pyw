import os
from pathlib import Path
import subprocess
import sys


def main():
    project = Path(__file__).resolve().parent
    interpreter = project / ".teachmechat-runtime/venv/Scripts/pythonw.exe"
    if not interpreter.is_file():
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "请先运行 Start-TeachMeChat.ps1 -Install 安装依赖。", "交我聊", 0x10)
        return
    sys.path.insert(0, str(project))
    from teachmechat.runtime import configure_runtime
    configure_runtime()
    subprocess.Popen([str(interpreter), "-B", "-m", "teachmechat"], cwd=project,
                     env=os.environ.copy(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    main()
