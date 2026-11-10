/* Private opt-in experiment. The LVGL owner and original flush remain unchanged. */
#include "driver/ppa.h"
#include "esp_heap_caps.h"
#include "freertos/task.h"
#include <stdatomic.h>

#define DISPLAY_PPA_ALIGNMENT CONFIG_CACHE_L2_CACHE_LINE_SIZE
static ppa_client_handle_t s_display_ppa;
static void (*s_cpu_draw_image)(lv_draw_ctx_t *, const lv_draw_img_dsc_t *,
                                const lv_area_t *, const uint8_t *, lv_img_cf_t);
static atomic_uint s_display_ppa_frames;
static portMUX_TYPE s_display_ppa_lock=portMUX_INITIALIZER_UNLOCKED;
typedef struct {
    uint32_t sequence, stage, at_ms, width, height, core;
    lv_area_t clip;
    uintptr_t source, destination, task;
} display_ppa_state_t;
static display_ppa_state_t s_display_ppa_state;

static void display_ppa_note_flush(uint32_t stage)
{
    uint32_t now=(uint32_t)(esp_timer_get_time()/1000);
    taskENTER_CRITICAL(&s_display_ppa_lock);
    s_display_ppa_state.stage=stage;
    s_display_ppa_state.at_ms=now;
    taskEXIT_CRITICAL(&s_display_ppa_lock);
}

static void display_ppa_mark(uint32_t stage, const uint16_t *source,
                             uint16_t *destination, uint32_t width,
                             uint32_t height, const lv_area_t *clip)
{
    uint32_t now=(uint32_t)(esp_timer_get_time()/1000);
    taskENTER_CRITICAL(&s_display_ppa_lock);
    if (stage==1) s_display_ppa_state.sequence++;
    s_display_ppa_state.stage=stage;
    s_display_ppa_state.at_ms=now;
    s_display_ppa_state.width=width;
    s_display_ppa_state.height=height;
    s_display_ppa_state.clip=*clip;
    s_display_ppa_state.source=(uintptr_t)source;
    s_display_ppa_state.destination=(uintptr_t)destination;
    s_display_ppa_state.task=(uintptr_t)xTaskGetCurrentTaskHandle();
    s_display_ppa_state.core=(uint32_t)xPortGetCoreID();
    taskEXIT_CRITICAL(&s_display_ppa_lock);
}

static esp_err_t display_ppa_copy(const uint16_t *source, uint16_t *destination,
                                uint32_t width, uint32_t height,
                                const lv_area_t *clip)
{
    display_ppa_mark(1,source,destination,width,height,clip);
    const size_t bytes = (size_t)width * height * sizeof(uint16_t);
    const size_t first_row = (size_t)clip->y1 * width * sizeof(uint16_t);
    const size_t row_bytes = (size_t)(clip->y2 - clip->y1 + 1) * width * sizeof(uint16_t);
    /* PPA invalidates whole destination rows, including pixels outside the ROI. */
    ESP_RETURN_ON_ERROR(esp_cache_msync((uint8_t *)destination + first_row, row_bytes,
                        ESP_CACHE_MSYNC_FLAG_DIR_C2M | ESP_CACHE_MSYNC_FLAG_UNALIGNED),
                        TAG, "LCD PPA preserve neighboring pixels failed");
    display_ppa_mark(2,source,destination,width,height,clip);
    const ppa_in_pic_blk_config_t input = {
               .buffer=source, .pic_w=width, .pic_h=height,
               .block_w=(uint32_t)(clip->x2-clip->x1+1),
               .block_h=(uint32_t)(clip->y2-clip->y1+1),
               .block_offset_x=(uint32_t)clip->x1, .block_offset_y=(uint32_t)clip->y1,
               .blend_cm=PPA_BLEND_COLOR_MODE_RGB565};
    const ppa_blend_oper_config_t operation = {
        .in_bg=input, .in_fg=input,
        .out = {.buffer=destination, .buffer_size=bytes, .pic_w=width, .pic_h=height,
                .block_offset_x=(uint32_t)clip->x1, .block_offset_y=(uint32_t)clip->y1,
                .blend_cm=PPA_BLEND_COLOR_MODE_RGB565},
        .bg_alpha_update_mode=PPA_ALPHA_FIX_VALUE, .bg_alpha_fix_val=0,
        .fg_alpha_update_mode=PPA_ALPHA_FIX_VALUE, .fg_alpha_fix_val=255,
        .mode=PPA_TRANS_MODE_BLOCKING,
    };
    display_ppa_mark(3,source,destination,width,height,clip);
    esp_err_t result=ppa_do_blend(s_display_ppa, &operation);
    display_ppa_mark(4,source,destination,width,height,clip);
    return result;
}

