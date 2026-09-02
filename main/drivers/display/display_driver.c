#include "display_driver.h"

#include "driver/ppa.h"
#include "esp_check.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch.h"
#include "esp_log.h"
#include "esp_lvgl_port.h"
#include "esp_memory_utils.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "app_task_affinity.h"
#include "hardware_board.h"
#include "qiming_display.h"

static const char *TAG = "display_driver";

#define DISPLAY_DRIVER_LANDSCAPE_ROTATION LV_DISP_ROT_270
#define DISPLAY_DRIVER_PORTRAIT_ROTATION  LV_DISP_ROT_NONE
#define DISPLAY_DRIVER_PHYSICAL_WIDTH     HARDWARE_BOARD_LCD_PHYSICAL_WIDTH
#define DISPLAY_DRIVER_PHYSICAL_HEIGHT    HARDWARE_BOARD_LCD_PHYSICAL_HEIGHT
#define DISPLAY_DRIVER_LVGL_TASK_STACK    (12U * 1024U)
#define DISPLAY_DRIVER_LVGL_TASK_PRIORITY 15
#define DISPLAY_DRIVER_DRAW_BUFFER_LINES  48U
#define DISPLAY_DRIVER_TOUCH_SCROLL_LIMIT_PX  18
#define DISPLAY_DRIVER_TOUCH_SCROLL_THROW     0
#define DISPLAY_DRIVER_TOUCH_GESTURE_LIMIT_PX 45
#define DISPLAY_DRIVER_DSI_FRAME_BUFFER_COUNT 2U
#define DISPLAY_DRIVER_DSI_FRAME_BYTES \
	((size_t)DISPLAY_DRIVER_PHYSICAL_WIDTH * DISPLAY_DRIVER_PHYSICAL_HEIGHT * sizeof(uint16_t))
/* The configured 24 MHz timing is about 53.6 Hz. Do not overwrite the
 * previous scanout buffer until one complete physical frame has elapsed. */
#define DISPLAY_DRIVER_DSI_FRAME_PERIOD_US 20000LL

static qiming_display_handles_t s_panel_handles;
static esp_lcd_touch_handle_t s_touch;
static lv_disp_t *s_display;
static lv_indev_t *s_touch_indev;
static void (*s_touch_read_cb)(lv_indev_drv_t *indev_drv, lv_indev_data_t *data);
static bool s_touch_pressed;
static lv_point_t s_touch_last_point;
static int64_t s_touch_pressed_at_us;
static bool s_initialized;
static display_driver_orientation_t s_orientation =
	DISPLAY_DRIVER_ORIENTATION_LANDSCAPE;
#if CONFIG_APP_CALL_VIDEO_DIRECT_LCD
static ppa_client_handle_t s_direct_ppa_client;
static uint16_t *s_direct_framebuffers[DISPLAY_DRIVER_DSI_FRAME_BUFFER_COUNT];
static uint8_t s_direct_target_fb = 1U;
static int64_t s_direct_last_flip_us;
#endif

_Static_assert(LV_COLOR_DEPTH == 16, "Qiming LVGL input uses RGB565");
_Static_assert(LV_COLOR_16_SWAP == 0,
	       "Qiming DSI frame buffers require native RGB565 byte order");
_Static_assert(DISPLAY_DRIVER_PHYSICAL_WIDTH == 480U &&
		       DISPLAY_DRIVER_PHYSICAL_HEIGHT == 640U,
	       "Qiming ST7102 panel geometry mismatch");

