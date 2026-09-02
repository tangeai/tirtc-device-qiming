#include "hosted_udp_diag.h"

#include <errno.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"

#include "app_memory_policy.h"
#include "app_task_affinity.h"

#define HOSTED_UDP_DIAG_MAGIC              0x43363144UL
#define HOSTED_UDP_DIAG_DEFAULT_PORT       5005U
#define HOSTED_UDP_DIAG_PACKET_BYTES       1600U
#define HOSTED_UDP_DIAG_SEQUENCE_CAPACITY  (256U * 1024U)
#define HOSTED_UDP_DIAG_SEEN_BYTES         (HOSTED_UDP_DIAG_SEQUENCE_CAPACITY / 8U)
#define HOSTED_UDP_DIAG_LONG_GAP_US        250000ULL
#define HOSTED_UDP_DIAG_TASK_STACK         (6U * 1024U)
#define HOSTED_UDP_DIAG_TASK_PRIORITY      17U

static TaskHandle_t s_task;
static bool s_stop_requested;
static uint8_t *s_seen_sequences;
static uint64_t s_last_rx_us;
static hosted_udp_diag_stats_t s_stats;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

static uint32_t hosted_udp_diag_read_be32(const uint8_t *data)
{
    uint32_t value = 0U;
    memcpy(&value, data, sizeof(value));
    return ntohl(value);
}

static bool hosted_udp_diag_mark_sequence(uint32_t sequence)
{
    if (sequence >= HOSTED_UDP_DIAG_SEQUENCE_CAPACITY || s_seen_sequences == NULL) {
        return false;
    }

    const size_t byte_index = sequence >> 3U;
    const uint8_t mask = (uint8_t)(1U << (sequence & 7U));
    if ((s_seen_sequences[byte_index] & mask) != 0U) {
        return true;
    }
    s_seen_sequences[byte_index] |= mask;
    return false;
}

static void hosted_udp_diag_update_missing_locked(void)
{
    if (s_stats.unique_packets == 0U ||
        s_stats.highest_sequence < s_stats.first_sequence) {
        s_stats.missing_packets = 0U;
        return;
    }

    const uint64_t span =
        (uint64_t)s_stats.highest_sequence - s_stats.first_sequence + 1ULL;
    s_stats.missing_packets = span > s_stats.unique_packets ?
        (uint32_t)(span - s_stats.unique_packets) : 0U;
}

static void hosted_udp_diag_task(void *arg)
{
    const uint16_t port = (uint16_t)(uintptr_t)arg;
    uint8_t packet[HOSTED_UDP_DIAG_PACKET_BYTES];
    int sock = -1;
    int task_error = 0;
    uint64_t start_us = (uint64_t)esp_timer_get_time();
    uint64_t previous_rx_us = 0ULL;
    uint64_t last_rx_us = 0ULL;

    sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        task_error = errno;
        goto done;
    }

    const struct timeval timeout = {
        .tv_sec = 0,
        .tv_usec = 200000,
    };
    (void)setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));

    const struct sockaddr_in listen_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(port),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(sock, (const struct sockaddr *)&listen_addr, sizeof(listen_addr)) != 0) {
        task_error = errno;
        goto done;
    }

    taskENTER_CRITICAL(&s_lock);
    s_stats.running = true;
    taskEXIT_CRITICAL(&s_lock);

    while (!s_stop_requested) {
        const ssize_t received = recvfrom(sock, packet, sizeof(packet), 0, NULL, NULL);
        if (received < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                continue;
            }
            taskENTER_CRITICAL(&s_lock);
            s_stats.receive_errors++;
            s_stats.last_error = errno;
            taskEXIT_CRITICAL(&s_lock);
            continue;
        }

        const uint64_t now_us = (uint64_t)esp_timer_get_time();
        if (received < 12 || hosted_udp_diag_read_be32(packet) != HOSTED_UDP_DIAG_MAGIC) {
            taskENTER_CRITICAL(&s_lock);
            s_stats.invalid_packets++;
            taskEXIT_CRITICAL(&s_lock);
            continue;
        }

        const uint32_t sequence = hosted_udp_diag_read_be32(packet + 4U);
        const bool sequence_overflow = sequence >= HOSTED_UDP_DIAG_SEQUENCE_CAPACITY;
        const bool duplicate = hosted_udp_diag_mark_sequence(sequence);
        const uint64_t interarrival_us = previous_rx_us > 0ULL ? now_us - previous_rx_us : 0ULL;

        taskENTER_CRITICAL(&s_lock);
        s_stats.packets++;
        s_stats.bytes += (uint32_t)received;
        if (sequence_overflow) {
            s_stats.sequence_overflow_packets++;
        } else if (duplicate) {
            s_stats.duplicate_packets++;
        } else {
            if (s_stats.unique_packets == 0U) {
                s_stats.first_sequence = sequence;
                s_stats.highest_sequence = sequence;
            } else if (sequence < s_stats.highest_sequence) {
                s_stats.out_of_order_packets++;
            } else if (sequence > s_stats.highest_sequence) {
                s_stats.highest_sequence = sequence;
            }
            s_stats.unique_packets++;
            hosted_udp_diag_update_missing_locked();
        }
        if (interarrival_us > s_stats.max_interarrival_us) {
            s_stats.max_interarrival_us =
                interarrival_us > UINT32_MAX ? UINT32_MAX : (uint32_t)interarrival_us;
        }
        if (interarrival_us >= HOSTED_UDP_DIAG_LONG_GAP_US) {
            s_stats.long_gap_count++;
        }
        s_stats.elapsed_ms = (uint32_t)((now_us - start_us) / 1000ULL);
        s_stats.last_receive_age_ms = 0U;
        s_last_rx_us = now_us;
        taskEXIT_CRITICAL(&s_lock);

        previous_rx_us = now_us;
        last_rx_us = now_us;
    }

