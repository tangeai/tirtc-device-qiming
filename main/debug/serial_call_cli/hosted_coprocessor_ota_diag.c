#include "hosted_coprocessor_ota_diag.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_hosted_ota.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"

#include "app_memory_policy.h"
#include "app_task_affinity.h"

#define COPROCESSOR_OTA_URL_MAX_LEN 192U
#define COPROCESSOR_OTA_CHUNK_SIZE   512U
#define COPROCESSOR_OTA_MAX_SIZE     (2U * 1024U * 1024U)
#define COPROCESSOR_OTA_TASK_STACK   (8U * 1024U)
#define COPROCESSOR_OTA_TASK_PRIO    5U

static const char *TAG = "cp_ota_diag";
static TaskHandle_t s_ota_task;
static char s_ota_url[COPROCESSOR_OTA_URL_MAX_LEN];

esp_err_t hosted_coprocessor_ota_diag_recover_partition(size_t image_size)
{
    const esp_partition_t *partition = esp_partition_find_first(
        ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_OTA_1, NULL);
    if (partition == NULL || image_size == 0U || image_size > partition->size) {
        return ESP_ERR_INVALID_SIZE;
    }

    uint8_t *chunk = heap_caps_malloc(COPROCESSOR_OTA_CHUNK_SIZE,
                                      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (chunk == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGW(TAG, "C61 recovery OTA begin: source=ota_1 bytes=%u",
             (unsigned)image_size);
    esp_err_t ret = esp_hosted_slave_ota_begin();
    size_t offset = 0U;
    while (ret == ESP_OK && offset < image_size) {
        const size_t bytes = MIN((size_t)COPROCESSOR_OTA_CHUNK_SIZE,
                                 image_size - offset);
        ret = esp_partition_read(partition, offset, chunk, bytes);
        if (ret == ESP_OK) {
            ret = esp_hosted_slave_ota_write(chunk, (uint32_t)bytes);
        }
        if (ret == ESP_OK) {
            offset += bytes;
        }
    }
    if (ret == ESP_OK) {
        ret = esp_hosted_slave_ota_end();
    }
    heap_caps_free(chunk);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "C61 recovery OTA failed: offset=%u ret=%s",
                 (unsigned)offset, esp_err_to_name(ret));
        return ret;
    }

    ret = esp_hosted_slave_ota_activate();
    if (ret == ESP_OK) {
        ESP_LOGW(TAG, "C61 recovery OTA activated; restarting P4");
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    }
    return ret;
}

static esp_err_t hosted_coprocessor_ota_diag_run(const char *url)
{
    esp_http_client_config_t config = {
        .url = url,
        .timeout_ms = 10000,
        .buffer_size = COPROCESSOR_OTA_CHUNK_SIZE,
        .buffer_size_tx = 512,
        .keep_alive_enable = true,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        return ESP_ERR_NO_MEM;
    }

    esp_err_t ret = esp_http_client_open(client, 0);
    if (ret != ESP_OK) {
        esp_http_client_cleanup(client);
        return ret;
    }

    int64_t content_length = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    if (status != 200 || content_length <= 0 ||
        content_length > COPROCESSOR_OTA_MAX_SIZE) {
        ESP_LOGE(TAG, "invalid firmware response: status=%d length=%lld",
                 status, (long long)content_length);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_ERR_INVALID_RESPONSE;
    }

    uint8_t *chunk = heap_caps_malloc(COPROCESSOR_OTA_CHUNK_SIZE,
                                      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (chunk == NULL) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "C61 OTA begin: bytes=%lld url=%s",
             (long long)content_length, url);
    ret = esp_hosted_slave_ota_begin();
    int64_t transferred = 0;
    while (ret == ESP_OK && transferred < content_length) {
        int read_len = esp_http_client_read(client,
                                            (char *)chunk,
                                            COPROCESSOR_OTA_CHUNK_SIZE);
        if (read_len < 0) {
            ret = ESP_FAIL;
            break;
        }
        if (read_len == 0) {
            if (esp_http_client_is_complete_data_received(client)) {
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        ret = esp_hosted_slave_ota_write(chunk, (uint32_t)read_len);
        if (ret == ESP_OK) {
            transferred += read_len;
        }
    }

    if (ret == ESP_OK && transferred != content_length) {
        ESP_LOGE(TAG, "C61 OTA truncated: got=%lld expected=%lld",
                 (long long)transferred, (long long)content_length);
        ret = ESP_ERR_INVALID_SIZE;
    }
    if (ret == ESP_OK) {
        ret = esp_hosted_slave_ota_end();
    }

    heap_caps_free(chunk);
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "C61 OTA failed: transferred=%lld ret=%s",
                 (long long)transferred, esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "C61 OTA image committed: bytes=%lld", (long long)transferred);
    ret = esp_hosted_slave_ota_activate();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "C61 OTA activate failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "C61 OTA activated; restarting P4 to resynchronize Hosted");
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
    return ESP_OK;
}

static void hosted_coprocessor_ota_diag_task(void *arg)
{
    (void)arg;
    (void)hosted_coprocessor_ota_diag_run(s_ota_url);
    s_ota_task = NULL;
    vTaskDeleteWithCaps(NULL);
}

esp_err_t hosted_coprocessor_ota_diag_start(const char *url)
{
    if (url == NULL || url[0] == '\0' || strlen(url) >= sizeof(s_ota_url)) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_ota_task != NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    strlcpy(s_ota_url, url, sizeof(s_ota_url));
    BaseType_t task_ret = xTaskCreatePinnedToCoreWithCaps(
        hosted_coprocessor_ota_diag_task,
        "cp_ota_diag",
        COPROCESSOR_OTA_TASK_STACK,
        NULL,
        COPROCESSOR_OTA_TASK_PRIO,
        &s_ota_task,
        APP_TASK_CORE_BACKGROUND,
        APP_TASK_STACK_CAPS_BACKGROUND);
    if (task_ret != pdPASS) {
        s_ota_task = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
