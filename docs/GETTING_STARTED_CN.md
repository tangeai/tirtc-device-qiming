# WT99P461-S1 烧录与开发

## 从完整包开始

1. 核对 WT99P461-S1 PCB 1V1、7 英寸屏和 P4 修订 v3.1–v3.99。
   连接 P4 下载 USB 口，使用 USB 数据线。不要选 C61 串口。
2. 备份并校验原 Flash。完整安装会清除原 Wi-Fi、绑定和设置。下载本板对应
   Release 的 `full-16MB.bin`，核对 `SHA256SUMS` 和长度 16,777,216 字节。
3. 用 Chrome 或 Edge 打开 [ESP Web Flasher](https://espressif.github.io/esptool-js/)，
   连接 P4 串口。点击 Add File，仅添加一个完整 BIN，地址设为 `0x0`，
   保留镜像参数后点击 Program。不要同时加入 ZIP 里的分段文件。
4. 等待烧录成功后复位。若使用分段 ZIP，先解压，按该版 `MANIFEST.json`
   的文件和偏移写入，不把 APP 单独写到 `0x0`。

P4 16 MB 包不含 C61。正常联网时保留当前 C61；联网异常先确认
[C61 版本与 SPI 准备条件](../coprocessor/esp32c61/README.md)，不要反复清 Flash。

## 配网和绑定

1. 手机连屏幕上显示的 `XiaoTai-XXXX` 热点，浏览器打开 `http://192.168.6.1`。
   选择可用的 2.4 GHz Wi-Fi 并输入密码。手机提示热点无法上网时保持连接，
   保存后等待设备联网。
2. 设备显示六位绑定码后，手机切回常用网络，进入
   [小钛平台](https://xiaotai.chat/)的设备管理添加设备。
3. 进入小钛首页后，点击表情或说“你好小钛”开始 AI 对讲。
   在线体验需要平台连接和有效的 AI 角色。验证范围见[版本说明](../RELEASE_NOTES.md)。

## 从源码构建

编译 P4 前，先按 [外部输入清单](../EXTERNAL_ASSETS.md) 补齐库和资源。

使用 ESP-IDF 5.5.5，进入本板工程目录，在已加载工具链的终端执行：

```sh
idf.py -B build -DIDF_TARGET=esp32p4 build
```

从空构建目录生成配置，不复用其他板的 `sdkconfig`。依赖版本由
`dependencies.lock` 固定，构建时应用工程内 Hosted 和 LVGL 补丁。正式烧录
按该次构建的 `flasher_args.json` 核对偏移和目标芯片。

Windows 若报命令行过长，可把源码放到更短路径，或在构建命令中加入
`-DCMAKE_NINJA_FORCE_RESPONSE_FILE=ON`。

TiRTC P4 Mini 2.6.0 在此包中不支持 SDK SSL，仅已发现的 SDK 服务入口采用
HTTP。平台发现、业务 HTTPS 和 MQTTS 不因此改变。
