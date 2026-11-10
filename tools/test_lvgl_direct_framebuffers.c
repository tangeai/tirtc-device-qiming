#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lvgl.h"

#define WIDTH 128
#define HEIGHT 64

typedef struct {
    lv_disp_t *display;
    lv_disp_draw_buf_t draw;
    lv_disp_drv_t driver;
    lv_color_t *buffers[2];
    const lv_color_t *front;
    lv_obj_t *image;
    lv_obj_t *control;
    lv_img_dsc_t descriptor;
    uint32_t refreshed_pixels;
} surface_t;

static _Alignas(128) lv_color_t s_picture[2][WIDTH * HEIGHT];
static _Alignas(128) lv_color_t s_unaligned_picture[WIDTH * HEIGHT + 64];
static uint32_t simulated_draw_ms, simulated_frames;

static void flush(lv_disp_drv_t *driver, const lv_area_t *area, lv_color_t *pixels)
{
    surface_t *surface = driver->user_data;
    assert(area->x1 == 0 && area->y1 == 0);
    assert(area->x2 == WIDTH - 1 && area->y2 == HEIGHT - 1);
    assert(pixels == surface->buffers[0] || pixels == surface->buffers[1]);
    if (lv_disp_flush_is_last(driver)) {
        surface->front = pixels;
        if (simulated_draw_ms) {
            simulated_frames++;
            lv_tick_inc(simulated_draw_ms);
        }
    }
    lv_disp_flush_ready(driver);
}

static void monitor(lv_disp_drv_t *driver, uint32_t elapsed, uint32_t pixels)
{
    (void)elapsed;
    surface_t *surface = driver->user_data;
    surface->refreshed_pixels = pixels;
}

static void create(surface_t *surface, bool direct)
{
    for (unsigned i = 0; i < 2; ++i) {
#ifdef DISPLAY_TEST_PPA
        surface->buffers[i] = aligned_alloc(128, WIDTH * HEIGHT * sizeof(lv_color_t));
        if(surface->buffers[i]) memset(surface->buffers[i],0,WIDTH * HEIGHT * sizeof(lv_color_t));
#else
        surface->buffers[i] = calloc(WIDTH * HEIGHT, sizeof(lv_color_t));
#endif
        assert(surface->buffers[i]);
    }
    lv_disp_draw_buf_init(&surface->draw, surface->buffers[0], surface->buffers[1],
                         WIDTH * HEIGHT);
    lv_disp_drv_init(&surface->driver);
    surface->driver.hor_res = WIDTH;
    surface->driver.ver_res = HEIGHT;
    surface->driver.draw_buf = &surface->draw;
    surface->driver.direct_mode = direct;
    surface->driver.full_refresh = !direct;
    surface->driver.flush_cb = flush;
    surface->driver.monitor_cb = monitor;
    surface->driver.user_data = surface;
    surface->display = lv_disp_drv_register(&surface->driver);
    assert(surface->display);
#ifdef DISPLAY_TEST_PPA
    if(direct) display_ppa_install(surface->display->driver->draw_ctx);
#endif
    lv_obj_t *screen = lv_disp_get_scr_act(surface->display);
    lv_obj_remove_style_all(screen);
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    surface->descriptor.header.cf = LV_IMG_CF_TRUE_COLOR;
    surface->descriptor.header.w = WIDTH;
    surface->descriptor.header.h = HEIGHT;
    surface->descriptor.data_size = sizeof(s_picture[0]);
    surface->descriptor.data = (const uint8_t *)s_picture[0];
    surface->image = lv_img_create(screen);
    lv_img_set_src(surface->image, &surface->descriptor);
    lv_obj_set_pos(surface->image, 0, 0);
    surface->control = lv_obj_create(screen);
    lv_obj_remove_style_all(surface->control);
    lv_obj_set_pos(surface->control, 5, 6);
    lv_obj_set_size(surface->control, 20, 18);
    lv_obj_set_style_bg_color(surface->control, lv_color_hex(0xff0000), 0);
    lv_obj_set_style_bg_opa(surface->control, LV_OPA_70, 0);
}

