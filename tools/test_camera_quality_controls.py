"""Exercise the production read-only V4L2 control snapshot with real UAPI types."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
driver = (ROOT / "main/drivers/camera/camera_driver.c").read_text(encoding="utf-8")
start = driver.index("static esp_err_t camera_driver_log_quality_controls(int fd)")
end = driver.index("\nesp_err_t camera_driver_deinit(void)", start)
production = driver[start:end]

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <linux/videodev2.h>
typedef int esp_err_t;
enum { ESP_OK, ESP_FAIL, ESP_ERR_INVALID_RESPONSE, ESP_ERR_INVALID_STATE, ESP_ERR_TIMEOUT };
enum { pdTRUE = 1 };
#define pdMS_TO_TICKS(value) (value)
#define ESP_LOGE(tag, ...) ((void)0)
#define ESP_LOGI(tag, ...) ((void)0)
static void *s_lock;
static bool s_camera_initialized;
static int s_fd = -1;
static int calls, fail_at, bad_value, lock_calls, unlock_calls;
static bool lock_ok = true;
static int xSemaphoreTake(void *lock, int timeout) {
    assert(lock == s_lock && timeout == 100);
    ++lock_calls;
    return lock_ok;
}
static void xSemaphoreGive(void *lock) {
    assert(lock == s_lock);
    ++unlock_calls;
}
static int test_ioctl(int fd, unsigned long request, void *arg) {
    assert(fd == 7);
    ++calls;
    if (calls == fail_at) { errno = EIO; return -1; }
    if (request == VIDIOC_G_EXT_CTRLS) {
        struct v4l2_ext_controls *c = arg;
        assert(c->count == 2 && c->ctrl_class == V4L2_CTRL_CLASS_USER);
        assert(c->controls[0].id == V4L2_CID_EXPOSURE);
        assert(c->controls[1].id == V4L2_CID_GAIN);
        c->controls[0].value = bad_value == 1 ? 701 : 699;
        c->controls[1].value = bad_value == 2 ? 101 : 100;
    } else if (request == VIDIOC_QUERY_EXT_CTRL) {
        struct v4l2_query_ext_ctrl *q = arg;
        assert(q->id == V4L2_CID_EXPOSURE || q->id == V4L2_CID_GAIN);
        q->minimum = bad_value == 3 && q->id == V4L2_CID_GAIN ? -1 : 0;
        q->maximum = q->id == V4L2_CID_EXPOSURE ? 700 : 100;
    } else {
        /* A setter, stream operation, buffer dequeue, or other ioctl fails here. */
        assert(request == VIDIOC_QUERYMENU);
        struct v4l2_querymenu *m = arg;
        assert(m->id == V4L2_CID_GAIN);
        assert(m->index == 0 || m->index == 100);
        m->value = m->index == 0 ? 1000 : 32000;
    }
    return 0;
}
#define ioctl test_ioctl
'''

cases = r'''
int main(void) {
    for (int i = 0; i <= 6; ++i) {
        calls = 0; fail_at = i;
        assert(camera_driver_log_quality_controls(7) == (i ? ESP_FAIL : ESP_OK));
        assert(calls == (i ? i : 6));
    }
    fail_at = 0;
    for (int i = 1; i <= 3; ++i) {
        calls = 0; bad_value = i;
        assert(camera_driver_log_quality_controls(7) == ESP_ERR_INVALID_RESPONSE);
        assert(calls == 3);
    }
    calls = 0; bad_value = 0;
    assert(camera_driver_log_quality() == ESP_ERR_INVALID_STATE);
    assert(!lock_calls && !unlock_calls && !calls);
    s_lock = &calls;
    assert(camera_driver_log_quality() == ESP_ERR_INVALID_STATE);
    assert(lock_calls == 1 && unlock_calls == 1 && !calls);
    s_camera_initialized = true;
    assert(camera_driver_log_quality() == ESP_ERR_INVALID_STATE);
    assert(lock_calls == 2 && unlock_calls == 2 && !calls);
    s_fd = 7; lock_ok = false;
    assert(camera_driver_log_quality() == ESP_ERR_TIMEOUT);
    assert(lock_calls == 3 && unlock_calls == 2 && !calls);
    lock_ok = true;
    assert(camera_driver_log_quality() == ESP_OK);
    assert(calls == 6 && lock_calls == 4 && unlock_calls == 3);
    calls = 0; fail_at = 4;
    assert(camera_driver_log_quality() == ESP_FAIL);
    assert(calls == 4 && lock_calls == 5 && unlock_calls == 4);
    puts("PASS: read-only controls, all six ioctl failures, limits, inactive camera and lock lifetime");
}
'''

with tempfile.TemporaryDirectory(prefix="wt99-camera-quality-") as folder:
    source = Path(folder) / "quality.c"
    binary = Path(folder) / "quality"
    source.write_text(harness + production + cases, encoding="utf-8")
    subprocess.run(["cc", "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra",
                    "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
