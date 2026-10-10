# TeachMeChat · 交我聊

> 基于 [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg)（留痕 / MemoTrace，MIT）二次开发；保留上游版权与许可说明：[NOTICE.md](NOTICE.md)。
> 微信 3.x / 4.x 支持范围、连接流程与未验证项：[WECHAT_COMPAT.md](WECHAT_COMPAT.md)
> 社交平台介绍文案与发布模板：[PROMO.md](PROMO.md)

Windows 桌面聊天起草助手。采用圆角外框、同色自定义标题栏，去掉突兀的系统白色标题条；保留最小化、最大化/还原、关闭、拖动和边缘缩放。主界面只保留联系人、聊天、回复及必要操作，常规同步状态不常驻刷屏。分享 XML 转为标题/摘要卡片，不展示原始协议内容。

**只生成草稿，不自动发送微信，不自动点击微信。** 请仅访问本人有权处理的数据，并了解所选 API 服务商的数据政策。

## 配色与视觉

采用“雾灰＋鼠尾草绿”的中亮度主题，不使用大面积纯白或纯黑。主窗口、消息气泡、设置页、输入框和机器人使用同一套色彩角色；降低背景亮度的同时保留正文与辅助文字的对比。公开设计参考及取舍见 [DESIGN.md](DESIGN.md)。这不是医学护眼声明；实际舒适度仍与屏幕亮度和环境光有关。

## 底部状态机器人

底部中央像素机器人采用仿真液晶屏：黑色底、亮绿色像素化文字（1.5 倍点阵放大）和细扫描线，内容字号已整体调大。红绿双灯现在位于液晶屏内部右侧，不再单独占用卡片角落。微信尚未连接时眼睛显示 `@@`；已连接、读取或生成中保持平静；回答真正生成完成才微笑，同一上下文无新消息刷新不会丢掉完成状态。手动背景成功生成也会微笑，文字会区分当前模式。

屏幕内信号灯：**生成建议时亮红灯、异常也亮红灯**（看屏幕文字区分），**已同步或回答完成亮绿灯**；等待、读取和暂停时两灯熄灭。长错误悬停可查看完整提示。左下角“连接微信”为带高光与按压位移的深色圆按钮，键盘同样可操作。

## 刷新与阅读

聊天框右上角提供环形箭头立即刷新，以及 iOS 风格“自动刷新”开关，开启后每 **5秒** 检查；无变化不重复调用模型。刷新周期不是模型生成的完成时限。

首次加载对齐最新消息，底部不再出现需要上滑才能找到消息的大块空白。停在底部时新消息将旧消息向上推；主动查看历史时保留阅读位置。不变化的列表不重建、不跳动；1000/5000条分批构建，首次大量加载仍可能需要时间。

“建议 / 分析”使用半粗标题与更宽松行距；分析段落用明确分区，显式 `**重点**` 仅转换字重，不执行任何模型HTML。“补充要求”保留边框和轻微立体按压效果。

## 上下文条数

聊天标题下选择 **100 / 200 / 500 / 1000 条**，或 **自定义 1–5000 条**。该值实际传给数据库读取，不只是展示设置；默认100。已保存配置时会按原保存模式记住选择，session模式只在本次生效，不新增保存密钥。

修改范围会停止旧分析、重新读取并撤销原发送授权，生成前确认新的条数。数量变多可能增加读取/媒体处理耗时和API费用。**模型输入仍有16000字符预算，读取1000条不保证1000条原文全部发给模型**；裁剪以最近消息优先并在建议限制中提示。

