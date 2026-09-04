#include "app_memory_policy.h"

#include <limits.h>
#include <stdint.h>
#include <string.h>

#include "esp_attr.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"

static portMUX_TYPE s_memory_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_psram_alloc_failures;
static uint32_t s_alloc_failures;
static size_t s_last_failed_size;
static uint32_t s_last_failed_caps;
static uintptr_t s_last_failed_function;

_Static_assert(APP_MEMORY_INTERNAL_FREE_CRITICAL_BYTES <
                   APP_MEMORY_INTERNAL_FREE_WARNING_BYTES,
               "internal free waterlines must be ordered");
_Static_assert(APP_MEMORY_INTERNAL_LARGEST_CRITICAL_BYTES <
                   APP_MEMORY_INTERNAL_LARGEST_WARNING_BYTES,
               "internal largest-block waterlines must be ordered");
_Static_assert(APP_MEMORY_DMA_FREE_CRITICAL_BYTES <
                   APP_MEMORY_DMA_FREE_WARNING_BYTES,
               "DMA free waterlines must be ordered");
_Static_assert(APP_MEMORY_DMA_LARGEST_CRITICAL_BYTES <
                   APP_MEMORY_DMA_LARGEST_WARNING_BYTES,
               "DMA largest-block waterlines must be ordered");
_Static_assert(APP_MEMORY_PSRAM_FREE_CRITICAL_BYTES <
                   APP_MEMORY_PSRAM_FREE_WARNING_BYTES,
               "PSRAM free waterlines must be ordered");
_Static_assert(APP_MEMORY_PSRAM_LARGEST_CRITICAL_BYTES <
                   APP_MEMORY_PSRAM_LARGEST_WARNING_BYTES,
               "PSRAM largest-block waterlines must be ordered");

static void app_memory_note_psram_failure(void)
{
    taskENTER_CRITICAL(&s_memory_lock);
    s_psram_alloc_failures++;
    taskEXIT_CRITICAL(&s_memory_lock);
}

static void IRAM_ATTR app_memory_alloc_failed_hook(size_t size,
                                                   uint32_t caps,
                                                   const char *function_name)
{
    __atomic_fetch_add(&s_alloc_failures, 1U, __ATOMIC_RELAXED);
    __atomic_store_n(&s_last_failed_size, size, __ATOMIC_RELAXED);
    __atomic_store_n(&s_last_failed_caps, caps, __ATOMIC_RELAXED);
    __atomic_store_n(&s_last_failed_function, (uintptr_t)function_name, __ATOMIC_RELAXED);
}

esp_err_t app_memory_policy_init(void)
{
    return heap_caps_register_failed_alloc_callback(app_memory_alloc_failed_hook);
}

void *app_memory_alloc_psram(size_t size)
{
    void *ptr = NULL;

    if (size == 0U) {
        return NULL;
    }

    ptr = heap_caps_malloc(size, APP_MEMORY_CAPS_PSRAM);
    if (ptr == NULL) {
        app_memory_note_psram_failure();
    }
    return ptr;
}

void *app_memory_calloc_psram(size_t count, size_t size)
{
    void *ptr = NULL;

    if (count == 0U || size == 0U || count > (SIZE_MAX / size)) {
        return NULL;
    }

    ptr = heap_caps_calloc(count, size, APP_MEMORY_CAPS_PSRAM);
    if (ptr == NULL) {
        app_memory_note_psram_failure();
    }
    return ptr;
}

void *app_memory_aligned_alloc_psram(size_t alignment, size_t size, uint32_t extra_caps)
{
    void *ptr = NULL;

    if (alignment == 0U || size == 0U) {
        return NULL;
    }

    ptr = heap_caps_aligned_alloc(alignment,
                                  size,
                                  APP_MEMORY_CAPS_PSRAM | extra_caps);
    if (ptr == NULL) {
        app_memory_note_psram_failure();
    }
    return ptr;
}

void *app_memory_aligned_calloc_psram(size_t alignment,
                                      size_t count,
                                      size_t size,
                                      uint32_t extra_caps)
{
    void *ptr = NULL;

    if (alignment == 0U || count == 0U || size == 0U || count > (SIZE_MAX / size)) {
        return NULL;
    }

    ptr = heap_caps_aligned_calloc(alignment,
                                   count,
                                   size,
                                   APP_MEMORY_CAPS_PSRAM | extra_caps);
    if (ptr == NULL) {
        app_memory_note_psram_failure();
    }
    return ptr;
}

