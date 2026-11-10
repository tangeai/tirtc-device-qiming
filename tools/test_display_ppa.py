"""Exercise the actual opt-in adapter; the real PPA pixels are checked on device."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "main/drivers/display/display_ppa_blit.inc").read_text(encoding="utf-8")
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lvgl.h"
typedef int esp_err_t;
typedef void *ppa_client_handle_t;
enum { ESP_OK, ESP_FAIL, ESP_ERR_NO_MEM, PPA_OPERATION_BLEND,
       PPA_BLEND_COLOR_MODE_RGB565, PPA_ALPHA_FIX_VALUE, PPA_TRANS_MODE_BLOCKING };
#define CONFIG_CACHE_L2_CACHE_LINE_SIZE 128
#define BSP_LCD_H_RES 64
#define BSP_LCD_V_RES 32
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
#define ESP_CACHE_MSYNC_FLAG_DIR_C2M 1
#define ESP_CACHE_MSYNC_FLAG_UNALIGNED 2
#define ESP_RETURN_ON_ERROR(expr,...) do { int ret=(expr); if(ret) return ret; } while(0)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)++errors)
typedef struct { int oper_type; unsigned max_pending_trans_num; } ppa_client_config_t;
typedef struct { const void *buffer; uint32_t pic_w,pic_h,block_w,block_h,block_offset_x,block_offset_y; int blend_cm; } ppa_in_pic_blk_config_t;
typedef struct { void *buffer; uint32_t buffer_size,pic_w,pic_h,block_offset_x,block_offset_y; int blend_cm; } ppa_out_t;
typedef struct { ppa_in_pic_blk_config_t in_bg,in_fg; ppa_out_t out; int bg_alpha_update_mode,fg_alpha_update_mode; unsigned bg_alpha_fix_val,fg_alpha_fix_val; int mode; } ppa_blend_oper_config_t;
static unsigned errors, calls, cpu_calls, unregistered;
static int operation_error, cache_error, register_error;
static bool masks, corrupt, external=true;
static unsigned allocations, allocation_failure;
static void *flushed;
static size_t flushed_size;
static unsigned char saved_rows[1024*600*2];
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define taskENTER_CRITICAL(lock) ((void)(lock))
#define taskEXIT_CRITICAL(lock) ((void)(lock))
static int64_t esp_timer_get_time(void) { return 1000000; }
static void *xTaskGetCurrentTaskHandle(void) { return (void *)7; }
static unsigned xPortGetCoreID(void) { return 1; }
static int esp_cache_msync(void *pointer, size_t bytes, unsigned flags) {
    assert(flags==(ESP_CACHE_MSYNC_FLAG_DIR_C2M|ESP_CACHE_MSYNC_FLAG_UNALIGNED));
    if(cache_error) return cache_error;
    assert(bytes<=sizeof(saved_rows));
    flushed=pointer; flushed_size=bytes;
    memcpy(saved_rows,pointer,bytes);
    return ESP_OK;
}
static bool esp_ptr_external_ram(const void *pointer) { assert(pointer); return external; }
#ifndef DISPLAY_PPA_REAL_LVGL
bool lv_draw_mask_is_any(const lv_area_t *clip) { assert(clip); return masks; }
#endif
static int ppa_register_client(const ppa_client_config_t *config, void **client) {
    assert(config->oper_type==PPA_OPERATION_BLEND && config->max_pending_trans_num==1);
    if(register_error) return register_error;
    *client=(void *)1; return ESP_OK;
}
static int ppa_unregister_client(void *client) { assert(client==(void *)1); unregistered++; return ESP_OK; }
static void *heap_caps_aligned_alloc(size_t alignment, size_t bytes, int flags) {
    assert(flags==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(++allocations==allocation_failure) return NULL;
    return aligned_alloc(alignment,bytes);
}
static void heap_caps_free(void *pointer) { free(pointer); }
static int ppa_do_blend(void *client, const ppa_blend_oper_config_t *o) {
    assert(client==(void *)1); calls++;
    if(operation_error) return operation_error;
    assert(o->mode==PPA_TRANS_MODE_BLOCKING);
    assert(o->in_fg.blend_cm==PPA_BLEND_COLOR_MODE_RGB565 && o->out.blend_cm==PPA_BLEND_COLOR_MODE_RGB565);
    assert(o->in_fg.pic_w==o->out.pic_w && o->in_fg.pic_h==o->out.pic_h);
    assert(o->bg_alpha_update_mode==PPA_ALPHA_FIX_VALUE && o->bg_alpha_fix_val==0);
    assert(o->fg_alpha_update_mode==PPA_ALPHA_FIX_VALUE && o->fg_alpha_fix_val==255);
    assert(o->in_bg.buffer==o->in_fg.buffer);
    assert(o->out.buffer_size==o->out.pic_w*o->out.pic_h*2);
    assert(o->in_fg.block_offset_x==o->out.block_offset_x && o->in_fg.block_offset_y==o->out.block_offset_y);
    uint16_t *destination=o->out.buffer;
    const uint16_t *source=o->in_fg.buffer;
    size_t offset=(size_t)o->out.block_offset_y*o->out.pic_w;
    assert(flushed==destination+offset);
    assert(flushed_size==(size_t)o->in_fg.block_h*o->out.pic_w*2);
    /* Model PPA's whole-row invalidation, including columns outside the ROI. */
    memset(destination+offset,0,flushed_size);
    memcpy(destination+offset,saved_rows,flushed_size);
    for(uint32_t y=0;y<o->in_fg.block_h;y++)
        for(uint32_t x=0;x<o->in_fg.block_w;x++) {
            size_t index=(size_t)(y+o->in_fg.block_offset_y)*o->in_fg.pic_w+x+o->in_fg.block_offset_x;
            destination[index]=source[index];
        }
    if(corrupt) destination[offset+o->out.block_offset_x]^=1;
    return ESP_OK;
}
#ifndef DISPLAY_PPA_REAL_LVGL
static bool _lv_area_intersect_stub(lv_area_t *result,const lv_area_t *a,const lv_area_t *b) {
    result->x1=a->x1>b->x1?a->x1:b->x1; result->y1=a->y1>b->y1?a->y1:b->y1;
    result->x2=a->x2<b->x2?a->x2:b->x2; result->y2=a->y2<b->y2?a->y2:b->y2;
    return result->x1<=result->x2 && result->y1<=result->y2;
}
#define _lv_area_intersect _lv_area_intersect_stub
#endif
@SOURCE@
static void cpu_draw(lv_draw_ctx_t *c,const lv_draw_img_dsc_t *d,const lv_area_t *a,const uint8_t *p,lv_img_cf_t f) {
    (void)c;(void)d;(void)a;(void)p;(void)f; cpu_calls++;
}
int main(void) {
    lv_draw_ctx_t context={.draw_img_decoded=cpu_draw};
    display_ppa_install(&context);
    assert(context.draw_img_decoded==display_ppa_draw_image && calls==6 && !errors);
    uint16_t *source=aligned_alloc(128,64*32*2), *destination=aligned_alloc(128,64*32*2);
    assert(source && destination);
    for(unsigned i=0;i<64*32;i++) { source[i]=(uint16_t)(i*31); destination[i]=0xa55a; }
    lv_area_t area={0,0,63,31}, clip={13,5,44,23};
    context.buf=destination; context.buf_area=&area; context.clip_area=&clip;
    lv_draw_img_dsc_t descriptor={.opa=LV_OPA_COVER,.zoom=LV_IMG_ZOOM_NONE};
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    assert(calls==7 && !cpu_calls && s_display_ppa_frames==1);
    display_ppa_note_flush(5);
    assert(s_display_ppa_state.stage==5);
    display_ppa_note_flush(6);
    assert(s_display_ppa_state.stage==6);
    for(unsigned y=0;y<32;y++) for(unsigned x=0;x<64;x++) {
        uint16_t expected=x>=13 && x<=44 && y>=5 && y<=23 ? source[y*64+x] : 0xa55a;
        assert(destination[y*64+x]==expected);
    }
    unsigned before=calls;
    descriptor.opa=128; context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    descriptor.opa=LV_OPA_COVER; descriptor.recolor_opa=1;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    descriptor.recolor_opa=0; descriptor.angle=90;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    descriptor.angle=0; descriptor.zoom=255;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    descriptor.zoom=LV_IMG_ZOOM_NONE; masks=true;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    masks=false; context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR_ALPHA);
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)destination,LV_IMG_CF_TRUE_COLOR);
    assert(calls==before && cpu_calls==7);
    descriptor.blend_mode=LV_BLEND_MODE_ADDITIVE;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    descriptor.blend_mode=LV_BLEND_MODE_NORMAL; external=false;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    external=true; context.buf=destination+1;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    context.buf=destination; lv_area_t smaller={0,0,63,30}; context.buf_area=&smaller;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    context.buf_area=&area;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)(source+4),LV_IMG_CF_TRUE_COLOR);
    assert(calls==before && cpu_calls==12);
    lv_area_t empty={64,0,90,30}; context.clip_area=&empty;
    assert(display_ppa_try_image(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR));
    assert(calls==before);
    context.clip_area=&clip; operation_error=ESP_FAIL;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    assert(calls==before+1 && cpu_calls==13 && errors==1);
    operation_error=0; cache_error=ESP_FAIL;
    context.draw_img_decoded(&context,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR);
    assert(calls==before+1 && cpu_calls==14 && errors==2);
    cache_error=0; corrupt=true;
    assert(display_ppa_self_test()==ESP_FAIL);
    corrupt=false;
    allocations=0; allocation_failure=1;
    assert(display_ppa_self_test()==ESP_ERR_NO_MEM);
    allocations=0; allocation_failure=2;
    assert(display_ppa_self_test()==ESP_ERR_NO_MEM);
    allocation_failure=0;
    ppa_unregister_client(s_display_ppa); s_display_ppa=NULL;
    context.draw_img_decoded=cpu_draw; register_error=ESP_FAIL;
    display_ppa_install(&context);
    assert(context.draw_img_decoded==cpu_draw && !s_display_ppa);
    assert(!display_ppa_try_image(NULL,&descriptor,&area,(uint8_t *)source,LV_IMG_CF_TRUE_COLOR));
    free(source); free(destination);
    puts("PASS: production PPA adapter, complete RGB565 self-test model, clipped row guards, style/mask/alias CPU delegation, cache/operation/self-test/register failures retained; actual hardware pixels remain a separate gate");
    return 0;
}
'''
SUPPORT, BODY = harness.split("@SOURCE@")
harness = SUPPORT + source + BODY
if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="display-ppa-") as directory:
        folder = Path(directory)
        (folder / "driver").mkdir()
        (folder / "freertos").mkdir()
        (folder / "freertos/task.h").write_text("", encoding="ascii")
        (folder / "driver/ppa.h").write_text("", encoding="ascii")
        (folder / "esp_heap_caps.h").write_text("", encoding="ascii")
        test, binary = folder / "test.c", folder / "test"
        test.write_text(harness, encoding="utf-8")
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable",
                        "-DLV_CONF_SKIP", "-DLV_COLOR_DEPTH=16", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", "-I", str(folder), "-I", str(root / "managed_components/lvgl__lvgl"),
                        str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
