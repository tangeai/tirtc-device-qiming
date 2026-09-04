# 源码来源与公开边界

本文记录启明 WT9932P4C61-TINY Device Monitor `1.0.1` 的源码、SDK、板级从机和验证边界。

## 版本身份

| 项目 | 内容 |
| --- | --- |
| 独立仓库 | https://github.com/tangeai/tirtc-device-qiming |
| 应用版本 | `1.0.1` |
| 比较基线 | `esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0` |
| 发布 Tag | `esp32-p4-wt9932p4c61-tiny-device-app-v1.0.1` |
| 目标板 | WT9932P4C61-TINY / WT01P461-S1 |
| ESP-IDF | `5.5.4` |
| 板级移植依据 | Wireless-Tag WT_BSP `a1ee353fee9dc4de56709c00d764edc7bbcd18b1` |

正式源码身份由 annotated Tag 及其 peeled commit 确定：

```powershell
git rev-parse esp32-p4-wt9932p4c61-tiny-device-app-v1.0.1
git rev-parse "esp32-p4-wt9932p4c61-tiny-device-app-v1.0.1^{commit}"
```

`1.0.0` Tag 保持不动；`1.0.1` 是其后的启明板型补丁版本。

## 公开范围

- 包含本板 APP、板级配置、必要 UI 资源、测试工具和实际链接的 P4 SDK。
- 保留 `sdkconfig` 与 `sdkconfig.defaults`，固定 P4、C61、SDIO、分区和媒体配置。
- C61 从机只提交可追溯的上游契约、覆盖层和构建脚本；生成源码和构建输出留在已忽略的 `.work`。
- 本地 ESP-Hosted、ESP Video 和 H264 含项目补丁，不描述为未修改的上游组件。
- 不包含真实 Wi-Fi 密码、设备密钥、Token、个人路径、运行日志或临时诊断库。
- BIN、ELF、MAP、构建目录和 `release_assets` 不进入 Git。烧录文件只作为同版本 Release 附件。

仓内必要的预编译 SDK `.a` 是源码构建依赖，不是可直接烧录的固件。

## TiRTC SDK 契约

| 项目 | 内容 |
| --- | --- |
| API 版本 | `2.3.0` |
| Nano source | `13e34c3e3e3dc6776be4713b5c1e3c17bd282766` |
| TGWebRTC baseline | `e39114731ad488c88573d16f0855a1326d97c989` |
| TGWebRTC closure | `24ccd07e124ef0503dd5ed2d79a1bbf5e46e780a` |
| TGTRP interface | `v1.5.10` |
| P4 library SHA-256 | `719d6fa90be6318a7052d5e5cb9b068014b04181a1aa951a5aa7331af1d39393` |
| `tiRTC.h` SHA-256 | `a53fa3392f71c8fd15c77891a772cc20939b5d253b995b3382486e514c134473` |

文件级依据见 [SDK 版本契约](components/tirtc_sdk/VERSION.md) 和
[SDK 校验清单](components/tirtc_sdk/SHA256SUMS.txt)。当前库不含
MRX/TRX/TTX/JTL/KG/KR/IRX/NET、socket/ICE 发送失败或 TGTRP poll 临时诊断标记。

## C61 从机契约

P4 主机使用本地 ESP-Hosted `2.12.12` 和 Wi-Fi Remote `1.6.3`；无线从机以
`espressif/esp_hosted` `2.12.11` 的 `slave` 示例为固定上游。来源、精确覆盖文件和
SHA-256 记录在 [C61 source manifest](coprocessor/esp32c61/source-manifest.json)。

C61 覆盖层保留 SDIO streaming、媒体优先内存策略、有界 RX 背压、独立 UDP 探针和
限频统计。P4 与 C61 是两个芯片，构建和烧录文件必须分别标明目标，不能混烧。

## 预发布构建证据

P4 和 C61 均使用 ESP-IDF `5.5.4`、GCC `14.2.0_20260121`，各自只使用一个构建目录。
预发布阶段执行干净构建，编译器警告、CMake 警告和错误均为 `0`。下列哈希用于锁定
已完成真机验证的候选；正式 Release 文件的最终哈希以随附件提供的 manifest 和清单为准。

| 输出 | 大小 | SHA-256 |
| --- | ---: | --- |
| P4 应用 BIN | `7,108,960` bytes | `8266e745219479809c0afbc18d257621bbc10ac490f92d921846822d095d944f` |
| P4 ELF | 开发侧保留 | `fb7f09d11c0f0420d82d500676f532aaf04fbc5d3b0fbe2b410c9173adb2c58c` |
| C61 `network_adapter.bin` | `967,840` bytes | `f76daa4897c5e5eb9cd1b58eae528799fdc6c86acdd222f0d33d194c1b3e1120` |
| C61 ELF | 开发侧保留 | `aba4e3849b3fdb951575a031c71677c9023f574cc0c4b8991991fdcbd9ecc0d2` |
| C61 4 MiB 完整镜像 | `4,194,304` bytes | `38156cb1916110cee9ebb9dc0421f69b82859cb4cccd134b9fe3e9f38d1a9444` |

P4 应用占用 `0x6c7960 / 0x730000` bytes，剩余 `0x686a0` bytes，构建工具显示 `6%`。
当前 `sdkconfig` SHA-256 为
`3002a5b500092aa03ac427996a99f58838dd63ea2c1c93c1b1c1383d4a3d4b26`。

正式 Release 阶段从最终 Tag 对应的唯一 P4 构建输出生成应用 BIN 和 16 MiB 完整镜像，
再生成 `release-manifest.json`、`SHA256SUMS.txt` 和烧录说明；这些产物不提交到 Git。

## 真机证据与边界

- 最终 P4 干净构建候选已烧录到 COM7，启动后内存完整性为 `1`，分配失败计数为 `0`。
- 同一候选已通过 ThingConnect IPC 实时查看，网页显示持续画面；退出后媒体任务停止、队列清空。
- 同一功能代码已完成设备呼叫双角色、微信下行 90 秒、IPC、AI 入口和 10 轮应用生命周期回归。
- C61 精确构建已通过 P4 CPOTA 安装并回读 ELF SHA；暖机双向 UDP、转发矩阵和接收隔离测试通过。
- 双向弱网在 `96KB/s` 限速下 RTC 保持连接并触发视频自适应；`32KB/s` 严重弱网下 MQTT 可能断线。

当前只枚举到一台启明 P4，第二台设备的精确最终候选双机复测尚未进行；双角色呼叫证据来自
相同功能代码、版本号和文档收口前的构建。音频底板未接入，麦克风、扬声器和 AEC 不在本次验收范围内。
静态检查、构建、烧录、联网、媒体效果和长期稳定性属于不同证据，不能互相替代。
