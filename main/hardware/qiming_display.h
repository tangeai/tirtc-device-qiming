#pragma once

#include <stdint.h>

#include "esp_err.h"
#include "esp_lcd_mipi_dsi.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_touch.h"

typedef struct {
	esp_lcd_dsi_bus_handle_t dsi_bus;
	esp_lcd_panel_io_handle_t panel_io;
	esp_lcd_panel_handle_t panel;
} qiming_display_handles_t;

esp_err_t qiming_display_panel_init(qiming_display_handles_t *handles);
esp_err_t qiming_display_set_brightness(uint8_t percent);
esp_err_t qiming_display_touch_init(esp_lcd_touch_handle_t *touch);
