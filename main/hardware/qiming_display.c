#include "qiming_display.h"

#include "driver/ledc.h"
#include "esp_check.h"
#include "esp_lcd_io_i2c.h"
#include "esp_lcd_st7102.h"
#include "esp_lcd_touch_st7123.h"
#include "esp_ldo_regulator.h"
#include "esp_log.h"

#include "hardware_board.h"

static const char *TAG = "qiming_display";

#define QIMING_DSI_PHYSICAL_WIDTH          HARDWARE_BOARD_LCD_PHYSICAL_WIDTH
#define QIMING_DSI_PHYSICAL_HEIGHT         HARDWARE_BOARD_LCD_PHYSICAL_HEIGHT
#define QIMING_DSI_DATA_LANES              2U
#define QIMING_DSI_LANE_BIT_RATE_MBPS      1000U
#define QIMING_DSI_PIXEL_CLOCK_MHZ         24.0f
#define QIMING_DSI_FRAME_BUFFER_COUNT      2U
#define QIMING_DSI_PHY_LDO_CHANNEL         3
#define QIMING_DSI_PHY_LDO_VOLTAGE_MV      2500
#define QIMING_BACKLIGHT_PWM_HZ            2000U
#define QIMING_BACKLIGHT_DUTY_MAX          1023U
#define QIMING_DISPLAY_I2C_ADDRESS         HARDWARE_BOARD_LCD_CONTROLLER_I2C_ADDR
#define QIMING_TOUCH_I2C_ADDRESS           HARDWARE_BOARD_TOUCH_CONTROLLER_I2C_ADDR
#define QIMING_I2C_PROBE_TIMEOUT_MS        HARDWARE_BOARD_I2C_PROBE_TIMEOUT_MS

static esp_ldo_channel_handle_t s_dsi_phy_ldo;
static esp_lcd_panel_io_handle_t s_touch_io;
static bool s_backlight_initialized;

/*
 * ST7102 command values and timings follow the WT9932P4C61-TINY profile in
 * Wireless-Tag WT_BSP. Keeping them in the board adapter prevents panel
 * details from leaking into the generic LVGL display driver.
 */
