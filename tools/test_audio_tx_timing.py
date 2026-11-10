"""Exercise the production metadata ring, including its default-off profile."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "audio_tx_timing.h"
static uint64_t now_us;
static int locked;
static unsigned current_core;
static void *current_task = (void *)1;
static int fail_hook = -1;
static void (*callbacks[2])(void);
void *xTaskGetCurrentTaskHandle(void) { return current_task; }
void *xTaskGetHandle(const char *name) { return (void *)(uintptr_t)(!strcmp(name,"eh_spi_rx") ? 2 : 3); }
unsigned xPortGetCoreID(void) { return current_core; }
int esp_register_freertos_tick_hook_for_cpu(void (*callback)(void), unsigned core) {
    if (fail_hook == (int)core) return ESP_ERR_NOT_SUPPORTED;
    callbacks[core] = callback; return ESP_OK;
}
void esp_deregister_freertos_tick_hook(void (*callback)(void)) {
    for (unsigned i=0;i<2;i++) if (callbacks[i] == callback) callbacks[i] = NULL;
}
int64_t esp_timer_get_time(void) { return (int64_t)now_us; }
static void enter(void) { assert(!locked); locked = 1; }
static void leave(void) { assert(locked); locked = 0; }
static int trace_printf(const char *format, ...) { (void)format; assert(!locked); return 0; }
static int trace_puts(const char *text) { (void)text; assert(!locked); return 0; }
#define printf trace_printf
#define puts trace_puts
#include "audio_tx_timing.c"
#undef printf
#undef puts
int main(void) {
#if CONFIG_APP_AUDIO_TX_TIMING_DIAGNOSTICS
    assert(audio_tx_timing_start() == ESP_ERR_INVALID_STATE);
    fail_hook = 1;
    assert(audio_tx_timing_worker_started() == ESP_ERR_NOT_SUPPORTED && !callbacks[0] && !callbacks[1]);
    assert(audio_tx_timing_start() == ESP_ERR_NOT_SUPPORTED);
    fail_hook = -1;
    assert(audio_tx_timing_worker_started() == ESP_OK && callbacks[0] && callbacks[1]);
    audio_tx_timing_record_t r = {.generation=3, .kind=0};
    audio_tx_timing_record(&r);
    assert(s_written == 0);
    assert(audio_tx_timing_start() == ESP_OK);
    callbacks[0](); callbacks[0](); current_core=1; callbacks[1]();
    assert(audio_tx_timing_ticks() == 3);
    current_task=(void *)2; callbacks[1]();
    current_task=(void *)3; callbacks[1](); callbacks[1]();
    uint32_t spi,tcpip;
    audio_tx_timing_network_ticks(1,&spi,&tcpip); assert(spi==1 && tcpip==2);
    audio_tx_timing_network_ticks(0,&spi,&tcpip); assert(!spi && !tcpip);
    assert(audio_tx_timing_ticks() == 3);
    assert(audio_tx_timing_dump() == ESP_ERR_INVALID_STATE);
    for (unsigned i=0; i<1300; ++i) {
        now_us += 20000; r.source_ms = i * 20;
        audio_tx_timing_record(&r);
    }
    assert(s_written == 1300 && s_records[1299 % TX_TIMING_CAPACITY].source_ms == 25980);
    audio_tx_timing_drop(3, 26000);
    assert(s_fault && s_fault_us == now_us && s_written == 1301);
    for (unsigned i=0; i<150; ++i) { now_us += 20000; audio_tx_timing_record(&r); }
    assert(s_armed);
    now_us++; audio_tx_timing_record(&r);
    assert(!s_armed && s_written == 1451);
    assert(audio_tx_timing_dump() == ESP_OK);
    assert(audio_tx_timing_start() == ESP_OK && !s_fault && !s_written);
    now_us = UINT32_MAX - 1000U;
    audio_tx_timing_drop(4, 0);
    now_us += 3000001U; audio_tx_timing_record(&r);
    assert(!s_armed && s_written == 1);
    assert(audio_tx_timing_start() == ESP_OK);
    assert(audio_tx_timing_stop() == ESP_OK && !s_armed);
    assert(audio_tx_timing_dump() == ESP_OK && !locked);
#else
    assert(audio_tx_timing_start() == ESP_ERR_NOT_SUPPORTED);
    assert(audio_tx_timing_stop() == ESP_ERR_NOT_SUPPORTED);
    assert(audio_tx_timing_dump() == ESP_ERR_NOT_SUPPORTED);
    audio_tx_timing_drop(1,2);
#endif
    puts("PASS: actual TX metadata ring, off/arm/wrap/fault/freeze/rearm/export; no payload or hot-path UART");
}
'''
with tempfile.TemporaryDirectory(prefix="audio-tx-timing-") as directory:
    directory = Path(directory)
    (directory / "freertos").mkdir()
    (directory / "lwip").mkdir()
    (directory / "lwip/opt.h").write_text('#define TCPIP_THREAD_NAME "tiT"\n', encoding="ascii")
    (directory / "esp_err.h").write_text(
        "#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_ERR_INVALID_STATE 1\n#define ESP_ERR_NOT_SUPPORTED 2\n", encoding="ascii")
    (directory / "esp_attr.h").write_text("#define EXT_RAM_BSS_ATTR\n#define IRAM_ATTR\n", encoding="ascii")
    (directory / "esp_freertos_hooks.h").write_text(
        "int esp_register_freertos_tick_hook_for_cpu(void (*callback)(void),unsigned core);\n"
        "void esp_deregister_freertos_tick_hook(void (*callback)(void));\n", encoding="ascii")
    (directory / "freertos/task.h").write_text(
        "void *xTaskGetCurrentTaskHandle(void);\nvoid *xTaskGetHandle(const char *name);\n"
        "unsigned xPortGetCoreID(void);\n", encoding="ascii")
    (directory / "esp_timer.h").write_text("#include <stdint.h>\nint64_t esp_timer_get_time(void);\n", encoding="ascii")
    (directory / "freertos/FreeRTOS.h").write_text(
        "typedef int portMUX_TYPE;\n#define portNUM_PROCESSORS 2\n#define configTICK_RATE_HZ 1000\n#define portMUX_INITIALIZER_UNLOCKED 0\n"
        "#define portENTER_CRITICAL(mux) ((void)(mux),enter())\n"
        "#define portEXIT_CRITICAL(mux) ((void)(mux),leave())\n", encoding="ascii")
    source = directory / "test.c"
    source.write_text(harness, encoding="ascii")
    for enabled in (0, 1):
        binary = directory / ("test-" + str(enabled))
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        "-DCONFIG_APP_AUDIO_TX_TIMING_DIAGNOSTICS=" + str(enabled),
                        "-I", str(directory), "-I", str(root / "components/starter_media/src"),
                        str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
