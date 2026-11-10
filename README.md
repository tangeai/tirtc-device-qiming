# 启明 WT99P461-S1 1V1 · 小钛

这是 7 英寸 WT99P461-S1 1V1 的源码分支。P4 跑小钛 AI，C61 负责 Wi-Fi。
配网并绑定后，点击首页表情或说“你好小钛”。旧款 WT9932P4C61-TINY 请用
`main` 和旧板固件。

## 下载

[固件与烧录说明](https://github.com/tangeai/tirtc-device-qiming/releases/tag/wt99p461-s1-1v1-v0.1.0-dev)

| 文件 | 用途 |
| --- | --- |
| P4 16 MB 完整包 | 首次安装，从 P4 的 `0x0` 烧录 |
| C61 4 MB 全量包 | C61 无法启动时，用 C61 专用串口恢复 |
| C61 OTA APP | C61 能联网时，由 P4 更新，不改 C61 分区表 |

全量烧录先备份。P4 和 C61 的镜像不能混刷。

## 开发

- [P4 编译前补齐外部输入](EXTERNAL_ASSETS.md)
- [P4 烧录、配网和编译](docs/GETTING_STARTED_CN.md)
- [C61 编译、串口恢复和 OTA 工具](coprocessor/esp32c61/README.md)

源码分支不附第三方库、字体、模型和媒体资源。C61 可独立编译。
