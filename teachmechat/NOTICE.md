# NOTICE · 版权与许可说明

本文档说明 TeachMeChat（交我聊，`teachmechat/` 目录）的版权与许可边界，方便发布者与使用者理解代码来源。本文档不构成法律意见。

## teachmechat 新增代码：MIT 许可

`teachmechat/` 目录下的新增代码以 **MIT 许可**发布，与仓库根目录 [LICENSE](../LICENSE) 一致。

> **TeachMeChat 新增代码版权**：Copyright (c) 2026 skywalkertzh

## 与 LC044/WeChatMsg（留痕 / MemoTrace）的关系

本仓库基于 [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) 的源码二次开发；上游项目在界面与文档中也使用“留痕 / MemoTrace”名称。根目录 [LICENSE](../LICENSE) 为 MIT，Copyright (c) 2024 SiYuan。

TeachMeChat 复用并以**只读**方式调用其 `wxManager/decrypt` 部分源码（例如 `common.py`、`wx_info_v3.py`、`wx_info_v4.py`、`decrypt_dat.py`、`version_list.json`），用于在用户本机读取用户自己的微信数据。TeachMeChat 不修改、不覆盖、不写入微信原始数据库，也不改变 MemoTrace 原有代码的许可。

## 第三方依赖

第三方依赖及其许可证记录见 [THIRD_PARTY.md](THIRD_PARTY.md)。该清单**尚未完成全面核验**：公开发布前必须由发布者逐项核验依赖、原生库与 Qt 组件的许可证义务，并保留必要的上游版权与许可证声明。

`release.py` 生成的源码包只包含显式允许清单中的源码与文档，不打包任何第三方 wheel、Qt 二进制或模型权重；包内 `MANIFEST.json` 只证明文件哈希，不代表安全审计或许可证审计已完成。

## 免责声明与使用边界

- 本工具是独立的第三方项目，**与腾讯公司及微信官方没有任何关系**，不代表、也不受其授权或背书。
- **使用者必须自行确保对所使用的数据拥有合法访问权**（例如本机登录账号自身的聊天数据），并遵守当地法律法规、微信软件许可协议及他人隐私。
- TeachMeChat **不提供、不包含任何绕过授权或安全机制的功能**：不破解他人账号、不绕过登录或权限校验、不导出你无权访问的数据，也不提供关闭系统安全防护的手段。
