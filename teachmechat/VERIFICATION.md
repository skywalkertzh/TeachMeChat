# TeachMeChat 0.2 桌面预览版验证记录

## 最新运行结果

- **本轮完整自动化：358 项，357 通过、1 跳过（缺 git），0 失败**，约 1047 秒；在外层文件夹改名为 `TeachMeChat` 后运行，venv 随目录移动后 `-Diagnostics` 与全量测试均正常。
- 新增 **Google Gemini 供应商**（`https://generativelanguage.googleapis.com/v1beta/openai`，OpenAI 兼容、Bearer 鉴权），供应商顺序 `openai → gemini → deepseek → glm → anthropic → kimi → custom`。
- 模型目录按 2026-10 联网核验的官方文档全量重写（共 49 条）：OpenAI 14、Anthropic 14、GLM 10、Kimi 4、DeepSeek 2、Gemini 5。含 gpt-6.1-sol/6-astra/6-sol·luna、gpt-5.6-sol·terra·luna、Claude fable/mythos-5-1 与 opus/sonnet/haiku 5-5、glm-5.3 系、gemini-3.8-flash 等；仅 Responses API 的型号（gpt-5.5-pro 等）不收录并在注释说明。逐型号档位与默认值均按官方来源登记，`model_catalog.py` 内保留来源链接与证据等级。
- 可移植改造：不再强制 E 盘，运行目录/缓存/模型默认位于项目内 `.teachmechat-runtime`（任意本机绝对路径，拒绝 UNC/相对路径）；可选 `TEACHMECHAT_REQUIRE_DRIVE=E:` 恢复严格盘符策略（作者机器默认行为不变）。启动器 Python 发现不再硬编码作者机器路径，改为 `-Python` / `TEACHMECHAT_PYTHON` / PATH。
- 开源文档：新增 NOTICE、LICENSE（teachmechat 目录）、CONTRIBUTING、SECURITY、CHANGELOG、PUBLISHING、WECHAT_COMPAT、PROMO 与 GitHub Actions 工作流；`release.py --check` 现覆盖 **84 项**显式源码文件。
- 液晶屏字体整体放大（消息20px、详情16px、1.5倍点阵），红绿双灯移入液晶屏内部右侧；生成红灯、完成绿灯、断开表情与测试同步更新。
- 新增300/500条消息最新贴底、短消息贴底、增量追加、历史锚点、resize及1000/5000条分批加载回归；5秒自动刷新开关鼠标/键盘、环形刷新按钮、分析重点字重与HTML不执行均通过。5000条不是虚拟列表，首次创建仍需时间；分批让出事件循环，不宣称5000条瞬时完成。
- 原生 Windows Qt 插件另跑 **7项合成窗口测试通过**，含实际最小化/最大化/还原/关闭、尺寸恢复与圆角裁剪。系统拖动/缩放只验证命中计算和系统API调用，未宣称已人工拖拽验证。
- 跳过项：Git不在本机PATH，无法执行Git本身的ignore匹配行为测试；静态规则及发布包允许清单测试通过。
- 严格发布门禁：**仍未通过**。既有Git跳过项未解决，本轮不把普通测试成功宣称为正式发布通过。
- 官方来源：OpenAI 模型/退役/推理文档，Anthropic `anthropics/skills` 与官方站，智谱 `docs.bigmodel.cn`，Kimi `platform.kimi.com`，DeepSeek Chat Completion 文档，Google `ai.google.dev` 兼容端点与逐模型页。官方站点对本次部分抓取有 403/超时，已用官方仓库文档与代理页交叉核对并标注证据等级；未调用真实模型 API 复核。
- PowerShell主启动器语法解析：0错误。
- PySide6 6.8.3已安装于E盘虚拟环境，锁文件记录Windows x64/Python3.10.20的实际依赖版本。
- 没有创建真实 `C:\TeachMeChat`（仅在设置中作为默认建议目录），没有读取用户保存的API配置、聊天、密钥或真实媒体。

## 已验证

### 数据与模型

- 原有合成SQLCipher V3/V4及未checkpoint WAL读取、主库/WAL内容不变、SHM缺失拒绝、只读SQL保护。
- 新增SQL总预算/progress取消、有界目录、内容与语音大小限制。
- GLM/Kimi协议模板、原生Anthropic endpoint/header/system/image/text/stop_reason/JSON schema；fake transport及本机mock，无真实服务调用。
- 每轮共享请求预算、每次HTTP尝试前取消守卫；媒体返回后取消不调用建议生成。
- Scheduler刷新屏障、generation/version、read_error失效、迟到结果陈旧、暂停、不可重试错误及close。

### 配置与桌面

- Windows真实DPAPI使用合成Key往返，主/视觉配置完整恢复；域/端口/provider/profile篡改拒绝。
- 目录owner、当前用户DACL、链接拒绝、原子写失败、损坏配置不覆盖及位置指针。
- 保存后重新打开桌面，直接恢复API配置而不弹出配置向导（合成临时目录）。
- 设置表单供应商模板、Key掩码、地址改变清空Key、三种保存方式、取消不写、媒体与刷新字段。
- 模型可下拉选择或手填；模型列表仅显式GET，分页/响应数量有界，更新配置后旧列表不能覆盖；第三方URL和Key不因选模型改变。
- gpt/o系、已登记Claude adaptive及GLM/Kimi/DeepSeek按精确ID和协议转换推理参数；未知别名保留默认，旧Anthropic预算序列化兼容。
- 桌面旧会话读取丢弃、失效撤销授权、暂停取消、显式复制、模型文字纯文本展示。
- 真正spawn本程序工作进程，使用手动合成源完成IPC并结束；不发现真实微信进程。

### 视觉检查

实际创建Qt窗口并截图检查，全部使用虚构联系人和合成消息：
- 主窗口1360×860、100%缩放。
- 窄窗口1000×700、150%缩放：回复卡片滚动，不截断主操作。
- 服务设置窗口：表单可滚动，Key掩码，保存按钮可见。

本轮重新检查浅色主界面和简化设置页：正文为纯文本气泡，分享XML显示标题/摘要/来源，未知群成员稳定区分；100%/150%缩放下可滚动。截图在E盘runtime/previews，未进入源码发布允许清单。聊天摘要只用于展示，不更改源消息或模型上下文。

## 没有被证明的事项

- 真实微信各构建版本、多账号/同进程换号、自动取钥与真实聊天端到端可靠性。
- 真实API模型权限、实际JSON/思考/视觉能力和费用；探测由用户主动执行。
- 真实Whisper turbo/GPU性能和模型下载；本轮未安装torch/whisper或权重。
- 新机器干净安装、签名与卸载、完整许可证审核、无E盘环境支持。
- 操作系统、Qt、宿主ZCode自身系统行为完全不写C盘。应用受控cache/temp/依赖位于E盘，小型配置按用户新需求可在C盘。
- SQLite正常WAL共享内存/锁行为的整个目录零写入；测试主库/WAL字节比较不包括SHM。

## 复现

```powershell
# 在项目根目录（外文件夹已改名为 TeachMeChat）执行
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -ReleaseCheck
.\.teachmechat-runtime\venv\Scripts\python.exe -B release.py --check
```

发布判定与尚未关闭的审计项见 RELEASE_AUDIT.md；测试通过不等于已经公开发布或完成安全认证。
