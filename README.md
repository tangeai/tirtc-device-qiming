# TiRTC 启明 WT9932P4C61-TINY

## 使用教程

### 1. 准备开发板

本工程用于启明云端 **WT9932P4C61-TINY / WT01P461-S1**：ESP32-P4 主芯片，
ESP32-C61 提供 Wi-Fi，配合 ST7102 屏幕、ST7123 触摸和 SC2336 MIPI 摄像头。
请勿烧录到 Waveshare 或其他 P4 板型。

- 断电后连接屏幕和摄像头，核对排线方向，再接通稳定电源。
- 使用可传数据的 USB 线连接 P4 的 **FUSB / USB Serial-JTAG** 下载口。
- 关闭占用串口的监视器，确认电脑能识别 P4 串口。
- 本包要求 P4 芯片修订版 `v3.1` 至 `v3.99`；烧录工具报告不兼容时停止，不使用强制写入。
- C61 需预先安装与 ESP-Hosted `2.12.12` 兼容的从机固件；烧录 P4 不会更新 C61。
- 当前不含音频底板，以下按视频操作说明，不提供麦克风和扬声器功能。

接口位置和线序见 [Wireless-Tag 板级资料](https://wiki.wireless-tag.com/docs/zh/WT9932P4C61-TINY/board_features.html)。

### 2. 下载固件

打开 [1.0.2 Release](https://github.com/tangeai/tirtc-device-qiming/releases/tag/esp32-p4-wt9932p4c61-tiny-device-app-v1.0.2)，
在 Assets 中下载固件、校验文件和烧录说明：

| 文件 | 用途 |
| --- | --- |
| [完整镜像](https://github.com/tangeai/tirtc-device-qiming/releases/download/esp32-p4-wt9932p4c61-tiny-device-app-v1.0.2/esp32p4-qiming-wt9932p4c61-tiny-full-v1.0.2.bin) | 推荐，16 MiB，从 `0x0` 烧录 |
| [应用 BIN](https://github.com/tangeai/tirtc-device-qiming/releases/download/esp32-p4-wt9932p4c61-tiny-device-app-v1.0.2/esp32p4-qiming-wt9932p4c61-tiny-app-v1.0.2.bin) | 仅应用程序，供匹配分区和启动配置的开发环境使用 |
| `SHA256SUMS.txt` | 校验下载文件是否完整 |
| `release-manifest.json` | 核对源码、构建输入、烧录地址和固件哈希 |
| `FLASHING_CN.md` | 随包提供的完整烧录步骤 |

完整镜像应为 **16,777,216 bytes**。在下载目录打开 PowerShell：

```powershell
(Get-Item .\esp32p4-qiming-wt9932p4c61-tiny-full-v1.0.2.bin).Length
Get-FileHash -Algorithm SHA256 .\esp32p4-qiming-wt9932p4c61-tiny-full-v1.0.2.bin
```

与同一 Release 的 `SHA256SUMS.txt` 比较，大小或哈希不符时不要烧录。

### 3. 烧录到 P4

**完整镜像会覆盖 P4 的全部 Flash，清除原有 Wi-Fi、绑定和本地设置。**
烧录后需要重新配网，并在平台确认绑定关系。

#### 网页烧录

1. 使用 Chrome 或 Edge 打开 [Espressif ESP Tool](https://espressif.github.io/esptool-js/)。
2. 连接 P4 下载口，选择电脑实际枚举的串口，确认识别为 ESP32-P4。
3. 添加 `esp32p4-qiming-wt9932p4c61-tiny-full-v1.0.2.bin`，地址填 **`0x0`**。
4. 若工具提供参数选择，设置 Flash Size `16MB`、Mode `DIO`、Frequency `80MHz`。
5. 开始烧录，等待写入和校验完成，再复位开发板。

自动进入下载模式失败时，按住 `BOOT`，点按 `RESET`，再松开 `BOOT`，重新连接。
不要把 C61 串口当作 P4，也不要给完整镜像额外添加第二份应用 BIN。

#### 命令行烧录

以下命令使用本包离线校验所用的 `esptool 4.12.0`：

```powershell
py -m pip install "esptool==4.12.0"
py -m esptool version
$port = Read-Host "P4 serial port"
py -m esptool --chip esp32p4 --port $port --baud 460800 write_flash --flash_mode dio --flash_freq 80m --flash_size 16MB 0x0 .\esp32p4-qiming-wt9932p4c61-tiny-full-v1.0.2.bin
```

高速写入失败时先检查数据线、供电和串口占用，再将波特率改为 `115200` 重试。
不要使用 `--force` 绕过检查，也不必提前执行整片擦除。

单独的应用 BIN 链接地址为 `0x10000`，**不能写到 `0x0`**。它不含启动程序、分区表和
资源分区，也不会改变当前启动分区；首次体验或恢复设备请使用完整镜像。

### 4. 配网与绑定

1. 复位后检查 `640x480` 横屏界面和触摸方向。
2. 在绑定提示中点击“设置WiFi”，或进入“设置 -> Wi-Fi 设置”。
3. 等待扫描结果，选择网络并输入密码；确认屏幕显示已连接，串口出现 `wifi connected` 和 IP。
4. 等待设备校时、获取绑定会话及订阅完成，屏幕显示有效的绑定码或二维码后再绑定。
5. 在 [设备管理网页](https://demo-open.tange-ai.com/devices) 登录账号，按页面提示添加设备、输入绑定码或扫码。
6. 确认网页中的设备在线，再进入视频功能。能扫描 Wi-Fi、拿到 IP 和平台在线是三个不同阶段。

绑定码过期后使用设备新显示的码。完整镜像会清除本地凭据，但不替你删除云端账号关系；
若平台提示已绑定，先在原账号中确认设备归属，不要反复擦除 Flash。

### 5. IPC 实时查看

1. 保持设备联网，在设备端进入“查看”。
2. 在设备管理网页找到该设备，点击“实时”，或使用设备页面提供的查看入口。
3. 等待连接完成和首帧到达，再检查画面是否持续更新。仅显示“已连接”不代表已有视频。
4. 在镜头前移动物体，检查运动画面；静态画面不能用于判断持续帧率。
5. 结束后退出网页查看，再测试一次重新进入。

此场景由设备摄像头向网页发送 H264，设备本地不显示摄像头预览。
如果只有黑屏，依次核对订阅、摄像头首帧、编码和发送日志，不先改分辨率。

### 6. 设备呼叫设备

1. 两台设备分别完成联网和绑定，确认双方平台状态在线。
2. 进入“设备呼叫 -> 联系人列表”，等待本次云端刷新完成；失败时使用右上角刷新重试。
3. 如果没有对方，进入“添加联系人”，输入对方的 12 位 Device ID，或扫描对方设备呼叫首页的二维码。
4. 需要审批的联系人先在对方完成确认，再回到联系人列表刷新。
5. 选择在线联系人发起视频呼叫；对方在来电界面接听。
6. 接通后分别检查两台屏幕的远端画面，结束时使用通话界面的挂断按钮。
7. 再交换主叫、被叫测试一次，确认两边均返回空闲状态。

对端也要支持视频能力。联系人存在不等于设备当前在线；没有视频能力的对端不能显示双向画面。

### 7. 微信视频

1. 在正式版微信小程序登录并完成设备呼叫授权。未授权时，添加微信联系人会提示先授权。
2. 在设备端进入“微信呼叫 -> 联系人列表”，等待授权联系人同步。
3. 需要手动添加时，进入“添加联系人”，使用小程序提供的 28 位 Open ID。
4. 从设备选择联系人发起呼叫，在手机接听；分别观察手机收到的设备画面和设备收到的手机画面。
5. 反向测试时，从小程序选择设备发起视频呼叫，在设备来电界面接听。
6. 结束后确认两端退出通话，再尝试第二次呼叫。

设备上行使用 H264，手机下行由服务端转换为 MJPEG 后显示。
下行视频还依赖小程序授权和服务端转发；接通但无图时先分清哪个方向缺少首帧。
若出现卡顿，保留该次连接与媒体日志，不以通话接通代替流畅性验收。

### 8. 日志与常见问题

串口日志波特率为 `115200`。启用串口终端后，可用以下查询命令检查状态：

```text
AT+HELP
AT+MEM?
AT+MEDIA?
AT+CALL?
AT+WX?
AT+HOSTED?
AT+WIFISTATS
```

| 现象 | 检查顺序 |
| --- | --- |
| 电脑找不到串口 | USB 数据线、P4 FUSB 接口、端口占用、BOOT/RESET 下载模式 |
| 烧录后无界面或方向错误 | 固件是否为启明版、屏幕型号、断电后检查排线 |
| Wi-Fi 列表为空 | C61 固件、Hosted 握手、SDIO 和供电 |
| 已连 Wi-Fi 但没有绑定码 | 时间同步、服务发现、HTTP 返回和临时 MQTT 订阅 |
| 联系人离线或呼叫失败 | 对方在线状态、联系人刷新、授权及通话状态 |
| 已接通但视频黑屏 | 区分上行/下行，检查订阅、首帧、解码和显示 |
| 视频卡顿或长时间运行异常 | 记录帧率、队列、内部 RAM 最大连续块和首次异常时间 |

## 代码架构

### 分层与目录

```text
main/application/       应用进入、退出、状态编排和资源所有权
main/ui/                LVGL 页面、触摸交互和显示资源
main/services/          绑定、在线、IPC、设备呼叫、微信呼叫
main/protocols/         HTTP、MQTT、RTC 和 TiRTC 适配
main/connectivity/      Wi-Fi 管理和网络状态
main/media/             摄像头编码管线、像素转换和媒体策略
main/drivers/           摄像头、显示和其他硬件驱动
main/hardware/          启明板型能力、引脚和初始化
main/platform/          存储、时间、日志和内存策略
components/tirtc_sdk/   TiRTC 头文件、静态库和版本契约
```

UI 只显示状态并提交用户动作；应用层切换业务和资源；服务层执行呼叫、绑定流程；
协议层管理连接与收发；驱动层持有硬件。页面不能直接释放 RTC 句柄或抢占摄像头。
进入和退出业务走同一所有者，防止下一次呼叫仍占用上一会话的任务或缓冲。

### 视频与显示

```text
上行：SC2336 -> YUV420 -> P4 H264 硬编码 -> 发送池 -> TiRTC
设备下行：TiRTC -> H264 软件解码 -> 像素转换 -> LVGL/DSI
微信下行：TiRTC -> JPEG 硬件解码 -> PPA 缩放/旋转 -> LVGL/DSI
```

摄像头管线见 [camera_pipeline.c](main/media/camera_pipeline.c)，
连接与收发见 [tirtc_session.c](main/protocols/tirtc/tirtc_session.c)，
下行呈现见 [call_video_renderer.c](main/services/call_video_renderer.c)。
显示缓冲由 LVGL 统一提交，视频与浮层不各自交换屏幕缓冲。

大块帧、发送池和适用任务栈放在 PSRAM；DMA 描述符及必须实时访问的控制结构留在内部 RAM。
DMA 边界执行缓存同步，队列使用有界池，避免在持续通话中无限申请内存。
更详细的所有权与媒体路径见 [P4 媒体架构](docs/P4_MEDIA_ARCHITECTURE.md)。

### 配置入口

| 文件 | 用途 |
| --- | --- |
| [app_config.h](main/application/app_config.h) | 服务入口、产品策略和空凭据占位 |
| [Kconfig.projbuild](main/Kconfig.projbuild) | 板级能力、媒体和日志开关 |
| [sdkconfig.defaults](sdkconfig.defaults) | 启明 P4/C61、SDIO、内存和分区默认配置 |
| [media_tuning.h](main/media/media_tuning.h) | 各场景的编码和缓冲参数 |
| [partitions.csv](partitions.csv) | Flash 分区布局 |

Wi-Fi 在屏幕配置，设备凭据由绑定流程写入 NVS，不要写进源码。
P4 不自带 Wi-Fi；不要将 C61/SDIO 配置改成 S3 原生 Wi-Fi，也不要直接替换本地修改过的 Hosted 组件。

### 获取源码与构建

使用 ESP-IDF `5.5.4` 和 RISC-V GCC `14.2.0_20260121`，先进入对应的 ESP-IDF PowerShell 环境：

```powershell
git clone https://github.com/tangeai/tirtc-device-qiming.git
cd tirtc-device-qiming
git checkout esp32-p4-wt9932p4c61-tiny-device-app-v1.0.2
. "$env:IDF_PATH\export.ps1"
idf.py --version
idf.py -B build reconfigure build
```

工程位于仓库根目录，统一使用 `build` 目录；首次构建需要下载 Component Manager 依赖。
保留启明的 `sdkconfig` 与 `sdkconfig.defaults`，不要覆盖现有 IDF 安装来尝试其他大版本。

修改代码后按生成的清单烧录并观察日志：

```powershell
$port = Read-Host "P4 serial port"
idf.py -B build -p $port flash monitor
```

文件及地址以该次构建的 `build/flasher_args.json` 为准，退出监视器使用 `Ctrl+]`。
源码、SDK 与验证记录见 [版本契约](VERSION.md) 和 [源码来源](SOURCE_PROVENANCE.md)；
项目及第三方授权以 [LICENSE](LICENSE) 和各组件许可证为准。