static const st7102_lcd_init_cmd_t s_st7102_init_commands[] = {
	{0x28, (uint8_t[]){0x00}, 0, 0},
	{0x10, (uint8_t[]){0x00}, 0, 0},
	{0x99, (uint8_t[]){0x71, 0x02, 0xA2}, 3, 0},
	{0x99, (uint8_t[]){0x71, 0x02, 0xA3}, 3, 0},
	{0x99, (uint8_t[]){0x71, 0x02, 0xA4}, 3, 0},
	{0xA4, (uint8_t[]){0x31}, 1, 0},
	{0xB0, (uint8_t[]){0x22, 0x43, 0x1E, 0x43, 0x2F, 0x57, 0x57}, 7, 0},
	{0xB7, (uint8_t[]){0x7D, 0x7D}, 2, 0},
	{0xBF, (uint8_t[]){0x7A, 0x7A}, 2, 0},
	{0xC8, (uint8_t[]){0x00, 0x00, 0x13, 0x23, 0x3E, 0x00, 0x6A, 0x03,
			      0xB0, 0x06, 0x11, 0x0F, 0x07, 0x85, 0x03, 0x21,
			      0xD5, 0x01, 0x18, 0x00, 0x22, 0x56, 0x0F, 0x98,
			      0x0A, 0x32, 0xF8, 0x0D, 0x48, 0x0F, 0xF3, 0x80,
			      0x0F, 0xAC, 0xC1, 0x03, 0xC4}, 37, 0},
	{0xC9, (uint8_t[]){0x00, 0x00, 0x13, 0x23, 0x3E, 0x00, 0x6A, 0x03,
			      0xB0, 0x06, 0x11, 0x0F, 0x07, 0x85, 0x03, 0x21,
			      0xD5, 0x01, 0x18, 0x00, 0x22, 0x56, 0x0F, 0x98,
			      0x0A, 0x32, 0xF8, 0x0D, 0x48, 0x0F, 0xF3, 0x80,
			      0x0F, 0xAC, 0xC1, 0x03, 0xC4}, 37, 0},
	{0xD7, (uint8_t[]){0x10, 0x0C, 0x02, 0x19, 0x40, 0x40}, 6, 0},
	{0xA3, (uint8_t[]){0x40, 0x03, 0x80, 0xCF, 0x44, 0x00, 0x00, 0x00,
			      0x02, 0x05, 0x6F, 0x6F, 0x00, 0x1A, 0x00, 0x45,
			      0x05, 0x00, 0x00, 0x00, 0x00, 0x46, 0x00, 0x00,
			      0x02, 0x20, 0x52, 0x00, 0x05, 0x00, 0x00, 0xFF}, 32, 0},
	{0xA6, (uint8_t[]){0x02, 0x00, 0x24, 0x55, 0x35, 0x00, 0x38, 0x00,
			      0x97, 0x97, 0x00, 0x24, 0x55, 0x36, 0x00, 0x37,
			      0x00, 0x97, 0x97, 0x02, 0xAC, 0x51, 0x3A, 0x00,
			      0x00, 0x00, 0x97, 0x97, 0x00, 0xAC, 0x21, 0x00,
			      0x0B, 0x00, 0x00, 0x97, 0x97, 0x00, 0x00, 0x06,
			      0x00, 0x00, 0x00, 0x00}, 44, 0},
	{0xA7, (uint8_t[]){0x19, 0x19, 0x00, 0x64, 0x40, 0x07, 0x16, 0x40,
			      0x00, 0x04, 0x03, 0x97, 0x97, 0x00, 0x64, 0x40,
			      0x25, 0x34, 0x00, 0x00, 0x02, 0x01, 0x97, 0x97,
			      0x00, 0x64, 0x40, 0x4B, 0x5A, 0x00, 0x00, 0x02,
			      0x01, 0x97, 0x97, 0x00, 0x24, 0x40, 0x69, 0x78,
			      0x00, 0x00, 0x00, 0x00, 0x97, 0x97, 0x00, 0x44}, 48, 0},
	{0xAC, (uint8_t[]){0x11, 0x08, 0x13, 0x0A, 0x18, 0x1A, 0x1B, 0x00,
			      0x06, 0x03, 0x19, 0x1B, 0x1B, 0x1B, 0x18, 0x1B,
			      0x10, 0x09, 0x12, 0x0B, 0x18, 0x1A, 0x1B, 0x02,
			      0x06, 0x01, 0x19, 0x1B, 0x1B, 0x1B, 0x18, 0x1B,
			      0xFF, 0x67, 0xFF, 0x67, 0x00}, 37, 0},
	{0xAD, (uint8_t[]){0xCC, 0x40, 0x46, 0x11, 0x04, 0x6F, 0x6F}, 7, 0},
	{0xE8, (uint8_t[]){0x30, 0x07, 0x00, 0xB3, 0xB3, 0x9C, 0x00,
			      0xE2, 0x04, 0x00, 0x00, 0x00, 0x00, 0xEF}, 14, 0},
	{0x75, (uint8_t[]){0x03, 0x04}, 2, 0},
	{0xE7, (uint8_t[]){0x8B, 0x3C, 0x00, 0x0C, 0xF0, 0x5D, 0x00, 0x5D,
			      0x00, 0x5D, 0x00, 0x5D, 0x00, 0xFF, 0x00, 0x08,
			      0x7B, 0x00, 0x00, 0xC8, 0x6A, 0x5A, 0x08, 0x1A,
			      0x3C, 0x00, 0x71, 0x01, 0x8C, 0x01, 0x7F, 0xF0,
			      0x22}, 33, 0},
	{0xE9, (uint8_t[]){0x3C, 0x7F, 0x08, 0x0D, 0x1A, 0x7A, 0x22, 0x1A, 0x33}, 9, 0},
	{0x99, (uint8_t[]){0x71, 0x02, 0x00}, 3, 0},
	{0x11, (uint8_t[]){0x00}, 0, 120},
	{0x29, (uint8_t[]){0x00}, 0, 20},
	{0x35, (uint8_t[]){0x00}, 1, 0},
	{0x36, (uint8_t[]){0x00}, 1, 0},
};

