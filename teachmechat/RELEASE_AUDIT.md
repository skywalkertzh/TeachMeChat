# TeachMeChat 发布审计与整改记录

## 判定

**桌面预览版，适合受控试用；尚未达到可宣称全面兼容、已签名的公开稳定发行标准。**

本轮按职责分离、最小权限、失败安全、显式授权、可复现性和测试可追溯原则检查。审计为源码审查与合成测试，不读取用户真实微信、配置、聊天或密钥。UI 从终端演示迁移为 PySide6 桌面，CLI 保留诊断用途。

## 已整改

| 优先级 | 原问题 | 当前处理与证据 |
|---|---|---|
| P1 | 媒体取消后仍可能新发起建议请求 | services.analyze_context 在各阶段检查取消；LLMClient 每次 HTTP/重试执行 guard；桌面用共享取消事件与隔离工作进程；test_desktop/CancellationBoundaryTests、test_providers/RequestGuardTests |
| P1 | 读取失效后旧内容继续分析或显示当前 | Scheduler generation/version/stale；桌面撤销同意、停旧分析并校验会话 ID，旧读取不得混入新会话；test_runtime_scheduler、test_desktop |
| P1 | 运行数据可能误入发布包 | 整体忽略 runtime，release.py 使用逐文件允许清单，不扫描聊天目录；合成敏感标记和链接边界测试 |
| P2 | R 同时刷新与生成抢跑旧上下文 | Scheduler 刷新屏障；桌面等待所选会话读取完成再生成 |
| P2 | 无统一查询截止 | SQL progress handler、总操作deadline、内容/语音SQL大小上限、有界目录发现；桌面worker超时结束本程序任务 |
| P2 | 多层请求重试难控制 | 文本与视觉共享每轮RequestBudget，包含HTTP重试；桌面失败即暂停自动分析，请求计数可见，避免无限收费；不虚构货币费用 |
| P2 | API 配置保存后不能完整恢复 | schema v1、完整主/视觉配置、DPAPI当前用户密钥、目录owner/DACL、绑定服务原点、损坏不覆盖；真实Windows DPAPI合成测试 |
| P2 | 供应商仅菜单无协议 | 统一ProviderSpec；GLM/Kimi OpenAI兼容，Anthropic原生Messages+schema+图片；离线协议契约测试 |
| P2 | 发布过程缺少清单 | 显式源码清单、SHA-256 manifest、固定环境版本、第三方许可待办；不自动上传 |

## 仍需验证或完善的发布阻碍

1. **真实兼容矩阵**：未对所有微信3.x/4.x构建、登录态、多账号、Windows权限组合做测试。用户反馈个人环境可用不等于全面兼容。
2. **同进程换号**：现有自动源主要绑定PID/启动时间和原数据库目录。未证明所有微信版本同进程账号切换都能检测。不能确认时用户必须断开重连；当前不宣传无缝多账号跟踪。
3. **真实外部服务**：GLM/Anthropic/Kimi为官方普通接口模板，具体模型、JSON/思考/视觉能力和账号权限由探测验证；本轮未发送真实聊天或使用真实API Key。
4. **本地ASR**：真实Whisper/GPU性能、内存峰值及取消未完成环境矩阵；大型模型依赖未默认安装。桌面可取消/终止本程序工作进程，不保证服务端已收请求能撤销收费。
5. **正式发行**：签名、安装卸载、无E盘机器支持、Windows沙盒/新机器安装和依赖许可全量审核尚未完成。当前运行数据策略保留本用户E盘约束，不是通用便携发行版。
6. **异常终止残留**：正常媒体任务清理临时文件，强杀/断电仍可能留下本程序临时媒体；发布包不会收集它们。自动清理只可针对明确归本程序所有的目录，不能删除用户文件。
7. **费用估算**：实现每轮次数上限而不是精确货币预算；不同模型价格和服务端计费不可由本机保证。
8. **读取只读表述**：不执行源库业务写入、checkpoint、rekey或迁移；SQLite WAL共享内存/锁文件有正常引擎行为，不能保证整个源目录字节绝对不变。
9. **发布门禁环境**：--release-check 禁止任何skip，并要求非空测试；若Git工具缺失导致ignore行为用例跳过，必须报告门禁失败而不是忽略。

## 安全与隐私约束

- 默认 C:\TeachMeChat 仅保存小型配置与加密凭据，首次向导由用户确认创建；依赖、模型、缓存和临时文件留在 E 盘。
- Key绑定当前Windows用户和服务原点；改服务地址须重新输入，无法解密不回退明文。
- 记住API配置不等于永久允许上传聊天；连接/切换会话/更换服务后重新确认范围。
- 复制建议必须用户点击，不自动发微信，不自动打开聊天链接。
- 没有通过隐藏进程、绕过安全软件或关闭防护来避免提示。读取自有微信进程仍可能触发安全软件关注，应透明说明。

## 验证方式

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -Tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-TeachMeChat.ps1 -ReleaseCheck
.\.teachmechat-runtime\venv\Scripts\python.exe -B release.py --check
```

最新实际运行数量及跳过项见 VERIFICATION.md。此文档是工程审计记录，不是法律认证或安全认证。
