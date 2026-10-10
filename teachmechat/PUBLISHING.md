# PUBLISHING · 发布清单（作者专用）

本文档是发布者把 TeachMeChat（交我聊）公开到 GitHub 前的操作清单。**按顺序执行，任何一步未通过都先停下修复。** 命令均为 Windows PowerShell 风格，`<项目目录>` 指你本机克隆/解压该仓库的路径占位符。

## a) 检查工作区没有私人数据

在 `<项目目录>` 下打开 PowerShell：

```powershell
cd <项目目录>

# 1. 按名称列出工作区中的个人数据目录与个人脚本（存在是正常的，关键是被忽略、不入库）
Get-ChildItem -Force | Where-Object { $_.Name -match '^(wxid_|.*_decrypted_)' } | Select-Object Name

# 2. 检查所有将进入提交的文件内容：搜索关键词（wxid_、本机绝对路径、你的联系人名/拼音等）
git grep -n -I -e 'wxid_' -e '<你的本机路径特征词>' -e '<你的联系人名>' -- .
# 预期：仅剩合成数据（wxid_synthetic_*）与文档/测试中的示例；出现真实 wxid 或本机绝对路径必须逐一清理

# 3. 检查未跟踪且未被忽略的文件（这些一旦 git add 就会入库）
git status --short --untracked-files=all
# 预期：只有你本次准备发布的源码/文档改动

# 4. 确认忽略规则确实生效（每条都应输出匹配的 .gitignore 规则）
git check-ignore -v "wxid_demo" "wxid_demo_decrypted_20260101-000000" "日志文件-2026-01-01-log.log" "data/example.db"

# 5. 确认已跟踪文件中没有私人数据类别
git ls-files | Select-String -Pattern 'wxid_|_decrypted_|\.db$|\.log$'
# 预期：无输出；如有输出，先 git rm --cached <路径> 并补充 .gitignore，再继续
```

必须同时满足：`wxid_*/`、`*_decrypted_*/`、`日志文件-*.log`（及 `*.log`）、`*.db` 以及你的任何个人导出脚本 **全部不入库**。

个人脚本的真实文件名不要写进共享 `.gitignore`（该文件会随源码发布，等于泄露联系人名）。把它们加入只在本机生效、永不提交的 `.git/info/exclude`：

```powershell
# 仓库初始化后执行一次；把 <你的个人脚本模式> 换成实际文件名模式（可多行）
Add-Content -Path .git\info\exclude -Value '<你的个人脚本模式>.py'
git status --short --untracked-files=all   # 再次确认个人脚本不出现
```

## b) 运行测试与检查

```powershell
python -m teachmechat --test
python -m teachmechat --release-check
python release.py --check
```

- `--test`：普通测试，允许明确报告的 skip。
- `--release-check`：发布门禁，**不允许任何 skip**（关键测试缺失或被跳过会直接失败），必须全绿。
- `release.py --check`：只校验发布允许清单中的文件都存在且路径安全，不生成压缩包。**任何新增源码/文档文件在发布前都要先加入 `release.py` 的 `SOURCE_ALLOWLIST`**，否则不会进入源码包。

## c) 构建源码包

```powershell
python release.py --build
```

产物：`<项目目录>\.teachmechat-runtime\release\teachmechat-source.zip`（内含 `MANIFEST.json`）。内容说明：