static esp_err_t qiming_display_init_backlight(void)
{
	if (s_backlight_initialized) {
		return ESP_OK;
	}

	const ledc_timer_config_t timer_config = {
		.speed_mode = LEDC_LOW_SPEED_MODE,
		.duty_resolution = LEDC_TIMER_10_BIT,
		.timer_num = LEDC_TIMER_1,
		.freq_hz = QIMING_BACKLIGHT_PWM_HZ,
		.clk_cfg = LEDC_AUTO_CLK,
	};
	ESP_RETURN_ON_ERROR(ledc_timer_config(&timer_config), TAG, "backlight timer init failed");

	const ledc_channel_config_t channel_config = {
		.gpio_num = HARDWARE_BOARD_LCD_BACKLIGHT_GPIO,
		.speed_mode = LEDC_LOW_SPEED_MODE,
		.channel = LEDC_CHANNEL_1,
		.intr_type = LEDC_INTR_DISABLE,
		.timer_sel = LEDC_TIMER_1,
		.duty = 0,
		.hpoint = 0,
	};
	ESP_RETURN_ON_ERROR(ledc_channel_config(&channel_config), TAG, "backlight channel init failed");
	s_backlight_initialized = true;
	return ESP_OK;
}

esp_err_t qiming_display_set_brightness(uint8_t percent)
{
	ESP_RETURN_ON_FALSE(s_backlight_initialized,
			    ESP_ERR_INVALID_STATE,
			    TAG,
			    "backlight is not initialized");
	if (percent > 100U) {
		percent = 100U;
	}
	const uint32_t duty = (QIMING_BACKLIGHT_DUTY_MAX * percent) / 100U;
	ESP_RETURN_ON_ERROR(ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, duty),
			    TAG,
			    "backlight duty set failed");
	return ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
}

esp_err_t qiming_display_panel_init(qiming_display_handles_t *handles)
{
	ESP_RETURN_ON_FALSE(handles != NULL, ESP_ERR_INVALID_ARG, TAG, "display handles are required");
	*handles = (qiming_display_handles_t){0};

	ESP_RETURN_ON_ERROR(hardware_board_init_i2c(), TAG, "shared i2c init failed");
	i2c_master_bus_handle_t i2c_bus = hardware_board_get_i2c_bus_handle();
	ESP_RETURN_ON_FALSE(i2c_bus != NULL, ESP_ERR_INVALID_STATE, TAG, "shared i2c unavailable");
	ESP_RETURN_ON_ERROR(i2c_master_probe(i2c_bus,
					     QIMING_DISPLAY_I2C_ADDRESS,
					     QIMING_I2C_PROBE_TIMEOUT_MS),
			    TAG,
			    "display controller not found");
	ESP_RETURN_ON_ERROR(qiming_display_init_backlight(), TAG, "backlight init failed");

	if (s_dsi_phy_ldo == NULL) {
		const esp_ldo_channel_config_t ldo_config = {
			.chan_id = QIMING_DSI_PHY_LDO_CHANNEL,
			.voltage_mv = QIMING_DSI_PHY_LDO_VOLTAGE_MV,
		};
		ESP_RETURN_ON_ERROR(esp_ldo_acquire_channel(&ldo_config, &s_dsi_phy_ldo),
				    TAG,
				    "DSI PHY power enable failed");
	}

	const esp_lcd_dsi_bus_config_t bus_config = {
		.bus_id = 0,
		.num_data_lanes = QIMING_DSI_DATA_LANES,
		// Let ESP-IDF select the PHY PLL reference for the actual P4 revision.
		// The legacy default is invalid on rev 3.x silicon and aborts in the LL.
		.phy_clk_src = 0,
		.lane_bit_rate_mbps = QIMING_DSI_LANE_BIT_RATE_MBPS,
	};
	ESP_RETURN_ON_ERROR(esp_lcd_new_dsi_bus(&bus_config, &handles->dsi_bus),
			    TAG,
			    "DSI bus create failed");

	const esp_lcd_dbi_io_config_t dbi_config = {
		.virtual_channel = 0,
		.lcd_cmd_bits = 8,
		.lcd_param_bits = 8,
	};
	ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_dbi(handles->dsi_bus,
						     &dbi_config,
						     &handles->panel_io),
			    TAG,
			    "DSI command IO create failed");

	const esp_lcd_dpi_panel_config_t dpi_config = {
		.virtual_channel = 0,
		.dpi_clk_src = MIPI_DSI_DPI_CLK_SRC_DEFAULT,
		.dpi_clock_freq_mhz = QIMING_DSI_PIXEL_CLOCK_MHZ,
		.pixel_format = LCD_COLOR_PIXEL_FORMAT_RGB565,
		.in_color_format = LCD_COLOR_FMT_RGB565,
		.out_color_format = LCD_COLOR_FMT_RGB888,
		.num_fbs = QIMING_DSI_FRAME_BUFFER_COUNT,
		.video_timing = {
			.h_size = QIMING_DSI_PHYSICAL_WIDTH,
			.v_size = QIMING_DSI_PHYSICAL_HEIGHT,
			.hsync_pulse_width = 2,
			.hsync_back_porch = 40,
			.hsync_front_porch = 40,
			.vsync_pulse_width = 2,
			.vsync_back_porch = 10,
			.vsync_front_porch = 145,
		},
		.flags = {
			.use_dma2d = true,
		},
	};
	const st7102_vendor_config_t vendor_config = {
		.init_cmds = s_st7102_init_commands,
		.init_cmds_size = sizeof(s_st7102_init_commands) / sizeof(s_st7102_init_commands[0]),
		.mipi_config = {
			.dsi_bus = handles->dsi_bus,
			.dpi_config = &dpi_config,
		},
		.flags = {
			.use_mipi_interface = 1,
		},
	};
	const esp_lcd_panel_dev_config_t panel_config = {
		.reset_gpio_num = HARDWARE_BOARD_LCD_RESET_GPIO,
		.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
		.bits_per_pixel = 24,
		.vendor_config = (void *)&vendor_config,
	};
	ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7102(handles->panel_io,
						     &panel_config,
						     &handles->panel),
			    TAG,
			    "ST7102 panel create failed");
	ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(handles->panel), TAG, "panel reset failed");
	ESP_RETURN_ON_ERROR(esp_lcd_panel_init(handles->panel), TAG, "panel init failed");
	ESP_RETURN_ON_ERROR(esp_lcd_panel_disp_on_off(handles->panel, true),
			    TAG,
			    "panel display enable failed");

	ESP_LOGI(TAG,
		 "panel ready: ST7102 %ux%u DSI lanes=%u lane=%uMbps input=RGB565 output=RGB888",
		 (unsigned)QIMING_DSI_PHYSICAL_WIDTH,
		 (unsigned)QIMING_DSI_PHYSICAL_HEIGHT,
		 (unsigned)QIMING_DSI_DATA_LANES,
		 (unsigned)QIMING_DSI_LANE_BIT_RATE_MBPS);
	return ESP_OK;
}

