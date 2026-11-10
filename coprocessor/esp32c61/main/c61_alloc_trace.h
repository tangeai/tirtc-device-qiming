#pragma once
#include <stdbool.h>
#include <stddef.h>

/* Diagnostic only: observe failed returns without allocating or changing them. */
void c61_alloc_trace_enable(void);
void c61_alloc_trace_rx_enter(void *owner);
bool c61_alloc_trace_format(char *output, size_t capacity);
