from pathlib import Path
import sys
import time

from .console import ask, choose, confirm, say, show_advice, show_banner, status as show_status
from .models import ProviderConfig, TeachMeChatError
from .settings import Settings


def configure_provider(saved=None, title="建议生成"):
    saved = saved or {}
    from .provider_specs import PROVIDERS, get_spec
    provider = choose(title + " · 选择服务商协议", [(spec.label, name) for name, spec in PROVIDERS.items()])
    spec = get_spec(provider)
    same = saved.get("provider") == provider
    url = ask("API 基础 URL（不要包含方法路径）",
              saved.get("base_url", "") if same else spec.base_url)
    model = ask("模型 ID（填写服务商提供的精确名称）", saved.get("model", "") if same else "")
    if not model:
        raise TeachMeChatError("模型 ID 不能为空。")
    key = ask("API Key（隐藏输入；仅本次运行有效）", secret=True)
    from .model_catalog import get_model_options
    options = get_model_options(provider, model, spec.protocol)
    reasoning = choose("推理设置；不支持时将明确报错", options)
    config = ProviderConfig(provider=provider, base_url=url, model=model, api_key=key, reasoning=reasoning)
    from .providers import LLMClient
    client = LLMClient(config)
    say("正在用无私人内容的小请求验证 API（可能产生少量费用）……")
    client.probe()
    say("API 鉴权和所选模型生成测试通过。")
    return config, client


def select_source():
    mode = choose("上下文来源", [
        ("在线微信：等待启动/登录并读取（版本兼容性需要验证）", "live"),
        ("已有明文快照：不会自动变成微信实时数据", "snapshot"),
        ("手动描述背景：无需启动微信", "manual")])
    if mode == "manual":
        return None, None, "手动背景模式"
    if not confirm("仅用于本人有权访问的数据。允许本程序读取你接下来选择的微信账号/数据库？"):
        raise TeachMeChatError("未授权读取，已停止。")
    from .sources import create_source
    if mode == "live":
        auto = choose("获取本地读取条件", [
            ("自动等待微信并复用仓库读取能力", True),
            ("手动填写数据库目录和密钥（不保存）", False)])
        if auto:
            from .discovery import processes, acquire, BoundLiveSource
            while True:
                found = processes()
                if not found:
                    say("等待微信启动……（Ctrl+C 退出）")
                    time.sleep(3)
                    continue
                process = found[0] if len(found) == 1 else choose("选择微信进程", [
                    (f"{p['name']} · PID {p['pid']}", p) for p in found])
                if process["version"] == 3 and sum(p["version"] == 3 for p in found) > 1:
                    raise TeachMeChatError("旧版仓库取钥按进程名匹配，不支持安全区分多个3.x进程；请用手动配置。")
                say("等待登录并获取读取条件；密钥仅留在本程序内存，不写日志……")
                try:
                    account = acquire(process)
                    break
                except TeachMeChatError as error:
                    say(error)
                    action = choose("读取条件未就绪", [("登录完成后重试", "retry"), ("退出", "quit")])
                    if action == "quit":
                        raise KeyboardInterrupt
            key = account.pop("key")
            source = create_source(Path(account["root"]), account["version"], mode="live", key=key,
                                   media_root=Path(account["media_root"]), account_id=account["account_id"])
            key = None
            source = BoundLiveSource(source, process)
        else:
            source = source_from_path(create_source, mode)
    else:
        source = source_from_path(create_source, mode)
    try:
        conversations = source.list_conversations()
        if not conversations:
            raise TeachMeChatError("未找到可读取的会话；请检查数据库目录、版本及登录状态。")
        method = choose("选择聊天", [("最近互动联系人列表", "recent"), ("输入名称或微信标识搜索", "search")])
        if method == "search":
            query = ask("联系人名称或标识").casefold()
            conversations = [c for c in conversations if query in c.name.casefold() or query in c.id.casefold()]
        if not conversations:
            raise TeachMeChatError("没有匹配的联系人。")
        conversation = choose("上下键选择目标会话", [
            (f"{c.name} · {c.id}", c) for c in conversations[:100]])
        return source, conversation, source.status_label
    except BaseException:
        source.close()
        raise


def source_from_path(factory, mode):
    version = choose("数据库版本", [("微信 3.x", 3), ("微信 4.x", 4)])
    root = Path(ask("数据库目录（Msg / db_storage / 解密快照目录）").strip('"'))
    media = ask("媒体账号根目录（可留空；缺失媒体仅显示占位）")
    account_id = ask("自己的微信标识（可留空；4.x推荐填写以准确区分我/对方）")
    key = ask("数据库密钥（隐藏输入，不保存）", secret=True) if mode == "live" else None
    return factory(root, version, mode=mode, key=key,
                   media_root=Path(media.strip('"')) if media else None, account_id=account_id)


