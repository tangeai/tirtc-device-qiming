# 启明 WT9932P4C61-TINY 上手指南

本文对应 Device Monitor `1.0.0`，补充板级环境和源码开发检查。
下载固件、网页/命令行烧录、配网绑定及各视频场景的完整步骤见 [使用教程](../README.md#使用教程)。
同版本 Release 提供应用 BIN、16 MiB 完整镜像及随包烧录说明。

## 准备硬件

| 项目 | 要求 |
| --- | --- |
| 主板 | WT9932P4C61-TINY / WT01P461-S1，ESP32-P4 |
| 无线从机 | ESP32-C61，预先安装与 ESP-Hosted `2.12.12` 兼容的 slave 固件 |
| 屏幕 / 触摸 | ST7102 / ST7123，本工程 UI 为 `640x480` 横屏 |
| 摄像头 | SC2336 MIPI，源码使用原生 `1024x600` YUV420 档位 |
| 供电与 USB | 稳定供电、可传数据的 USB 线，确认电脑能够识别串口 |
| 音频底板 | 当前未适配，不支持麦克风、扬声器和 AEC |

排线方向和电气连接以
[Wireless-Tag 板级资料](https://wiki.wireless-tag.com/docs/zh/WT9932P4C61-TINY/board_features.html)
为准。连接或调整屏幕、摄像头排线前应断电，不要带电插拔。

P4 的程序只运行在主芯片上，不会顺带更新 C61 固件。需要区分 P4 启动成功、
Hosted 握手完成、Wi-Fi 获得 IP 和 TiRTC 在线这几个阶段。

## 准备开发环境

使用 ESP-IDF `5.5.4` 及其配套的 RISC-V GCC `14.2.0_20260121`。
在对应安装的 PowerShell 环境中确认：

```powershell
. "$env:IDF_PATH\export.ps1"
idf.py --version
riscv32-esp-elf-gcc --version
$env:ESP_IDF_VERSION
```

`idf.py --version` 应为 `5.5.4`，`ESP_IDF_VERSION` 应为 `5.5`。
缺少环境导出会使 Wi-Fi Remote 漏载 IDF 对应的 Kconfig；本工程会在配置阶段直接报错。
不要只设置一个版本字符串绕过检查，应从正确的 IDF 安装执行环境导出。

板级移植依据为 Wireless-Tag `WT_BSP` 提交
`a1ee353fee9dc4de56709c00d764edc7bbcd18b1`，应用保留 LVGL 8 ABI。
本工程没有跟随 WT_BSP 最新分支切换到 IDF 6.x / LVGL 9。
如需做后续大版本适配，应独立验证 SDK、显示和依赖契约，不覆盖现有 IDF 安装。

## 获取与构建

```powershell
git clone https://github.com/tangeai/tirtc-device-qiming.git
cd tirtc-device-qiming
git checkout esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0
idf.py -B build reconfigure build
```

工程位于仓库根目录，所有开发构建使用同一个 `build` 目录。
保留仓内 `sdkconfig` 与 `sdkconfig.defaults` 的启明配置，不套用其他 P4 板型配置。
首次配置可能下载 Component Manager 依赖，需要能够访问相应服务。
本次发布未在全新电脑重新下载所有依赖，依赖解析也是首次构建需要检查的边界。

C61 使用 4-bit SDIO：CLK18、CMD19、D0-D3 为 GPIO14/15/16/17、复位 GPIO13。
主机 ESP-Hosted 为仓内本地组件，版本和补丁见
[ESP-Hosted PATCHES](../components/espressif__esp_hosted/PATCHES.md)。
不要仅因为上游有新版本就替换本地 Hosted 或 H264 组件。

## 发布固件烧录

从 [1.0.0 Release](https://github.com/tangeai/tirtc-device-qiming/releases/tag/esp32-p4-wt9932p4c61-tiny-device-app-v1.0.0)
下载 `esp32p4-qiming-wt9932p4c61-tiny-full-v1.0.0.bin`、`SHA256SUMS.txt` 和 `FLASHING_CN.md`。
核对文件为 `16,777,216` bytes 且 SHA-256 一致后，从 `0x0` 烧录；
参数为 `DIO / 80MHz / 16MB`，P4 芯片修订版要求 `v3.1` 至 `v3.99`。

完整烧录会清除 Wi-Fi、绑定和本地设置，需要重新配网；不会更新 C61 从机固件。
详细命令和网页工具操作见 [烧录到 P4](../README.md#3-烧录到-p4)。

## 本地开发烧录

先关闭占用串口的监视器或其他工具，输入实际连接的 P4 串口：

```powershell
$port = Read-Host "P4 serial port"
idf.py -B build -p $port flash monitor
```

这条命令使用当前构建的烧录清单。退出监视器使用 `Ctrl+]`。
排查串口占用、USB 线或启动模式时，应先保留错误日志，不默认擦除 Flash。

- 文件和偏移以 `build/flasher_args.json` 为准。
- 应用 BIN 不能单独写到 `0x0`；只有 Release 中的 `full` 镜像可按上述步骤从 `0x0` 烧录。
- 不要用其他板型的分区表或从机固件替代本工程配置。
- 清空 NVS 会丢失配网和绑定等本机状态；只有明确需要重置时才执行。

## 首次启动和绑定

1. 核对日志中的 `1.0.0`、工程名称、启明板型、屏幕和摄像头能力。
2. 在屏幕 Wi-Fi 页面选择网络，确认获得 IP；不要把扫描成功当成联网成功。
3. 等待校时、设备 Report 和临时 MQTT 订阅完成，再使用屏幕显示的绑定码。
4. 在设备管理网页完成账号绑定，确认正式 MQTT、平台状态和 TiRTC 在线。
5. 逐项验证媒体功能，再执行退出、重新进入及重复连接测试。

部署入口分工如下；它们是默认配置，不代表本次对这些远端服务进行了在线验收。

| 用途 | 默认入口 |
| --- | --- |
| 用户设备管理网页 | `https://demo-open.tange-ai.com/devices` |
| JSON 服务发现 | `https://ep-open.tangeopen.com/services` |
| 设备业务 API fallback | `https://srv-open.tangeopen.com` |
| 设备 MQTT fallback | `mqtts://mqtt-open.tangeopen.com:8883` |

配置定义在 [app_config.h](../main/application/app_config.h)。
更换环境时分别核对网页、发现、API 和 MQTT 地址；不要用一个 URL 覆盖全部职责。
不要把 Wi-Fi 密码、设备密钥或 token 写进代码、截图或公开日志。

## 按功能验收

下表是建议测试清单，全部需要在精确版本的目标硬件上执行；它不是已通过清单。

| 功能 | 需要检查的结果 |
| --- | --- |
| 显示与触摸 | 横屏方向正确，文字完整，触点一致，返回和设置操作可用 |
| Wi-Fi 与绑定 | 中文 SSID、连接、重连、绑定码有效期及正式在线状态正确 |
| IPC | 远端订阅后出图，画面比例正确，停止查看后下一次可重新获取摄像头 |
| 设备呼叫 | 双角色的拨打、来电、接听、拒绝、取消和挂断，界面与连接状态一致 |
| 微信 VoIP | 正式版小程序双方向呼叫，上下行视频、横屏显示和退出均核对 |
| 会话切换 | IPC、设备呼叫、微信依次切换，没有遗留连接、媒体任务或硬件占用 |
| 网络与长稳 | 正常网与双向弱网分别记录丢包、时延、帧率、队列和内存水位 |
| 摄像头负载 | 静态画面与动态高运动画面分别测试，不用静态低码率推断性能余量 |

媒体目标见 [媒体参数](P4_MEDIA_ARCHITECTURE.md#默认参数)。
音频底板未适配，采集、播放和 AEC 不列入已支持功能。
微信下行视频卡顿仍待验证，不能把能接通或偶尔出图写成流畅性通过。

## 日志与排障

当前启用串口 AT 调试入口，波特率 `115200`。以下命令用于查询，不改变连接状态：

```text
AT+HELP
AT+MEM?
AT+MEDIA?
AT+CALL?
AT+WX?
AT+HOSTED?
AT+WIFISTATS
```

局域网抓屏服务默认关闭。呼叫、挂断、Wi-Fi 切换等会改变状态的命令，
应在明确测试步骤中执行，不与手动操作同时抢占资源。

| 现象 | 优先核对 |
| --- | --- |
| IDF/Kconfig 配置阶段失败 | IDF 5.5.4 环境是否完整导出，P4/C61/SDIO 选项是否一致 |
| TiRTC 或 H264 符号缺失 | 仓内组件是否被覆盖，SDK 文件清单是否一致 |
| 串口打不开或无法烧录 | 端口占用、USB 数据线、实际串口及启动模式 |
| 无 Wi-Fi 或 Hosted 握手失败 | C61 slave 固件兼容性、复位 GPIO 和 SDIO 连接 |
| 绑定失败 | 时间同步、HTTP 状态、临时 MQTT 订阅及绑定码是否仍有效 |
| IPC 已连接但黑屏 | 视频订阅、摄像头首帧、编码输出和发送返回，逐层定位第一异常 |
| 微信下行卡顿 | 区分远端视频产出、实际 transport、接收回调、解码和显示耗时 |
| 长时间运行后异常 | 内部 RAM、最大连续块、PSRAM、队列以及重复会话的资源释放 |

保留首个错误、状态转移、耗时和水位，避免逐帧刷屏。
构建、烧录、联网、媒体效果和长稳属于不同证据，分别记录。
