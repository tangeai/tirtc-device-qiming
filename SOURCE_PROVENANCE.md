# 源码来源与公开边界

本文记录启明 WT9932P4C61-TINY Device Monitor `1.0.0` 的源码身份、SDK 和验证事实。
项目在独立仓维护；文档风格对齐设备示例统一仓，硬件和功能契约以启明源码为准。

## 来源快照

| 项目 | 内容 |
| --- | --- |
| 独立仓库 | https://github.com/tangeai/tirtc-device-qiming |
| 应用版本 | `1.0.0` |
| 项目 Tag | `esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0` |
| 工程位置 | 仓库根目录 |
| 历史策略 | 一个无父提交的首版快照，旧开发历史另存仓外备份 |
| 目标板 | WT9932P4C61-TINY / WT01P461-S1 |
| 板级移植依据 | Wireless-Tag WT_BSP `a1ee353fee9dc4de56709c00d764edc7bbcd18b1` |
| ESP-IDF | `5.5.4` |

最终公开身份由 annotated Tag 和它指向的 commit 确定：

```powershell
git rev-parse esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0
git rev-parse "esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0^{commit}"
git rev-list --count HEAD
```

末条命令在该 Tag 的首版快照中应返回 `1`。
已编译的内部源码快照为 `89d3e535068bbee54d073b6aabecb2d7d4c5936a`，
tree 为 `b77ef8b915de84163eeaf0c34ab94941eee22eb1`。
该内部快照保存在仓外备份，不作为额外公开提交。公开收口仅调整 Markdown 和根目录 LICENSE，
所有代码、SDK、配置和构建脚本与已编译快照保持一致。

## 公开范围

- 包含本板 APP、板级配置、必要 UI 资源、工具以及实际链接的 P4 SDK。
- 保留 `sdkconfig` 与 `sdkconfig.defaults`，固定本轮启明 C61 配置输入。
- 本地 ESP-Hosted 和 H264 含项目补丁，不将它们描述为未修改的上游组件。
- 根目录 LICENSE 保留独立远端仓初始化时的 MIT 条款；第三方组件、SDK 和资源遵守各自许可证。
- 不包含旧 Git 调试历史、内部交接资料、真实凭据或个人机器配置。
- `build*/`、`managed_components/`、临时日志、BIN、ELF、MAP 和固件包不进入 Git。
- 当前仅交付源码，不生成 `release_assets`、`RELEASE.md`、`TEST_GUIDE.md` 或固件 Release 附件。

仓内必要的预编译 SDK `.a` 是应用依赖，不是可烧录的固件。

## TiRTC SDK 字节契约

| 项目 | 内容 |
| --- | --- |
| API 版本 | `2.3.0` |
| 包渠道 | P4 Release candidate；已用 Release 配置构建，不代表整机验收完成 |
| Nano source | `13e34c3e3e3dc6776be4713b5c1e3c17bd282766` |
| TGWebRTC baseline | `e39114731ad488c88573d16f0855a1326d97c989` |
| TGWebRTC closure | `24ccd07e124ef0503dd5ed2d79a1bbf5e46e780a` |
| TGTRP interface | `v1.5.10` |
| P4 library SHA-256 | `719d6fa90be6318a7052d5e5cb9b068014b04181a1aa951a5aa7331af1d39393` |
| tiRTC.h SHA-256 | `a53fa3392f71c8fd15c77891a772cc20939b5d253b995b3382486e514c134473` |

文件级依据见 [SDK 版本契约](components/tirtc_sdk/VERSION.md) 和
[SDK 校验清单](components/tirtc_sdk/SHA256SUMS.txt)。六项校验已通过。
两层构建均显式使用 `RELEASE=y`；noSCTP / noDTLS 为构建口径，
运行时 TGTRP 或 KCP 仍由服务端协商。

本包保留主动连接失败回收、TURN 轻量查询、NACK 工作区真实容量及 P4 connection RTC 栈
`12288` 字节的修复。临时 MRX/TRX/TTX/JTL/KG/KR/IRX/NET、
socket/ICE 发送失败和 TGTRP poll 诊断未纳入本库。

## 板级与组件边界

ESP-Hosted 为本地 `2.12.12`，上游提交
`098525357e19c81099f2c3769938bd877190a8f5`。其 SDIO 源文件 SHA-256 为
`a7077b0be0419a268f7b04aa1d9d5e029264325b5d909c7e98665b0235e0d27f`；
本地修改详见 [PATCHES](components/espressif__esp_hosted/PATCHES.md)。
Wi-Fi Remote 版本为 `1.6.3`。

H264 使用本地 `1.3.6` 组件，保留板级内存适配并回移强制下一帧 IDR 接口。
屏幕、触摸、摄像头和 C61 的引脚及方向属于本板契约，不从 Waveshare 默认值推导。
音频底板尚未适配，相关驱动和能力门控维持关闭。

## 构建与运行证据

本轮只在一个 `build` 目录进行开发验证，不制作公开固件资产。
已完成 ESP-IDF `5.5.4`、GCC `14.2.0_20260121`、Python `3.14.4` 下的无缓存重编：

| 检查 | 结果 |
| --- | --- |
| APP | `1865/1865` 构建步骤完成，退出码 `0` |
| Bootloader | `133/133` 构建步骤完成 |
| 编译警告 / 错误 | `0 / 0` |
| sdkconfig SHA-256 | `bbc9cbadbd206645b135c6e5a315c432b5ef0fc4bbc2c853741ec3dbb01f987b` |
| 本地构建日志 SHA-256 | `3f1c0f6c196e05985fed32317a918023bbeb9663cbde176cec354d4c194c3070` |
| 应用大小 / 分区大小 | `0x6c5760 / 0x730000` bytes |
| 分区剩余 | `0x6a8a0` bytes，约 `426KiB`，构建工具显示 `6%` |

构建后仅调整文档和许可证，通过 Git blob 比对确认其余输入不变。
本地构建日志和产物不随源码分发，日志哈希仅作为已留存开发证据的身份。
没有从最终 Tag 新增烧录证据，也未在全新开发环境重新解析和下载全部依赖。

本版本仍缺少精确 SDK 下的完整设备回归，包括双角色重复呼叫、微信小程序外部实呼、
弱网和长稳。微信下行卡顿尚未完成根因验证；音频、AI 对讲和 AEC 等待底板适配。
源码与 SDK 一致性、编译通过、网络可用、实际媒体效果和长期稳定性应分别验收。
