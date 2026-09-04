#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define C61_SEQUENCE_WINDOW_BITS 2048U

typedef struct {
    uint32_t highest;
    uint8_t seen[C61_SEQUENCE_WINDOW_BITS / 8U];
    bool initialized;
} c61_sequence_window_t;

typedef enum {
    C61_SEQUENCE_NEW,
    C61_SEQUENCE_DUPLICATE,
    C61_SEQUENCE_TOO_OLD,
} c61_sequence_result_t;

static inline void c61_sequence_window_reset(c61_sequence_window_t *window)
{
    memset(window, 0, sizeof(*window));
}

static inline void c61_sequence_window_clear_bit(c61_sequence_window_t *window,
                                                  uint32_t sequence)
{
    window->seen[(sequence % C61_SEQUENCE_WINDOW_BITS) >> 3] &=
        (uint8_t)~(1U << (sequence & 7U));
}

static inline c61_sequence_result_t c61_sequence_window_record(
    c61_sequence_window_t *window, uint32_t sequence, bool *reordered)
{
    *reordered = false;
    if (!window->initialized) {
        c61_sequence_window_reset(window);
        window->initialized = true;
        window->highest = sequence;
    } else if (sequence > window->highest) {
        const uint32_t advance = sequence - window->highest;
        if (advance >= C61_SEQUENCE_WINDOW_BITS) {
            memset(window->seen, 0, sizeof(window->seen));
        } else {
            for (uint32_t next = window->highest + 1U; next <= sequence; ++next) {
                c61_sequence_window_clear_bit(window, next);
            }
        }
        window->highest = sequence;
    } else if (window->highest - sequence >= C61_SEQUENCE_WINDOW_BITS) {
        return C61_SEQUENCE_TOO_OLD;
    } else if (sequence < window->highest) {
        *reordered = true;
    }

    const uint8_t bit = (uint8_t)(1U << (sequence & 7U));
    uint8_t *slot = &window->seen[(sequence % C61_SEQUENCE_WINDOW_BITS) >> 3];
    if ((*slot & bit) != 0) {
        return C61_SEQUENCE_DUPLICATE;
    }
    *slot |= bit;
    return C61_SEQUENCE_NEW;
}
