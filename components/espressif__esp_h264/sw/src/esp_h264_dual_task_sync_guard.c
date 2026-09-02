/*
 * SPDX-FileCopyrightText: 2026 TiRTC project contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "sdkconfig.h"

#if CONFIG_IDF_TARGET_ESP32P4

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "H264_SYNC";

#define TINYH264_FILTER_TASK_NAME "h264FilterTask"

/* Provided by GNU ld when --wrap=xTaskGenericNotify is enabled. */
BaseType_t __real_xTaskGenericNotify(TaskHandle_t task,
                                     UBaseType_t index,
                                     uint32_t value,
                                     eNotifyAction action,
                                     uint32_t *previous_value);

static bool is_tinyh264_phase_notification(TaskHandle_t task,
                                           UBaseType_t index,
                                           uint32_t value,
                                           eNotifyAction action,
                                           uint32_t *previous_value)
{
    if (task == NULL || index != 0U || value != UINT32_MAX ||
        action != eSetValueWithoutOverwrite || previous_value != NULL) {
        return false;
    }

    const char *task_name = pcTaskGetName(task);
    return task_name != NULL &&
           strcmp(task_name, TINYH264_FILTER_TASK_NAME) == 0;
}

BaseType_t __wrap_xTaskGenericNotify(TaskHandle_t task,
                                     UBaseType_t index,
                                     uint32_t value,
                                     eNotifyAction action,
                                     uint32_t *previous_value)
{
    BaseType_t result = __real_xTaskGenericNotify(task,
                                                  index,
                                                  value,
                                                  action,
                                                  previous_value);
    if (result == pdPASS ||
        !is_tinyh264_phase_notification(task,
                                        index,
                                        value,
                                        action,
                                        previous_value)) {
        return result;
    }

    /*
     * The prebuilt dual-task decoder sends block progress with
     * eSetValueWithOverwrite, waits until the helper raises its all-filtered
     * event, updates the shared next-picture pointers, then sends UINT32_MAX as
     * the next phase with eSetValueWithoutOverwrite. A redundant block-progress
     * value can still be in the notification slot after the event is raised.
     * Letting the helper consume that stale value after the pointer update can
     * corrupt deblocking state; waiting and retrying only widens that window.
     *
     * At this point the all-filtered event proves that the pending block index
     * is obsolete. Replace it atomically with the phase value so the helper's
     * next wake-up initializes exactly the state now owned by the caller.
     */
    result = __real_xTaskGenericNotify(task,
                                       index,
                                       value,
                                       eSetValueWithOverwrite,
                                       previous_value);

    static uint32_t corrected_collisions;
    const uint32_t corrected = __atomic_add_fetch(&corrected_collisions,
                                                   1U,
                                                   __ATOMIC_RELAXED);
    if (corrected == 1U || (corrected % 256U) == 0U) {
        ESP_LOGW(TAG,
                 "TinyH264 stale progress replaced: corrected=%lu result=%ld",
                 (unsigned long)corrected,
                 (long)result);
    }
    return result;
}

#endif /* CONFIG_IDF_TARGET_ESP32P4 */
