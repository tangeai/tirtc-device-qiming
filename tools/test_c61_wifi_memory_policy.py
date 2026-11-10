"""Exercise the production C61 init policy without an ESP-IDF runtime."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
defaults = dict(line.split("=", 1) for line in
                (ROOT / "sdkconfig.defaults").read_text(encoding="utf-8").splitlines()
                if line.startswith("CONFIG_") and "=" in line)
assert defaults["CONFIG_ESP_HOSTED_CP_TARGET_ESP32C61"] == "y"
assert defaults["CONFIG_WIFI_RMT_RX_BA_WIN"] == "6"
assert int(defaults["CONFIG_WIFI_RMT_STATIC_RX_BUFFER_NUM"]) >= 6
assert defaults["CONFIG_WIFI_RMT_AMPDU_RX_ENABLED"] == "y"
assert defaults["CONFIG_WIFI_RMT_AMPDU_TX_ENABLED"] == "y"
c61_defaults = (ROOT / "coprocessor/esp32c61/sdkconfig.defaults").read_text(encoding="utf-8")
for option in ("ESP_WIFI_IRAM_OPT", "ESP_WIFI_RX_IRAM_OPT", "ESP_WIFI_SLP_IRAM_OPT"):
    assert f"# CONFIG_{option} is not set" in c61_defaults
assert "CONFIG_ESP_WIFI_NVS_ENABLED=y" in c61_defaults
source = (ROOT / "components/wifi_manager/src/wifi_manager.c").read_text(encoding="utf-8")
start = source.index("static void apply_coprocessor_memory_policy(")
end = source.index("\nstatic bool s_started;", start)
function = source[start:end]
harness = r"""
#include <string.h>
#include <stdint.h>
typedef struct {
    int static_rx_buf_num, dynamic_rx_buf_num;
    int tx_buf_type, static_tx_buf_num, dynamic_tx_buf_num, cache_tx_buf_num;
    int rx_ba_win, ampdu_rx_enable, ampdu_tx_enable;
    uint32_t feature_caps;
    unsigned char untouched[96];
} wifi_init_config_t;
@POLICY@
int main(void) {
    for (int dynamic = 0; dynamic <= 1; ++dynamic) {
        for (int cap = 1; cap <= 128; ++cap) {
            wifi_init_config_t input;
            memset(&input, 0x5a, sizeof(input));
            input.tx_buf_type = dynamic;
            input.static_tx_buf_num = dynamic ? 0 : cap;
            input.dynamic_tx_buf_num = dynamic ? cap : 0;
            input.cache_tx_buf_num = 32;
            wifi_init_config_t expected = input, actual = input;
#if CONFIG_ESP_HOSTED_CP_TARGET_ESP32C61
            expected.tx_buf_type = 1;
            expected.static_tx_buf_num = 0;
            expected.dynamic_tx_buf_num = cap;
            expected.cache_tx_buf_num = 0;
#endif
            apply_coprocessor_memory_policy(&actual);
            if (memcmp(&actual, &expected, sizeof(actual))) return 1;
            apply_coprocessor_memory_policy(&actual);
            if (memcmp(&actual, &expected, sizeof(actual))) return 2;
        }
    }
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="c61-memory-policy-") as directory:
    test = Path(directory) / "test.c"
    test.write_text(harness.replace("@POLICY@", function), encoding="utf-8")
    for enabled in (0, 1):
        binary = Path(directory) / f"test-{enabled}"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        f"-DCONFIG_ESP_HOSTED_CP_TARGET_ESP32C61={enabled}",
                        str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        print(f"PASS: C61={enabled}, 256 profiles, TX ceiling/other fields/idempotence")