- 只包含 `SOURCE_ALLOWLIST` 显式列出的文件：`teachmechat/` 源码与测试、`teachmechat/` 下全部文档（README、DESIGN、VERIFICATION、RELEASE_AUDIT、THIRD_PARTY、NOTICE、CONTRIBUTING、SECURITY、CHANGELOG、PUBLISHING）、根 `LICENSE`、`.gitignore`、启动脚本（`TeachMeChat.pyw`、`Start-TeachMeChat.ps1`、`Install-TeachMeChat-ASR.ps1`、`teachmechat/Preview-Desktop.ps1`）、`release.py`、`requirements.txt`、`requirements-lock.txt`，以及 `wxManager/decrypt` 的只读子集（`common.py`、`wx_info_v3.py`、`wx_info_v4.py`、`decrypt_dat.py`、`version_list.json`）。
- `MANIFEST.json` 记录每个文件的 SHA256 哈希、大小与范围声明，并明确 `dependency_license_audit: not_performed`（哈希不等于许可审计）。
- **不包含**：虚拟环境、Qt/第三方 wheel、模型权重、任何数据库、密钥、日志、`.teachmechat-runtime`。
- 注意：输出与临时文件必须是**本机绝对路径**（默认在项目运行目录下，拒绝 UNC/网络路径）；如需强制固定在某个盘（例如作者的 E 盘），可设置环境变量 `TEACHMECHAT_REQUIRE_DRIVE=E:`。
- `.github/workflows/` 下的 CI 文件不进入源码包（`release.py` 的 `_safe_name` 只允许 `.py/.pyw/.md/.ps1` 后缀，且不在允许清单中），它只随 GitHub 仓库本身发布。

## d) 版本号提升与 CHANGELOG 更新

1. 修改 `teachmechat/__init__.py` 的 `__version__`（例如 `"0.2.0"` → `"0.3.0"`）。桌面“关于交我聊”对话框自动引用该值，无需再改界面代码。
2. 在 `teachmechat/CHANGELOG.md` 顶部新增对应版本段落（新增/修复/安全），日期用发布当天。
3. 确认 b) 步的三项检查在新版本号下重新跑通。

## e) 核对版权人

`teachmechat/LICENSE` 与 `teachmechat/NOTICE.md` 当前使用 `skywalkertzh` 作为 TeachMeChat 新增代码版权人；发布前确认这仍是你希望公开展示的名字或组织名。根 `LICENSE` 保留上游 Copyright (c) 2024 SiYuan，不得删除或覆盖。

## f) 创建 GitHub 仓库建议

- 仓库描述建议：`基于 LC044/WeChatMsg（留痕 / MemoTrace）二次开发的本地优先 Windows 微信回复草稿助手：只读读取、不自动发送。`
- Topics：`wechat`、`ai-assistant`、`pyside6`、`privacy`、`local-first`、`wechatmsg`
- README 首屏必须明确：上游仓库链接、上游 MIT 版权、二次开发关系、与腾讯/微信官方无关。
- 建议 default branch 使用 `main`；开启 Issues（已有 Issue 模板）；Wiki 可按需关闭。
- 若从现有本地仓库推送，请确保推送的是干净历史（不含私人数据提交）；必要时用全新 `git init` 的副本发布。

## g) 打 tag 与 Release

```powershell
git tag v0.2.0
git push origin v0.2.0
```

在 GitHub Releases 基于 tag 创建 Release，文案要点：

- 一句话定位与核心边界：**只生成本地草稿、不自动发送微信、只读读取、与腾讯/微信官方无关。**
- 本版本亮点（从 `CHANGELOG.md` 摘 3–5 条）。
- 安装与首次使用（指向 README 的启动/设置章节）。
- 附加 c) 步生成的 `teachmechat-source.zip`（含 MANIFEST）作为源码下载。
- 提醒使用者：只处理自己有权访问的数据，并自行核验 [THIRD_PARTY.md](../teachmechat/THIRD_PARTY.md) 中的第三方许可。

## h) 明确不可发布的内容

以下内容**永远不要**提交、推送到 GitHub 或放入任何 Release 附件：

- 解密后的微信数据库与快照：`wxid_*/`、`*_decrypted_*/`、任何 `*.db`。
- 模型权重（Whisper/PyTorch 等）与 `runtime`/虚拟环境（`.teachmechat-runtime/`、`venv*`、pip 缓存）。
- 作者个人导出脚本与产物：任何本机专用导出脚本（例如 `export_<联系人>_*.py`、`run_<联系人>_*.py`）、`.bat` 导出脚本、任何导出目录。
- 任何 API Key、凭据或配置文件：`credentials.json`、`settings.json`、`keys.json`、`.env*`。
- 日志文件（`*.log`）、系统凭据转储、微信安装信息或账号相关截图。

