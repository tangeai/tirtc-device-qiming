#include "c61_diagnostics.h"
#include "sdkconfig.h"
#ifdef CONFIG_WT_C61_ALLOC_TRACE
#include "c61_alloc_trace.h"
#endif
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "eh_cp_feat_peer_data.h"
#include "eh_mempool_ll.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_private/wifi.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "nvs.h"

#define DIAG_MESSAGE_ID 0x57545331U
#define PROBE_MS 15000U
static const char *TAG = "c61_diag";
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static wifi_rxcb_t s_sta_rx;
static QueueHandle_t s_commands;
static uint8_t s_seen[63];
static uint32_t s_unique, s_duplicate, s_phase[5], s_forward, s_forward_error;
static uint32_t s_callback_max_us;
static uint32_t s_alloc_failures, s_alloc_size, s_alloc_caps;
static char s_alloc_function[32];
static uint32_t s_probe_until_ms;
static bool s_sink;

static uint16_t be16(const uint8_t *p) { return (uint16_t)p[0] * 256U + p[1]; }
static uint32_t be32(const uint8_t *p) { return (uint32_t)be16(p) * 65536U + be16(p + 2); }

static bool probe_sequence(const uint8_t *p, unsigned len, uint32_t *sequence)
{
    if (len < 14U + 20U + 8U + 8U || be16(p + 12) != 0x0800 ||
        (p[14] >> 4) != 4 || p[23] != 17) return false;
    unsigned ihl = (p[14] & 15U) * 4U;
    if (ihl < 20 || len < 14U + ihl + 16U || (be16(p + 20) & 0x3fffU)) return false;
    const uint8_t *udp = p + 14 + ihl;
    if (be16(udp + 2) != 49161 || be16(udp + 4) < 16 ||
        memcmp(udp + 8, "XTP1", 4)) return false;
    *sequence = be32(udp + 12);
    return *sequence < 500U;
}

static esp_err_t observed_sta_rx(void *buffer, uint16_t len, void *owner)
{
    int64_t start = esp_timer_get_time();
    uint32_t sequence = 0, now = (uint32_t)(esp_timer_get_time() / 1000);
    bool selected = buffer && probe_sequence(buffer, len, &sequence);
    taskENTER_CRITICAL(&s_lock);
    wifi_rxcb_t next = s_sta_rx;
    bool active = s_probe_until_ms && (int32_t)(s_probe_until_ms - now) > 0;
    bool sink = selected && active && s_sink;
    if (selected && active) {
        uint8_t mask = 1U << (sequence % 8U);
        if (s_seen[sequence / 8U] & mask) s_duplicate++;
        else {
            s_seen[sequence / 8U] |= mask;
            s_unique++;
            s_phase[sequence / 100U]++;
        }
        if (!sink) s_forward++;
    }
    taskEXIT_CRITICAL(&s_lock);
#ifdef CONFIG_WT_C61_ALLOC_TRACE
    if (selected && active) c61_alloc_trace_rx_enter(owner);
#endif
    esp_err_t err = ESP_OK;
    if (sink || next == NULL) esp_wifi_internal_free_rx_buffer(owner);
    else err = next(buffer, len, owner);
    uint32_t elapsed = (uint32_t)(esp_timer_get_time() - start);
    taskENTER_CRITICAL(&s_lock);
    if (elapsed > s_callback_max_us) s_callback_max_us = elapsed;
    if (selected && active && err != ESP_OK) s_forward_error++;
    taskEXIT_CRITICAL(&s_lock);
    return err;
}

esp_err_t __real_esp_wifi_internal_reg_rxcb(wifi_interface_t ifx, wifi_rxcb_t callback);
esp_err_t __wrap_esp_wifi_internal_reg_rxcb(wifi_interface_t ifx, wifi_rxcb_t callback)
{
    if (ifx == WIFI_IF_STA) {
        taskENTER_CRITICAL(&s_lock);
        wifi_rxcb_t previous = s_sta_rx;
        s_sta_rx = callback;
        taskEXIT_CRITICAL(&s_lock);
        esp_err_t err = __real_esp_wifi_internal_reg_rxcb(ifx, callback ? observed_sta_rx : NULL);
        if (err != ESP_OK) {
            taskENTER_CRITICAL(&s_lock);
            s_sta_rx = previous;
            taskEXIT_CRITICAL(&s_lock);
        }
        return err;
    }
    return __real_esp_wifi_internal_reg_rxcb(ifx, callback);
}

static void allocation_failed(size_t size, uint32_t caps, const char *function)
{
    portENTER_CRITICAL_SAFE(&s_lock);
    s_alloc_failures++;
    s_alloc_size = (uint32_t)size;
    s_alloc_caps = caps;
    unsigned i = 0;
    if (function) for (; i + 1U < sizeof(s_alloc_function) && function[i]; ++i) s_alloc_function[i] = function[i];
    s_alloc_function[i] = 0;
    portEXIT_CRITICAL_SAFE(&s_lock);
}