#if CONFIG_APP_CALL_VIDEO_DIRECT_LCD
static esp_err_t display_driver_prepare_direct_presenter(void)
{
	void *fb0 = NULL;
	void *fb1 = NULL;
	const ppa_client_config_t ppa_config = {
		.oper_type = PPA_OPERATION_SRM,
		.max_pending_trans_num = 1,
		.data_burst_length = PPA_DATA_BURST_LENGTH_128,
	};

	ESP_RETURN_ON_ERROR(esp_lcd_dpi_panel_get_frame_buffer(s_panel_handles.panel,
							       DISPLAY_DRIVER_DSI_FRAME_BUFFER_COUNT,
							       &fb0,
							       &fb1),
			    TAG,
			    "DSI frame buffers unavailable");
	ESP_RETURN_ON_FALSE(fb0 != NULL && fb1 != NULL &&
				    esp_ptr_external_ram(fb0) &&
				    esp_ptr_external_ram(fb1) &&
				    esp_ptr_dma_ext_capable(fb0) &&
				    esp_ptr_dma_ext_capable(fb1),
			    ESP_ERR_INVALID_STATE,
			    TAG,
			    "DSI frame buffers are not PSRAM DMA capable");
	ESP_RETURN_ON_ERROR(ppa_register_client(&ppa_config, &s_direct_ppa_client),
			    TAG,
			    "direct display PPA client create failed");

	s_direct_framebuffers[0] = fb0;
	s_direct_framebuffers[1] = fb1;
	s_direct_target_fb = 1U;
	s_direct_last_flip_us = 0;
	ESP_LOGI(TAG,
		 "direct video presenter ready: logical=%ux%u physical=%ux%u buffers=2 ppa=rotate-cw90",
		 (unsigned)HARDWARE_BOARD_LCD_WIDTH,
		 (unsigned)HARDWARE_BOARD_LCD_HEIGHT,
		 (unsigned)DISPLAY_DRIVER_PHYSICAL_WIDTH,
		 (unsigned)DISPLAY_DRIVER_PHYSICAL_HEIGHT);
	return ESP_OK;
}
#endif

static void display_driver_touch_read_diagnostic(lv_indev_drv_t *indev_drv,
						 lv_indev_data_t *data)
{
	if (s_touch_read_cb == NULL || data == NULL) {
		return;
	}

	s_touch_read_cb(indev_drv, data);
	if (data->state == LV_INDEV_STATE_PRESSED) {
		if (!s_touch_pressed) {
			s_touch_pressed = true;
			s_touch_pressed_at_us = esp_timer_get_time();
			s_touch_last_point = data->point;
			ESP_LOGI(TAG,
				 "touch raw press: x=%d y=%d physical=%ux%u rotation=%u",
				 (int)data->point.x,
				 (int)data->point.y,
				 (unsigned)DISPLAY_DRIVER_PHYSICAL_WIDTH,
				 (unsigned)DISPLAY_DRIVER_PHYSICAL_HEIGHT,
				 (unsigned)(s_display != NULL ? lv_disp_get_rotation(s_display) : 0));
		}
		s_touch_last_point = data->point;
		return;
	}

	if (s_touch_pressed) {
		const int64_t duration_us = esp_timer_get_time() - s_touch_pressed_at_us;
		ESP_LOGI(TAG,
			 "touch raw release: x=%d y=%d held_ms=%lld",
			 (int)s_touch_last_point.x,
			 (int)s_touch_last_point.y,
			 (long long)(duration_us / 1000));
		s_touch_pressed = false;
	}
}

static void display_driver_configure_touch(lv_indev_t *indev)
{
	if (indev == NULL || indev->driver == NULL) {
		return;
	}

	indev->driver->scroll_limit = DISPLAY_DRIVER_TOUCH_SCROLL_LIMIT_PX;
	indev->driver->scroll_throw = DISPLAY_DRIVER_TOUCH_SCROLL_THROW;
	indev->driver->gesture_limit = DISPLAY_DRIVER_TOUCH_GESTURE_LIMIT_PX;
	s_touch_read_cb = indev->driver->read_cb;
	indev->driver->read_cb = display_driver_touch_read_diagnostic;
	ESP_LOGI(TAG,
		 "touch input ready: scroll_limit=%u scroll_throw=%u gesture_limit=%u edge_diag=1",
		 (unsigned)indev->driver->scroll_limit,
		 (unsigned)indev->driver->scroll_throw,
		 (unsigned)indev->driver->gesture_limit);
}

