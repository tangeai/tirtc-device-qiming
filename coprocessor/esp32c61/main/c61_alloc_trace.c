#include "c61_alloc_trace.h"
#include <inttypes.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "esp_attr.h"
#include "esp_private/wifi_os_adapter.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"

#define SITE_COUNT 8
typedef struct {
    uintptr_t caller;
    uint32_t size, caps, count;
    char kind;
} failed_site_t;

static portMUX_TYPE s_trace_lock = portMUX_INITIALIZER_UNLOCKED;
static atomic_bool s_enabled;
static failed_site_t s_sites[SITE_COUNT];
static unsigned s_used;
static uint32_t s_observations, s_untracked;
static void *(*s_wifi_malloc)(size_t);
#define OWNER_COUNT 32
static struct { void *owner; uint32_t entered_us; } s_owners[OWNER_COUNT];
static uint32_t s_owner_live, s_owner_peak, s_owner_released, s_owner_overflow;
static uint32_t s_owner_max_us, s_failure_owner_peak;

/* Keep the failure path bounded and allocation-free, including ISR callers.
 * Nested allocator wrappers are observations, not distinct failed allocations. */
static void IRAM_ATTR failed_return(char kind, uintptr_t caller, size_t size, uint32_t caps)
{
    if (!atomic_load_explicit(&s_enabled, memory_order_relaxed) || !size) return;
    portENTER_CRITICAL_SAFE(&s_trace_lock);
    s_observations++;
    if (s_owner_live > s_failure_owner_peak) s_failure_owner_peak = s_owner_live;
    unsigned i;
    for (i = 0; i < s_used; ++i) {
        if (s_sites[i].caller == caller && s_sites[i].kind == kind &&
            s_sites[i].size == size && s_sites[i].caps == caps) break;
    }
    if (i < SITE_COUNT) {
        if (i == s_used) {
            s_sites[i] = (failed_site_t){.caller=caller, .size=size, .caps=caps, .kind=kind};
            s_used++;
        }
        s_sites[i].count++;
    } else s_untracked++;
    portEXIT_CRITICAL_SAFE(&s_trace_lock);
}

void c61_alloc_trace_rx_enter(void *owner)
{
    if (!owner || !atomic_load_explicit(&s_enabled, memory_order_relaxed)) return;
    uint32_t now = (uint32_t)esp_timer_get_time();
    portENTER_CRITICAL_SAFE(&s_trace_lock);
    unsigned i;
    for (i = 0; i < OWNER_COUNT && s_owners[i].owner; ++i) {}
    if (i < OWNER_COUNT) {
        s_owners[i].owner = owner;
        s_owners[i].entered_us = now;
        if (++s_owner_live > s_owner_peak) s_owner_peak = s_owner_live;
    } else s_owner_overflow++;
    portEXIT_CRITICAL_SAFE(&s_trace_lock);
}

void __real_esp_wifi_internal_free_rx_buffer(void *owner);
void IRAM_ATTR __wrap_esp_wifi_internal_free_rx_buffer(void *owner)
{
    uint32_t now = (uint32_t)esp_timer_get_time();
    portENTER_CRITICAL_SAFE(&s_trace_lock);
    for (unsigned i = 0; owner && i < OWNER_COUNT; ++i) {
        if (s_owners[i].owner != owner) continue;
        uint32_t elapsed = now - s_owners[i].entered_us;
        if (elapsed > s_owner_max_us) s_owner_max_us = elapsed;
        s_owners[i].owner = NULL;
        s_owner_live--;
        s_owner_released++;
        break;
    }
    portEXIT_CRITICAL_SAFE(&s_trace_lock);
    __real_esp_wifi_internal_free_rx_buffer(owner);
}

void *__real_malloc(size_t size);
void *__real_calloc(size_t count, size_t size);
void *__real_realloc(void *pointer, size_t size);
void *__real_heap_caps_malloc(size_t size, uint32_t caps);

void *IRAM_ATTR __wrap_malloc(size_t size)
{
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    void *result = __real_malloc(size);
    if (!result) failed_return('m', caller, size, 0);
    return result;
}

void *IRAM_ATTR __wrap_calloc(size_t count, size_t size)
{
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    void *result = __real_calloc(count, size);
    size_t total = size && count > SIZE_MAX / size ? SIZE_MAX : count * size;
    if (!result) failed_return('c', caller, total, 0);
    return result;
}

void *IRAM_ATTR __wrap_realloc(void *pointer, size_t size)
{
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    void *result = __real_realloc(pointer, size);
    if (!result) failed_return('r', caller, size, 0);
    return result;
}

void *IRAM_ATTR __wrap_heap_caps_malloc(size_t size, uint32_t caps)
{
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    void *result = __real_heap_caps_malloc(size, caps);
    if (!result) failed_return('h', caller, size, caps);
    return result;
}

static void *IRAM_ATTR observed_wifi_malloc(size_t size)
{
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    void *result = s_wifi_malloc(size);
    if (!result) failed_return('w', caller, size, 0);
    return result;
}

void c61_alloc_trace_enable(void)
{
    /* The first trace identified wifi_malloc; observe its driver-side caller
     * through the existing OS adapter, retaining the allocator and its result. */
    if (!s_wifi_malloc && g_wifi_osi_funcs._wifi_malloc) {
        s_wifi_malloc = g_wifi_osi_funcs._wifi_malloc;
        g_wifi_osi_funcs._wifi_malloc = observed_wifi_malloc;
    }
    atomic_store_explicit(&s_enabled, true, memory_order_release);
}

bool c61_alloc_trace_format(char *output, size_t capacity)
{
    if (!output || !capacity) return false;
    failed_site_t sites[SITE_COUNT];
    unsigned used;
    uint32_t observations, untracked, live, peak, released, overflow, max_us, failure_peak;
    portENTER_CRITICAL_SAFE(&s_trace_lock);
    memcpy(sites, s_sites, sizeof(sites));
    used = s_used;
    observations = s_observations;
    untracked = s_untracked;
    live = s_owner_live;
    peak = s_owner_peak;
    released = s_owner_released;
    overflow = s_owner_overflow;
    max_us = s_owner_max_us;
    failure_peak = s_failure_owner_peak;
    portEXIT_CRITICAL_SAFE(&s_trace_lock);
    int n = snprintf(output, capacity, "alloc_trace=1,wifi_hook=%u,observations=%"PRIu32",untracked=%"PRIu32
                     ",rx_live_peak_released=%"PRIu32"/%"PRIu32"/%"PRIu32",rx_overflow=%"PRIu32
                     ",rx_hold_max_us=%"PRIu32",failure_rx_live_max=%"PRIu32",sites=",
                     g_wifi_osi_funcs._wifi_malloc == observed_wifi_malloc, observations, untracked,
                     live, peak, released, overflow, max_us, failure_peak);
    if (n < 0 || (size_t)n >= capacity) return false;
    size_t length = (size_t)n;
    for (unsigned i = 0; i < used; ++i) {
        n = snprintf(output + length, capacity - length, "%s%c@0x%"PRIxPTR"/%"PRIu32"/0x%"PRIx32"/%"PRIu32,
                     i ? ";" : "", sites[i].kind, sites[i].caller, sites[i].size, sites[i].caps, sites[i].count);
        if (n < 0 || (size_t)n >= capacity - length) return false;
        length += (size_t)n;
    }
    return true;
}
