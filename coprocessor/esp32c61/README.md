# C61 联网固件

适用 **WT99P461-S1 1V1 / ESP32-C61 rev1.0 / 4 MB Flash**。配套
ESP-Hosted 3.0.7，SPI Mode 3、10 MHz。不要用旧启明 SDIO 或微雪 C6 镜像。

[下载 C61 全量镜像和 OTA APP](https://github.com/tangeai/tirtc-device-qiming/releases/tag/wt99p461-s1-1v1-v0.1.0-dev)

## C61 无法启动：串口恢复

用 C61 专用下载口和 3.3 V 串口。先备份，再把 4 MB 全量 BIN 写到 **C61 的
`0x0`**。全量包会替换原厂分区、备用槽和 NVS，不要刷入 P4 或用它做 OTA。

## C61 能联网：由 P4 更新

结束 AI 或通话。电脑与 P4 在同一局域网，连的是 **P4 UART0**，不是 C61 下载口。
从发布页下载 OTA APP 并核对 SHA-256。可以用仓库的工具完成下载、SPI 更新和
重启核对（需要 Python 和 `pyserial`）：

```text
python tools/c61_ota.py --firmware <OTA文件> --sha256 <OTA文件的SHA256> --serial <P4的UART0> --bind-ip <电脑IPv4> --device-ip <P4的IPv4>
```

也可以在可信局域网内自行提供该文件，通过 P4 UART0 发送
`AT+CPOTA=http://<电脑IP>:<端口>/<OTA文件名>,<SHA256>`。
请勿把 GitHub 下载链接直接填给设备。更新只写 C61 非活动 APP 槽，保留分区表和
NVS；开机不会自动升级。重启后用 `AT+C61=INFO` 查运行身份，再确认 Wi-Fi。
不要连续升级两次，避免覆盖唯一可用的原厂备用槽。应用级回退要求备用槽可用、
且新 APP 能运行到检查代码，不能替代引导器回滚或串口备份。

## 编译

使用 ESP-IDF 5.5.5，从本目录运行：

```sh
idf.py -B build -DIDF_TARGET=esp32c61 build
```

`build/xiaotai_wt99p461_c61.bin` 是 OTA APP。全量镜像按同次构建的
`flasher_args.json` 合并，不能把 OTA APP 直接写到 `0x0`。
