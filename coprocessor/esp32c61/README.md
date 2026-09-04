# ESP32-C61 网络协处理器

这里保存启明 WT9932P4C61-TINY 所需 C61 固件的可追溯源码覆盖层。它以
Espressif `espressif/esp_hosted` `2.12.11` 的 `slave` 示例为固定上游，使用
ESP-IDF `5.5.4` 构建。`source-manifest.json` 同时固定上游输入和启明覆盖文件的
SHA-256，避免把实验目录或来源不明的二进制作为发布依据。

启明覆盖层包含以下板级策略：

- C61 使用 SDIO high-speed streaming，TX 队列为 20。
- Wi-Fi RX 缓冲为 16/64，BA 接收窗口为 12。
- C61 不启用蓝牙和低功耗路径，优先保留媒体数据面的内存与调度余量。
- Host 到 Wi-Fi 的瞬时 `ESP_ERR_NO_MEM` 使用 50 ms 有界背压，不丢弃已经接收的 SDIO 帧。
- 混杂抓包默认关闭，只能通过显式诊断命令开启，避免占用正常 MJPEG 下行的 RX 缓冲。
- 保留限频统计和独立 UDP 数据面探针，用于区分空口、C61、SDIO、P4 socket 和媒体层问题。

在 ESP-IDF 5.5.4 PowerShell 环境中构建：

```powershell
cd coprocessor\esp32c61
.\build.ps1 -RefreshSource
```

脚本只使用 `coprocessor/esp32c61/.work/b` 作为 C61 构建目录，并生成：

- `network_adapter.bin`：C61 应用镜像，烧录地址 `0x10000`。
- `qiming-c61-network-adapter-full.bin`：C61 4 MiB 完整镜像，烧录地址 `0x0`。

P4 的 16 MiB 完整镜像不会写入 C61。正式 Release 必须同时提供匹配的 C61
完整镜像，并分别标明芯片和烧录接口，不能把两个芯片的镜像混烧。