static void refresh(surface_t *surface)
{
    lv_tick_inc(40);
    lv_refr_now(surface->display);
    assert(surface->front);
}

typedef struct {
    surface_t *surface;
    uint32_t origin, sequence;
} cadence_t;

static void cadence_video(lv_timer_t *timer)
{
    cadence_t *cadence = timer->user_data;
    uint32_t sequence = (lv_tick_get() - cadence->origin) / 67U;
    if (sequence != cadence->sequence) {
        cadence->sequence = sequence;
        lv_obj_invalidate(cadence->surface->image);
    }
}

static uint32_t measure_cadence(uint32_t refresh_ms)
{
    surface_t surface = {0};
    create(&surface, true);
    lv_timer_set_period(_lv_disp_get_refr_timer(surface.display), refresh_ms);
    cadence_t cadence = {.surface=&surface, .origin=lv_tick_get()};
    lv_timer_t *timer = lv_timer_create(cadence_video, 10, &cadence);
    simulated_draw_ms = 60;
    simulated_frames = 0;
    while (lv_tick_get() - cadence.origin < 30000U) {
        uint32_t delay = lv_timer_handler();
        if (delay > 10U) delay = 10U;
        lv_tick_inc(delay ? delay : 1U);
    }
    uint32_t frames = simulated_frames;
    simulated_draw_ms = 0;
    lv_timer_del(timer);
    lv_disp_remove(surface.display);
    for (unsigned i=0; i<2; ++i) free(surface.buffers[i]);
    return frames;
}

#ifdef DISPLAY_TEST_IMAGE_COVER
#include "test_lvgl_image_cover.c"
#endif

