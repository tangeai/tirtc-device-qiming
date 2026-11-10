"""ASan/UBSan check of the exact C61 diagnostic packet selector."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "coprocessor/esp32c61/main/c61_diagnostics.c").read_text(encoding="utf-8")
start = source.index("static uint16_t be16(")
end = source.index("static esp_err_t observed_sta_rx(", start)
harness = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
@PARSER@
static void make(uint8_t *p, unsigned ihl, unsigned seq) {
    memset(p, 0, 128);
    p[12] = 8; p[14] = 0x40 | (ihl / 4); p[23] = 17;
    uint8_t *udp = p + 14 + ihl;
    udp[2] = 0xc0; udp[3] = 9; udp[5] = 32;
    memcpy(udp + 8, "XTP1", 4);
    udp[14] = seq >> 8; udp[15] = seq;
}
int main(void) {
    uint8_t frame[128]; uint32_t seq;
    for (unsigned ihl = 20; ihl <= 60; ihl += 4) {
        for (unsigned i = 0; i < 501; ++i) {
            make(frame, ihl, i);
            for (unsigned len = 0; len <= sizeof(frame); ++len) {
                uint8_t *exact = malloc(len ? len : 1);
                memcpy(exact, frame, len);
                bool accepted = probe_sequence(exact, len, &seq);
                free(exact);
                if (accepted != (len >= 14 + ihl + 16 && i < 500)) return 1;
                if (accepted && seq != i) return 2;
            }
        }
    }
    make(frame, 20, 0); frame[20] = 0x20;
    if (probe_sequence(frame, 128, &seq)) return 3;
    make(frame, 20, 0); frame[23] = 6;
    if (probe_sequence(frame, 128, &seq)) return 4;
    make(frame, 20, 0); frame[37]++;
    if (probe_sequence(frame, 128, &seq)) return 5;
    return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="c61-probe-parser-") as directory:
    test = Path(directory) / "test.c"
    binary = Path(directory) / "test"
    test.write_text(harness.replace("@PARSER@", source[start:end]), encoding="utf-8")
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("PASS: exact selector, 11 IP header sizes, 501 sequences, 129 packet lengths, rejected non-probe traffic")
