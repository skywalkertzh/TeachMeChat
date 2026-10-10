from pathlib import Path, PureWindowsPath
import os
import sys
import tempfile


def _local_absolute(value, message: str) -> Path:
    """本机绝对路径校验：拒绝相对路径、UNC/网络路径与 \\\\?\\ 扩展前缀。"""
    text = str(value).strip()
    if not text or "\x00" in text or text.startswith(("\\\\", "//")):
        raise ValueError(message)
    if PureWindowsPath(text).drive.startswith("\\\\"):
        raise ValueError(message)
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError(message)
    return path.resolve()


def _required_drive() -> str:
    """可选的 TEACHMECHAT_REQUIRE_DRIVE（例如 "E:"）；未设置时不限制盘符。"""
    required = os.environ.get("TEACHMECHAT_REQUIRE_DRIVE", "").strip().upper()
    if required and not required.endswith(":"):
        required += ":"
    return required


def configure_runtime(root: str | Path | None = None) -> Path:
    project = Path(__file__).resolve().parent.parent
    runtime = _local_absolute(
        root or os.environ.get("TEACHMECHAT_HOME", project / ".teachmechat-runtime"),
        "TeachMeChat 的运行目录必须使用本机绝对路径（不支持网络路径）。",
    )
    required = _required_drive()
    if required and runtime.drive.upper() != required:
        raise ValueError(f"TeachMeChat 的运行目录必须位于 {required} 盘（由 TEACHMECHAT_REQUIRE_DRIVE 强制）。")
    runtime.mkdir(parents=True, exist_ok=True)
    locations = {
        "TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp",
        "PIP_CACHE_DIR": "cache/pip", "XDG_CACHE_HOME": "cache",
        "HF_HOME": "cache/huggingface", "HF_HUB_CACHE": "cache/huggingface/hub",
        "HUGGINGFACE_HUB_CACHE": "cache/huggingface/hub",
        "TRANSFORMERS_CACHE": "cache/huggingface/transformers",
        "TORCH_HOME": "cache/torch", "NUMBA_CACHE_DIR": "cache/numba",
        "MPLCONFIGDIR": "cache/matplotlib", "CUDA_CACHE_PATH": "cache/cuda",
        "TRITON_CACHE_DIR": "cache/triton", "PYTHONPYCACHEPREFIX": "cache/pycache",
    }
    for name, relative in locations.items():
        directory = runtime / relative
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)
    os.environ["TEACHMECHAT_HOME"] = str(runtime)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(runtime / "tmp")
    return runtime
