# LVGL 8.4.0 图像覆盖补丁

工程构建时应用 [图像覆盖补丁](../tools/patches/lvgl-8.4.0-image-cover.patch)。
它修正覆盖检查事件的参数读取，并仅在原尺寸、不透明且无变换的 RGB 图像上
报告完整覆盖，避免重复重绘。透明、裁剪和变换场景保持原判断。

上游为 [LVGL 8.4.0](https://github.com/lvgl/lvgl/tree/v8.4.0)，保留 MIT 许可。
