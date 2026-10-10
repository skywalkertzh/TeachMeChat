"""Isolated workers: no widgets, console prompts, credential persistence or logs."""
from dataclasses import replace
from pathlib import Path
import time

from ..context_options import DEFAULT_CONTEXT_MESSAGES, validate_context_limit
from ..models import TeachMeChatError
from ..services import OperationCancelled, RequestBudget, analyze_context


def _safe_error(error):
    return str(error) if isinstance(error, TeachMeChatError) else "操作失败。未显示可能包含私人内容的原始错误。"


def _source(spec, cancelled, connection):
    from ..sources import create_source
    if spec["mode"] == "manual":
        return None
    if spec["mode"] == "auto":
        from ..discovery import processes, acquire, BoundLiveSource
        while not cancelled.is_set():
            found = processes()
            if not found:
                connection.send(("progress", "等待微信启动与登录……"))
                cancelled.wait(3)
                continue
            if len(found) != 1:
                raise TeachMeChatError("检测到多个微信进程。请使用手动连接，避免选择错误账号。")
            connection.send(("progress", "正在验证本地读取条件……"))
            try:
                account = acquire(found[0])
            except TeachMeChatError as error:
                if "尚未登录" not in str(error):
                    raise
                connection.send(("progress", "等待微信登录，或当前版本尚未支持。可随时取消连接。"))
                cancelled.wait(8)
                continue
            if cancelled.is_set():
                raise OperationCancelled("连接已取消。")
            source = create_source(Path(account["root"]), account["version"], mode="live",
                                   key=account.pop("key"), media_root=Path(account["media_root"]),
                                   account_id=account["account_id"])
            return BoundLiveSource(source, found[0])
        raise OperationCancelled("连接已取消。")
    return create_source(Path(spec["root"]), int(spec["version"]),
                         mode="live" if spec["mode"] in {"live", "live-manual"} else "snapshot",
                         key=spec.get("key"), media_root=Path(spec["media_root"]) if spec.get("media_root") else None,
                         account_id=spec.get("account_id", ""))


def source_worker(pipe, cancelled, runtime):
    from ..runtime import configure_runtime
    configure_runtime(runtime)
    source = None
    try:
        while not cancelled.is_set():
            if not pipe.poll(.2):
                continue
            operation, payload = pipe.recv()
            try:
                if operation == "open":
                    if source is not None:
                        source.close()
                    source = _source(payload, cancelled, pipe)
                    conversations = source.list_conversations() if source else []
                    if not cancelled.is_set():
                        pipe.send(("opened", (conversations, source.status_label if source else "手动背景")))
                elif operation == "recent":
                    if isinstance(payload, str):
                        conversation_id, limit = payload, DEFAULT_CONTEXT_MESSAGES
                    elif isinstance(payload, dict) and set(payload) == {"conversation_id", "limit"}:
                        conversation_id = payload["conversation_id"]
                        limit = validate_context_limit(payload["limit"])
                    else:
                        raise TeachMeChatError("读取上下文请求无效。")
                    if not isinstance(conversation_id, str) or not conversation_id.strip():
                        raise TeachMeChatError("读取上下文需要有效的会话标识。")
                    if source is None:
                        messages = []
                    else:
                        messages = source.recent(conversation_id, limit=limit)
                    if not cancelled.is_set():
                        pipe.send(("messages", (conversation_id, messages)))
                elif operation == "stop":
                    break
            except Exception as error:
                if not cancelled.is_set():
                    pipe.send(("error", _safe_error(error)))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        if source is not None:
            source.close()
        pipe.close()


def analysis_worker(pipe, cancelled, runtime):
    from ..runtime import configure_runtime
    from ..media import MediaProcessor
    from ..providers import LLMClient
    configure_runtime(runtime)
    processor = None
    media_signature = None
    try:
        while not cancelled.is_set():
            if not pipe.poll(.2):
                continue
            operation, payload = pipe.recv()
            if operation == "stop":
                break
            budget = RequestBudget(cancelled, payload.get("limit", 12))
            try:
                if operation == "models":
                    from ..providers import discover_models
                    models = discover_models(payload["primary"], request_guard=budget.before_request)
                    budget.check()
                    pipe.send(("models", models))
                    continue
                client = LLMClient(payload["primary"], request_guard=budget.before_request)
                if operation == "probe":
                    kind = payload["kind"]
                    if kind == "structured":
                        result = client.probe_structured()
                    elif kind == "vision":
                        from io import BytesIO
                        from PIL import Image
                        image = BytesIO()
                        Image.new("RGB", (32, 32), "blue").save(image, format="PNG")
                        client.describe_image(image.getvalue(), "image/png")
                        result = "视觉请求通过（合成小图）。"
                    else:
                        result = client.probe()
                    budget.check()
                    pipe.send(("probe", (kind, result, budget.count)))
                    continue
                vision_config = payload.get("vision")
                vision = LLMClient(vision_config, request_guard=budget.before_request) if vision_config else None
                options = payload.get("options", {})
                signature = (repr(vision_config), getattr(vision_config, "api_key", ""), options.get("whisper_path", ""))
                if processor is None or signature != media_signature:
                    if processor:
                        processor.close()
                    processor = MediaProcessor(Path(runtime), vision_client=vision,
                                               whisper_path=options.get("whisper_path", ""))
                    media_signature = signature
                processor.vision_client = vision
                advice, enriched = analyze_context(client, processor, payload["messages"],
                                                   payload.get("background", ""), budget)
                pipe.send(("advice", (advice, enriched, budget.count)))
            except Exception as error:
                if not cancelled.is_set():
                    pipe.send(("error", (_safe_error(error), budget.count)))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        if processor is not None:
            processor.cancel()
            processor.close()
        pipe.close()
