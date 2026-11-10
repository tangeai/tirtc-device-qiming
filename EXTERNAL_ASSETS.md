# P4 外部构建输入

这个分支提供 P4、C61 和 OTA 工具的代码。第三方静态库、字体、模型和媒体资源
不随源码分发。直接体验请用 [Release 固件](https://github.com/tangeai/tirtc-device-qiming/releases/tag/wt99p461-s1-1v1-v0.1.0-dev)。

**C61 可独立编译**，按 [C61 指南](coprocessor/esp32c61/README.md) 操作，不需要
P4 外部输入。

## 从源码编译 P4

先从原供应方或有权提供这些文件的渠道取得 `external-assets.json` 里的输入，
按清单的相对路径放在一个本机目录。清单锁定了准确的字节和 SHA-256，不能用同名
文件、其他型号库或新模型替代。已有相同版本的本机开发树也可作为输入。

```sh
python tools/restore_assets.py /path/to/authorized-assets
python tools/restore_assets.py --check
```

工具只读本机输入，先验全量文件，再补缺失项；不会覆盖不同内容的现有文件。
补齐后按 [P4 编译说明](docs/GETTING_STARTED_CN.md#从源码构建) 操作。
不要把补齐的输入重新提交到分支。供应商和许可见 [THIRD_PARTY.md](THIRD_PARTY.md)。
