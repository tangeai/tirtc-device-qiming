"""Check real priority policy and codec selection, not runtime scheduling."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
renderer = (root / "main/services/call_video_renderer.c").read_text(encoding="utf-8")
config = (root / "main/services/call_video_renderer_config.h").read_text(encoding="utf-8")
camera = (root / "main/media/camera_pipeline.c").read_text(encoding="utf-8")
display = (root / "main/drivers/display/display_driver.c").read_text(encoding="utf-8")
audio = (root / "components/starter_media/src/starter_media.c").read_text(encoding="utf-8")
selector = re.search(r"UBaseType_t task_priority\s*=.*?;", renderer, re.S).group()
h264_priority = re.search(r"#define CALL_VIDEO_TASK_PRIORITY\s+(\d+U?)", config)[1]
assert "#define CAMERA_PIPELINE_TASK_PRIORITY    APP_TASK_PRIORITY_CAMERA" in camera
assert "#define DISPLAY_DRIVER_LVGL_TASK_PRIORITY APP_TASK_PRIORITY_UI" in display
assert re.search(r"xTaskCreatePinnedToCoreWithCaps\(task_entry,.*?\btask_priority,", renderer, re.S)
for task, policy in (("audio_sink_task", "APP_TASK_PRIORITY_AUDIO_PLAYBACK"),
                     ("audio_uplink_task", "APP_TASK_PRIORITY_AUDIO_PACKET"),
                     ("audio_capture_task", "APP_TASK_PRIORITY_AUDIO_CAPTURE")):
    arguments = re.search(r"xTaskCreate(?:PinnedToCore)?WithCaps\(" + task +
                          r",([^)]*)\)", audio, re.S)[1]
    assert policy + "," in arguments
tx_arguments = re.search(r"xTaskCreatePinnedToCoreWithCaps\(audio_uplink_task,([^)]*)\)", audio, re.S)[1]
assert "APP_TASK_CORE_AUDIO," in tx_arguments

harness = r'''
#include <assert.h>
#include "app_task_affinity.h"
typedef unsigned UBaseType_t;
enum { CALL_VIDEO_CODEC_H264, CALL_VIDEO_CODEC_MJPEG };
#define CALL_VIDEO_TASK_PRIORITY @H264@
static unsigned priority(int codec) { @SELECTOR@ return task_priority; }
int main(void) {
#if CONFIG_FREERTOS_UNICORE
    assert(APP_TASK_CORE_AUDIO == tskNO_AFFINITY);
#else
    assert(APP_TASK_CORE_AUDIO == 1 && APP_TASK_CORE_AUDIO != APP_TASK_CORE_NETWORK);
#endif
    assert(APP_TASK_PRIORITY_CAMERA > APP_TASK_PRIORITY_UI);
    assert(priority(CALL_VIDEO_CODEC_MJPEG) > APP_TASK_PRIORITY_UI);
    assert(priority(CALL_VIDEO_CODEC_H264) < APP_TASK_PRIORITY_UI);
    assert(priority(CALL_VIDEO_CODEC_H264) == CALL_VIDEO_TASK_PRIORITY);
    assert(priority(CALL_VIDEO_CODEC_MJPEG) < APP_TASK_PRIORITY_AUDIO_PLAYBACK);
    assert(APP_TASK_PRIORITY_CAMERA < APP_TASK_PRIORITY_AUDIO_PLAYBACK);
    assert(APP_TASK_PRIORITY_AUDIO_PACKET > APP_TASK_PRIORITY_CAMERA);
    assert(APP_TASK_PRIORITY_AUDIO_PACKET > priority(CALL_VIDEO_CODEC_MJPEG));
    assert(APP_TASK_PRIORITY_AUDIO_PACKET <= APP_TASK_PRIORITY_AUDIO_PLAYBACK);
    assert(APP_TASK_PRIORITY_AUDIO_PACKET <= APP_TASK_PRIORITY_AUDIO_CAPTURE);
    return 0;
}
'''.replace("@H264@", h264_priority).replace("@SELECTOR@", selector)
with tempfile.TemporaryDirectory(prefix="p4-media-scheduling-") as folder:
    path = Path(folder)
    (path / "freertos").mkdir()
    (path / "freertos/FreeRTOS.h").write_text("#define tskNO_AFFINITY 2147483647\n", encoding="ascii")
    (path / "sdkconfig.h").write_text("", encoding="ascii")
    (path / "esp_heap_caps.h").write_text("", encoding="ascii")
    (path / "test.c").write_text(harness, encoding="ascii")
    for unicore in (0, 1):
        binary = path / f"test-{unicore}"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", f"-DCONFIG_FREERTOS_UNICORE={unicore}",
                        "-I", str(path), "-I", str(root / "main/platform"),
                        str(path / "test.c"), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
print("PASS: hardware completion/UI/audio ordering, H264 unchanged, actual codec selector, SMP/unicore")
