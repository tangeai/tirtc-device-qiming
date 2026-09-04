#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    bool running;
    uint16_t port;
    uint32_t packets;
    uint32_t unique_packets;
    uint32_t bytes;
    uint32_t first_sequence;
    uint32_t highest_sequence;
    uint32_t missing_packets;
    uint32_t duplicate_packets;
    uint32_t out_of_order_packets;
    uint32_t invalid_packets;
    uint32_t sequence_overflow_packets;
    uint32_t receive_errors;
    uint32_t long_gap_count;
    uint32_t max_interarrival_us;
    uint32_t elapsed_ms;
    uint32_t last_receive_age_ms;
    int last_error;
    bool echo_enabled;
    uint32_t echo_sent;
    uint32_t echo_errors;
    uint32_t echo_retry_attempts;
    uint32_t echo_recovered;
    uint32_t echo_unrecovered;
    uint32_t echo_max_wait_us;
    uint32_t echo_enomem_packets;
    uint32_t echo_arp_unresolved_packets;
} hosted_udp_diag_stats_t;

esp_err_t hosted_udp_diag_start(uint16_t port);
esp_err_t hosted_udp_diag_start_echo(uint16_t port);
esp_err_t hosted_udp_diag_stop(void);
void hosted_udp_diag_get_stats(hosted_udp_diag_stats_t *stats);
