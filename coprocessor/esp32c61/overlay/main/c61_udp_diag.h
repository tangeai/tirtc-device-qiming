#pragma once

#include <stdint.h>

void c61_udp_diag_take_snapshot(uint32_t *packets,
                                uint32_t *promisc_unique,
                                uint32_t *promisc_retries);

void c61_udp_diag_promisc_start(void);
void c61_udp_diag_promisc_stop(void);
