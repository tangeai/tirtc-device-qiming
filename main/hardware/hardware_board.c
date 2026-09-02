#include "hardware_board.h"

#include "driver/gpio.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "hardware";

static hardware_board_t s_board = {
	.type = HARDWARE_BOARD_TYPE,
	.boot_button_gpio = HARDWARE_BOARD_BOOT_BUTTON_GPIO,
	.capabilities = {
		.display = HARDWARE_BOARD_DISPLAY_ENABLED != 0,
		.touch = HARDWARE_BOARD_TOUCH_ENABLED != 0,
		.audio_input = HARDWARE_BOARD_AUDIO_ENABLED != 0,
		.audio_output = HARDWARE_BOARD_AUDIO_ENABLED != 0,
		.camera = HARDWARE_BOARD_CAMERA_ENABLED != 0,
		/* The slot is present, but no SD/SDSPI driver is owned by this app yet. */
		.sdcard = false,
	},
	.i2c = {
		.port = HARDWARE_BOARD_I2C_NUM,
		.sda_gpio = HARDWARE_BOARD_I2C_SDA,
		.scl_gpio = HARDWARE_BOARD_I2C_SCL,
		.freq_hz = HARDWARE_BOARD_I2C_FREQ_HZ,
	},
	.display = {
		.spi_host = SPI2_HOST,
		.spi_mosi_gpio = GPIO_NUM_NC,
		.spi_clk_gpio = GPIO_NUM_NC,
		.spi_cs_gpio = GPIO_NUM_NC,
		.dc_gpio = GPIO_NUM_NC,
		.reset_gpio = HARDWARE_BOARD_LCD_RESET_GPIO,
		.backlight_gpio = HARDWARE_BOARD_LCD_BACKLIGHT_GPIO,
		.backlight_ledc_timer = LEDC_TIMER_1,
		.backlight_ledc_channel = LEDC_CHANNEL_1,
		.pixel_clock_hz = 24000000,
		.width = HARDWARE_BOARD_LCD_WIDTH,
		.height = HARDWARE_BOARD_LCD_HEIGHT,
		.draw_buffer_height = 40,
		.cmd_bits = 0,
		.param_bits = 0,
		.bits_per_pixel = 16,
	},
	.audio = {
		.i2s_port = HARDWARE_BOARD_AUDIO_I2S_PORT,
		.lrck_gpio = HARDWARE_BOARD_AUDIO_LRCK,
		.mclk_gpio = HARDWARE_BOARD_AUDIO_MCLK,
		.bclk_gpio = HARDWARE_BOARD_AUDIO_BCLK,
		.din_gpio = HARDWARE_BOARD_AUDIO_DIN,
		.dout_gpio = HARDWARE_BOARD_AUDIO_DOUT,
		.pa_gpio = HARDWARE_BOARD_AUDIO_PA_GPIO,
		.sample_rate_hz = HARDWARE_BOARD_AUDIO_SAMPLE_RATE_HZ,
		.bits_per_sample = HARDWARE_BOARD_AUDIO_BITS_PER_SAMPLE,
		.channels = HARDWARE_BOARD_AUDIO_CHANNELS,
		.adc_channels = HARDWARE_BOARD_AUDIO_ADC_CHANNELS,
		.default_volume_percent = HARDWARE_BOARD_AUDIO_DEFAULT_VOLUME,
		.default_adc_gain_db = HARDWARE_BOARD_AUDIO_DEFAULT_ADC_GAIN_DB,
		.speaker_codec = HARDWARE_AUDIO_CODEC_NONE,
		.microphone_codec = HARDWARE_AUDIO_CODEC_NONE,
		.speaker_codec_i2c_addr = 0,
		.microphone_codec_i2c_addr = 0,
		.microphone_select_mask = 0,
	},
	.camera = {
		.enabled = HARDWARE_BOARD_CAMERA_ENABLED != 0,
		.pwdn_gpio = HARDWARE_BOARD_CAMERA_POWER_GPIO,
		.reset_gpio = GPIO_NUM_NC,
		.xclk_gpio = GPIO_NUM_NC,
		.sccb_sda_gpio = HARDWARE_BOARD_I2C_SDA,
		.sccb_scl_gpio = HARDWARE_BOARD_I2C_SCL,
		.data_gpio = {
			GPIO_NUM_NC,
			GPIO_NUM_NC,
			GPIO_NUM_NC,
			GPIO_NUM_NC,
			GPIO_NUM_NC,
			GPIO_NUM_NC,
			GPIO_NUM_NC,
			GPIO_NUM_NC,
		},
		.vsync_gpio = GPIO_NUM_NC,
		.href_gpio = GPIO_NUM_NC,
		.pclk_gpio = GPIO_NUM_NC,
		.xclk_ledc_timer = LEDC_TIMER_0,
		.xclk_ledc_channel = LEDC_CHANNEL_0,
		.xclk_freq_hz = 0,
		.frame_buffer_count = HARDWARE_BOARD_CAMERA_BUFFER_COUNT,
		.hmirror = false,
		.vflip = false,
	},
};

