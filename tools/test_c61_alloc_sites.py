"""Check real diagnostic wrapper semantics, bounds and zero-size handling."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = root / "coprocessor/esp32c61/main"
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "c61_alloc_trace.h"
#include "esp_private/wifi_os_adapter.h"
static int marker;
static uint32_t clock_us;
static unsigned freed;
int64_t esp_timer_get_time(void) { return clock_us += 23; }
void __real_esp_wifi_internal_free_rx_buffer(void *p) { (void)p; freed++; }
void __wrap_esp_wifi_internal_free_rx_buffer(void *p);
void *__real_malloc(size_t n) { return n == 1 ? &marker : NULL; }
void *__real_calloc(size_t n, size_t s) { return n == 1 && s == 1 ? &marker : NULL; }
void *__real_realloc(void *p, size_t s) { return s == 1 ? p : NULL; }
void *__real_heap_caps_malloc(size_t n, uint32_t c) { (void)c; return n == 1 ? &marker : NULL; }
wifi_osi_funcs_t g_wifi_osi_funcs = { ._wifi_malloc=__real_malloc };
void *__wrap_malloc(size_t);
void *__wrap_calloc(size_t, size_t);
void *__wrap_realloc(void *, size_t);
void *__wrap_heap_caps_malloc(size_t, uint32_t);
int main(void) {
    char buffer[896], short_buffer[2];
    assert(__wrap_malloc(1848) == NULL);
    assert(c61_alloc_trace_format(buffer, sizeof(buffer)));
    assert(strstr(buffer, "observations=0,"));
    c61_alloc_trace_enable();
    c61_alloc_trace_enable();
    assert(g_wifi_osi_funcs._wifi_malloc(1) == &marker);
    assert(__wrap_malloc(1) == &marker);
    assert(__wrap_calloc(1, 1) == &marker);
    assert(__wrap_realloc(&marker, 1) == &marker);
    assert(__wrap_heap_caps_malloc(1, 0x1800) == &marker);
    assert(__wrap_malloc(0) == NULL);
    assert(__wrap_calloc(3, 0) == NULL);
    assert(__wrap_realloc(&marker, 0) == NULL);
    assert(__wrap_heap_caps_malloc(0, 0x1800) == NULL);
    assert(c61_alloc_trace_format(buffer, sizeof(buffer)));
    assert(strstr(buffer, "observations=0,"));
    for (int i = 0; i < 3; ++i) assert(__wrap_malloc(1848) == NULL);
    assert(__wrap_calloc(2, 924) == NULL);
    assert(__wrap_realloc(&marker, 1848) == NULL);
    assert(__wrap_heap_caps_malloc(1848, 0x1800) == NULL);
    assert(__wrap_calloc(SIZE_MAX, 2) == NULL);
    assert(c61_alloc_trace_format(buffer, sizeof(buffer)));
    assert(strstr(buffer, "observations=7,untracked=0,"));
    assert(strstr(buffer, "m@0x") && strstr(buffer, "c@0x"));
    assert(strstr(buffer, "r@0x") && strstr(buffer, "h@0x"));
    assert(strstr(buffer, "/1848/0x1800/1"));
    assert(strstr(buffer, "/1848/0x0/3"));
    for (int i = 0; i < 2; ++i) assert(g_wifi_osi_funcs._wifi_malloc(1848) == NULL);
    assert(c61_alloc_trace_format(buffer, sizeof(buffer)));
    assert(strstr(buffer, "wifi_hook=1,") && strstr(buffer, "w@0x"));
    assert(strstr(buffer, "observations=9,untracked=0,"));
    for (int i = 0; i < 20; ++i) assert(__wrap_heap_caps_malloc(4096 + i, 0x1800) == NULL);
    assert(c61_alloc_trace_format(buffer, sizeof(buffer)));
    assert(strstr(buffer, "observations=29,untracked=18,"));
    int owners[33];
    for (unsigned i = 0; i < 33; ++i) c61_alloc_trace_rx_enter(&owners[i]);
    assert(c61_alloc_trace_format(buffer, sizeof(buffer)));
    assert(strstr(buffer, "rx_live_peak_released=32/32/0,"));
    assert(strstr(buffer, "rx_overflow=1,"));
    for (unsigned i = 0; i < 33; ++i) __wrap_esp_wifi_internal_free_rx_buffer(&owners[i]);
    __wrap_esp_wifi_internal_free_rx_buffer(NULL);
    assert(freed == 34);
    assert(c61_alloc_trace_format(buffer, sizeof(buffer)));
    assert(strstr(buffer, "rx_live_peak_released=0/32/32,"));
    assert(!c61_alloc_trace_format(NULL, sizeof(buffer)));
    assert(!c61_alloc_trace_format(short_buffer, 0));
    assert(!c61_alloc_trace_format(short_buffer, sizeof(short_buffer)));
    assert(short_buffer[1] == 0);
    puts("PASS: failure propagation, success pointers, zero-size, overflow, 8-site bound, count aggregation, truncation");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="c61-alloc-sites-") as folder:
    path = Path(folder)
    (path / "freertos").mkdir()
    (path / "esp_private").mkdir()
    (path / "esp_private/wifi_os_adapter.h").write_text(
        "#include <stddef.h>\ntypedef struct { void *(*_wifi_malloc)(size_t); } wifi_osi_funcs_t;\n"
        "extern wifi_osi_funcs_t g_wifi_osi_funcs;\n", encoding="ascii")
    (path / "esp_attr.h").write_text("#define IRAM_ATTR\n", encoding="ascii")
    (path / "esp_timer.h").write_text("#include <stdint.h>\nint64_t esp_timer_get_time(void);\n", encoding="ascii")
    (path / "freertos/FreeRTOS.h").write_text(
        "typedef int portMUX_TYPE;\n#define portMUX_INITIALIZER_UNLOCKED 0\n"
        "#define portENTER_CRITICAL_SAFE(p) ((void)(p))\n"
        "#define portEXIT_CRITICAL_SAFE(p) ((void)(p))\n", encoding="ascii")
    (path / "test.c").write_text(harness, encoding="ascii")
    binary = path / "test"
    subprocess.run(["cc", "-std=c11", "-O0", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(path), "-I", str(source), str(path / "test.c"),
                    str(source / "c61_alloc_trace.c"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