esp_err_t display_driver_init(display_driver_handles_t *handles)
{
	if (s_initialized) {
		if (handles != NULL) {
			handles->display = s_display;
			handles->touch_indev = s_touch_indev;
		}
		return ESP_OK;
	}

	if (handles != NULL) {
		handles->display = NULL;
		handles->touch_indev = NULL;
	}
	ESP_RETURN_ON_FALSE(hardware_board_has_display(),
			    ESP_ERR_NOT_SUPPORTED,
			    TAG,
			    "display capability is disabled");

	ESP_RETURN_ON_ERROR(qiming_display_panel_init(&s_panel_handles),
			    TAG,
			    "Qiming panel init failed");

#if CONFIG_APP_CALL_VIDEO_DIRECT_LCD
	esp_err_t direct_ret = display_driver_prepare_direct_presenter();
	if (direct_ret != ESP_OK) {
		ESP_LOGW(TAG,
			 "direct video presenter unavailable; LVGL fallback remains active: %s",
			 esp_err_to_name(direct_ret));
	}
#endif

	lvgl_port_cfg_t lvgl_config = ESP_LVGL_PORT_INIT_CONFIG();
	lvgl_config.task_stack = DISPLAY_DRIVER_LVGL_TASK_STACK;
	lvgl_config.task_priority = DISPLAY_DRIVER_LVGL_TASK_PRIORITY;
	lvgl_config.task_affinity = APP_TASK_CORE_UI;
	/* The LVGL worker does not own cache-off or DMA operations. Keep its
	 * sizeable stack in PSRAM and preserve internal RAM for Hosted-SDIO. */
	lvgl_config.task_stack_caps = APP_TASK_STACK_CAPS_BACKGROUND;
	ESP_RETURN_ON_ERROR(lvgl_port_init(&lvgl_config), TAG, "LVGL port init failed");

	const lvgl_port_display_cfg_t display_config = {
		.io_handle = s_panel_handles.panel_io,
		.panel_handle = s_panel_handles.panel,
		/* LVGL 8 cannot safely combine software rotation with full-refresh DSI
		 * frame buffers. Render landscape strips and release every chunk through
		 * the normal transfer-complete callback. */
		.buffer_size = HARDWARE_BOARD_LCD_WIDTH * DISPLAY_DRIVER_DRAW_BUFFER_LINES,
		.double_buffer = true,
		.hres = DISPLAY_DRIVER_PHYSICAL_WIDTH,
		.vres = DISPLAY_DRIVER_PHYSICAL_HEIGHT,
		.rotation = {
			.swap_xy = false,
			.mirror_x = false,
			.mirror_y = false,
		},
		.flags = {
			.buff_dma = false,
			/*
			 * The two full-screen LVGL draw buffers are long-lived payload
			 * memory. Keep them in PSRAM so Hosted SDIO, I2C and media DMA
			 * retain contiguous internal memory.
			 */
			.buff_spiram = true,
			.sw_rotate = true,
			.full_refresh = false,
		},
	};
	const lvgl_port_display_dsi_cfg_t dsi_config = {
		.flags = {
			.avoid_tearing = false,
		},
	};
	s_display = lvgl_port_add_disp_dsi(&display_config, &dsi_config);
	ESP_RETURN_ON_FALSE(s_display != NULL, ESP_ERR_NO_MEM, TAG, "LVGL DSI display add failed");
	lv_disp_set_rotation(s_display, DISPLAY_DRIVER_LANDSCAPE_ROTATION);
	s_orientation = DISPLAY_DRIVER_ORIENTATION_LANDSCAPE;

	if (hardware_board_has_touch()) {
		esp_err_t touch_ret = qiming_display_touch_init(&s_touch);
		if (touch_ret == ESP_OK) {
			const lvgl_port_touch_cfg_t touch_config = {
				.disp = s_display,
				.handle = s_touch,
			};
			s_touch_indev = lvgl_port_add_touch(&touch_config);
			if (s_touch_indev != NULL) {
				display_driver_configure_touch(s_touch_indev);
			} else {
				ESP_LOGW(TAG, "LVGL touch input unavailable: no memory");
			}
		} else {
			/*
			 * Keep the screen and non-touch services usable when the touch
			 * controller is absent or its flex cable is not seated.
			 */
			ESP_LOGW(TAG,
				 "touch unavailable; display continues without pointer input: %s",
				 esp_err_to_name(touch_ret));
		}
	}

	ESP_RETURN_ON_ERROR(qiming_display_set_brightness(100),
			    TAG,
			    "display backlight enable failed");
	s_initialized = true;
	if (handles != NULL) {
		handles->display = s_display;
		handles->touch_indev = s_touch_indev;
	}

	ESP_LOGI(TAG,
		 "display ready: panel=%ux%u ui=%ux%u rotation=%u buffers=2x%u-lines@psram input=RGB565 "
		 "output=RGB888 avoid_tearing=0",
		 (unsigned)DISPLAY_DRIVER_PHYSICAL_WIDTH,
		 (unsigned)DISPLAY_DRIVER_PHYSICAL_HEIGHT,
		 (unsigned)display_driver_width(),
		 (unsigned)display_driver_height(),
		 (unsigned)DISPLAY_DRIVER_LANDSCAPE_ROTATION,
		 (unsigned)DISPLAY_DRIVER_DRAW_BUFFER_LINES);
	return ESP_OK;
}