int main(void)
{
    lv_init();
#ifdef DISPLAY_TEST_IMAGE_COVER
    test_image_cover();
#endif
    surface_t direct = {0}, reference = {0};
    create(&direct, true);
    create(&reference, false);
    unsigned old_left = 32, old_width = 64;
    uint64_t pixel_hash = 14695981039346656037ULL;
    for (unsigned frame = 0; frame < 40; ++frame) {
        unsigned left = frame % 3 == 0 ? 24 : 32;
        unsigned width = frame % 3 == 0 ? 80 : 64;
        lv_color_t *picture = s_picture[frame & 1];
        memset(picture, 0, sizeof(s_picture[0]));
        for (unsigned y = 0; y < HEIGHT; ++y) {
            for (unsigned x = left; x < left + width; ++x) {
                picture[y * WIDTH + x] = lv_color_make((uint8_t)(frame * 5 + x),
                                                      (uint8_t)(y * 3),
                                                      (uint8_t)(frame * 7));
            }
        }
        if (frame % 5 == 3) {
            memcpy(s_unaligned_picture+4,picture,sizeof(s_picture[0]));
            picture=s_unaligned_picture+4;
        }
        surface_t *surfaces[] = {&direct, &reference};
        for (unsigned i = 0; i < 2; ++i) {
            surface_t *surface = surfaces[i];
            lv_img_cache_invalidate_src(&surface->descriptor);
            surface->descriptor.data = (const uint8_t *)picture;
            if (frame % 11 == 0) {
                lv_obj_add_flag(surface->image, LV_OBJ_FLAG_HIDDEN);
            } else if (lv_obj_has_flag(surface->image, LV_OBJ_FLAG_HIDDEN)) {
                lv_obj_clear_flag(surface->image, LV_OBJ_FLAG_HIDDEN);
            }
            if (frame % 7 == 0) {
                lv_obj_set_style_bg_color(surface->control,
                                         lv_color_hex(frame & 1 ? 0x00ff00 : 0xff0000), 0);
                lv_obj_set_pos(surface->control, 5 + frame, 6);
            }
            bool visible = frame % 6 != 0;
            if (!i) {
                set_object_visible(surface->control, visible);
            } else if (visible) {
                lv_obj_clear_flag(surface->control, LV_OBJ_FLAG_HIDDEN);
            } else {
                lv_obj_add_flag(surface->control, LV_OBJ_FLAG_HIDDEN);
            }
            if (!i && frame) {
                lv_area_t dirty = {
                    .x1 = (lv_coord_t)(left < old_left ? left : old_left),
                    .y1 = 0,
                    .x2 = (lv_coord_t)((left + width > old_left + old_width ?
                                       left + width : old_left + old_width) - 1),
                    .y2 = HEIGHT - 1,
                };
                lv_obj_invalidate_area(surface->image, &dirty);
            } else {
                lv_obj_invalidate(surface->image);
            }
            refresh(surface);
        }
        if (frame && frame % 11 > 1) {
            assert(direct.refreshed_pixels < WIDTH * HEIGHT);
            assert(reference.refreshed_pixels == WIDTH * HEIGHT);
        }
        for (unsigned pixel = 0; pixel < WIDTH * HEIGHT; ++pixel) {
            if (direct.front[pixel].full != reference.front[pixel].full) {
                fprintf(stderr, "frame=%u pixel=%u direct=%x full=%x\n", frame, pixel,
                        direct.front[pixel].full, reference.front[pixel].full);
                abort();
            }
            pixel_hash ^= reference.front[pixel].full;
            pixel_hash *= 1099511628211ULL;
        }
        old_left = left;
        old_width = width;
    }
    printf("PIXEL_HASH: %016llx\n", (unsigned long long)pixel_hash);
    /* Reproduce the old 100 ms UI no-op invalidation with the actual LVGL. */
    set_object_visible(direct.control, true);
    refresh(&direct);
    assert(direct.display->inv_p == 0);
    lv_obj_clear_flag(direct.control, LV_OBJ_FLAG_HIDDEN);
    assert(direct.display->inv_p > 0);
    refresh(&direct);
    for (unsigned i = 0; i < 1000; ++i) set_object_visible(direct.control, true);
    assert(direct.display->inv_p == 0);
    set_object_visible(direct.control, false);
    assert(direct.display->inv_p > 0 && lv_obj_has_flag(direct.control, LV_OBJ_FLAG_HIDDEN));
    refresh(&direct);
    for (unsigned i = 0; i < 1000; ++i) set_object_visible(direct.control, false);
    assert(direct.display->inv_p == 0);
    set_object_visible(direct.control, true);
    assert(direct.display->inv_p > 0 && !lv_obj_has_flag(direct.control, LV_OBJ_FLAG_HIDDEN));
    set_object_visible(NULL, true);
    set_object_visible(NULL, false);
#ifdef DISPLAY_TEST_PPA
    assert(atomic_load(&s_display_ppa_frames)>10);
    puts("PASS: opt-in production PPA adapter used with actual LVGL, 40 frames/all pixels equal CPU full refresh");
#endif
    lv_disp_remove(direct.display);
    lv_disp_remove(reference.display);
    for (unsigned i = 0; i < 2; ++i) {
        free(direct.buffers[i]);
        free(reference.buffers[i]);
    }
    puts("PASS: actual LVGL direct double buffers match full refresh, 40 frames/all pixels, ROI changes/hide/overlay/movement; old repeated flag clear invalidates, production visibility no-ops do not");
    uint32_t slow = measure_cadence(30), aligned = measure_cadence(10);
    printf("Actual LVGL cadence model: 30ms=%u frames, 10ms=%u frames in 30s, 67ms input / 60ms blocking draw\n", slow, aligned);
    /* This bounded model does not support blaming the 30ms refresh period. */
    assert(aligned == slow && slow >= 440U);
    return 0;
}
