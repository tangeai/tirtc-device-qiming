"""Compile the actual diagnostic wrappers and retain callback ownership."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "main/drivers/display/display_driver.c").read_text(encoding="utf-8")
begin = source.index("static void (*s_original_flush)")
depth, selected = 1, []
for line in source[begin:].splitlines(keepends=True):
    if re.match(r"\s*#\s*(?:if|ifdef|ifndef)\b", line):
        depth += 1
    elif re.match(r"\s*#\s*endif\b", line):
        depth -= 1
        if depth == 0:
            break
    selected.append(line)
assert depth == 0
functions = "".join(selected)
assert "lv_disp_flush_ready" not in functions
assert "#if CONFIG_APP_DISPLAY_TIMING_DIAGNOSTICS" in source
assert re.search(r"config APP_DISPLAY_TIMING_DIAGNOSTICS\n.*\n    default n",
                 (ROOT / "main/Kconfig.projbuild").read_text(encoding="utf-8"))
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
typedef struct { int marker; } lv_disp_drv_t;
typedef struct { int marker,x1,y1,x2,y2; } lv_area_t;
typedef uint16_t lv_color_t;
typedef int16_t lv_coord_t;
typedef int lv_img_cf_t;
typedef struct { int marker; } lv_draw_ctx_t;
typedef struct { int marker; } lv_draw_img_dsc_t;
typedef struct { int marker; } lv_draw_rect_dsc_t;
static int64_t clock_us;
static int logs, flushes, starts, monitors, images, copies;
static int rectangles, backgrounds;
static int flush_stage, flush_notes;
static void display_ppa_note_flush(unsigned stage) {
    assert(stage==(flush_notes%2 ? 6U : 5U)); flush_stage=stage; flush_notes++;
}
#define ESP_LOGI(...) ((void)++logs)
static int64_t esp_timer_get_time(void) { return clock_us; }
@FUNCTIONS@
static void original_flush(lv_disp_drv_t *d, const lv_area_t *a, lv_color_t *p) {
    assert(d->marker==4 && a->marker==7 && *p==0xf800);
#if CONFIG_APP_DISPLAY_PPA_BLIT_DIAGNOSTICS
    assert(flush_stage==5);
#endif
    flushes++; clock_us+=1234;
}
static void original_start(lv_disp_drv_t *d) { assert(d->marker==4); starts++; }
static void original_monitor(lv_disp_drv_t *d, uint32_t ms, uint32_t px) {
    assert(d->marker==4 && ms==9 && px==614400); monitors++;
}
static void original_image(lv_draw_ctx_t *c, const lv_draw_img_dsc_t *d,
                           const lv_area_t *a, const uint8_t *p, lv_img_cf_t f) {
    assert(c->marker==1 && d->marker==2 && a->marker==7 && *p==3 && f==4);
    images++; clock_us+=222;
}
static void original_rectangle(lv_draw_ctx_t *c, const lv_draw_rect_dsc_t *d, const lv_area_t *a) {
    assert(c->marker==1 && d->marker==8 && a->marker==7);
    rectangles++; clock_us+=444;
}
static void original_background(lv_draw_ctx_t *c, const lv_draw_rect_dsc_t *d, const lv_area_t *a) {
    assert(c->marker==1 && d->marker==8 && a->marker==7);
    backgrounds++; clock_us+=555;
}
static void original_copy(lv_draw_ctx_t *c, void *d, lv_coord_t ds,
                          const lv_area_t *da, void *s, lv_coord_t ss,
                          const lv_area_t *sa) {
    assert(c->marker==1 && d==s && ds==19 && ss==21 && da==sa && da->marker==7);
    copies++; clock_us+=333;
}
int main(void) {
    lv_disp_drv_t d={4}; lv_area_t a={.marker=7,.x1=10,.y1=20,.x2=30,.y2=40}; lv_color_t p=0xf800;
    s_original_flush=original_flush;
    s_original_render_start=original_start;
    s_original_monitor=original_monitor;
    s_original_draw_image=original_image;
    s_original_buffer_copy=original_copy;
    s_original_draw_rectangle=original_rectangle;
    s_original_draw_background=original_background;
    lv_draw_ctx_t context={1}; lv_draw_img_dsc_t descriptor={2}; uint8_t pixel=3;
    lv_draw_rect_dsc_t rectangle={8};
    clock_us=1;
    display_driver_render_start(&d);
    display_driver_draw_image(&context,&descriptor,&a,&pixel,4);
    display_driver_draw_rectangle(&context,&rectangle,&a);
    display_driver_draw_background(&context,&rectangle,&a);
    display_driver_buffer_copy(&context,&pixel,19,&a,&pixel,21,&a);
    clock_us+=8000;
    display_driver_flush(&d,&a,&p);
    display_driver_monitor(&d,9,614400);
    assert(flushes==1 && starts==1 && monitors==1 && logs==0);
    assert(s_render_count==1 && s_flush_total_us==1234 && s_render_total_us==10788);
    assert(images==1 && copies==1 && s_image_count==1 && s_copy_count==1);
    assert(s_image_total_us==222 && s_image_max_us==222);
    assert(s_copy_total_us==333 && s_copy_max_us==333);
    assert(rectangles==1 && backgrounds==1 && s_rectangle_count==1 && s_background_count==1);
    assert(s_rectangle_total_us==444 && s_rectangle_max_us==444 && s_slowest_rectangle.x2==30);
    assert(s_background_total_us==555 && s_background_max_us==555);
    s_original_render_start=NULL; s_original_monitor=NULL;
    clock_us=15000001;
    display_driver_render_start(&d);
    display_driver_flush(&d,&a,&p);
    display_driver_monitor(&d,9,614400);
    assert(flushes==2 && starts==1 && monitors==1 && logs==2);
#if CONFIG_APP_DISPLAY_PPA_BLIT_DIAGNOSTICS
    assert(flush_stage==6 && flush_notes==4);
#endif
    assert(s_render_count==0 && s_flush_total_us==0 && s_render_total_us==0);
    assert(!s_image_count && !s_copy_count && !s_image_total_us && !s_copy_total_us);
    assert(!s_rectangle_count && !s_background_count && !s_rectangle_total_us && !s_background_total_us);
    return 0;
}
'''.replace("@FUNCTIONS@", functions)
with tempfile.TemporaryDirectory(prefix="display-timing-") as directory:
    test = Path(directory) / "test.c"
    binary = Path(directory) / "test"
    test.write_text(harness, encoding="ascii")
    for ppa in (0, 1):
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", "-Wno-unused-function",
                        f"-DCONFIG_APP_DISPLAY_PPA_BLIT_DIAGNOSTICS={ppa}",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
print("PASS: display timing delegates exactly once, no extra flush-ready, bounded aggregates, default off")

product = (ROOT / "components/starter_product/src/starter_product.c").read_text(encoding="utf-8")
begin = product.index("static void product_video_tick(lv_timer_t *timer)\n{")
end = product.index("\n}\n#endif", begin) + 2
video_tick = product[begin:end]
tick_harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef struct { int marker; } lv_timer_t;
typedef struct { int state; } starter_runtime_status_t;
enum { PAGE_CALL=12, STARTER_RUNTIME_H5_ACTIVE=1 };
static int s_page, state, status_calls, video_calls, logs;
static int64_t clock_us;
static uint32_t status_cost=123, video_cost=456;
static uint64_t log_status, log_video;
static uint32_t log_n, log_status_max, log_video_max;
static int64_t esp_timer_get_time(void) { return clock_us; }
static starter_runtime_status_t starter_runtime_status(void) {
    status_calls++; clock_us+=status_cost;
    return (starter_runtime_status_t){state};
}
static void *lv_scr_act(void) { return &state; }
static void p4_video_ui_tick(void *screen, bool show) {
    assert(screen==&state && show==(s_page==PAGE_CALL || state==STARTER_RUNTIME_H5_ACTIVE));
    video_calls++; clock_us+=video_cost;
}
#define ESP_LOGI(tag,format,n,sa,sm,va,vm) do { logs++; log_n=(n); log_status=(sa); \
    log_status_max=(sm); log_video=(va); log_video_max=(vm); } while(0)
@VIDEO_TICK@
int main(void) {
    clock_us=1; product_video_tick(NULL);
    assert(status_calls==1 && video_calls==1 && !logs);
    s_page=PAGE_CALL; state=STARTER_RUNTIME_H5_ACTIVE;
    clock_us=15000001; product_video_tick(NULL);
    assert(status_calls==2 && video_calls==2);
#if CONFIG_APP_DISPLAY_TIMING_DIAGNOSTICS
    assert(logs==1 && log_n==2 && log_status==123 && log_status_max==123);
    assert(log_video==456 && log_video_max==456);
    status_cost=21; video_cost=42; clock_us+=15000000;
    product_video_tick(NULL);
    assert(logs==2 && log_n==1 && log_status==21 && log_video==42);
#else
    assert(!logs);
#endif
    return 0;
}
'''.replace("@VIDEO_TICK@", video_tick)
with tempfile.TemporaryDirectory(prefix="product-video-timing-") as directory:
    test = Path(directory) / "test.c"
    binary = Path(directory) / "test"
    test.write_text(tick_harness, encoding="utf-8")
    for enabled in (0, 1):
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-variable", "-Wno-unused-function",
                        f"-DCONFIG_APP_DISPLAY_TIMING_DIAGNOSTICS={enabled}",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
print("PASS: UI timing preserves status/video calls with diagnostics off/on and resets aggregates")
