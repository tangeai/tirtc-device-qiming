#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "c61_diagnostics.h"

void app_main(void)
{
    /* ESP-Hosted 3.0.7 owns CP initialization through its registered hooks. */
    esp_err_t nvs = nvs_flash_init();
    if (nvs != ESP_OK) c61_diagnostics_boot_failure(nvs);
    ESP_ERROR_CHECK(nvs);
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    c61_diagnostics_start();
    ESP_LOGI("wt99p461_c61", "C61 SPI companion: Hosted 3.0.7, module GPIO mapping");
}
