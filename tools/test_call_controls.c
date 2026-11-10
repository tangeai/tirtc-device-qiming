#include <assert.h>
#include <stdlib.h>
#include <string.h>

static void test_flush(lv_disp_drv_t *driver, const lv_area_t *area, lv_color_t *pixels)
{
    (void)area;
    (void)pixels;
    lv_disp_flush_ready(driver);
}

static lv_obj_t *button(lv_obj_t *screen)
{
    lv_obj_t *object = lv_btn_create(screen);
    lv_obj_set_pos(object, 12, 184);
    lv_obj_set_size(object, 88, 42);
    lv_label_create(object);
    return object;
}

int main(void)
{
    lv_init();
    lv_color_t *pixels = calloc(320U * 240U, sizeof(*pixels));
    assert(pixels);
    lv_disp_draw_buf_t buffer;
    lv_disp_draw_buf_init(&buffer, pixels, NULL, 320U * 240U);
    lv_disp_drv_t driver;
    lv_disp_drv_init(&driver);
    driver.hor_res = 320;
    driver.ver_res = 240;
    driver.draw_buf = &buffer;
    driver.flush_cb = test_flush;
    lv_disp_t *display = lv_disp_drv_register(&driver);
    assert(display);
    lv_obj_t *screen = lv_disp_get_scr_act(display);
    s_page = PAGE_CALL;
    s_header_title = lv_label_create(screen);
    s_call_peer_label = lv_label_create(screen);
    s_call_status_label = lv_label_create(screen);
    s_call_accept_button = button(screen);
    s_call_reject_button = button(screen);
    s_call_mute_button = button(screen);
    s_call_hangup_button = button(screen);
    s_call_camera_button = button(screen);
    starter_runtime_product_snapshot_t product = {
        .call_video=true, .call_wechat=true, .call_camera_enabled=true,
        .call_peer="test"
    };
    starter_runtime_status_t runtime = {.state=STARTER_RUNTIME_CALL_ACTIVE};
    refresh_call_controls(runtime, &product);
    lv_refr_now(display);
    assert(display->inv_p == 0);

    /* Reproduce the previous voice-to-video layout/text detour each UI tick. */
    lv_obj_set_pos(s_call_hangup_button, 176, 161);
    lv_obj_set_size(s_call_hangup_button, 62, 62);
    set_button_text(s_call_mute_button, "静音");
    refresh_call_controls(runtime, &product);
    lv_refr_now(display);
    assert(display->inv_p == 0);
    lv_obj_set_pos(s_call_hangup_button, 176, 161);
    lv_obj_set_size(s_call_hangup_button, 62, 62);
    set_button_text(s_call_mute_button, "静音");
    assert(display->inv_p > 0);
    refresh_call_controls(runtime, &product);
    lv_refr_now(display);

    for (unsigned i=0; i<1000; ++i) refresh_call_controls(runtime, &product);
    assert(display->inv_p == 0);
    assert(lv_obj_get_x(s_call_hangup_button)==220 && lv_obj_get_y(s_call_hangup_button)==184);
    assert(lv_obj_get_width(s_call_hangup_button)==88 && lv_obj_get_height(s_call_hangup_button)==42);
    assert(!strcmp(lv_label_get_text(lv_obj_get_child(s_call_mute_button,0)), "关麦"));

    s_preferences.microphone_muted=true;
    product.call_camera_enabled=false;
    refresh_call_controls(runtime, &product);
    assert(display->inv_p > 0);
    lv_refr_now(display);
    for (unsigned i=0; i<1000; ++i) refresh_call_controls(runtime, &product);
    assert(display->inv_p == 0);
    assert(!strcmp(lv_label_get_text(lv_obj_get_child(s_call_mute_button,0)), "开麦"));
    assert(!strcmp(lv_label_get_text(lv_obj_get_child(s_call_camera_button,0)), "开摄像头"));

    product.call_video=false;
    refresh_call_controls(runtime, &product);
    lv_refr_now(display);
    assert(lv_obj_get_x(s_call_hangup_button)==176 && lv_obj_get_y(s_call_hangup_button)==161);
    assert(lv_obj_get_width(s_call_hangup_button)==62 && lv_obj_get_height(s_call_hangup_button)==62);
    for (unsigned i=0; i<1000; ++i) refresh_call_controls(runtime, &product);
    assert(display->inv_p == 0);
    runtime.state=STARTER_RUNTIME_CALL_INCOMING;
    refresh_call_controls(runtime, &product);
    assert(!lv_obj_has_flag(s_call_accept_button,LV_OBJ_FLAG_HIDDEN));
    assert(lv_obj_has_flag(s_call_hangup_button,LV_OBJ_FLAG_HIDDEN));
    runtime.state=STARTER_RUNTIME_CALL_CONNECTING;
    refresh_call_controls(runtime, &product);
    lv_refr_now(display);
    assert(lv_obj_has_flag(s_call_accept_button,LV_OBJ_FLAG_HIDDEN));
    assert(!lv_obj_has_flag(s_call_hangup_button,LV_OBJ_FLAG_HIDDEN));
    for (unsigned i=0; i<1000; ++i) refresh_call_controls(runtime, &product);
    assert(display->inv_p == 0);
    s_door_call=true;
    refresh_call_controls(runtime, &product);
    assert(door_refreshes==1);
    s_door_call=false;
    lv_disp_remove(display);
    free(pixels);
    puts("PASS: actual production call controls; old layout/text detour invalidates, 1000 steady refreshes do not; video/audio/mute/camera/incoming/connecting retained");
    return 0;
}