void app_memory_get_snapshot(app_memory_snapshot_t *snapshot)
{
    if (snapshot == NULL) {
        return;
    }

    memset(snapshot, 0, sizeof(*snapshot));
    snapshot->internal_free = heap_caps_get_free_size(APP_MEMORY_CAPS_CONTROL);
    snapshot->internal_largest = heap_caps_get_largest_free_block(APP_MEMORY_CAPS_CONTROL);
    snapshot->internal_min_free = heap_caps_get_minimum_free_size(APP_MEMORY_CAPS_CONTROL);
    snapshot->dma_free = heap_caps_get_free_size(APP_MEMORY_CAPS_DMA);
    snapshot->dma_largest = heap_caps_get_largest_free_block(APP_MEMORY_CAPS_DMA);
    snapshot->dma_min_free = heap_caps_get_minimum_free_size(APP_MEMORY_CAPS_DMA);
    snapshot->psram_free = heap_caps_get_free_size(APP_MEMORY_CAPS_PSRAM);
    snapshot->psram_largest = heap_caps_get_largest_free_block(APP_MEMORY_CAPS_PSRAM);
    snapshot->psram_min_free = heap_caps_get_minimum_free_size(APP_MEMORY_CAPS_PSRAM);

    taskENTER_CRITICAL(&s_memory_lock);
    snapshot->psram_alloc_failures = s_psram_alloc_failures;
    taskEXIT_CRITICAL(&s_memory_lock);
    snapshot->alloc_failures =
        __atomic_load_n(&s_alloc_failures, __ATOMIC_RELAXED);
    snapshot->last_failed_size =
        __atomic_load_n(&s_last_failed_size, __ATOMIC_RELAXED);
    snapshot->last_failed_caps =
        __atomic_load_n(&s_last_failed_caps, __ATOMIC_RELAXED);
    snapshot->last_failed_function = (const char *)
        __atomic_load_n(&s_last_failed_function, __ATOMIC_RELAXED);
}

app_memory_health_t app_memory_classify(const app_memory_snapshot_t *snapshot)
{
    if (snapshot == NULL) {
        return APP_MEMORY_HEALTH_CRITICAL;
    }

    if (snapshot->internal_free < APP_MEMORY_INTERNAL_FREE_CRITICAL_BYTES ||
        snapshot->internal_largest < APP_MEMORY_INTERNAL_LARGEST_CRITICAL_BYTES ||
        snapshot->dma_free < APP_MEMORY_DMA_FREE_CRITICAL_BYTES ||
        snapshot->dma_largest < APP_MEMORY_DMA_LARGEST_CRITICAL_BYTES ||
        snapshot->psram_free < APP_MEMORY_PSRAM_FREE_CRITICAL_BYTES ||
        snapshot->psram_largest < APP_MEMORY_PSRAM_LARGEST_CRITICAL_BYTES) {
        return APP_MEMORY_HEALTH_CRITICAL;
    }

    if (snapshot->internal_free < APP_MEMORY_INTERNAL_FREE_WARNING_BYTES ||
        snapshot->internal_largest < APP_MEMORY_INTERNAL_LARGEST_WARNING_BYTES ||
        snapshot->dma_free < APP_MEMORY_DMA_FREE_WARNING_BYTES ||
        snapshot->dma_largest < APP_MEMORY_DMA_LARGEST_WARNING_BYTES ||
        snapshot->psram_free < APP_MEMORY_PSRAM_FREE_WARNING_BYTES ||
        snapshot->psram_largest < APP_MEMORY_PSRAM_LARGEST_WARNING_BYTES) {
        return APP_MEMORY_HEALTH_WARNING;
    }

    return APP_MEMORY_HEALTH_NORMAL;
}

const char *app_memory_health_name(app_memory_health_t health)
{
    switch (health) {
    case APP_MEMORY_HEALTH_NORMAL:
        return "normal";
    case APP_MEMORY_HEALTH_WARNING:
        return "warning";
    case APP_MEMORY_HEALTH_CRITICAL:
        return "critical";
    default:
        return "unknown";
    }
}
