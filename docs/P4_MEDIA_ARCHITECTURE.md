# 启明 ESP32-P4 媒体架构

本文对应启明 Device Monitor `1.0.0`，说明摄像头、音频、TiRTC、显示和内存的所有权。每条媒体链路由明确的生命周期所有者管理，避免跨层争抢硬件或连接句柄。参数以本仓配置为准，验证状态见 [源码来源](../SOURCE_PROVENANCE.md)。

## 分层

| 层 | 责任 |
| --- | --- |
| `drivers` | 摄像头、显示、触摸、音频 codec、DMA 和硬件生命周期 |
| `media` | 摄像头 H264 pipeline、像素格式转换、媒体档位和运行指标 |
| `services` | IPC、设备呼叫、微信 VoIP、AI Chat、绑定和 OTA 等业务服务 |
| `protocols/tirtc` | TiRTC SDK、连接句柄、订阅、回调和媒体收发队列 |
| `application` | 业务进入/退出、资源租约和所有权切换 |
| `ui` | 状态展示和用户动作，不持有媒体设备或连接 |

## 内存

P4 使用 capability-based allocation，不把所有 heap 当作可互换内存。

| 内存 | 长期所有者 | 策略 |
| --- | --- | --- |
| Internal RAM | DMA 描述符、实时控制队列、mutex、音频 I/O 控制、flash/NVS task stack | 显式 `MALLOC_CAP_INTERNAL`，媒体分配失败时不回退到这里 |
| DMA-capable internal RAM | ESP-Hosted 描述符、摄像头/H264/JPEG 驱动和 DMA escrow | IDF 内部预留配置 `160KiB`，运行时 escrow 目标 `96KiB`，不存放长期大块 SDIO payload |
| PSRAM | SDIO streaming RX、H264/JPEG payload、RTC TX pool、解码帧、RGB565 帧、HTTP/MQTT 工作区和后台 task stack | 显式 `MALLOC_CAP_SPIRAM`，固定池优先于实时动态扩容 |

启动早期按顺序预热：

1. P4 JPEG decoder 的内部 DMA 描述符。
2. DMA escrow。
3. H264 encoder。
4. RTC 视频发送池。
5. 视频缩放/旋转工作区和下行显示池。
6. 音频底板存在时预热 AEC 工作集；当前核心板不申请音频资源。

启动预热尽量在服务发现、绑定、MQTT、TiRTC 和 UI 申请长期资源前完成。escrow 是可借出和回收的运行时保留块，不代表始终空闲；配置预留值也不能代替实际 free/largest 水位。视频大块留在 PSRAM，内部 RAM 承担硬件必须的描述符和实时控制。

RTC 视频发送池使用固定 PSRAM slot；音频发送和播放缓冲也使用独立固定池。队列只保存描述符和 slot index，不保存大 payload。后台网络、媒体和 UI task 使用 PSRAM stack；flash/NVS、实时音频和小型应用控制 task 保留 internal stack。

ESP-Hosted streaming RX 使用两个 `64KB` cache-aligned PSRAM DMA 缓冲，只有 PSRAM DMA 分配失败时才回退到 `4KB` internal DMA 缓冲。这样把 Wi-Fi burst payload 留在 PSRAM，同时保护 H264、JPEG 和音频依赖的内部 DMA 连续块。

## 摄像头上行

`main/media/camera_pipeline.c` 持有实时 RTC 摄像头：

- IPC 使用 SC2336 原生 `1024x600` YUV420 和 ESP32-P4 H264 硬编，上行目标为 `20fps`、`4Mbps`。
- 传感器输出与编码器输入尺寸一致时走 YUV420 direct，不增加 RGB565 中转。
- 热路径为 `camera_driver -> camera_pipeline -> H264 encoder -> tirtc_session`。
- RTC 上行不做本地摄像头预览。
- QR scanner 只在扫码页持有摄像头，离开后释放。
- PSRAM 中的 H264 输入和输出在 DMA 边界使用 `esp_cache_msync`。
- 第一帧必须是完整关键帧，丢失依赖后重新请求 IDR。

设备间呼叫使用 `384x256@12fps`、`256kbps`；微信 VoIP 使用 `480x320@15fps`、`480kbps`。它们是独立于 IPC 的上行档位，退出通话后恢复正常媒体配置。

## 视频下行

`main/services/call_video_renderer.c` 是下行视频的统一 renderer，但 codec path 分开：

### 设备间呼叫

- 接收 constrained-baseline H264。
- 源尺寸上限为 `384x256`，使用 `contain` 等比例映射到 `640x480`，剩余区域留边。
- 软件 H264 decoder 输出 YUV420。
- PPA 优先完成缩放、裁剪和 RGB565 转换，软件路径作为回退。
- H264 依赖帧丢失时进入 key-frame resync，不继续显示错误参考帧。
- 压缩输入使用 24 个 `256KiB` PSRAM slot，decoded pool 为 4 帧；输入溢出后标记延迟恢复，在下一次 IDR 到达时清空旧依赖链并切换到新一代解码状态。
- TinyH264 保持单任务所有者，可在双核间调度；硬件 JPEG 和转换任务与显示一起放在 CPU1，网络与 RTC 控制优先留在 CPU0。
- 解码任务优先保持 H264 参考链连续；转换任务每处理一帧主动让出一个 tick，避免持续占满调度窗口。

### 微信 VoIP

