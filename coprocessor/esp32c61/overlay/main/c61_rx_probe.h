#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

/* Lab-only receiver. A true result consumes only magic-tagged UDP/5005. */
bool c61_rx_probe_observe(const void *buffer, uint16_t length);
void c61_tx_probe_result(int result);
void c61_tx_probe_backpressure(int result, uint32_t wait_us);
esp_err_t c61_rx_probe_init(void);
