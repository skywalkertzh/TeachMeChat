# TeachMeChat · 交我聊

> 基于 [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg)（留痕 / MemoTrace，MIT）二次开发的本地优先 Windows 微信回复草稿助手。

## 一句话定位

**把你的话先说好、再由你自己发出去**：本地**只读**读取你授权的微信聊天，用你自选的模型（OpenAI / Google Gemini / DeepSeek / GLM / Anthropic / Kimi / 自定义）生成三条回复草稿、对话态势分析与关怀建议，绝不自动发送的 Windows 桌面助手。

## 快速开始（四行）

```powershell
git clone https://github.com/skywalkertzh/TeachMeChat.git
cd TeachMeChat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1
```

第 3 行安装依赖，第 4 行打开窗口。没有 git 就下载 ZIP（见下文）；每一步的细节与报错处理都在下面几节。

## 适用场景

*以下只是场景举例；草稿是措辞参考，不承诺任何沟通效果。*

- **应付领导 / 同事**：工作群里被点名、临时要汇报，先让草稿给出一版语气得体、要点齐全的回复，再自己改。
- **委婉拒绝与回怼**：不想撕破脸又不想憋着，让草稿先把台阶或要点铺好，选一版顺眼的使用。
- **哄对象 / 家人**：闹别扭后不知道怎么开口，让草稿给出几种不同语气的说法，挑最像自己的那版。
- **破冰与道歉**：久未联系、想重新搭话、说错话之后——第一句最难写，让草稿先给个起点。
- **事务性寒暄**：逢年过节问候、例行回消息这类“周报式”寒暄，要求得体又不想太费神，草稿可以先打个底。

## 核心亮点

- **只生成草稿，绝不自动发送**：没有“代发”功能，不自动点击微信；复制草稿需要你手动点一下。
- **本地只读**：使用 SQLCipher 只读连接读取你本机已登录账号的数据库，不写入源库、不强制 checkpoint；读取需要你的授权。
- **自选模型，API Key 可加密记住**：内置 OpenAI / Google Gemini / DeepSeek / GLM / Anthropic / Kimi 模板，第三方可自填；Key 可用 Windows DPAPI 绑定当前用户加密保存，也可选择不保存。
- **三栏界面 + 液晶状态机器人**：联系人 / 聊天 / 回复三栏；底部像素机器人用仿真液晶屏显示状态——生成亮红灯、完成亮绿灯，未连接时是一对 `@@` 眼睛。
- **上下文 100–1000 条可选**：预设 100 / 200 / 500 / 1000，也可自定义 1–5000 条；默认 100。
- **自动 / 手动刷新**：自动模式每 5 秒检查新消息，没有变化不重复调用模型；也可以点环形刷新按钮手动刷新。
- **图片与语音**：图片在本地解码后交给视觉模型识别；语音可回退微信已有转写，或配合自备的 Whisper turbo 权重做本地转写。

## 明确不做什么

- **不代发**：不自动发送消息、不自动点击微信。
- **不监控他人**：只读取你本人有权访问的本机数据，不用于监控或采集他人信息。
- **不预测对方心理**：不做“读心”式承诺，草稿只是措辞参考。
- **不做心理诊断**：生成的文字不构成任何专业建议。

## 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10/11（64 位）；暂不支持 macOS / Linux |
| Python | 64 位 Python 3.10+（推荐 3.10–3.12）。本仓库在 Windows 10 x64 + Python 3.10.20 上完成验证 |
| 微信 | Windows 版微信 3.x（`WeChat.exe`）或 4.x（`Weixin.exe`），使用时需保持登录；兼容范围见 [WECHAT_COMPAT.md](teachmechat/WECHAT_COMPAT.md) |
| 磁盘 | 依赖约数百 MB；可选本地语音转写另需数 GB。全部放在项目文件夹内，不写系统盘全局环境 |
| 网络 | 安装依赖需访问 PyPI（国内可配镜像）；使用时需访问你配置的模型 API |

## 一、下载

方式一（推荐，之后可用 `git pull` 更新）：

```powershell
git clone https://github.com/skywalkertzh/TeachMeChat.git
cd TeachMeChat
```

方式二：在仓库页面点 **Code → Download ZIP**，解压到本地磁盘（没有 git 时用这种）。

注意：请把项目放在**本机本地磁盘**路径（如 `D:\TeachMeChat`）。运行目录不支持网络共享 / UNC 路径（如 `\\server\share\...`）。

## 二、安装