字体参考 [微软 Windows Typography](https://learn.microsoft.com/en-us/windows/apps/design/style/typography)：简体中文优先 Microsoft YaHei UI，英文回退 Segoe UI/Variable；正文常规字重，标题半粗，LCD数字用Consolas。不下载或安装额外字体。

## 启动桌面版

获取代码（`git clone` 或 Download ZIP）与完整下载安装步骤见根目录 [README.md](../README.md)；本节列出环境准备与全部启动入口。

环境准备：Windows 10/11、64 位 Python 3.10+。先安装依赖（会创建项目内隔离环境 `<项目目录>\.teachmechat-runtime\venv`，不写全局 Python）：

```powershell
cd <项目目录>
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Install
```

之后启动窗口（也可双击根目录 **TeachMeChat.pyw**，需要 Windows 已关联 Python）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1
```

安装器优先使用已记录的 `teachmechat/requirements-lock.txt`，依赖、pip缓存及临时文件都放在项目运行目录（默认为 `<项目目录>\.teachmechat-runtime`，见下文磁盘策略）。已在 Windows x64 / Python 3.10.20 验证；其他环境未宣称验证。Bypass 仅作用于当前 PowerShell 进程，不修改持久执行策略。

其他入口：

```powershell
# 合成数据视觉演示，不读取保存配置或微信，不发API请求
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Demo
# 保留原终端模式（诊断用途，主要新配置流程在桌面）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Cli
# 显式配置目录（示例；任意本机绝对路径均可）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -ConfigDir D:\TeachMeChatConfig
```

## 第一次设置，以及下次免输入

首次进入“工作空间设置”：

1. 选择服务商、填写 API Key，在可编辑下拉框选择模型；也可手输第三方模型 ID。点击“获取模型”才会向当前配置的 `/models` 发出请求，不发送聊天内容，也不生成文字。列表不支持或失败时仍可手填。
2. 推理控件的标题会随模型变化：显示“思考开关”（只有开/关）、“推理强度”（low/medium/high 等档位）或“推理设置”（未登记档位）。档位按**精确模型 ID 加协议**匹配官方文档，不使用名称前缀猜测；未知模型只提供默认，不发送控制参数。
3. 内置模型清单只是参考，不保证你的账号或地区可用；“获取模型”返回的是当前端点实际列表。部分新模型（如 `gpt-5.5`）只登记名称并明确标注档位未核实，请以“获取模型”和探测结果为准。
4. “存储与隐私”选择配置目录，默认 **C:\TeachMeChat**，也可选择其他盘符的自定义目录。
5. 选择保存方式：
   - **加密保存设置与 API Key**：Windows DPAPI 绑定当前用户，目录限制当前用户访问；下次启动直接恢复模型/URL/Key/推理选项，不再逐项输入。
   - **仅保存公开配置**：不保存 Key，下次只补 Key。
   - **仅本次会话**：不写配置；既有保存文件不会因此自动删除。
6. 主模型与视觉模型可复用，也可各设一个服务商。

默认配置目录只存小型配置与加密凭据；**模型、依赖、下载缓存及临时媒体保存在项目内运行目录**（默认 `<项目目录>\.teachmechat-runtime`），不会自动选择系统盘以外的位置。不自动提权，不覆盖其他用户目录。Windows 用户或机器改变、密文损坏时需要重新录入 Key，不回退为明文。

设置页提供“删除已保存的 API Key”和“导入旧版公开设置”。旧版本来没有保存 Key，因此迁移后需补录一次。修改 API 地址或服务商会清空当前表单 Key，避免把已有凭据发送到新地址。

配置位置指针存于运行目录，不含 Key。查找优先级：显式 `-ConfigDir` / `--config-dir` > 已记住的目录 > `C:\TeachMeChat`。开发测试不会创建真实默认目录或读取你的真实配置。

## 标准供应商模板

| 供应商 | 基础 URL | 协议 |
|---|---|---|
| OpenAI | https://api.openai.com/v1 | OpenAI Chat Completions |
| Google Gemini | https://generativelanguage.googleapis.com/v1beta/openai | OpenAI兼容（Bearer） |
| DeepSeek | https://api.deepseek.com/v1 | OpenAI兼容 |
| GLM / 智谱 | https://open.bigmodel.cn/api/paas/v4 | OpenAI兼容 |
| Anthropic | https://api.anthropic.com/v1 | 原生 Messages |
| Kimi / Moonshot | https://api.moonshot.cn/v1 | OpenAI兼容 |
| 自定义 | 手动填写 | 显式选择OpenAI或Anthropic协议 |

这是普通推理 API 模板，不把 Coding 套餐当通用 API。第三方继续选择“自定义”，填写自己的 URL、Key、模型 ID，并选择兼容协议；已登记原厂模型按精确 ID 与协议提供对应档位，代理仍可能不支持，可退回默认。未知别名不猜能力。

已登记的官方档位（2026-10 联网核验各厂商官方文档，来源链接记录在 `model_catalog.py`，会随官方更新维护）：

- **OpenAI**：`gpt-6.1-sol`/`gpt-6-sol`/`gpt-6-luna`/`gpt-5.6-sol·terra·luna`/`gpt-5.5` 支持 `none`（部分模型报错）到 `xhigh`/`max` 的 reasoning_effort；`gpt-6-astra` 无 `none`，默认档位官方未核实；`gpt-5`/`gpt-5.1`/`o3`/`o4-mini` 保留但官方已列入退役计划。仅 Responses API 的型号（如 `gpt-5.5-pro`）不收录。
- **Google Gemini**：`gemini-3.8-flash`（low/medium/high，默认 medium）、`gemini-3.6-flash`、`gemini-3.5-flash-lite`（默认 minimal）、`gemini-3-flash-preview`、`gemini-3.1-pro-preview`（默认 high）。注意官方没有裸 `gemini-3-pro`/`gemini-3-flash` 名称，Flash 主力为 3.8；2.5 系列仅限既往使用者。
- **Anthropic**：`claude-fable-5-1`/`mythos-5-1`/`opus-5-5`/`sonnet-5-5`/`haiku-5-5`/`opus-5`/`sonnet-5` 使用 adaptive effort（low–xhigh/max，默认 medium 或 high 视型号）；`opus-4-8/4-7` 可关闭思考；`opus-4-6`/`sonnet-4-6` 为 adaptive 四档；`sonnet-4-5`/`haiku-4-5`/`opus-4-5` 属 legacy（token 预算）。
- **DeepSeek**（`deepseek-flash`、`deepseek-v4-pro`）：`none/low/high/max`，默认 high；none 等同关闭思考。
- **GLM**：`glm-5.3`/`5.3-flash`/`5.3-flashx` 仅开启思考，`low/high/max`，默认 max；`glm-5.2` 可开关且额外支持 xhigh/medium/minimal；`glm-5.1`/`glm-5-turbo`/`glm-4.7` 是开关无档位。
- **Kimi**：`kimi-k3` 始终思考，`low/high/max` 默认 max；`kimi-k2.7-code(-highspeed)` 始终思考、无档位；`kimi-k2.6` 为开关。

内置清单是离线参考，不保证当前账号或地区可用；实际可用模型以“获取模型”和探测结果为准。数字“思考预算”不再是新设置的输入项。旧 Anthropic enabled/预算值保留序列化兼容；不适用于当前模型的旧档位在表单中明确提示恢复默认。文字/JSON/视觉测试仍由用户主动点击，可能产生生成费用。

Anthropic 使用原生鉴权、system、图片内容块和 JSON schema 输出，不伪装成 Chat Completions。若某模型不支持原生结构化，可显式选择“提示词 JSON”，结果仍严格验证恰好三个草稿，不静默降级。

## 使用流程

- 点击“连接微信”，确认本机只读授权后自动等待登录；不再先选择一堆数据源类型。快照和手动密钥入口收在“更多 → 其他导入方式”。
- 选联系人，查看昵称、时间、左右消息气泡；链接分享显示标题/摘要/来源，无法解析的消息明确占位。只调整预览，不改原始记录或模型输入。
- 点击“生成”，确认本次会话外发范围后获取三个建议；想加要求时展开“补充要求”。不连接微信也可用“手动输入”。
- 设置首屏保留服务商、Key、可选择模型和模型对应推理档位；自定义地址、协议、JSON模式与超时在“高级参数”，第三方默认展开。
- 自动模式每5秒检查；没有新内容不重复分析。刷新和重新生成都会等读取完成，不先分析旧缓存。
- 视觉识别与文本生成共享单轮请求预算，默认12次；计入HTTP重试。不提供虚构的货币费用估算。
- 点击“暂停”停止后续采集/分析并取消本程序旧任务；已经到达服务端的请求不能保证撤回或免计费。
- 模型或读取失败会暂停/撤销对应状态，不悄悄反复上传旧上下文；切换会话需重新确认范围。
- 每张草稿卡有“复制”，只有点击才修改剪贴板。

5秒是检查周期，不是微信同步、媒体处理和模型生成都在5秒内完成的保证。默认不保存聊天历史或手动背景。

## 图片与语音

图片先本地解码、检查格式/尺寸并剥除元数据，再发送视觉模型。原图缺失可退到缩略图；不支持的加密/图像格式明确显示缺失，不编造内容，不自动打开聊天链接。

语音可使用运行目录中已放置的 Whisper turbo / large-v3-turbo 权重。已配置时优先turbo；缺少后端/权重或失败时，只能明确回退到微信已有转写，不冒充turbo。

**大型依赖和权重没有默认下载。**可选安装：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-TeachMeChat-ASR.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-TeachMeChat-ASR.ps1 -DownloadTurbo
```

均使用项目运行目录缓存；显卡版PyTorch需自行选择与机器匹配的版本，已装后可用 `-Backend ExistingTorch`。普通启动不隐式下载模型。

## 运行目录与磁盘策略

运行目录默认为 `<项目目录>\.teachmechat-runtime`（venv、pip/PyTorch/HuggingFace 缓存、临时媒体、模型都放这里）。也可用环境变量 `TEACHMECHAT_HOME` 指向其他本机绝对路径。缓存路径在安装依赖之前就会重定向，避免写入系统默认缓存目录。

默认接受任意本机盘符（拒绝网络共享/UNC 路径）。如需强制固定在某个盘（例如作者机器上的 E 盘），设置环境变量 `TEACHMECHAT_REQUIRE_DRIVE=E:`，运行目录、缓存与模型不在该盘时会给出明确错误而不是静默改写。所有本程序可控制的文件都在运行目录内；Windows 与第三方组件自身的系统写入不在本程序控制范围。

## 验证与发布状态

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Diagnostics
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -ReleaseCheck
.\.teachmechat-runtime\venv\Scripts\python.exe -B release.py --check
```

普通测试允许明确报告skip；严格发布门禁不允许任何skip。全部自动测试使用合成数据、fake API或本机模拟服务，不读取真实微信/API Key。桌面预览也只用虚构联系人。

- [发布审计](RELEASE_AUDIT.md)：已修问题及剩余阻碍。
- [验证记录](VERIFICATION.md)：实际通过/跳过结果，不把合成测试当真实兼容证明。
- [第三方许可说明](THIRD_PARTY.md)：公开打包前必须核验的依赖义务。

**当前是桌面预览版，不是已签名、全面兼容的稳定公开发行版。**同进程微信换号、真实模型服务、所有微信格式、新机器安装/GPU及许可矩阵仍需专项验证。不通过关闭防护、隐藏行为或绕过检测来消除安全软件提示。