static void received_command(uint32_t id, const uint8_t *data, size_t length, void *context)
{
    (void)id;
    (void)context;
    if (!data || !length) return;
    uint8_t command = 0;
    if (length == 4 && !memcmp(data, "INFO", 4)) command = 1;
    if (length == 7 && !memcmp(data, "RXRESET", 7)) command = 2;
    if (length == 5 && !memcmp(data, "SINK1", 5)) command = 3;
    if (length == 5 && !memcmp(data, "SINK0", 5)) command = 4;
    if (length == 8 && !memcmp(data, "ROLLBACK", 8)) command = 5;
    if (command) (void)xQueueSend(s_commands, &command, 0);
}

static const esp_partition_t *known_recovery_partition(void)
{
    const esp_partition_t *previous = esp_ota_get_next_update_partition(NULL);
    esp_app_desc_t description;
    if (!previous || esp_ota_get_partition_description(previous, &description) != ESP_OK) return NULL;
    char sha[65];
    for (unsigned i = 0; i < 32; ++i) snprintf(sha + i * 2, 3, "%02x", description.app_elf_sha256[i]);
    return !strcmp(sha, "2a6e367f18958c6e91cae33efe1401b26da2ee7affc9fe1957ec31d0e2e77240")
        ? previous : NULL;
}

void c61_diagnostics_boot_failure(esp_err_t error)
{
    const esp_partition_t *previous = known_recovery_partition();
    ESP_LOGE(TAG, "new C61 APP startup failed: %s; known recovery=%s",
             esp_err_to_name(error), previous ? "available" : "unavailable");
    if (previous && esp_ota_set_boot_partition(previous) == ESP_OK) esp_restart();
}

static void reply(uint8_t command)
{
    if (command == 5) {
        const esp_partition_t *previous = known_recovery_partition();
        if (!previous) {
            const char error[] = "rollback=ERROR_NO_VERIFIED_PREVIOUS_IMAGE";
            (void)eh_cp_feat_peer_data_send(DIAG_MESSAGE_ID, (const uint8_t *)error, sizeof(error) - 1);
            return;
        }
        const char accepted[] = "rollback=selecting_verified_official_2.12.13";
        (void)eh_cp_feat_peer_data_send(DIAG_MESSAGE_ID, (const uint8_t *)accepted, sizeof(accepted) - 1);
        vTaskDelay(pdMS_TO_TICKS(2000));
        esp_err_t err = esp_ota_set_boot_partition(previous);
        if (err == ESP_OK) esp_restart();
        ESP_LOGE(TAG, "requested rollback failed: %s", esp_err_to_name(err));
        return;
    }
    char message[896];
#ifdef CONFIG_WT_C61_ALLOC_TRACE
    if (command == 1 && c61_alloc_trace_format(message, sizeof(message))) {
        esp_err_t trace_err = eh_cp_feat_peer_data_send(DIAG_MESSAGE_ID,
            (const uint8_t *)message, strlen(message));
        if (trace_err != ESP_OK) ESP_LOGE(TAG, "allocation trace response failed: %s", esp_err_to_name(trace_err));
    }
#endif
    const esp_app_desc_t *app = esp_app_get_description();
    char sha[65];
    for (unsigned i = 0; i < 32; ++i) snprintf(sha + i * 2, 3, "%02x", app->app_elf_sha256[i]);
    taskENTER_CRITICAL(&s_lock);
    if (command != 1) {
        if (command == 3 || command == 4) s_sink = command == 3;
        memset(s_seen, 0, sizeof(s_seen));
        memset(s_phase, 0, sizeof(s_phase));
        s_unique = s_duplicate = s_forward = s_forward_error = s_callback_max_us = 0;
        s_probe_until_ms = (uint32_t)(esp_timer_get_time() / 1000) + PROBE_MS;
    }
    uint32_t unique = s_unique, duplicate = s_duplicate, forward = s_forward;
    uint32_t forward_error = s_forward_error, failed = s_alloc_failures, callback_max = s_callback_max_us;
    char function[sizeof(s_alloc_function)];
    memcpy(function, s_alloc_function, sizeof(function));
    uint32_t size = s_alloc_size, caps = s_alloc_caps, phases[5];
    memcpy(phases, s_phase, sizeof(phases));
    bool sink = s_sink;
    taskEXIT_CRITICAL(&s_lock);
    const esp_partition_t *running = esp_ota_get_running_partition();
    wifi_ap_record_t ap = {0};
    esp_err_t ap_err = esp_wifi_sta_get_ap_info(&ap);
    struct eh_mp_mempool *pool = NULL;
    struct eh_mp_mempool_info info;
    unsigned pool_blocks = 0, pool_free = 0, pool_min = 0;
    while ((pool = eh_mp_mempool_info_get_next(pool, &info))) {
        if (info.omi_block_size >= 1500) {
            pool_blocks += info.omi_num_blocks;
            pool_free += info.omi_num_free;
            pool_min += info.omi_min_free;
        }
    }
    snprintf(message, sizeof(message),
             "elf=%s,idf=%s,part=0x%lx,free=%u,largest=%u,minimum=%u,alloc_fail=%lu,last_size=%lu,last_caps=0x%lx,last_function=%s,ap_err=%d,rssi=%d,sink=%u,rx_unique=%lu,duplicate=%lu,forward_calls=%lu,forward_error=%lu,phases=%lu/%lu/%lu/%lu/%lu,callback_max_us=%lu,pool_free_min_total=%u/%u/%u",
             sha, app->idf_ver, (unsigned long)(running ? running->address : 0),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned long)failed, (unsigned long)size, (unsigned long)caps, function, ap_err,
             (int)ap.rssi, (unsigned)sink, (unsigned long)unique, (unsigned long)duplicate,
             (unsigned long)forward, (unsigned long)forward_error,
             (unsigned long)phases[0], (unsigned long)phases[1], (unsigned long)phases[2],
             (unsigned long)phases[3], (unsigned long)phases[4], (unsigned long)callback_max,
             pool_free, pool_min, pool_blocks);
    esp_err_t err = eh_cp_feat_peer_data_send(DIAG_MESSAGE_ID, (const uint8_t *)message, strlen(message));
    if (err != ESP_OK) ESP_LOGE(TAG, "diagnostic response failed: %s", esp_err_to_name(err));
}

