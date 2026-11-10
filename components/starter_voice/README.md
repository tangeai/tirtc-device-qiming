# P4 唤醒组件

本组件从处理后的 PCM 识别“你好小钛”，识别成功后向应用提交唤醒事件。参数和模型位置如下：

| 内容 | 文件 |
| --- | --- |
| 识别流程 | [starter_voice.c](src/starter_voice.c) |
| 模型与参数 | [head.h](model/head.h)、[nihaoxiaotai.tflite](model/nihaoxiaotai.tflite) |
| 特征提取 | [mel_extractor.c](vendor/mel_extractor.c) |
| 应用配置 | [Kconfig.xiaotai](../../main/Kconfig.xiaotai) |
| 构建和依赖 | [CMakeLists.txt](CMakeLists.txt)、[idf_component.yml](idf_component.yml) |
| 供应商来源 | [UPSTREAM](vendor/UPSTREAM.md) |

模型以 `nihaoxiaotai.tflite` 嵌入，使用本目录资源。文件摘要见[版本与依赖](../../docs/DEPENDENCIES.md)。

当前按用户选择恢复 `nihaoxiaotai_v9.3_20260915_nhwc_tflite.zip` 的模型及分类头，两个资源按原字节成对恢复。输入按时间优先排列为 INT8 `[1,98,32]`；模型首层自行转换为 `[1,98,1,32]`，应用不要额外转置。输出为 INT8 `[1,256]`，量化参数继续从实际张量读取。

`wake_model_config.h` 统一特征帧数与 PCM 窗口，当前为 16192 个采样点（16 kHz、1.012 秒）。旧分类头未提供前端元数据，后端明确锁定其 98 帧、32 频带、16 kHz、512 FFT、160 Mel hop 契约，主机用例再核对配套资源摘要和模型实际张量；运行时仍校验张量，不靠猜测兼容其他包。

默认唤醒阈值恢复为原来的 0.95，160ms 推理 hop、命中策略和音频处理不变。此次回退基于同一实际失败输入的新旧模型对照，新模型低分可在电脑复现，旧模型在相同结束时刻的窗口可超过 0.95。新模型训练或输入契约的具体根因仍未证实；回退是恢复旧模型，不代表修复新模型。主机契约和静音自检不能证明实际识别率，快/正常/慢语速和误唤醒仍需真机测试。

## 诊断分数

界面中的唤醒分数来自被接受的那一帧，随事件一起保存，不是整句话的最高分；
`AT+WAKE?` 的 `last` 则是最近一次推理分数。AI 会话期间暂停唤醒检测。
降低阈值可能让更早、分数尚在上升的帧触发，随后暂停检测，因此触发分数较低
不等于漏唤醒更多。验证识别效果要记录有效试说次数、成功次数及误唤醒，不能只比较显示分数。

## FFT 与卷积适配

特征提取保留 P4 ANSI FFT 路径。初始化、FFT 或位反转失败时不继续消费错误结果。

当前锁定 TFLM 1.4.1 官方 Git Tag 对应提交 `7b82a0d27416f3ebb080c39b61e0d961cad2127d`，ESP-NN 仍为 1.3.2。TFLM 上游 `conv.cc` 已在 Prepare 和 Eval 两处使用 filter 张量的实际通道数，因此移除了旧版构建期源码替换。唤醒模型、阈值和音频前处理没有随依赖升级改变。

ESP-NN 1.4.0 已发布，但当前 IDF 组件管理器使用的镜像尚未提供该版本；尝试并行指定 Git 来源时，依赖解析仍选中镜像中的 1.3.2。此项升级留待能生成一致锁文件并完成构建、真机唤醒回归时再做。

## 检查方法

主机契约用例为 `python3 tools/test_wake_model.py`，需要 Linux/WSL C++ 编译器。
它检查资源摘要、真实 FlatBuffer/算子、分类头和生产 PCM 窗口的填满、换行、
连续 hop、缺口与过期保护；ASan/UBSan 检查不代替板端推理或识别率。

配置完成后检查 `managed_components/espressif__esp-tflite-micro/tensorflow/lite/micro/kernels/esp_nn/conv.cc` 的 Prepare 和 Eval 是否均使用 `filter->dims->data[3]`。链接后的固件门禁还会检查产品入口和驱动所有权。

模型更换后，先核对模型与分类头摘要，再完成一次干净构建。设备启动时应出现 `KWS nhwc-20260915 INT8 98x32` 和 `wake self-test=ESP_OK`；随后分别测试快、正常、慢语速，记录命中次数与推理耗时。静态检查和构建均不能代替实际唤醒率验证。

调节效果时分别记录不同语速、距离、环境噪声和扬声器播放中的识别情况。卷积适配不调整采集、AEC、增益、阈值或任务调度；相关音频路径见[系统架构](../../docs/P4_MEDIA_ARCHITECTURE.md#音频采集)。
