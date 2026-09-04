"""Verify the actual AWB normalization against IDF's effective window."""

import subprocess
from pathlib import Path

from check_hosted_rx_ownership import wsl_path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "components/espressif__esp_video/src/device/esp_video_isp_device.c"
HARNESS = r"""
#include <assert.h>
#include <stdio.h>
#define ISP_AWB_WINDOW_X_NUM 5
#define ISP_AWB_WINDOW_Y_NUM 5
typedef struct { int x, y; } point;
typedef struct { point top_left, btm_right; } window;
typedef struct { window subwindow; } config;
static void normalize(config *awb_config) {
@BODY@
}
int main(void) {
    const int edges[] = {1, 19, 20, 21, 24, 25, 240, 320, 352, 480, 600, 640, 1024};
    unsigned cases = 0;
    for (unsigned x=0; x<sizeof(edges)/sizeof(edges[0]); x++) {
        for (unsigned y=0; y<sizeof(edges)/sizeof(edges[0]); y++) {
            for (int offset=0; offset<3; offset++) {
                int w=edges[x], h=edges[y];
                config cfg = {{{offset, offset+3}, {offset+w-1, offset+h+2}}};
                config expected=cfg;
                /* IDF validates minimum blocks before applying the floor. */
                if (w/5 >= 4 && h/5 >= 4) {
                    expected.subwindow.btm_right.x -= w%5;
                    expected.subwindow.btm_right.y -= h%5;
                }
                normalize(&cfg);
                assert(cfg.subwindow.top_left.x == expected.subwindow.top_left.x);
                assert(cfg.subwindow.top_left.y == expected.subwindow.top_left.y);
                assert(cfg.subwindow.btm_right.x == expected.subwindow.btm_right.x);
                assert(cfg.subwindow.btm_right.y == expected.subwindow.btm_right.y);
                cases++;
            }
        }
    }
    printf("AWB effective grid equivalence: %u cases passed\n", cases);
}
"""


def main():
    source = SOURCE.read_text(encoding="utf-8")
    begin = source.index("    int subwindow_width =", source.index("static void isp_init_awb_param"))
    end = source.index("#endif", begin)
    output = ROOT / "build/c61-investigation/awb-grid-check"
    output.mkdir(parents=True, exist_ok=True)
    test = output / "check.c"
    exe = output / "check"
    test.write_text(HARNESS.replace("@BODY@", source[begin:end]), encoding="utf-8")
    subprocess.run(["wsl", "-d", "Ubuntu", "--", "gcc", "-std=c11", "-Wall", "-Wextra",
                    "-Werror", wsl_path(test), "-o", wsl_path(exe)], check=True)
    subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(exe)], check=True)


if __name__ == "__main__":
    main()