static void diagnostics_task(void *argument)
{
    (void)argument;
    /* Application-level OTA safety for this first migration only. The old
     * bootloader has no automatic rollback; preserve its known-good OTA slot. */
    const esp_app_desc_t *current = esp_app_get_description();
    const esp_partition_t *previous = known_recovery_partition();
    bool recovery_valid = previous != NULL;
    nvs_handle_t nvs = 0;
    uint8_t approved_sha[32];
    size_t approved_size = sizeof(approved_sha);
    bool nvs_ready = nvs_open("wt_cp_ota", NVS_READWRITE, &nvs) == ESP_OK;
    bool verified = nvs_ready && nvs_get_blob(nvs, "verified", approved_sha, &approved_size) == ESP_OK &&
                    approved_size == 32 && !memcmp(approved_sha, current->app_elf_sha256, 32);
    int64_t start = esp_timer_get_time();
    unsigned healthy = 0;
    while (true) {
        uint8_t command;
        if (xQueueReceive(s_commands, &command, pdMS_TO_TICKS(1000)) == pdTRUE) reply(command);
        if (verified || !recovery_valid) continue;
        wifi_ap_record_t ap = {0};
        healthy = esp_wifi_sta_get_ap_info(&ap) == ESP_OK ? healthy + 1U : 0U;
        if (healthy >= 4U) {
            esp_err_t err = nvs_ready ? nvs_set_blob(nvs, "verified", current->app_elf_sha256, 32) : ESP_FAIL;
            if (err == ESP_OK) err = nvs_commit(nvs);
            ESP_LOGI(TAG, "OTA first-boot radio/RPC health verified; persist=%s", esp_err_to_name(err));
            verified = true;
        } else if (esp_timer_get_time() - start >= 60000000) {
            ESP_LOGE(TAG, "OTA first-boot health failed; selecting known-good C61 slot at 0x%lx",
                     (unsigned long)previous->address);
            esp_err_t err = esp_ota_set_boot_partition(previous);
            if (err == ESP_OK) esp_restart();
            ESP_LOGE(TAG, "OTA safety rollback failed: %s", esp_err_to_name(err));
            recovery_valid = false;
        }
    }
}

void c61_diagnostics_start(void)
{
    ESP_ERROR_CHECK(heap_caps_register_failed_alloc_callback(allocation_failed));
#ifdef CONFIG_WT_C61_ALLOC_TRACE
    c61_alloc_trace_enable();
#endif
    s_commands = xQueueCreate(4, sizeof(uint8_t));
    ESP_ERROR_CHECK(s_commands ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(eh_cp_feat_peer_data_init());
    ESP_ERROR_CHECK(eh_cp_feat_peer_data_register_callback(DIAG_MESSAGE_ID, received_command, NULL));
    ESP_ERROR_CHECK(xTaskCreate(diagnostics_task, "c61_diag", 6144, NULL, 3, NULL) == pdPASS
                    ? ESP_OK : ESP_ERR_NO_MEM);
}