def keyboard_action():
    if sys.platform == "win32":
        import msvcrt
        if msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in {"\x00", "\xe0"}:
                msvcrt.getwch()
                return ""
            if char == "\x03":
                raise KeyboardInterrupt
            return "refresh" if char == "\r" else char.lower()
    return ""


def run(runtime: Path):
    show_banner(runtime)
    settings = Settings(runtime)
    saved = settings.load()
    config, client = configure_provider(saved.get("provider"))
    source = None
    processor = None
    scheduler = None
    from threading import Event
    from .services import RequestBudget, analyze_context
    cancelled = Event()
    try:
        source, conversation, status = select_source()
        say(status)
        background = ask("描述关系背景、沟通目标和边界（单行，可留空）")
        if source is None and not background:
            raise TeachMeChatError("手动模式至少需要一段背景或对话描述。")
        vision = None
        if source is not None and confirm("启用图片内容识别？图片将发给所选视觉服务商"):
            reuse = confirm("使用同一个 API 和模型识别图片？该模型必须支持图像输入", True)
            if reuse:
                vision = client
            else:
                _, vision = configure_provider(title="图片识别")
            from io import BytesIO
            from PIL import Image
            sample = BytesIO()
            Image.new("RGB", (32, 32), "blue").save(sample, format="PNG")
            say("正在用程序生成的非私人小图验证视觉接口……")
            vision.describe_image(sample.getvalue(), "image/png")
            say("视觉接口测试通过。")
        whisper_path = ""
        if source is not None:
            whisper_path = ask("E盘本地 Whisper turbo 权重路径（留空不加载；不会自动下载）",
                               saved.get("whisper_path", ""))
        say(f"将向 {config.base_url} 的模型 {config.model} 发送：手动背景及选定会话最近最多100条文字上下文。")
        if vision is not None:
            say(f"视觉图片接收方：{vision.config.base_url} · {vision.config.model}")
        say("图片启用时发送选中会话的相关图片；本地语音转写的文字也会进入上下文。密钥和其他会话不发送。")
        if not confirm("确认发送以上范围到你配置的外部服务？"):
            raise TeachMeChatError("未授权外发，已停止；没有发送聊天上下文。")
        automatic = source is not None and choose("刷新方式", [
            ("每5秒自动刷新（Enter也可立即刷新）", True), ("仅按Enter检查", False)])
        if confirm("保存非敏感设置到E盘？API Key与聊天背景不保存", True):
            settings.save(config, whisper_path=whisper_path, auto_refresh=bool(automatic))
        from .media import MediaProcessor
        from .coach import generate_advice
        from .scheduler import Scheduler
        processor = MediaProcessor(runtime, vision_client=vision, whisper_path=whisper_path)
        fetch = (lambda: source.recent(conversation.id, limit=100)) if source is not None else (lambda: [])

        def analyze(messages, context):
            from .providers import LLMClient
            budget = RequestBudget(cancelled, 12)
            guarded = LLMClient(config, request_guard=budget.before_request)
            if vision is not None:
                processor.vision_client = LLMClient(vision.config, request_guard=budget.before_request)
            return analyze_context(guarded, processor, messages, context, budget)[0]

        scheduler = Scheduler(fetch, analyze, background, automatic=bool(automatic), interval=5.0)
        say("Enter 检查更新 | R 重新生成 | Q 退出；无新内容不重复调用模型。")
        while True:
            for event in scheduler.tick():
                now = time.strftime("%H:%M:%S")
                if event.kind == "messages":
                    label = f"[{now}] 已检查 {len(event.value)} 条"
                    if event.value:
                        stamp = max(message.timestamp for message in event.value)
                        try:
                            latest = time.strftime("%m-%d %H:%M:%S", time.localtime(stamp))
                        except (ValueError, OSError, OverflowError):
                            latest = "时间未知"
                        label += f"  |  最新已读 {latest}"
                    show_status(label + "  |  Enter 刷新 / R 重写 / Q 退出")
                elif event.kind == "analyzing":
                    say(f"[{now}] 正在处理媒体并生成建议……")
                elif event.kind == "advice":
                    show_advice(*event.value)
                elif event.kind == "read_error":
                    say(f"[{now}] 读取失败：{event.value} 保留上次结果，数据可能陈旧。")
                elif event.kind == "analysis_error":
                    say(f"[{now}] 分析失败：{event.value} 保留上次结果；退避重试最多3轮，之后按 R 重试。")
            action = keyboard_action()
            if action in {"q", "\x1b"}:
                break
            if action in {"refresh", "r"}:
                scheduler.request(regenerate=action == "r")
            time.sleep(0.1)
    finally:
        cancelled.set()
        if processor is not None and hasattr(processor, "cancel"):
            processor.cancel()
        if scheduler is not None:
            say("正在结束本程序任务（在途API请求受超时限制），不会退出微信……")
            scheduler.close()
        if processor is not None:
            processor.close()
        if source is not None:
            source.close()