bool display_driver_is_initialized(void)
{
	return s_initialized;
}

uint16_t display_driver_width(void)
{
	if (s_display != NULL) {
		return (uint16_t)lv_disp_get_hor_res(s_display);
	}
	return hardware_board_get_display_config()->width;
}

uint16_t display_driver_height(void)
{
	if (s_display != NULL) {
		return (uint16_t)lv_disp_get_ver_res(s_display);
	}
	return hardware_board_get_display_config()->height;
}

display_driver_orientation_t display_driver_get_orientation(void)
{
	return s_orientation;
}

esp_err_t display_driver_set_orientation(display_driver_orientation_t orientation)
{
	ESP_RETURN_ON_FALSE(s_initialized && s_display != NULL,
			    ESP_ERR_INVALID_STATE,
			    TAG,
			    "display is not initialized");
	ESP_RETURN_ON_FALSE(orientation == DISPLAY_DRIVER_ORIENTATION_PORTRAIT ||
				    orientation == DISPLAY_DRIVER_ORIENTATION_LANDSCAPE,
			    ESP_ERR_INVALID_ARG,
			    TAG,
			    "invalid display orientation");
	if (orientation == s_orientation) {
		return ESP_OK;
	}

	const lv_disp_rot_t rotation =
		orientation == DISPLAY_DRIVER_ORIENTATION_PORTRAIT ?
			DISPLAY_DRIVER_PORTRAIT_ROTATION :
			DISPLAY_DRIVER_LANDSCAPE_ROTATION;
	lv_disp_set_rotation(s_display, rotation);
	s_orientation = orientation;
	ESP_LOGI(TAG,
		 "display orientation: mode=%s ui=%ux%u rotation=%u",
		 orientation == DISPLAY_DRIVER_ORIENTATION_PORTRAIT ? "portrait" : "landscape",
		 (unsigned)display_driver_width(),
		 (unsigned)display_driver_height(),
		 (unsigned)rotation);
	return ESP_OK;
}

