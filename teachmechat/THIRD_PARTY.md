# 第三方组件与分发边界

此项目源代码保留根目录 MIT LICENSE（Copyright 2024 SiYuan）。这不意味着第三方依赖全部采用 MIT，也不构成法律意见。

## 本机安装环境清单

从隔离环境包元数据读取；版本固定在 requirements-lock.txt。包元数据不足以证明其内含全部原生库的许可。

| 包 | 版本 | 元数据声明 |
|---|---|---|
| PySide6 / Addons / Essentials / shiboken6 | 6.8.3 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| aiofiles | 25.1.0 | Apache-2.0 |
| pillow | 12.3.0 | MIT-CMU |
| protobuf | 4.25.9 | BSD 3-Clause |
| psutil | 7.2.2 | BSD-3-Clause |
| pycryptodome | 3.24.0 | BSD / Public Domain |
| Pymem | 1.14.0 | MIT |
| pywin32 | 312 | PSF |
| xmltodict | 1.0.4 | MIT |
| yara-python | 4.5.4 | Apache 2.0 |
| zstandard | 0.25.0 | BSD-3-Clause |
| pysilk-mod | 1.6.4 | see LICENSE，需进一步核验 |
| lz4 / prompt_toolkit / sqlcipher3 / wcwidth | 见锁文件 | 本轮读取字段未声明完整许可，需进一步核验 |

## 公开发布前仍需完成

- 核对所使用 Qt 模块及其许可证、第三方声明与重新链接/替换等义务；源码使用与打包商业二进制不能混为一谈。
- 核对 SQLCipher wheel 内含引擎、密码库及编译依赖的许可证。
- 核对 SILK 解码器相关许可证和适用条件。
- 如打包 Whisper/PyTorch/模型权重，分别核对代码、模型与原生加速组件许可；它们当前未随应用安装或发布。
- 分发前生成完整软件物料清单，保留上游版权及必要的 LICENSE/NOTICE；最终由发布者核验。

当前 release.py 生成的是源码包，**不打包虚拟环境、Qt 二进制、第三方 wheel 或模型**。manifest 只能证明文件哈希，不代表安全审计或许可证审计完成。