## i) 仓库命名与文件夹改名

外文件夹已由上游下载名 `WeChatMsgArchive-master` 改名为 **`TeachMeChat`**（与启动入口及文档标题一致）。在别的机器上重新解压/克隆发布包时会再得到下载时的默认名，按下面步骤改回即可。

步骤（PowerShell，在仓库的**上一级**目录执行；先关闭正在运行的 TeachMeChat 应用，以及打开了该目录的编辑器/终端）：

```powershell
# 1. 进入仓库的上一级目录（将 <仓库上一级目录> 换成实际路径）
cd <仓库上一级目录>

# 2. 重命名外层文件夹（示例：改为 TeachMeChat）
Rename-Item -Path .\WeChatMsgArchive-master -NewName TeachMeChat

# 3. 若报“正被另一进程使用”：先关闭占用该目录的应用/编辑器/终端再重试；不要强制删除
```

注意事项：

- 只改**外层文件夹 / 仓库名**。内部包目录 `teachmechat/`、入口 `TeachMeChat.pyw`、启动脚本中的相对路径都以项目根为基准，`python -m teachmechat` 的 import 名保持不变；改外层名不需要改任何代码。本机改名后已验证 `-Diagnostics` 与 venv 在新路径可用。
- **git 仓库重命名不影响提交历史**（历史中不记录文件夹名）。GitHub 端可后续在仓库 Settings 中改名，旧地址会自动重定向。
- 运行目录 `.teachmechat-runtime` 位于项目内，会随文件夹一起移动；rename 后 venv 已实测可用。若个别环境残留创建时的绝对路径导致失败：先重跑一次 `-Install`；仍失败再删除 `.teachmechat-runtime` 重新安装（会重新下载依赖/模型，请预留时间）。
- 改名后重新执行 b) 节的测试与 `release.py --check`，确认路径改动没有影响发布流程。
- GitHub 仓库名建议 `TeachMeChat`；repository description 直接使用 [PROMO.md](PROMO.md) 中“GitHub 仓库简介”的原文（≤350 字符）。Topics 沿用 f) 节的建议。

## j) README 首屏导引（发布独立仓库时）

GitHub 仓库页首屏展示的是根目录 `README.md`。当前完整说明位于 `teachmechat/README.md`，发布独立仓库时二选一：

**方案 A（推荐）：根 README 导引到包内说明**

- 在仓库根新建 `README.md`，首屏写明项目名、一句话定位与隐私边界，并**明确链接到** `teachmechat/README.md` 获取完整说明；`teachmechat/` 内部的相对链接（DESIGN.md、VERIFICATION.md 等）保持原样即可继续有效。
- 同步保留上游 README，先改名再新增：

```powershell
# 在仓库根执行
Rename-Item -Path .\readme.md -NewName readme-upstream.md
```

**方案 B：把 teachmechat/README.md 复制为根 README.md**

- 先按上面的命令把上游 `readme.md` 改名为 `readme-upstream.md`（Windows 文件名不区分大小写，`readme.md` 与 `README.md` 不能同时存在，必须先改名）。
- 复制 `teachmechat/README.md` 为根 `README.md` 后，**必须把文中相对链接改为 `teachmechat/` 前缀**（如 `DESIGN.md` → `teachmechat/DESIGN.md`、`RELEASE_AUDIT.md` → `teachmechat/RELEASE_AUDIT.md`），否则在仓库页全部失效。

共同注意事项：

- **上游 MIT 署名必须保留**：根 `LICENSE` 中的上游版权段落、`readme-upstream.md`（上游项目名与链接）都不得删除；`teachmechat/NOTICE.md` 的版权人占位符按 e) 节替换。
- 新增的文档文件（`WECHAT_COMPAT.md`、`PROMO.md`，以及如要进入源码包的新根 `README.md`）需按 b) 节规则加入 `release.py` 的 `SOURCE_ALLOWLIST`，否则不会随源码包发布。
- 改动完成后按 c) 节重新构建源码包，确认 `MANIFEST.json` 中包含新文档。
