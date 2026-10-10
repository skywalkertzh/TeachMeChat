import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .models import TeachMeChatError


def processes() -> list[dict]:
    try:
        import psutil
    except ImportError:
        raise TeachMeChatError("缺少 psutil，请使用启动器 -Install 安装基础依赖。") from None
    result = []
    for process in psutil.process_iter(["pid", "name", "create_time"]):
        name = (process.info.get("name") or "").lower()
        if name in {"wechat.exe", "weixin.exe"}:
            result.append({"pid": process.pid, "version": 3 if name == "wechat.exe" else 4,
                           "started": process.info.get("create_time"), "name": name})
    return result


def acquire(process: dict, timeout: float = 90) -> dict:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    child = subprocess.Popen([sys.executable, "-B", "-m", "teachmechat.key_worker"],
                             cwd=Path(__file__).resolve().parent.parent,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        payload = json.dumps({"pid": process["pid"], "version": process["version"]}) + "\n"
        output, _ = child.communicate(payload, timeout=timeout)
        if child.returncode != 0 or len(output) > 65536:
            raise TeachMeChatError("微信读取组件失败；可改用手动配置或已有快照。")
        result = json.loads(output)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise TeachMeChatError("获取读取条件超时；已结束本程序读取任务，未退出微信。") from None
    except (ValueError, OSError):
        raise TeachMeChatError("微信读取组件返回无效结果；未保存密钥。") from None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    if not isinstance(result, dict) or not result.get("ok"):
        code = result.get("code", "reader_error") if isinstance(result, dict) else "reader_error"
        messages = {
            "dependencies": "缺少微信读取依赖，请先运行启动器 -Install。",
            "permission": "无法只读访问微信进程；请检查权限，不会自动提权。",
            "unsupported": "当前微信版本不在仓库支持表中，请选择手动配置或快照模式。",
            "not_ready": "微信尚未登录或仓库尚不能取得此版本的读取条件。",
        }
        raise TeachMeChatError(messages.get(code, "微信信息读取失败；可改用手动配置或已有快照。"))
    result["process"] = process
    return result


class BoundLiveSource:
    def __init__(self, source, process: dict):
        self.source, self.process = source, process
        self.status_label = source.status_label

    def _check(self):
        current = processes()
        if not any(p["pid"] == self.process["pid"] and p["started"] == self.process["started"] for p in current):
            raise TeachMeChatError("微信进程已退出或重启；请重新选择在线账号，旧会话不会继续采集。")

    def list_conversations(self):
        self._check()
        return self.source.list_conversations()

    def recent(self, conversation_id, limit=100):
        self._check()
        return self.source.recent(conversation_id, limit)

    def close(self):
        self.source.close()
