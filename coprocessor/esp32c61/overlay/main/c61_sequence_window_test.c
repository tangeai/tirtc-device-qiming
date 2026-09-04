#include <assert.h>
#include <stdbool.h>
#include <stdio.h>

#include "c61_sequence_window.h"

int main(void)
{
    c61_sequence_window_t window;
    bool reordered;
    c61_sequence_window_reset(&window);

    for (uint32_t sequence = 0; sequence < 65536U; ++sequence) {
        assert(c61_sequence_window_record(&window, sequence, &reordered) ==
               C61_SEQUENCE_NEW);
        assert(!reordered);
    }
    assert(c61_sequence_window_record(&window, 65535U, &reordered) ==
           C61_SEQUENCE_DUPLICATE);

    c61_sequence_window_reset(&window);
    assert(c61_sequence_window_record(&window, 100U, &reordered) == C61_SEQUENCE_NEW);
    assert(c61_sequence_window_record(&window, 102U, &reordered) == C61_SEQUENCE_NEW);
    assert(c61_sequence_window_record(&window, 101U, &reordered) == C61_SEQUENCE_NEW);
    assert(reordered);
    assert(c61_sequence_window_record(&window, 101U, &reordered) ==
           C61_SEQUENCE_DUPLICATE);

    assert(c61_sequence_window_record(&window, 3000U, &reordered) == C61_SEQUENCE_NEW);
    assert(c61_sequence_window_record(&window, 100U, &reordered) ==
           C61_SEQUENCE_TOO_OLD);
    assert(c61_sequence_window_record(&window, 953U, &reordered) == C61_SEQUENCE_NEW);
    assert(reordered);
    assert(c61_sequence_window_record(&window, 952U, &reordered) ==
           C61_SEQUENCE_TOO_OLD);

    c61_sequence_window_reset(&window);
    for (uint32_t block = 0; block < 256U; ++block) {
        for (uint32_t i = 0; i < 256U; ++i) {
            const uint32_t sequence = block * 256U + ((i * 73U) & 255U);
            assert(c61_sequence_window_record(&window, sequence, &reordered) ==
                   C61_SEQUENCE_NEW);
            assert(c61_sequence_window_record(&window, sequence, &reordered) ==
                   C61_SEQUENCE_DUPLICATE);
        }
    }

    puts("c61_sequence_window_test: PASS");
    return 0;
}