在项目目录打开 PowerShell，执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Install
```

这一步会做什么：

- 创建**项目内隔离环境** `<项目目录>\.teachmechat-runtime\venv`，按 `teachmechat/requirements-lock.txt`（Windows x64 / Python 3.10.20 已验证的组合）安装 PySide6、sqlcipher3 等依赖；
- **不修改系统 Python、不写全局 site-packages**；pip 缓存与临时文件也重定向到项目运行目录；
- 中断后把同一条命令再执行一次即可，支持重复运行。

Python 按以下顺序查找：`-Python` 参数 → 环境变量 `TEACHMECHAT_PYTHON` → PATH 中的 `python.exe` / `py.exe`。没找到会明确报错，此时手动指定（路径替换为你机器上的实际路径）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Install -Python "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

国内网络若下载慢或超时，先切 PyPI 镜像再安装（只影响当前窗口）：

```powershell
$env:PIP_INDEX_URL = 'https://pypi.tuna.tsinghua.edu.cn/simple'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Install
```

（可选）本地语音转写为 Whisper，会额外下载 PyTorch + Whisper（数 GB），**不装也能用**——语音回退到微信自带转写：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-TeachMeChat-ASR.ps1
# 追加 -DownloadTurbo 再下载 turbo 权重
```

## 三、启动与自检

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1
```

窗口正常打开即安装成功。也可以直接**双击项目根目录的 `TeachMeChat.pyw`**（需要系统已关联 .py/.pyw；未安装依赖时会弹窗提醒先执行 `-Install`）。

启动前后可用的自检入口：

```powershell
# 打印 Python 版本、运行目录、依赖是否就绪；不访问微信与外部 API
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Diagnostics

# 用合成数据预览界面：不读配置、不连微信、不发 API 请求
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Demo

# 开发者：全部合成数据测试 / 不允许跳过的发布门禁
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -ReleaseCheck
```

`-Diagnostics` 里 `sqlcipher3: available` 表示读取微信数据库的组件就绪；`whisper` / `torch` 显示 `not installed` 只影响本地语音转写，属正常。

## 四、首次配置：连通模型 API（一次输入，下次免填）

首次启动进入“工作空间设置”：

1. 选择**服务商**，基础 URL 自动带出：

   | 供应商 | 基础 URL | 协议 |
   |---|---|---|
   | OpenAI | `https://api.openai.com/v1` | OpenAI Chat Completions |
   | Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | OpenAI 兼容 |
   | DeepSeek | `https://api.deepseek.com/v1` | OpenAI 兼容 |
   | GLM / 智谱 | `https://open.bigmodel.cn/api/paas/v4` | OpenAI 兼容 |
   | Anthropic | `https://api.anthropic.com/v1` | 原生 Messages |
   | Kimi / Moonshot | `https://api.moonshot.cn/v1` | OpenAI 兼容 |
   | 自定义 | 手动填写 | 显式选择 OpenAI 或 Anthropic 协议 |

2. 填 **API Key**，在可编辑下拉框里选模型（也可直接输入模型 ID）。
3. 点 **“获取模型”**——这会把你的 Key 发到上表地址请求模型列表（`/models`），**不发送任何聊天内容**。返回列表就说明地址、Key、网络全部连通；这是接入的验收点。列表失败也不拦你手填，但请先排查：Key 是否有效、Base URL 是否与上表一致、公司网络是否需要代理。
4. **“存储与隐私”**：选配置目录（默认 `C:\TeachMeChat`，可改为其他本地目录，如 `D:\TeachMeChatConfig`——只存小型配置与加密凭据，不存聊天记录），并选保存方式：
   - **加密保存设置与 API Key**（推荐）：Windows DPAPI 绑定当前用户，下次启动直接恢复，不再逐项输入；
   - 仅保存公开配置：不存 Key，下次补填；
   - 仅本次会话：不写盘，既有存档不受影响。
5. 文字 / 结构化 / 视觉的“测试”按钮会真实生成一次内容（可能有少量费用），由你主动点击；“获取模型”本身不产生生成费用。

界面上推理档位（思考开关 / 推理强度）会随所选模型自动变换；完整档位说明与更多细节见 [teachmechat/README.md](teachmechat/README.md)。

## 五、连接微信

1. 保持微信已启动并**已登录**。也可以先开应用再启动微信——应用每 3 秒自动检测并等待。
2. 在主窗口点击左下角 **“连接微信”**，确认“只读访问本人数据”的授权。
3. 应用自动校验读取条件（定位数据库、取密钥、建立只读连接）。成功后列出最近会话，选一位联系人即可看到上下文。
4. 点 **“生成”**，确认本次外发范围后得到 3 条回复草稿 + 对话态势分析 + 关怀建议。“复制”由你手动点击。

注意事项（完整版见 [WECHAT_COMPAT.md](teachmechat/WECHAT_COMPAT.md)）：

- 自动连接要求本机**只有一个微信进程**；多开请改用“更多 → 其他导入方式”里的手动连接。
- 微信 3.x 的安装版本必须在静态偏移表内，不在时会明确提示（405）而不是猜测；备选：手动目录 + 密钥、明文快照导入、纯手动录入背景。
- 微信退出或重启后停止采集，重新连接即可；同进程切换账号请断开重连。
- 单次获取读取条件有 90 秒超时，超时只结束本程序的读取任务，**不会退出微信**。
- 数据库密钥仅存在于程序内存中，不写日志、不落盘。

## 六、常见问题排错