esp_err_t display_driver_blit_rgb565(uint16_t x,
				    uint16_t y,
				    uint16_t width,
				    uint16_t height,
				    const uint16_t *pixels,
				    uint32_t *elapsed_us)
{
	(void)x;
	(void)y;
	(void)width;
	(void)height;
	(void)pixels;
	if (elapsed_us != NULL) {
		*elapsed_us = 0;
	}

#if CONFIG_APP_CALL_VIDEO_DIRECT_LCD
	ESP_RETURN_ON_FALSE(s_initialized && s_display != NULL &&
				    s_panel_handles.panel != NULL &&
				    s_direct_ppa_client != NULL,
			    ESP_ERR_INVALID_STATE,
			    TAG,
			    "direct video presenter is not initialized");
	ESP_RETURN_ON_FALSE(s_orientation == DISPLAY_DRIVER_ORIENTATION_LANDSCAPE &&
				    x == 0U && y == 0U &&
				    width == HARDWARE_BOARD_LCD_WIDTH &&
				    height == HARDWARE_BOARD_LCD_HEIGHT,
			    ESP_ERR_INVALID_SIZE,
			    TAG,
			    "direct video requires one full logical landscape frame");
	ESP_RETURN_ON_FALSE(pixels != NULL &&
				    esp_ptr_external_ram(pixels) &&
				    esp_ptr_dma_ext_capable(pixels),
			    ESP_ERR_INVALID_ARG,
			    TAG,
			    "direct video source is not PSRAM DMA capable");

	/* cur_fb_index changes when draw_bitmap() queues the flip, while the DSI
	 * engine adopts that link list at the next physical frame boundary. The
	 * video source is normally much slower than the panel; this bounded wait
	 * only protects an input burst from rewriting the buffer still scanning. */
	int64_t now_us = esp_timer_get_time();
	if (s_direct_last_flip_us > 0 &&
	    now_us - s_direct_last_flip_us < DISPLAY_DRIVER_DSI_FRAME_PERIOD_US) {
		int64_t remaining_us = DISPLAY_DRIVER_DSI_FRAME_PERIOD_US -
				       (now_us - s_direct_last_flip_us);
		TickType_t wait_ticks = pdMS_TO_TICKS((remaining_us + 999LL) / 1000LL);
		vTaskDelay(wait_ticks > 0 ? wait_ticks : 1);
	}

	uint16_t *target = s_direct_framebuffers[s_direct_target_fb];
	ESP_RETURN_ON_FALSE(target != NULL,
			    ESP_ERR_INVALID_STATE,
			    TAG,
			    "direct video target frame buffer is unavailable");
	int64_t started_us = esp_timer_get_time();
	const ppa_srm_oper_config_t operation = {
		.in = {
			.buffer = (void *)pixels,
			.pic_w = width,
			.pic_h = height,
			.block_w = width,
			.block_h = height,
			.block_offset_x = 0,
			.block_offset_y = 0,
			.srm_cm = PPA_SRM_COLOR_MODE_RGB565,
			.yuv_range = PPA_COLOR_RANGE_LIMIT,
			.yuv_std = PPA_COLOR_CONV_STD_RGB_YUV_BT601,
		},
		.out = {
			.buffer = target,
			.buffer_size = DISPLAY_DRIVER_DSI_FRAME_BYTES,
			.pic_w = DISPLAY_DRIVER_PHYSICAL_WIDTH,
			.pic_h = DISPLAY_DRIVER_PHYSICAL_HEIGHT,
			.block_offset_x = 0,
			.block_offset_y = 0,
			.srm_cm = PPA_SRM_COLOR_MODE_RGB565,
			.yuv_range = PPA_COLOR_RANGE_LIMIT,
			.yuv_std = PPA_COLOR_CONV_STD_RGB_YUV_BT601,
		},
		/* LVGL_ROT_270 maps logical landscape to a clockwise 90-degree
		 * physical scanout. PPA angles are counterclockwise. */
		.rotation_angle = PPA_SRM_ROTATION_ANGLE_270,
		.scale_x = 1.0f,
		.scale_y = 1.0f,
		.mode = PPA_TRANS_MODE_BLOCKING,
	};
	ESP_RETURN_ON_ERROR(ppa_do_scale_rotate_mirror(s_direct_ppa_client, &operation),
			    TAG,
			    "direct video PPA rotation failed");
	ESP_RETURN_ON_ERROR(esp_lcd_panel_draw_bitmap(s_panel_handles.panel,
						      0,
						      0,
						      DISPLAY_DRIVER_PHYSICAL_WIDTH,
						      DISPLAY_DRIVER_PHYSICAL_HEIGHT,
						      target),
			    TAG,
			    "direct video frame buffer flip failed");

	s_direct_target_fb ^= 1U;
	s_direct_last_flip_us = esp_timer_get_time();
	if (elapsed_us != NULL) {
		*elapsed_us = (uint32_t)(s_direct_last_flip_us - started_us);
	}
	return ESP_OK;
#else
	return ESP_ERR_NOT_SUPPORTED;
#endif
}