static bool s_i2c_initialized;
static bool s_optional_capabilities_probed;
#if HARDWARE_BOARD_AUDIO_ENABLED
static bool s_audio_power_initialized;
#endif
static bool s_camera_power_initialized;
static bool s_camera_power_enabled;
static i2c_master_bus_handle_t s_i2c_bus_handle;

_Static_assert(HARDWARE_BOARD_TOUCH_ENABLED == 0 || HARDWARE_BOARD_DISPLAY_ENABLED != 0,
	       "touch requires the display controller");
_Static_assert(HARDWARE_BOARD_LCD_WIDTH == HARDWARE_BOARD_LCD_PHYSICAL_HEIGHT &&
		       HARDWARE_BOARD_LCD_HEIGHT == HARDWARE_BOARD_LCD_PHYSICAL_WIDTH,
	       "Qiming landscape geometry must match the rotated physical panel");

const hardware_board_t *hardware_board_get(void)
{
	return &s_board;
}

const hardware_i2c_config_t *hardware_board_get_i2c_config(void)
{
	return &s_board.i2c;
}

const hardware_display_config_t *hardware_board_get_display_config(void)
{
	return &s_board.display;
}

const hardware_audio_config_t *hardware_board_get_audio_config(void)
{
	return &s_board.audio;
}

const hardware_camera_config_t *hardware_board_get_camera_config(void)
{
	return &s_board.camera;
}

const hardware_board_capabilities_t *hardware_board_get_capabilities(void)
{
	return &s_board.capabilities;
}

gpio_num_t hardware_board_get_boot_button_gpio(void)
{
	return s_board.boot_button_gpio;
}

bool hardware_board_has_display(void)
{
	return s_board.capabilities.display;
}

bool hardware_board_has_touch(void)
{
	return s_board.capabilities.touch;
}

bool hardware_board_has_audio_input(void)
{
	return s_board.capabilities.audio_input;
}

bool hardware_board_has_audio_output(void)
{
	return s_board.capabilities.audio_output;
}

bool hardware_board_has_camera(void)
{
	return s_board.capabilities.camera;
}

esp_err_t hardware_board_probe_optional_capabilities(void)
{
	if (s_optional_capabilities_probed) {
		return ESP_OK;
	}

	ESP_RETURN_ON_ERROR(hardware_board_init_i2c(), TAG, "i2c init for capability probe failed");
	ESP_RETURN_ON_FALSE(s_i2c_bus_handle != NULL,
			    ESP_ERR_INVALID_STATE,
			    TAG,
			    "i2c handle missing for capability probe");

	bool display_detected = false;
	bool touch_detected = false;
	if (HARDWARE_BOARD_DISPLAY_ENABLED != 0) {
		const gpio_config_t reset_config = {
			.pin_bit_mask = 1ULL << HARDWARE_BOARD_LCD_RESET_GPIO,
			.mode = GPIO_MODE_OUTPUT,
			.pull_up_en = GPIO_PULLUP_DISABLE,
			.pull_down_en = GPIO_PULLDOWN_DISABLE,
			.intr_type = GPIO_INTR_DISABLE,
		};
		ESP_RETURN_ON_ERROR(gpio_config(&reset_config), TAG, "display reset gpio init failed");
		ESP_RETURN_ON_ERROR(gpio_set_level(HARDWARE_BOARD_LCD_RESET_GPIO, 0),
				    TAG,
				    "display reset assert failed");
		vTaskDelay(pdMS_TO_TICKS(HARDWARE_BOARD_LCD_RESET_ASSERT_MS));
		ESP_RETURN_ON_ERROR(gpio_set_level(HARDWARE_BOARD_LCD_RESET_GPIO, 1),
				    TAG,
				    "display reset release failed");
		vTaskDelay(pdMS_TO_TICKS(HARDWARE_BOARD_LCD_RESET_SETTLE_MS));

		for (uint32_t attempt = 1; attempt <= HARDWARE_BOARD_UI_PROBE_ATTEMPTS; ++attempt) {
			display_detected = i2c_master_probe(s_i2c_bus_handle,
						    HARDWARE_BOARD_LCD_CONTROLLER_I2C_ADDR,
						    HARDWARE_BOARD_I2C_PROBE_TIMEOUT_MS) == ESP_OK;
			if (display_detected || attempt == HARDWARE_BOARD_UI_PROBE_ATTEMPTS) {
				break;
			}
			vTaskDelay(pdMS_TO_TICKS(HARDWARE_BOARD_UI_PROBE_RETRY_MS));
		}
	}
	if (HARDWARE_BOARD_TOUCH_ENABLED != 0) {
		touch_detected = i2c_master_probe(s_i2c_bus_handle,
					  HARDWARE_BOARD_TOUCH_CONTROLLER_I2C_ADDR,
					  HARDWARE_BOARD_I2C_PROBE_TIMEOUT_MS) == ESP_OK;
	}

	/*
	 * The P4/C61 module can be used without the external display carrier. Keep
	 * camera, network and RTC services available in that supported assembly;
	 * touch is valid only together with its associated panel.
	 */
	s_board.capabilities.display = display_detected;
	s_board.capabilities.touch = display_detected && touch_detected;
	s_optional_capabilities_probed = true;

	if (display_detected && touch_detected) {
		ESP_LOGI(TAG, "optional UI hardware ready: display=1 touch=1");
	} else {
		ESP_LOGW(TAG,
			 "optional UI hardware unavailable: display=%d touch=%d sda=%d scl=%d; continuing headless",
			 display_detected ? 1 : 0,
			 touch_detected ? 1 : 0,
			 gpio_get_level(HARDWARE_BOARD_I2C_SDA),
			 gpio_get_level(HARDWARE_BOARD_I2C_SCL));
	}
	return ESP_OK;
}