static bool display_ppa_try_image(lv_draw_ctx_t *context,
                                  const lv_draw_img_dsc_t *descriptor,
                                  const lv_area_t *area, const uint8_t *pixels,
                                  lv_img_cf_t format)
{
    if (!s_display_ppa || !context || !descriptor || !area || !pixels ||
        !context->buf || !context->buf_area || !context->clip_area ||
        format != LV_IMG_CF_TRUE_COLOR || descriptor->opa != LV_OPA_COVER ||
        descriptor->recolor_opa != LV_OPA_TRANSP || descriptor->angle != 0 ||
        descriptor->zoom != LV_IMG_ZOOM_NONE || descriptor->blend_mode != LV_BLEND_MODE_NORMAL ||
        area->x1 != 0 || area->y1 != 0 ||
        area->x2 != BSP_LCD_H_RES-1 || area->y2 != BSP_LCD_V_RES-1 ||
        context->buf_area->x1 != area->x1 || context->buf_area->y1 != area->y1 ||
        context->buf_area->x2 != area->x2 || context->buf_area->y2 != area->y2 ||
        !esp_ptr_external_ram(pixels) || !esp_ptr_external_ram(context->buf) ||
        lv_draw_mask_is_any(context->clip_area)) return false;
    const size_t bytes = (size_t)BSP_LCD_H_RES * BSP_LCD_V_RES * sizeof(uint16_t);
    uintptr_t source = (uintptr_t)pixels, destination = (uintptr_t)context->buf;
    if ((source % DISPLAY_PPA_ALIGNMENT) || (destination % DISPLAY_PPA_ALIGNMENT) ||
        (bytes % DISPLAY_PPA_ALIGNMENT) ||
        (source < destination+bytes && destination < source+bytes)) return false;
    lv_area_t clip;
    if (!_lv_area_intersect(&clip, area, context->clip_area)) return true;
    esp_err_t result = display_ppa_copy((const uint16_t *)pixels, context->buf,
                                       BSP_LCD_H_RES, BSP_LCD_V_RES, &clip);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "LCD PPA image failed: %s; original CPU draw retained", esp_err_to_name(result));
        return false;
    }
    if (atomic_fetch_add(&s_display_ppa_frames,1) == 0) ESP_LOGI(TAG, "LCD PPA blend opaque RGB565 first blit completed");
    return true;
}

static void display_ppa_draw_image(lv_draw_ctx_t *context,
                                   const lv_draw_img_dsc_t *descriptor,
                                   const lv_area_t *area, const uint8_t *pixels,
                                   lv_img_cf_t format)
{
    if (!display_ppa_try_image(context, descriptor, area, pixels, format))
        s_cpu_draw_image(context, descriptor, area, pixels, format);
}

static esp_err_t display_ppa_self_test(void)
{
    const uint32_t width=1024, height=600;
    const size_t bytes=(size_t)width*height*sizeof(uint16_t);
    uint16_t *source=heap_caps_aligned_alloc(DISPLAY_PPA_ALIGNMENT, bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    uint16_t *destination=heap_caps_aligned_alloc(DISPLAY_PPA_ALIGNMENT, bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!source || !destination) {
        heap_caps_free(source);
        heap_caps_free(destination);
        return ESP_ERR_NO_MEM;
    }
    for (uint32_t i=0; i<width*height; ++i) source[i]=(uint16_t)i;
    const lv_area_t regions[]={{0,0,1023,599},{545,223,739,350},{13,17,173,153},
                              {0,0,0,0},{1023,599,1023,599},{1,0,1022,599}};
    esp_err_t result=ESP_OK;
    for (size_t test=0; test<sizeof(regions)/sizeof(regions[0]) && result==ESP_OK; ++test) {
        for (uint32_t i=0; i<width*height; ++i) destination[i]=0xa55a;
        result=display_ppa_copy(source, destination, width, height, &regions[test]);
        for (uint32_t y=0; y<height && result==ESP_OK; ++y) {
            for (uint32_t x=0; x<width; ++x) {
                bool inside=x>=(uint32_t)regions[test].x1 && x<=(uint32_t)regions[test].x2 &&
                            y>=(uint32_t)regions[test].y1 && y<=(uint32_t)regions[test].y2;
                uint16_t expected=inside ? source[y*width+x] : 0xa55a;
                if (destination[y*width+x] != expected) {
                    ESP_LOGE(TAG, "LCD PPA self-test mismatch case=%u x=%lu y=%lu expected=%04x actual=%04x",
                             (unsigned)test, (unsigned long)x, (unsigned long)y,
                             (unsigned)expected, (unsigned)destination[y*width+x]);
                    result=ESP_FAIL;
                    break;
                }
            }
        }
    }
    heap_caps_free(source);
    heap_caps_free(destination);
    if (result==ESP_OK) ESP_LOGI(TAG, "LCD PPA self-test passed: 65536 RGB565 values, six panel-size ROI/border cases including 545,223-739,350, neighboring pixels preserved");
    return result;
}

static void display_ppa_install(lv_draw_ctx_t *context)
{
    if (!context || !context->draw_img_decoded) return;
    const ppa_client_config_t config={.oper_type=PPA_OPERATION_BLEND, .max_pending_trans_num=1};
    esp_err_t result=ppa_register_client(&config, &s_display_ppa);
    if (result==ESP_OK) result=display_ppa_self_test();
    if (result!=ESP_OK) {
        ESP_LOGE(TAG, "LCD PPA unavailable: %s; CPU renderer unchanged", esp_err_to_name(result));
        if (s_display_ppa) ppa_unregister_client(s_display_ppa);
        s_display_ppa=NULL;
        return;
    }
    s_cpu_draw_image=context->draw_img_decoded;
    context->draw_img_decoded=display_ppa_draw_image;
}
