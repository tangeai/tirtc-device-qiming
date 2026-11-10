"""Exercise production crop/scale, RGB slot ownership and SPS color signaling."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r"^(?:static )?[^\n]*\b" + name + r"\(", source, re.M)
    if match is None:
        raise ValueError(name)
    opening = source.index("{", match.start())
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


converter = (ROOT / "main/media/video_frame_converter.c").read_text(encoding="utf-8")
renderer = (ROOT / "main/services/call_video_renderer.c").read_text(encoding="utf-8")
present = function(renderer, "call_video_renderer_present_next_rgb565")
assert "if (trace != NULL && ready->trace.frame_index" not in present
assert "*trace = ready->trace;" in present
mjpeg = function(renderer, "call_video_mjpeg_renderer_task")
layout = mjpeg.index(".trace.render_x")
assert layout < mjpeg.index("call_video_output_finish_write", layout)
macros = renderer.split("#define CALL_VIDEO_DECODED_SLOT_CAPACITY", 1)[1].split("_Static_assert", 1)[0]
macros = "#define CALL_VIDEO_DECODED_SLOT_CAPACITY" + macros
fit_type = converter.split("typedef struct {", 1)[1].split("} video_frame_ppa_fit_t;", 1)[0]
fit_type = "typedef struct {" + fit_type + "} video_frame_ppa_fit_t;"
slot_type = renderer.split("typedef struct {\n    uint16_t *pixels;", 1)[1].split("} call_video_output_slot_t;", 1)[0]
slot_type = "typedef struct {\n    uint16_t *pixels;" + slot_type + "} call_video_output_slot_t;"
functions = "\n".join(function(converter, name) for name in (
    "video_frame_rotation_is_valid", "video_frame_rotation_swaps_axes",
    "video_frame_resolve_ppa_fit", "video_frame_apply_fit_crop"))
functions += "\n" + function(renderer, "call_video_prepare_output_pool")
functions += "\n" + function(renderer, "call_video_output_begin_write")
functions += "\n" + "\n".join(function(renderer, name) for name in (
    "call_video_elapsed_us", "call_video_pts_is_newer",
    "call_video_note_received", "call_video_adaptive_playout_is_active"))
assert "const bool adaptive_playout = call_video_adaptive_playout_is_active(now_us);" in renderer

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "call_video_renderer.h"
#include "video_frame_converter.h"
#define MALLOC_CAP_DMA 1
#define MALLOC_CAP_CACHE_ALIGNED 2
#define CALL_VIDEO_CACHE_LINE_SIZE 64U
#define VIDEO_FRAME_PPA_SCALE_STEPS 16U
#define VIDEO_FRAME_PPA_SCALE_MAX_STEPS 255U
#define pdTRUE 1
#define pdMS_TO_TICKS(x) (x)
#define taskENTER_CRITICAL(x) ((void)(x))
#define taskEXIT_CRITICAL(x) ((void)(x))
#define ESP_RETURN_ON_FALSE(cond, error, ...) do { if (!(cond)) return (error); } while (0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
@MACROS@
@FIT_TYPE@
typedef enum { CALL_VIDEO_OUTPUT_FREE, CALL_VIDEO_OUTPUT_WRITING,
       CALL_VIDEO_OUTPUT_READY, CALL_VIDEO_OUTPUT_PRESENTED } call_video_output_state_t;
@SLOT_TYPE@
struct video_frame_converter {
    video_frame_converter_config_t config;
    int stats_lock;
    video_frame_converter_stats_t stats;
};
static struct {
    int lock;
    void *frame_mutex;
    call_video_codec_t codec;
    call_video_output_slot_t output_slots[CALL_VIDEO_OUTPUT_SLOT_COUNT];
    unsigned conversion_dropped_frames;
    int64_t last_received_at_us, adaptive_gap_confirm_until_us;
    int64_t adaptive_playout_until_us, adaptive_playout_activated_at_us;
    uint32_t receive_gap_window_max_us, adaptive_playout_generation;
    uint32_t received_pts, stale_received_frames;
    uint8_t adaptive_gap_samples, adaptive_playout_depth;
    bool received_pts_valid;
} s_renderer;
static size_t allocated[CALL_VIDEO_OUTPUT_SLOT_COUNT];
static unsigned allocations;
static int xSemaphoreTake(void *mutex, unsigned ticks) { (void)ticks; return mutex != NULL; }
static void xSemaphoreGive(void *mutex) { (void)mutex; }
static bool call_video_output_pop_ready_locked(uint8_t *index) {
    for (uint8_t i = 0; i < CALL_VIDEO_OUTPUT_SLOT_COUNT; i++) {
        if (s_renderer.output_slots[i].state == CALL_VIDEO_OUTPUT_READY) { *index = i; return true; }
    }
    return false;
}
static void *app_memory_aligned_calloc_psram(size_t align, size_t n, size_t size, int caps) {
    (void)caps;
    assert(allocations < CALL_VIDEO_OUTPUT_SLOT_COUNT);
    allocated[allocations++] = n * size;
    void *data = aligned_alloc(align, n * size);
    assert(data); memset(data, 0, n * size); return data;
}
@FUNCTIONS@
int main(void) {
    assert(CALL_VIDEO_MJPEG_FIT_MODE == VIDEO_FRAME_FIT_CONTAIN);
    assert(CALL_VIDEO_OUTPUT_SLOT_COUNT == 20);
    assert(CALL_VIDEO_MJPEG_OUTPUT_SLOT_COUNT == 3);
    assert(CALL_VIDEO_MJPEG_RENDER_WIDTH == 1024 && CALL_VIDEO_MJPEG_RENDER_HEIGHT == 600);
    unsigned cases = 0;
    for (unsigned codec=0;codec<2;codec++) {
        memset(&s_renderer,0,sizeof(s_renderer));s_renderer.codec=codec;
        call_video_note_received(1000000,1);
        call_video_note_received(1100000,2);
        call_video_note_received(2100000,3);
        assert(s_renderer.receive_gap_window_max_us==1000000);
        assert(call_video_adaptive_playout_is_active(2100000)==(codec==CALL_VIDEO_CODEC_H264));
        assert((s_renderer.adaptive_playout_generation!=0)==(codec==CALL_VIDEO_CODEC_H264));
        call_video_note_received(2200000,2);
        assert(s_renderer.stale_received_frames==1);
        s_renderer.adaptive_playout_until_us=9999999;
        assert(call_video_adaptive_playout_is_active(2300000)==(codec==CALL_VIDEO_CODEC_H264));
        cases++;
    }
    const uint16_t sources[][2] = {{240,320},{352,480},{480,640},{640,480},{1024,600},{600,1024}};
    for (unsigned i = 0; i < sizeof(sources)/sizeof(sources[0]); i++) {
        for (unsigned angle = 0; angle < 360; angle += 90) {
            struct video_frame_converter c = {.config = {
                .output_width = CALL_VIDEO_MJPEG_RENDER_WIDTH,
                .output_height = CALL_VIDEO_MJPEG_RENDER_HEIGHT,
                .fit_mode = CALL_VIDEO_MJPEG_FIT_MODE}};
            uint16_t x=0,y=0,w=sources[i][0],h=sources[i][1];
            assert(video_frame_apply_fit_crop(&c, angle, false, w, h, &x,&y,&w,&h) == ESP_OK);
            assert(x==0 && y==0 && w==sources[i][0] && h==sources[i][1]);
            video_frame_ppa_fit_t fit;
            assert(video_frame_resolve_ppa_fit(w,h,1024,600,angle,false,&fit));
            assert(fit.render_width <= 1024 && fit.render_height <= 600);
            assert(fit.offset_x*2+fit.render_width <= 1024 && fit.offset_y*2+fit.render_height <= 600);
            uint16_t rw=(angle==90 || angle==270)?h:w;
            uint16_t rh=(angle==90 || angle==270)?w:h;
            int aspect_error = (int)fit.render_width*rh - (int)fit.render_height*rw;
            assert(abs(aspect_error) <= rw+rh);
            cases++;
        }
    }
    assert(call_video_prepare_output_pool() == ESP_OK);
    assert(allocations == CALL_VIDEO_OUTPUT_SLOT_COUNT);
    size_t total = 0;
    for (unsigned i = 0; i < CALL_VIDEO_OUTPUT_SLOT_COUNT; i++) {
        total += allocated[i];
        assert(allocated[i] == (i < 3 ? 1024*600*2 : 512*300*2));
    }
    assert(total == CALL_VIDEO_RGB_POOL_BYTES && total == 8908800);
    s_renderer.frame_mutex = &s_renderer;
    for (unsigned codec=0; codec<2; codec++) {
        s_renderer.codec=codec;
        unsigned count=codec==CALL_VIDEO_CODEC_MJPEG?3:20;
        for (unsigned repeat=0; repeat<4; repeat++) {
            for (unsigned i=0;i<20;i++) s_renderer.output_slots[i].state=CALL_VIDEO_OUTPUT_FREE;
            for (unsigned i=0;i<count;i++) {
                uint8_t slot=255; uint16_t *pixels=NULL;
                assert(call_video_output_begin_write(&slot,&pixels)==ESP_OK && slot==i);
                assert(pixels==s_renderer.output_slots[i].pixels);
                assert(s_renderer.output_slots[i].width==(codec?1024:512));
                assert(s_renderer.output_slots[i].height==(codec?600:300));
                size_t frame_size=(size_t)s_renderer.output_slots[i].width*s_renderer.output_slots[i].height*2;
                assert(frame_size<=allocated[i]);
                memset(pixels,0x5a,frame_size);
                s_renderer.output_slots[i].state=CALL_VIDEO_OUTPUT_PRESENTED;
                cases++;
            }
            uint8_t slot=255; uint16_t *pixels=NULL;
            assert(call_video_output_begin_write(&slot,&pixels)==ESP_ERR_NOT_FOUND);
            s_renderer.output_slots[1].state=CALL_VIDEO_OUTPUT_READY;
            assert(call_video_output_begin_write(&slot,&pixels)==ESP_OK && slot==1);
            assert(s_renderer.output_slots[0].state==CALL_VIDEO_OUTPUT_PRESENTED);
        }
    }
    for(unsigned i=0;i<20;i++) free(s_renderer.output_slots[i].pixels);
    printf("crop/scale and RGB ownership: %u cases passed; RGB pool=%zu bytes\n",cases,total);
}
'''


def run(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command}\n{result.stdout}\n{result.stderr}")
    return result.stdout


class Bits:
    def __init__(self, data):
        self.bits = "".join(f"{value:08b}" for value in data)
        self.position = 0

    def u(self, length):
        value = int(self.bits[self.position:self.position + length], 2)
        self.position += length
        return value

    def ue(self):
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
        return (1 << zeros) - 1 + (self.u(zeros) if zeros else 0)


def parse_sps(hex_data):
    nal = bytes.fromhex(hex_data)[4:]
    rbsp = bytearray()
    zeros = 0
    for byte in nal:
        if zeros >= 2 and byte == 3:
            zeros = 0
            continue
        rbsp.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    bits = Bits(rbsp)
    assert bits.u(8) & 31 == 7
    assert bits.u(8) == 66
    bits.u(8); bits.u(8)
    bits.ue(); bits.ue()
    assert bits.ue() == 2
    bits.ue(); bits.u(1)
    width = 16 * (bits.ue() + 1)
    height = 16 * (bits.ue() + 1)
    assert bits.u(1) == 1
    bits.u(1)
    if bits.u(1):
        left, right, top, bottom = [bits.ue() for _ in range(4)]
        width -= 2 * (left + right)
        height -= 2 * (top + bottom)
    assert bits.u(1) == 1
    assert bits.u(1) == 0 and bits.u(1) == 0
    present = bits.u(1)
    full = matrix = None
    if present:
        assert bits.u(3) == 5
        full = bits.u(1)
        if bits.u(1):
            assert bits.u(8) == 2 and bits.u(8) == 2
            matrix = bits.u(8)
    assert bits.u(1) == 0 and bits.u(1) == 1
    tick, scale, fixed = bits.u(32), bits.u(32), bits.u(1)
    assert tick == 1 and fixed == 1
    return width, height, scale // 2, present, full, matrix


with tempfile.TemporaryDirectory(prefix="wt99-video-presentation-") as name:
    tmp = Path(name)
    (tmp / "soc").mkdir()
    (tmp / "esp_err.h").write_text("#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_ERR_INVALID_ARG 1\n#define ESP_ERR_TIMEOUT 2\n#define ESP_ERR_NOT_FOUND 3\n#define ESP_ERR_INVALID_SIZE 4\n#define ESP_ERR_NO_MEM 5\n")
    # Hardware-independent policy headers are included unchanged; only board
    # peripheral includes are excluded from this host build.
    board = (ROOT / "main/hardware/hardware_board_config.h").read_text(encoding="utf-8")
    board = "\n".join(line for line in board.splitlines() if not line.startswith("#include"))
    (tmp / "hardware_board_config.h").write_text("#define BSP_LCD_H_RES 1024U\n#define BSP_LCD_V_RES 600U\n" + board)
    (tmp / "soc/soc_caps.h").write_text("#define SOC_PSRAM_DMA_CAPABLE 0\n#define SOC_DMA_CAN_ACCESS_FLASH 0\n")
    (tmp / "esp_h264_efuse.h").write_text("#pragma once\n")
    code = HARNESS.replace("@MACROS@", macros).replace("@FIT_TYPE@", fit_type).replace("@SLOT_TYPE@", slot_type).replace("@FUNCTIONS@", functions)
    (tmp / "geometry.c").write_text(code)
    common = ["cc", "-std=c11", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", str(tmp)]
    includes = ["-I", str(ROOT / "main/services"), "-I", str(ROOT / "main/media")]
    run(common + includes + [str(tmp / "geometry.c"), "-o", str(tmp / "geometry")])
    print(run([str(tmp / "geometry")]), end="")
    ui_source = (ROOT / "components/p4_hardware/p4_video.c").read_text(encoding="utf-8")
    ui_test = r'''
#include <assert.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include "hardware_board_config.h"
#include "esp_err.h"
#define LV_IMG_CF_TRUE_COLOR 1
#define LV_OBJ_FLAG_HIDDEN 1
#define LV_OBJ_FLAG_CLICKABLE 2
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define LV_MIN(a,b) ((a)<(b)?(a):(b))
#define LV_MAX(a,b) ((a)>(b)?(a):(b))
typedef struct {bool hidden;} lv_obj_t;
typedef struct {int x1,y1,x2,y2;} lv_area_t;
typedef struct {uint16_t render_x,render_y,render_width,render_height;} call_video_frame_trace_t;
typedef struct {struct {unsigned cf,w,h;} header; size_t data_size; const uint8_t *data;} lv_img_dsc_t;
static atomic_uint s_live_generation=1;
static lv_obj_t *s_image, image;
static lv_img_dsc_t s_image_desc;
static lv_area_t s_active_area, last_dirty;
static bool s_active_area_valid;
static unsigned full_draws, partial_draws;
static call_video_frame_trace_t frame_trace={.render_x=292,.render_width=440,.render_height=600};
static const uint16_t buffers[2][2]={{1,2},{3,4}};
static unsigned next, releases, sources, invalidations, zoom, pivot_x, pivot_y;
static uint16_t frame_width=1024,frame_height=600;
static bool pinned, available=true, invalid;
static int64_t esp_timer_get_time(void) { static int64_t time; return ++time; }
static void lv_img_cache_invalidate_src(const void *src) { assert(src==&s_image_desc); invalidations++; }
static lv_obj_t *lv_img_create(lv_obj_t *screen) { (void)screen; return &image; }
static void lv_img_set_pivot(lv_obj_t *obj,int x,int y) { (void)obj;pivot_x=x;pivot_y=y; }
static void lv_img_set_antialias(lv_obj_t *obj,bool enable) { (void)obj;assert(!enable); }
static void lv_obj_set_pos(lv_obj_t *obj,int x,int y) { (void)obj;assert(!x&&!y); }
static void lv_obj_move_background(lv_obj_t *obj) { (void)obj; }
static void lv_obj_add_flag(lv_obj_t *obj,int flag) { assert(flag==LV_OBJ_FLAG_HIDDEN); obj->hidden=true; }
static bool lv_obj_has_flag(lv_obj_t *obj,int flag) { assert(flag==LV_OBJ_FLAG_HIDDEN); return obj->hidden; }
static void lv_obj_clear_flag(lv_obj_t *obj,int flag) { if(flag==LV_OBJ_FLAG_HIDDEN) obj->hidden=false; }
static void lv_obj_invalidate(lv_obj_t *obj) { assert(obj==s_image); assert(pinned && s_image_desc.data); full_draws++; }
static void lv_obj_invalidate_area(lv_obj_t *obj, const lv_area_t *area) {
    assert(obj==s_image && pinned && s_image_desc.data);
    assert(area->x1>=0 && area->y1>=0 && area->x2<1024 && area->y2<600);
    last_dirty=*area; partial_draws++;
}
static void lv_img_set_src(lv_obj_t *obj,const void *src) {
    assert(obj==s_image&&src==&s_image_desc);sources++;
    pivot_x=s_image_desc.header.w/2;pivot_y=s_image_desc.header.h/2;
}
static void lv_img_set_zoom(lv_obj_t *obj,unsigned value) { (void)obj;zoom=value; }
static esp_err_t call_video_renderer_present_next_rgb565(const uint16_t **pixels,size_t *count,
    uint16_t *width,uint16_t *height,void *sequence,call_video_frame_trace_t *trace) {
    assert(!sequence&&trace);
    if(!available) return ESP_ERR_NOT_FOUND;
    *width=frame_width; *height=frame_height; *count=(size_t)*width**height+(invalid?1:0);
    *pixels=buffers[next]; *trace=frame_trace; pinned=true; return ESP_OK;
}
static void call_video_renderer_release_presented_rgb565(void) { releases++;pinned=false; }
@UI_FUNCTIONS@
int main(void) {
    lv_obj_t screen={0};
    p4_video_ui_tick(&screen,true);
    assert(pinned && !releases && sources==1 && zoom==256 && !image.hidden);
    assert(!pivot_x && !pivot_y);
    assert(s_image_desc.data==(const uint8_t *)buffers[0]);
    assert(s_image_desc.data_size==1024*600*2);
    assert(full_draws==1 && partial_draws==0 && s_active_area_valid);
    available=false;
    p4_video_ui_tick(&screen,true);
    assert(pinned && !releases && s_image_desc.data==(const uint8_t *)buffers[0]);
    available=true;next=1;
    p4_video_ui_tick(&screen,true);
    assert(pinned && !releases && sources==1 && s_image_desc.data==(const uint8_t *)buffers[1]);
    assert(full_draws==1 && partial_draws==1);
    assert(last_dirty.x1==292 && last_dirty.x2==731 && last_dirty.y1==0 && last_dirty.y2==599);
    frame_trace.render_x=287; frame_trace.render_width=450;
    p4_video_ui_tick(&screen,true);
    assert(last_dirty.x1==287 && last_dirty.x2==736 && partial_draws==2);
    frame_trace.render_x=292; frame_trace.render_width=440;
    p4_video_ui_tick(&screen,true);
    assert(last_dirty.x1==287 && last_dirty.x2==736 && partial_draws==3);
    frame_trace.render_x=1020; frame_trace.render_width=440;
    p4_video_ui_tick(&screen,true);
    assert(!s_active_area_valid && full_draws==2);
    frame_trace.render_x=292;
    p4_video_ui_tick(&screen,true);
    assert(s_active_area_valid && full_draws==3);
    frame_width=512;frame_height=300;
    p4_video_ui_tick(&screen,true);
    assert(pinned && !releases && sources==2 && zoom==512);
    assert(!pivot_x && !pivot_y);
    p4_video_ui_reset();
    assert(!pinned && releases==1 && s_image==NULL && !s_image_desc.data);
    p4_video_ui_tick(&screen,true);
    assert(pinned && sources==3 && zoom==512 && !image.hidden);
    p4_video_ui_tick(&screen,false);
    assert(!pinned && releases==2 && image.hidden && !s_image_desc.data);
    p4_video_ui_tick(&screen,true);
    assert(pinned && !image.hidden && s_image_desc.data);
    invalid=true;
    p4_video_ui_tick(&screen,true);
    assert(!pinned && releases==3 && image.hidden && !s_image_desc.data);
    atomic_store(&s_live_generation,0);
    p4_video_ui_tick(&screen,true);
    assert(!pinned && releases==4);
    assert(invalidations>=8);
    puts("LVGL RGB ownership: direct source, retention, dirty picture bounds/union, no-frame, switch, reset, hide, invalid and stop passed");
}
'''
    ui_test = ui_test.replace("@UI_FUNCTIONS@", "\n".join(function(ui_source, name) for name in (
        "p4_video_ui_reset", "p4_video_ui_tick")))
    (tmp / "ui.c").write_text(ui_test)
    run(common + [str(tmp / "ui.c"), "-o", str(tmp / "ui")])
    print(run([str(tmp / "ui")]), end="")
    (tmp / "sps.c").write_text(r'''
#include <stdio.h>
#include "h264_nal.h"
int main(void) {
    const unsigned sizes[][2]={{1024,600},{384,256},{320,240}};
    const unsigned rates[]={1,12,15,20,30};
    for(unsigned i=0;i<3;i++) for(unsigned f=0;f<5;f++) for(unsigned mode=0;mode<4;mode++) {
        unsigned char buffer[160]={0};
        esp_h264_enc_vui_color_t c={.present=mode!=0,.full_range=mode==1,
            .color_description_present=true,.color_primaries=2,.transfer_characteristics=2,.matrix_coefficients=6};
        unsigned bits=esp_h264_enc_set_sps(buffer,sizeof(buffer),sizes[i][1],sizes[i][0],rates[f],mode==3?NULL:&c);
        printf("%u %u %u %u ", sizes[i][0],sizes[i][1],rates[f],mode);
        for(unsigned b=0;b<(bits+7)/8;b++) printf("%02x",buffer[b]);
        puts("");
    }
}
''')
    h264 = ROOT / "components/espressif__esp_h264"
    run(common + ["-I", str(h264 / "hw/src"), "-I", str(h264 / "interface/include"),
                  str(tmp / "sps.c"), str(h264 / "hw/src/h264_nal.c"), "-o", str(tmp / "sps")])
    samples = run([str(tmp / "sps")]).splitlines()
    for line in samples:
        width, height, fps, mode, value = line.split()
        mode = int(mode)
        expected_color = (1, 1 if mode == 1 else 0, 6) if mode in (1, 2) else (0, None, None)
        assert parse_sps(value) == (int(width), int(height), int(fps), *expected_color), line
    print(f"production SPS parse: {len(samples)} size/rate/color profiles passed")