esp_err_t hardware_board_init_i2c(void)
{
	if (s_i2c_initialized) {
		return ESP_OK;
	}
	/*
	 * GPIO0 releases the SC2336 onto the same control bus as the panel and
	 * touch controller. Make every participant electrically valid before the
	 * bus is created, matching the WT9932P4C61-TINY board power sequence.
	 */
	if (s_board.capabilities.camera) {
		ESP_RETURN_ON_ERROR(hardware_board_set_camera_power(true),
				    TAG,
				    "camera rail enable before i2c failed");
	}

	const i2c_master_bus_config_t config = {
		.i2c_port = HARDWARE_BOARD_I2C_NUM,
		.sda_io_num = HARDWARE_BOARD_I2C_SDA,
		.scl_io_num = HARDWARE_BOARD_I2C_SCL,
		.clk_source = I2C_CLK_SRC_DEFAULT,
		.glitch_ignore_cnt = 7,
		.flags.enable_internal_pullup = true,
	};
	ESP_RETURN_ON_ERROR(i2c_new_master_bus(&config, &s_i2c_bus_handle),
			    TAG,
			    "shared i2c init failed");
	s_i2c_initialized = true;
	ESP_LOGI(TAG,
		 "shared i2c ready: port=%d sda=%d scl=%d freq=%u",
		 (int)HARDWARE_BOARD_I2C_NUM,
		 (int)HARDWARE_BOARD_I2C_SDA,
		 (int)HARDWARE_BOARD_I2C_SCL,
		 (unsigned)HARDWARE_BOARD_I2C_FREQ_HZ);
	return ESP_OK;
}

i2c_master_bus_handle_t hardware_board_get_i2c_bus_handle(void)
{
	return s_i2c_bus_handle;
}

esp_err_t hardware_board_init_io_expander(void)
{
	return ESP_OK;
}

esp_err_t hardware_board_set_lcd_chip_select(bool active)
{
	(void)active;
	return ESP_OK;
}

esp_err_t hardware_board_set_audio_power(bool enable)
{
#if HARDWARE_BOARD_AUDIO_ENABLED
	if (!s_audio_power_initialized) {
		gpio_config_t gpio_cfg = {
			.pin_bit_mask = 1ULL << HARDWARE_BOARD_AUDIO_PA_GPIO,
			.mode = GPIO_MODE_OUTPUT,
			.pull_up_en = GPIO_PULLUP_DISABLE,
			.pull_down_en = GPIO_PULLDOWN_DISABLE,
			.intr_type = GPIO_INTR_DISABLE,
		};
		ESP_RETURN_ON_ERROR(gpio_config(&gpio_cfg), TAG, "audio pa gpio init failed");
		s_audio_power_initialized = true;
	}
	return gpio_set_level(HARDWARE_BOARD_AUDIO_PA_GPIO, enable ? 1 : 0);
#else
	(void)enable;
	return ESP_ERR_NOT_SUPPORTED;
#endif
}