esp_err_t qiming_display_touch_init(esp_lcd_touch_handle_t *touch)
{
	ESP_RETURN_ON_FALSE(touch != NULL, ESP_ERR_INVALID_ARG, TAG, "touch handle is required");
	*touch = NULL;

	ESP_RETURN_ON_ERROR(hardware_board_init_i2c(), TAG, "shared i2c init failed");
	i2c_master_bus_handle_t i2c_bus = hardware_board_get_i2c_bus_handle();
	ESP_RETURN_ON_FALSE(i2c_bus != NULL, ESP_ERR_INVALID_STATE, TAG, "shared i2c unavailable");
	ESP_RETURN_ON_ERROR(i2c_master_probe(i2c_bus,
					     QIMING_TOUCH_I2C_ADDRESS,
					     QIMING_I2C_PROBE_TIMEOUT_MS),
			    TAG,
			    "ST7123 touch controller not found");

	esp_lcd_panel_io_i2c_config_t io_config = ESP_LCD_TOUCH_IO_I2C_ST7123_CONFIG();
	ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_i2c(i2c_bus, &io_config, &s_touch_io),
			    TAG,
			    "touch IO create failed");

	const esp_lcd_touch_config_t touch_config = {
		.x_max = QIMING_DSI_PHYSICAL_WIDTH,
		.y_max = QIMING_DSI_PHYSICAL_HEIGHT,
		.rst_gpio_num = GPIO_NUM_NC,
		.int_gpio_num = GPIO_NUM_NC,
		.levels = {
			.reset = 0,
			.interrupt = 0,
		},
		.flags = {
			.swap_xy = 0,
			.mirror_x = 0,
			.mirror_y = 0,
		},
	};
	ESP_RETURN_ON_ERROR(esp_lcd_touch_new_i2c_st7123(s_touch_io, &touch_config, touch),
			    TAG,
			    "ST7123 touch init failed");
	ESP_LOGI(TAG, "touch ready: ST7123 %ux%u", (unsigned)touch_config.x_max,
		 (unsigned)touch_config.y_max);
	return ESP_OK;
}