- 设备上报 `down_video_mt=mjpeg`、`screen_width=640`、`screen_height=480`，下行 query 请求长边 `480`、比例 `133`、方向 `1`、最高 `15fps`。屏幕尺寸不等于实际编码尺寸。
- 服务端显示请求使用 `object_fit=contain`、`video_res_mode=fit_screen`；这是服务端契约，与本机 PPA 的呈现策略分开。
- 服务端把微信视频转换为独立 MJPEG 帧。
- P4 hardware JPEG decoder 输出 RGB565。
- 解码入口只有一条统一 MJPEG 路径，支持不超过 `640x480` 解码预算的服务端实际帧，不维护另一套低分辨率 fallback。
- TiRTC JPEG 帧头不携带旋转元数据。应用为微信 renderer 选择 `NORMALIZE_LANDSCAPE`：实际竖帧顺时针转 `90` 度，横帧保留 `0` 度。SC2336 上行向服务端上报 `camera_rotation=270`；这是上行方向信息，不能用来推导下行的旋转。
- PPA 直接基于服务端实际帧执行一次居中 `cover`：服务端实际帧大于显示视口时，对称裁切并等比缩小到 `640x480`；低分辨率档位等比放大并居中裁切。显示层不再做第二次缩放，也不做非等比拉伸。
- 压缩输入复用 24 个 `256KiB` PSRAM slot；解码和显示使用固定 PSRAM pool。
- MJPEG 帧彼此独立。队列积压时释放旧帧并解码最新帧，避免延迟持续增长。
- WHIP 连接接受后按媒体策略订阅远端视频。现有首包超时路径最多补发一次订阅；这是启动容错，不是微信持续卡顿的根因修复，也不用于长期重复订阅。

统一输出由 12 个 `640x480` RGB565 PSRAM slot 组成，约 `7.03MiB`。Qiming DSI 双缓冲由 LVGL 独占，视频帧和浮层都通过同一显示所有者提交，避免 direct-LCD 与 LVGL 交换帧缓冲时发生竞争。固定池描述的是容量，不代表播放时必须填满队列。

## 音频和 AEC

当前音频底板未适配，采集、播放和 AEC 不初始化。以下是保留代码的所有权设计，不是本板已验证的音频功能：

- IPC、设备呼叫和微信 VoIP 使用 RTC media owner。
- AI Chat 使用独立 media owner。
- 进入业务时先 prepare 自适应播放缓冲，媒体真正 active 后启用 AEC。
- AEC 优先使用 codec 同步 DAC reference；无法锁定时使用 `80ms` 软件延迟参考。
- 退出业务时停止采集、播放和 AEC 处理，但保留预热工作区供后续会话复用。

播放控制器根据 underflow、积压和抖动调整目标缓冲，不通过长期固定大延迟掩盖弱网。

## TiRTC 发送与码率

`main/protocols/tirtc/tirtc_session.c` 持有连接和发送队列：

- 视频进入预分配 PSRAM TX pool。
- 发送任务优先丢弃过期视频，不让旧帧无界堆积。
- 音频使用独立队列，视频启动期间只允许有界延后。
- 无效句柄、远端关闭和 teardown 在协议层与应用层闭环，UI 不直接释放连接。

运行时 transport 由服务端协商为 TGTRP 或 KCP，不由 APP 的构建参数单独决定。正常配置下，`CONFIG_APP_RTC_VIDEO_AUTO_ADAPT_ENABLE` 和 `CONFIG_APP_RTC_SDK_VIDEO_ADAPT_ENABLE` 均关闭；保留的自动控制代码不代表本版已启用弱网降级。

后续启用 TiRTC `2.3.0` 码率反馈时，应在连接建立后注册参数，SDK 回调只投递绝对目标码率，由应用控制任务调整编码器。须独立验证控制器和实际 transport，避免本地策略与 SDK 反馈同时改写配置。接收端丢弃显示旧帧不能修复传输层的缺段或发送端停流。

## 默认参数

| 项目 | 默认值 |
| --- | --- |
| IPC | `1024x600@20fps`, `4Mbps` |
| 设备呼叫上行 | `384x256@12fps`, `256kbps` |
| 微信上行 | `480x320@15fps`, `480kbps` |
| H264 名义 GOP | IPC / 微信 `2s`，设备呼叫 `4s` |
| H264 output buffer | `1MB` |
| Max delta payload | `256KB` |
| Startup max delta payload | 首 `2500ms` 为 `128KB` |
| 本地自动弱网降级 | 关闭 |
| TiRTC SDK/TGMP bitrate adaptation | 关闭 |
| Wait subscribe before capture | 关闭 |
| Qiming DSI presentation | LVGL 独占，Direct LCD 关闭 |

## 失败边界

- 丢弃二维码预览帧不能停止 RTC。
- 丢弃视频帧或显示帧不能关闭 TiRTC 连接。
- JPEG/H264 单帧解码失败只能丢帧并保留下一次恢复机会。
- 媒体队列必须有界；业务退出后队列、帧 slot 和连接状态归零。
- 日志只保留首帧、状态转换、周期汇总和可执行错误，不按帧刷屏。

## 验证

1. 验证横屏显示和触摸坐标。
2. 验证绑定、正式 MQTT 和 TiRTC 上线。
3. 分别验证 IPC、设备呼叫和微信 VoIP；AI Chat 在音频底板适配前应明确返回“不支持”，不能进入半初始化页面。
4. 对微信 VoIP 确认 H264 上行与 MJPEG 下行均有首帧证据。
5. 先保持每个主要场景至少 5 分钟，再做独立长稳；观察 fps、bitrate、queue、DMA largest block 和 PSRAM pool。当前不做音频/AEC 功能通过结论。
6. 每个场景连续进入和退出至少 10 次，确认无残留资源和连接句柄。

上述是待执行的验收步骤。本版本已经编译通过，但当前 SDK 下的完整真机矩阵尚未完成，微信下行卡顿仍待验证。