| 现象 | 处理 |
|---|---|
| `Provide -Python with an existing Python 3.10+ executable` | 未找到 Python：安装 64 位 Python 3.10+（python.org 安装时勾选 Add python.exe to PATH），或用 `-Python` / `TEACHMECHAT_PYTHON` 指定 |
| `Environment not installed` / `Desktop dependencies missing` | 先执行一次 `-Install`；中断过就重跑同一条命令 |
| pip 下载慢、超时 | 设置 `PIP_INDEX_URL` 镜像后重跑 `-Install`（见“二、安装”） |
| 双击 `TeachMeChat.pyw` 没反应 | 系统未关联 .py/.pyw；改用上面的 PowerShell 命令启动 |
| 看到安全软件提示 | 应用需要读取本机微信进程内存以取数据库密钥，可能被安全软件关注。本项目**不会**通过关闭防护、隐藏行为来规避提示；请自行判断是否放行，或改用不用读进程的手动方式 |
| 提示“检测到多个微信进程” | 关闭多余的微信实例，或使用手动连接方式 |
| 提示 405 / 版本不在支持表 | 见 WECHAT_COMPAT 的三条替代路径（手动目录 + 密钥 / 明文快照 / 手动输入） |
| 提示权限不足、无法只读访问微信进程 | 让应用与微信以相同权限级别运行，或改用手动目录 + 密钥 |
| 看不到新消息 | 依次检查：是否用的快照模式（快照需重新导出）、自动刷新是否开启（每 5 秒检查）、微信是否重启过（需重新连接） |
| “获取模型”失败 | 见“四、首次配置”第 3 条的三个排查方向 |

## 七、更新与卸载

- **更新**：`git pull`（或重新下载 ZIP 覆盖）后，重跑一次 `-Install`（补齐新增依赖），再启动。
- **卸载**：关闭应用后删除项目文件夹即可——venv、缓存、临时文件全在里面；若用过默认配置目录，再删除 `C:\TeachMeChat`。本程序不修改系统 Python、不设置持久环境变量，没有其他系统改动需要清理。

## 八、运行目录与磁盘策略

所有本程序可控制的文件都在项目内的 `.teachmechat-runtime`（venv、pip / PyTorch / HuggingFace 缓存、临时媒体、Whisper 权重）。**想把依赖放到哪个盘，就把项目整个放在该盘**，例如 `D:\TeachMeChat`。配置（很小）默认在 `C:\TeachMeChat`，可在向导中改到任意本地目录，或用 `-ConfigDir D:\TeachMeChatConfig` 指定。

（以 `python -m teachmechat` 直接运行时，还可用环境变量 `TEACHMECHAT_HOME` 指向自定义运行目录；启动脚本固定使用项目内 `.teachmechat-runtime`。）

## 隐私与安全边界

- **只出草稿**：不自动发送消息、不自动点击微信、不写入微信源数据库。
- **明确授权**：连接微信、变更外发范围、切换服务商都需要你确认；聊天内容只会发送到你配置的模型 API。
- **凭据保护**：API Key 默认经 Windows DPAPI 当前用户加密保存（或选择不保存）；微信数据库密钥只留在内存。
- **透明**：不通过隐藏进程、关闭防护、绕过安全软件来“消除提示”；读取微信进程可能触发安全软件关注，属预期行为。
- 使用者须确保对所处理的数据拥有合法访问权，并遵守适用法律与微信软件许可协议。本项目与腾讯公司、微信官方无关。

## 更多文档

- 完整使用说明（界面细节、推理档位、媒体处理）：[teachmechat/README.md](teachmechat/README.md)
- 微信 3.x / 4.x 适配、连接时序、未验证项：[teachmechat/WECHAT_COMPAT.md](teachmechat/WECHAT_COMPAT.md)
- 发布审计与已识别边界：[teachmechat/RELEASE_AUDIT.md](teachmechat/RELEASE_AUDIT.md)
- 验证记录（实际通过 / 跳过结果）：[teachmechat/VERIFICATION.md](teachmechat/VERIFICATION.md)
- 贡献指南：[teachmechat/CONTRIBUTING.md](teachmechat/CONTRIBUTING.md) ｜ 安全策略：[teachmechat/SECURITY.md](teachmechat/SECURITY.md)
- 推广介绍文案：[teachmechat/PROMO.md](teachmechat/PROMO.md) ｜ 上游原始 README：[README-UPSTREAM.md](README-UPSTREAM.md)

## 许可与归属

- 上游 `LC044/WeChatMsg`：MIT，Copyright (c) 2024 SiYuan，见根 [LICENSE](LICENSE)。
- TeachMeChat 新增代码：**MIT License，Copyright (c) 2026 skywalkertzh**，见 [teachmechat/LICENSE](teachmechat/LICENSE) 与 [NOTICE.md](teachmechat/NOTICE.md)。
- 第三方依赖的许可记录及尚未完成的核验项：[teachmechat/THIRD_PARTY.md](teachmechat/THIRD_PARTY.md)。

**当前为桌面预览版**：核心流程可用，但不宣称对所有微信版本、所有环境全面兼容——自动连接失败时请使用手动方式；新机器安装、真实模型服务兼容性与 GPU 路径等仍需更多实测。