esp_err_t hardware_board_set_camera_power(bool enable)
{
	if (!s_board.capabilities.camera) {
		return ESP_ERR_NOT_SUPPORTED;
	}
	if (!s_camera_power_initialized) {
		const gpio_config_t gpio_cfg = {
			.pin_bit_mask = 1ULL << HARDWARE_BOARD_CAMERA_POWER_GPIO,
			.mode = GPIO_MODE_OUTPUT,
			.pull_up_en = GPIO_PULLUP_DISABLE,
			.pull_down_en = GPIO_PULLDOWN_DISABLE,
			.intr_type = GPIO_INTR_DISABLE,
		};
		ESP_RETURN_ON_ERROR(gpio_config(&gpio_cfg), TAG, "camera power gpio init failed");
		/*
		 * A USB/JTAG reset can leave the camera rail powered while the P4
		 * restarts. Force one low pulse so a partial SCCB transaction cannot
		 * survive the reset and hold the shared bus in an undefined state.
		 */
		ESP_RETURN_ON_ERROR(gpio_set_level(HARDWARE_BOARD_CAMERA_POWER_GPIO, 0),
				    TAG,
				    "camera power reset assert failed");
		vTaskDelay(pdMS_TO_TICKS(HARDWARE_BOARD_CAMERA_POWER_OFF_MS));
		s_camera_power_initialized = true;
		s_camera_power_enabled = false;
	}

	const bool power_changed = s_camera_power_enabled != enable;
	ESP_RETURN_ON_ERROR(gpio_set_level(HARDWARE_BOARD_CAMERA_POWER_GPIO, enable ? 1 : 0),
			    TAG,
			    "camera power switch failed");
	s_camera_power_enabled = enable;
	if (enable && power_changed) {
		vTaskDelay(pdMS_TO_TICKS(HARDWARE_BOARD_CAMERA_POWER_SETTLE_MS));
	}
	return ESP_OK;
}

esp_err_t hardware_board_prepare_camera(void)
{
	if (!s_board.capabilities.camera) {
		return ESP_ERR_NOT_SUPPORTED;
	}

	ESP_RETURN_ON_ERROR(hardware_board_init_i2c(), TAG, "camera i2c init failed");
	ESP_RETURN_ON_FALSE(s_i2c_bus_handle != NULL,
			    ESP_ERR_INVALID_STATE,
			    TAG,
			    "camera i2c handle missing");

	for (uint32_t attempt = 1; attempt <= HARDWARE_BOARD_CAMERA_PROBE_ATTEMPTS; ++attempt) {
		esp_err_t ret = i2c_master_probe(s_i2c_bus_handle,
					 HARDWARE_BOARD_CAMERA_I2C_ADDR,
					 HARDWARE_BOARD_I2C_PROBE_TIMEOUT_MS);
		if (ret == ESP_OK) {
			ESP_LOGI(TAG,
				 "camera control ready: addr=0x%02x attempt=%u off=%ums settle=%ums",
				 HARDWARE_BOARD_CAMERA_I2C_ADDR,
				 (unsigned)attempt,
				 (unsigned)HARDWARE_BOARD_CAMERA_POWER_OFF_MS,
				 (unsigned)HARDWARE_BOARD_CAMERA_POWER_SETTLE_MS);
			return ESP_OK;
		}

		const int sda_level = gpio_get_level(HARDWARE_BOARD_I2C_SDA);
		const int scl_level = gpio_get_level(HARDWARE_BOARD_I2C_SCL);
		if (attempt == HARDWARE_BOARD_CAMERA_PROBE_ATTEMPTS) {
			ESP_LOGE(TAG,
				 "camera control unavailable: addr=0x%02x attempts=%u ret=%s sda=%d scl=%d",
				 HARDWARE_BOARD_CAMERA_I2C_ADDR,
				 (unsigned)attempt,
				 esp_err_to_name(ret),
				 sda_level,
				 scl_level);
			return ret;
		}

		ESP_LOGW(TAG,
			 "camera control recovery: addr=0x%02x attempt=%u ret=%s sda=%d scl=%d",
			 HARDWARE_BOARD_CAMERA_I2C_ADDR,
			 (unsigned)attempt,
			 esp_err_to_name(ret),
			 sda_level,
			 scl_level);
		ESP_RETURN_ON_ERROR(hardware_board_set_camera_power(false),
				    TAG,
				    "camera recovery power off failed");
		vTaskDelay(pdMS_TO_TICKS(HARDWARE_BOARD_CAMERA_POWER_OFF_MS));
		ESP_RETURN_ON_ERROR(hardware_board_set_camera_power(true),
				    TAG,
				    "camera recovery power on failed");
	}

	return ESP_FAIL;
}

esp_err_t hardware_board_init(void)
{
	ESP_RETURN_ON_ERROR(hardware_board_init_i2c(), TAG, "i2c init failed");
	if (s_board.capabilities.audio_output) {
		ESP_RETURN_ON_ERROR(hardware_board_set_audio_power(false), TAG, "audio power init failed");
	}
	return ESP_OK;
}
