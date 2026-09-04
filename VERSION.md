# TiRTC WT9932P4C61-TINY Device App Version

| 项目 | 内容 |
| --- | --- |
| 应用工程 | TiRTC WT9932P4C61-TINY Device App |
| 应用版本 | `1.0.2`，启明独立板型维护版本 |
| 比较基线 | `esp32-p4-wt9932p4c61-tiny-device-app-v1.0.1` |
| 独立源码仓 | https://github.com/tangeai/tirtc-device-qiming |
| 项目 Tag | `esp32-p4-wt9932p4c61-tiny-device-app-v1.0.2` |
| 发布范围 | Git 提供源码；同版本 Release 提供应用 BIN、16 MiB 完整镜像、烧录说明和校验清单 |
| 目标芯片 | ESP32-P4 |
| 目标开发板 | WT9932P4C61-TINY / WT01P461-S1 |
| ESP-IDF | `5.5.4` |
| TiRTC SDK | `2.3.0` ESP32-P4 package |
| 板级参考 | Wireless-Tag `WT_BSP` / `a1ee353fee9dc4de56709c00d764edc7bbcd18b1` |
| TiRTC Nano | `13e34c3e3e3dc6776be4713b5c1e3c17bd282766` |
| tgwebrtc | baseline `e39114731ad488c88573d16f0855a1326d97c989`, closure `24ccd07e124ef0503dd5ed2d79a1bbf5e46e780a` |
| TGTRP | `v1.5.10` |
| TiRTC P4 library MD5 | `399aee6a9e81eceb36af2a0366e02e45` |
| TiRTC P4 library SHA-256 | `719d6fa90be6318a7052d5e5cb9b068014b04181a1aa951a5aa7331af1d39393` |
| `tiRTC.h` SHA-256 | `a53fa3392f71c8fd15c77891a772cc20939b5d253b995b3382486e514c134473` |
| ESP-Hosted | local `2.12.12`, upstream `098525357e19c81099f2c3769938bd877190a8f5` |
| ESP-Hosted SDIO source SHA-256 | `a7077b0be0419a268f7b04aa1d9d5e029264325b5d909c7e98665b0235e0d27f` |
| H264 组件 | 本地 `1.3.6`，保留板级内存适配并回移开发组件的强制下一帧 IDR 接口 |

## SDK 契约

- `TIRTC_VERSION_MAJOR/MINOR/PATCH` 为 `2.3.0`。
- 当前 P4 Release 构建库包含主动连接失败资源清理、TURN 轻量查询 key、NACK scratch/容量修复和 12KB connection RTC task 栈。
- FreeRTOS tick 为 `1000Hz`，trace、stats formatting 和 runtime stats 关闭。
- APP 的 `CONFIG_LWIP_MAX_SOCKETS=16`。SDK 历史元信息写为 `10`，原始构建配置快照未找回；本版按已接受的配置证据缺口保留，不据此宣称存在运行时不匹配，也未改变库和 APP 参数。
- 启用 SDK 码率自适应时，在连接建立后注册 `TiRtcConnSetVideoBitrateParams()`。
- 启用后，`on_update_bitrate()` 只投递绝对目标码率到应用控制任务，不在 SDK 回调线程内调整编码器。
- `TIRTC_VIDEO_JPEG` 用于微信 VoIP MJPEG 下行。
- 详细文件级校验见 `components/tirtc_sdk/SHA256SUMS.txt`。

## 当前移植能力

- ST7102 DSI 显示和 ST7123 触摸使用 `640x480` 横屏 UI。
- SC2336 使用原生 `1024x600@30fps` YUV420 采集；IPC H264 上行为 `1024x600@20fps`、目标码率 `4Mbps`。
- ESP32-C61 使用 ESP-Hosted SDIO：CLK18、CMD19、D0-D3 为 14/15/16/17、复位 GPIO13。
- ESP-Hosted 以仓内本地组件固定在 `2.12.12`，SDIO 层保留 C61/P4 已验证的 PSRAM DMA 双缓冲、显式所有权队列和背压策略。
- 设备间 H264 双向视频和微信 H264 上行/MJPEG 下行保留原业务链路。
- 音频底板资料未提供，采集、播放和 AEC 当前由板级能力门控关闭。
- 传输类型由服务端协商为 TGTRP 或 KCP；TGMP 与本地自动弱网降级均默认关闭，避免两个控制器同时改写编码器策略。
- JPEG 解码器、H264 编码器和 RTC 媒体池在启动早期预热。

## 安全边界

源码默认不包含真实 Wi-Fi 密码、设备密钥、access key、token 或个人账号。设备凭证通过绑定流程写入 NVS。

RTC 服务地址保留调用方配置的协议，移除按 SDK 版本将 HTTPS 静默降级到 HTTP 的旧兼容逻辑；TLS 校验和连接失败仍由 SDK 原路径处理。

## 验证边界

- 版本、源码范围、SDK 校验、引用和差异静态复核已完成；使用 ESP-IDF `5.5.4` 在唯一 `build` 目录完成 P4 APP、Bootloader 和 C61 从机的干净构建，均为 0 警告、0 错误。
- 构建前校验 IDF 环境版本及 P4/C61/SDIO 板级配置，避免缺失 Kconfig 环境变量时生成错误板型配置。
- 真机完成双向设备呼叫、微信视频、IPC 实时查看、应用退出和 10 轮资源生命周期回归；微信下行 90 秒样本未出现秒级停帧或解码失败。
- C61 独立 UDP 暖机回环、转发矩阵和弱网测试已完成；`96KB/s` 限速下 RTC 保持连接，`32KB/s` 严重弱网下 MQTT 可能断线，属于已知边界。
- 当前板型未接音频底板，麦克风、扬声器和 AEC 不在本次真机验收范围内。

源码来源、构建输入和公开范围见 [SOURCE_PROVENANCE.md](SOURCE_PROVENANCE.md)。
