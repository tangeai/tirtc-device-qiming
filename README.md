# TiRTC 启明 WT9932P4C61-TINY Device Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![ESP-IDF](https://img.shields.io/badge/ESP--IDF-5.5.4-E7352C?logo=espressif)](https://docs.espressif.com/projects/esp-idf/)
[![Chip](https://img.shields.io/badge/Chip-ESP32--P4-000000)](https://www.espressif.com/en/products/socs/esp32-p4)
[![TiRTC SDK](https://img.shields.io/badge/TiRTC%20SDK-2.3.0-1769AA)](https://docs.tange.ai/products/tirtc/en/overview/what-is-tirtc.html)

这是面向启明云端 WT9932P4C61-TINY / WT01P461-S1 的完整设备应用。
ESP32-P4 负责摄像头、H264 编码、视频解码、触摸屏和业务 UI；
ESP32-C61 通过 ESP-Hosted/SDIO 提供 Wi-Fi。源码包含设备绑定、ThingConnect、
IPC、设备互呼、微信 VoIP、AI Chat 和 OTA 分层，当前板型未接入音频底板。

启明版本在本仓独立维护，文档入口与
[TiRTC 设备示例统一仓](https://github.com/tangeai/tirtc-device-example)保持一致的组织方式。
当前 `1.0.0` 只发布源码，不提供 BIN、完整烧录镜像或 `release_assets`。

## 从这里开始

| 目标 | 入口 |
| --- | --- |
| 安装环境、构建、烧录和完成首次联网 | [开发者上手指南](docs/GETTING_STARTED_CN.md) |
| 理解视频、PSRAM、SDIO 和连接归属 | [P4 媒体架构](docs/P4_MEDIA_ARCHITECTURE.md) |
| 核对应用、SDK、工具链和静态库哈希 | [版本契约](VERSION.md) |
| 核对开发来源、公开范围和验证边界 | [源码来源](SOURCE_PROVENANCE.md) |
| 核对开发板接口和电气连接 | [Wireless-Tag 板级资料](https://wiki.wireless-tag.com/docs/zh/WT9932P4C61-TINY/board_features.html) |

从本项目 Tag 开始，工程位于仓库根目录：

```powershell
git clone https://github.com/tangeai/tirtc-device-qiming.git
cd tirtc-device-qiming
git checkout esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0
```

## 版本身份

| 项目 | 当前值 |
| --- | --- |
| 应用版本 | `1.0.0` |
| 发布日期 | `2026-09-02` |
| 源码历史 | 首版独立快照，只保留一个初始提交 |
| 项目 Tag | `esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0` |
| 目标板 | WT9932P4C61-TINY / WT01P461-S1 |
| 网络 | ESP32-C61 + ESP-Hosted/SDIO |
| ESP-IDF | `5.5.4` |
| TiRTC SDK | `2.3.0` P4 Release 构建包，具体来源见版本契约 |
| 屏幕 | ST7102 `480x640` 物理面板，`640x480` 横屏 UI |
| 触摸 | ST7123，I2C0 GPIO7/GPIO8 |
| 摄像头 | SC2336，原生 `1024x600@30fps` YUV420 档位 |
| Flash | `16MB`，双 OTA 分区 |
| 音频 | 等待可选底板适配，当前禁用 |

P4 没有原生 Wi-Fi，构建 P4 工程不会更新 C61 从机固件。网络异常时，先核对
C61 固件与 ESP-Hosted 的兼容性、SDIO 接线及复位信号，再沿网络和业务日志定位。

## 主要能力

以下描述源码具备的路径；精确版本的真机验证状态见“启动与验证”。

- 屏幕配网，服务发现、绑定码、设备凭证保存和正式 MQTT/TiRTC 在线。
- IPC 使用 SC2336 YUV420 与 P4 H264 硬件编码上行，不启用本地摄像头预览。
- 设备呼叫保留 H264 上行和 constrained-baseline H264 下行。
- 微信 VoIP 保留 H264 上行、服务端 MJPEG 下行及 `640x480` 横屏显示。
- LVGL 页面覆盖 Wi-Fi、绑定、联系人、呼叫、设置和 OTA。
- 业务生命周期统一编排连接及媒体资源，大块媒体缓冲和适用的任务栈优先放入 PSRAM。
- 当前无麦克风、扬声器和 AEC；AI Chat 音频入口由板级能力门控，不宣称可用。

## 1.0.0 更新

- 固定启明屏幕、触摸、SC2336 和 C61 板级契约，独立于 Waveshare 板型维护。
- ESP-Hosted 固定为仓内 `2.12.12`，保留 PSRAM 双缓冲、明确的队列所有权及背压处理。
- TiRTC `2.3.0` 包包含主动连接失败回收、TURN 轻量查询、NACK 工作区容量修复，
  以及 P4 connection RTC 任务 `12KiB` 栈；临时传输诊断代码不随本包发布。
- 本地 H264 `1.3.6` 回移强制下一帧 IDR 接口，保留原有板级内存适配。
- 构建前校验 IDF 环境及 P4/C61/SDIO 配置，避免选错板型或漏载 Kconfig。
- 移除将 HTTPS 服务地址静默改为 HTTP 的旧兼容逻辑，保留配置协议和原有失败语义。
- 微信主动呼叫使用正式版参数；TGMP 与本地自动弱网降级均默认关闭。

## 默认媒体参数

方向均以启明设备为参照；这些是配置目标，不是实测帧率或画质承诺。

| 场景 | 当前源码默认值 |
| --- | --- |
| IPC 上行 | `1024x600@20fps`，`4Mbps`，H264，名义 GOP `2s` |
| 设备呼叫上行 | `384x256@12fps`，`256kbps`，H264，名义 GOP `4s` |
| 设备呼叫下行 | constrained-baseline H264，解码上限 `384x256`，等比例显示到 `640x480` |
| 微信上行 | `480x320@15fps`，`480kbps`，H264，名义 GOP `2s` |
| 微信下行 | 请求 MJPEG，长边 `480`、比例参数 `133`、方向参数 `1`、最高 `15fps` |
| 微信显示契约 | 屏幕 `640x480`，`object_fit=contain`，`video_res_mode=fit_screen` |
| 微信本地呈现 | 竖帧转横向后，PPA 等比 `cover` 到 `640x480`；与服务端显示请求分开 |
| 音频 / AEC | 底板未适配，关闭 |
| SDK/TGMP 码率控制 | 默认关闭 |
| 本地自动弱网降级 | 默认关闭 |

微信下行实际尺寸由微信与服务端共同决定，请求参数不等于实际输出。
TGTRP 或 KCP 由服务端协商，不能用 `p2p=kcp` 构建参数代替运行时结论。
首次出流、订阅恢复和关键帧请求仍可触发 IDR，名义 GOP 不等于故障等待时间。

## 配置与构建

Wi-Fi 在屏幕配置并保存到 NVS，设备凭证由绑定流程下发，不需要写入源码。
应用入口在 [app_config.h](main/application/app_config.h)，板级开关在
[Kconfig.projbuild](main/Kconfig.projbuild)，默认配置在 [sdkconfig.defaults](sdkconfig.defaults)，
媒体参数在 [media_tuning.h](main/media/media_tuning.h)。

进入已安装的 ESP-IDF `5.5.4` 环境后执行：

```powershell
. "$env:IDF_PATH\export.ps1"
idf.py -B build reconfigure build
```

本仓保留启明的 `sdkconfig` 和 `sdkconfig.defaults`，使用唯一 `build` 目录。
不要把当前已验证的 IDF 5.5.4 环境原地覆盖为 6.x。
本地开发烧录使用构建生成的 `build/flasher_args.json` 文件及偏移；
应用 BIN 不能单独写到 `0x0`。详细步骤见上手指南。

## 启动与验证

复位后先核对版本、板型和网络阶段；下面是日志字段示意，不是本次新采集的真机日志：

```text
firmware version: 1.0.0 project=tirtc_esp32p4_wt9932p4c61_tiny_device_app ...
system ready: board=wt9932p4c61_tiny_qiming display=1 touch=1 audio=0/0 camera=1
wifi connected: ssid=... ip=...
binding verification code ready: mqtt subscribed
```

开发侧已在唯一 `build` 目录完成 APP 和 Bootloader 无缓存重编，编译警告和错误均为 0。
此后只整理 Markdown 和许可证，业务代码、SDK、分区和配置未改变。
[源码来源](SOURCE_PROVENANCE.md)记录构建输入身份和验证边界。

当前 SDK 更换后的整机、重复连接、弱网和长稳回归尚未完成。
微信下行卡顿仍为待验证问题，本次不宣称已解决，也不以构建通过代替真机验收。

## 目录

```text
components/tirtc_sdk/  TiRTC 头文件、静态库和版本契约
main/application/      生命周期、业务状态和资源所有权
main/connectivity/     网络状态和 Wi-Fi 管理
main/drivers/          音频、摄像头、显示及测试媒体驱动
main/hardware/         启明 WT9932P4C61-TINY 板级能力与初始化
main/media/            摄像头 pipeline、像素转换和媒体策略
main/platform/         存储、时间、日志和内存策略
main/protocols/        HTTP、MQTT、RTC 和 TiRTC 适配
main/services/         绑定、在线、呼叫、VoIP、AI、IPC 和 OTA
main/ui/               LVGL 页面、布局和资源
docs/                  上手指南和媒体架构
tools/                 静态分析和媒体日志工具
```

UI 展示状态并分发动作，应用层编排生命周期，服务层实现业务，协议层持有连接，
媒体层处理帧，驱动层持有硬件。硬件差异在板级层维护，不向业务层复制特殊分支。

## License

项目许可证见 [LICENSE](LICENSE)。SDK、组件、字体和其他第三方资源保留各自许可证；
根目录 MIT 许可证不替代第三方授权条款。
