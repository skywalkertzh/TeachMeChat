# CONTRIBUTING · 贡献指南

感谢参与 TeachMeChat（交我聊）。贡献代码前请先阅读本指南；本项目以**隐私优先、只读、本地**为核心约束，违反这些约束的改动不会被接受。

## 开发环境

- Windows 10 / 11（桌面界面基于 PySide6；其他平台未验证）
- Python 3.10 或更高（当前验证环境为 Windows x64 / Python 3.10）
- 安装依赖（在仓库根目录执行）：

```powershell
python -m pip install -r teachmechat/requirements.txt
```

大型可选依赖（Whisper 权重、PyTorch 等）**不要**默认安装，按需参考 `Install-TeachMeChat-ASR.ps1`。

## 测试

```powershell
# 普通测试（合成数据与 fake API，允许明确 skip）
python -m teachmechat --test

# 发布门禁：关键测试不允许 skip，CI 不跑这一项
python -m teachmechat --release-check
```

- GUI 相关测试必须可以在无显示环境运行：设置环境变量 `QT_QPA_PLATFORM=offscreen`（测试入口会自带默认值，本地排查时显式设置更可靠）。
- 所有自动化测试只使用**合成数据、fake API 或本机模拟服务**，不读取真实微信数据、真实配置或真实 API Key。
- **禁止提交**真实聊天记录、密钥、解密导出、日志、`wxid_*`/`*_decrypted_*` 目录或任何真实账号数据；新测试只能内置虚构联系人（例如 `wxid_synthetic_*`）。

## 代码规则

- **只读微信源数据**：只通过 `wxManager/decrypt` 的只读路径读取用户数据，**绝不写入、修改或覆盖微信源数据库**。
- **密钥绝不落盘或打印**：API Key 只允许按现有 DPAPI 机制加密保存；日志、异常信息、测试输出中都不得出现明文密钥。
- **模型档位登记**：推理档位只按**精确模型 ID + 协议**匹配官方文档登记，并在 `model_catalog.py` 中写明来源链接；未知模型只给 `default`，不猜测能力。
- **新增供应商**：必须同时提交对应的协议测试（鉴权、请求体、结构化输出），不得静默降级到其他协议。
- **UI 文案使用中文**，保持与现有界面一致的术语与语气。
- **隐私优先**：不新增遥测、外发或自动上传行为；不自动发送微信消息；不为消除安全软件提示而关闭防护或隐藏行为。

## PR 检查清单

- [ ] `python -m teachmechat --test` 通过（列出 skip 项及原因）
- [ ] 未提交任何真实数据、密钥、导出或日志（自查 `git status`）
- [ ] 涉及微信读取的改动保持只读，没有写源库路径
- [ ] 涉及模型/供应商的改动附带来源链接或协议测试
- [ ] 新增文件已加入 `release.py` 的 `SOURCE_ALLOWLIST`（否则不会进入发布包）
- [ ] 界面文案为中文，截图只使用合成演示数据（`--demo`）

## 报告问题

- 功能缺陷与建议：使用仓库的 GitHub Issue 模板（问题 / 功能建议 / 提问）。
- 安全漏洞：**不要开公开 Issue**，请按 [SECURITY.md](SECURITY.md) 的方式私下报告。