done:
    if (sock >= 0) {
        shutdown(sock, 0);
        close(sock);
    }

    const uint64_t end_us = (uint64_t)esp_timer_get_time();
    uint8_t *seen_sequences = NULL;
    taskENTER_CRITICAL(&s_lock);
    s_stats.running = false;
    s_stats.elapsed_ms = (uint32_t)((end_us - start_us) / 1000ULL);
    s_stats.last_receive_age_ms = last_rx_us > 0ULL ?
        (uint32_t)((end_us - last_rx_us) / 1000ULL) : UINT32_MAX;
    if (task_error != 0) {
        s_stats.last_error = task_error;
    }
    seen_sequences = s_seen_sequences;
    s_seen_sequences = NULL;
    s_last_rx_us = last_rx_us;
    s_task = NULL;
    taskEXIT_CRITICAL(&s_lock);
    heap_caps_free(seen_sequences);
    vTaskDelete(NULL);
}

esp_err_t hosted_udp_diag_start(uint16_t port)
{
    if (port == 0U) {
        port = HOSTED_UDP_DIAG_DEFAULT_PORT;
    }

    taskENTER_CRITICAL(&s_lock);
    if (s_task != NULL) {
        taskEXIT_CRITICAL(&s_lock);
        return ESP_ERR_INVALID_STATE;
    }
    memset(&s_stats, 0, sizeof(s_stats));
    s_stats.port = port;
    s_stats.last_receive_age_ms = UINT32_MAX;
    s_stop_requested = false;
    s_last_rx_us = 0ULL;
    taskEXIT_CRITICAL(&s_lock);

    s_seen_sequences = heap_caps_calloc(1U,
                                        HOSTED_UDP_DIAG_SEEN_BYTES,
                                        APP_MEMORY_CAPS_PSRAM);
    if (s_seen_sequences == NULL) {
        return ESP_ERR_NO_MEM;
    }

    const BaseType_t task_ret = xTaskCreatePinnedToCoreWithCaps(
        hosted_udp_diag_task,
        "hosted_udp_rx",
        HOSTED_UDP_DIAG_TASK_STACK,
        (void *)(uintptr_t)port,
        HOSTED_UDP_DIAG_TASK_PRIORITY,
        &s_task,
        APP_TASK_CORE_NETWORK,
        APP_TASK_STACK_CAPS_BACKGROUND);
    if (task_ret != pdPASS) {
        heap_caps_free(s_seen_sequences);
        s_seen_sequences = NULL;
        s_task = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

esp_err_t hosted_udp_diag_stop(void)
{
    taskENTER_CRITICAL(&s_lock);
    if (s_task == NULL) {
        taskEXIT_CRITICAL(&s_lock);
        return ESP_ERR_INVALID_STATE;
    }
    s_stop_requested = true;
    taskEXIT_CRITICAL(&s_lock);

    for (uint32_t attempt = 0U; attempt < 20U; ++attempt) {
        vTaskDelay(pdMS_TO_TICKS(25));
        taskENTER_CRITICAL(&s_lock);
        const bool stopped = s_task == NULL;
        taskEXIT_CRITICAL(&s_lock);
        if (stopped) {
            return ESP_OK;
        }
    }
    return ESP_ERR_TIMEOUT;
}

void hosted_udp_diag_get_stats(hosted_udp_diag_stats_t *stats)
{
    if (stats == NULL) {
        return;
    }

    const uint64_t now_us = (uint64_t)esp_timer_get_time();
    taskENTER_CRITICAL(&s_lock);
    *stats = s_stats;
    if (s_stats.running && s_last_rx_us > 0ULL) {
        const uint64_t age_us = now_us > s_last_rx_us ? now_us - s_last_rx_us : 0ULL;
        stats->last_receive_age_ms = age_us / 1000ULL > UINT32_MAX ?
            UINT32_MAX : (uint32_t)(age_us / 1000ULL);
    }
    taskEXIT_CRITICAL(&s_lock);
}
