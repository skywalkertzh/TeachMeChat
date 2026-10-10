"""Isolated entry point for the repository's existing local account reader."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types


def load_reader(version: int):
    base = Path(__file__).resolve().parent.parent / "wxManager"
    for name, directory in (("wxManager", base), ("wxManager.decrypt", base / "decrypt")):
        package = types.ModuleType(name)
        package.__path__ = [str(directory)]
        sys.modules[name] = package
    name = f"wxManager.decrypt.wx_info_v{version}"
    spec = importlib.util.spec_from_file_location(name, base / "decrypt" / f"wx_info_v{version}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_account(pid: int, version: int) -> dict:
    module = load_reader(version)
    if version == 3:
        table = Path(__file__).resolve().parent.parent / "wxManager/decrypt/version_list.json"
        info = module.dump_wechat_info_v3(json.loads(table.read_text(encoding="utf-8")), pid)
        if info.errcode != 200 or not info.key:
            return {"ok": False, "code": "unsupported" if info.errcode == 405 else "not_ready"}
        return {"ok": True, "root": str(Path(info.wx_dir) / "Msg"),
                "media_root": info.wx_dir, "account_id": info.wxid,
                "key": info.key, "version": 3, "label": info.nick_name or info.wxid}
    module.open_process = lambda target: module.ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, target)
    handle = module.open_process(pid)
    if not handle:
        return {"ok": False, "code": "permission"}
    try:
        root = module.get_wx_dir(handle)
        if not root:
            return {"ok": False, "code": "not_ready"}
        root = Path(root)
        candidate = next((root / p for p in ("favorite/favorite_fts.db", "head_image/head_image.db")
                          if (root / p).is_file()), None)
        if candidate is None:
            return {"ok": False, "code": "not_ready"}
        with candidate.open("rb") as stream:
            first_page = stream.read(4096)
        candidates = module.get_key_inner(pid, module.get_memory_regions(handle))
        key = next((bytes(value).hex() for value in candidates
                    if value and module.is_ok(value, first_page)), "")
        if not key:
            return {"ok": False, "code": "not_ready"}
        account = root.parent.name
        return {"ok": True, "root": str(root), "media_root": str(root.parent),
                "account_id": account.rsplit("_", 1)[0], "key": key,
                "version": 4, "label": account}
    finally:
        module.ctypes.windll.kernel32.CloseHandle(handle)


def main():
    from .runtime import configure_runtime
    configure_runtime()
    response = {"ok": False, "code": "reader_error"}
    try:
        request = json.loads(sys.stdin.readline())
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                response = read_account(int(request["pid"]), int(request["version"]))
    except ImportError:
        response = {"ok": False, "code": "dependencies"}
    except Exception:
        pass
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    main()
