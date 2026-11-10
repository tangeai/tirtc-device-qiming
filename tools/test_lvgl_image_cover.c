#include <assert.h>
#include <stdio.h>
#include <string.h>

static unsigned cover_background_draws;

static void cover_background_event(lv_event_t *event)
{
    (void)event;
    cover_background_draws++;
}

static lv_cover_res_t image_cover(lv_obj_t *image, const lv_area_t *area)
{
    lv_cover_check_info_t information;
    /* Make the old parameter-as-area cast reproducible, including its padding. */
    memset(&information, 0x7f, sizeof(information));
    information.res = LV_COVER_RES_COVER;
    information.area = area;
    assert(lv_event_send(image, LV_EVENT_COVER_CHECK, &information) == LV_RES_OK);
    return information.res;
}

static void test_image_cover(void)
{
    surface_t surface = {0};
    create(&surface, true);
    lv_obj_add_flag(surface.control, LV_OBJ_FLAG_HIDDEN);
    refresh(&surface);
    const lv_area_t panel = {0, 0, WIDTH-1, HEIGHT-1};
#if DISPLAY_TEST_IMAGE_COVER_FIXED
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_COVER);
    const lv_area_t inner = {17, 13, 50, 40}, outside = {-1, 0, WIDTH-1, HEIGHT-1};
    assert(image_cover(surface.image, &inner) == LV_COVER_RES_COVER);
    assert(image_cover(surface.image, &outside) == LV_COVER_RES_NOT_COVER);
    lv_obj_set_style_opa(surface.image, LV_OPA_50, 0);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    lv_obj_set_style_opa(surface.image, LV_OPA_COVER, 0);
    lv_obj_set_style_img_opa(surface.image, LV_OPA_50, 0);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    lv_obj_set_style_img_opa(surface.image, LV_OPA_COVER, 0);
    lv_img_set_angle(surface.image, 900);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    lv_img_set_angle(surface.image, 0);
    lv_obj_set_style_pad_left(surface.image, 2, 0);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    lv_obj_set_style_pad_left(surface.image, 0, 0);
    lv_obj_set_style_border_width(surface.image, 2, 0);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    lv_obj_set_style_border_width(surface.image, 0, 0);
    lv_img_set_offset_x(surface.image, 1);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    lv_img_set_offset_x(surface.image, 0);
    lv_obj_set_style_clip_corner(surface.image, true, 0);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_MASKED);
    lv_obj_set_style_clip_corner(surface.image, false, 0);
    surface.descriptor.header.cf = LV_IMG_CF_TRUE_COLOR_ALPHA;
    lv_img_set_src(surface.image, &surface.descriptor);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    surface.descriptor.header.cf = LV_IMG_CF_TRUE_COLOR;
    lv_img_set_src(surface.image, &surface.descriptor);
    lv_obj_set_pos(surface.image, 11, 7);
    lv_obj_update_layout(surface.image);
    const lv_area_t translated = {11, 7, WIDTH+10, HEIGHT+6};
    assert(image_cover(surface.image, &translated) == LV_COVER_RES_COVER);
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
    lv_obj_set_pos(surface.image, 0, 0);
    refresh(&surface);
#else
    assert(image_cover(surface.image, &panel) == LV_COVER_RES_NOT_COVER);
#endif
    lv_obj_t *screen = lv_disp_get_scr_act(surface.display);
    lv_obj_add_event_cb(screen, cover_background_event, LV_EVENT_DRAW_MAIN, NULL);
    cover_background_draws = 0;
    lv_obj_invalidate(surface.image);
    refresh(&surface);
#if DISPLAY_TEST_IMAGE_COVER_FIXED
    assert(cover_background_draws == 0);
    puts("PASS: opaque image covers its background; opacity, padding, alpha, rotation, masking and translated bounds retained");
#else
    assert(cover_background_draws > 0);
    puts("REPRODUCED: pinned LVGL opaque image redraws the fully covered screen background");
#endif
    lv_disp_remove(surface.display);
    for(unsigned i=0; i<2; ++i) free(surface.buffers[i]);
}
