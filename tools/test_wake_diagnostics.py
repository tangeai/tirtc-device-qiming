"""Compile the actual read-only AT wake snapshot without microphone/model work."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "components/starter_at/src/starter_at.c").read_text(encoding="utf-8")
begin = source.index("static void at_wake_status(void)")
production = source[begin:source.index("static void at_command", begin)]
assert 'strcmp(line, "AT+WAKE?")' in source
assert 'at_wake_status();' in source
for forbidden in ("wake_backend_", "feed_pcm", "voice_configure", "set_listening"):
    assert forbidden not in production
harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "starter_voice.h"
static starter_voice_status_t snapshot;
static int calls, replies;
static int64_t clock_us;
static starter_voice_status_t starter_voice_status_mock(void) { calls++; return snapshot; }
#define starter_voice_status starter_voice_status_mock
static int64_t esp_timer_get_time(void) { return clock_us; }
static void at_reply(const char *text) { assert(strcmp(text,"OK")==0); replies++; }
@PRODUCTION@
int main(void) {
    snapshot = (starter_voice_status_t){.threshold_milli=800,.init_error=1};
    starter_voice_status_t before=snapshot;
    at_wake_status();
    assert(memcmp(&snapshot,&before,sizeof(snapshot))==0);
    snapshot=(starter_voice_status_t){.ready=true,.listening=true,.threshold_milli=900,
        .fed=140,.model_frames=7,.model_detected=2,.detections=1,
        .last_raw_probability_milli=923,.last_raw_at_ms=1000,
        .detect_avg_us=93000,.max_detect_us=96000,.reject_age=1};
    clock_us=1050000; before=snapshot;
    at_wake_status();
    assert(memcmp(&snapshot,&before,sizeof(snapshot))==0);
    snapshot.listening=false; before=snapshot;
    at_wake_status();
    assert(memcmp(&snapshot,&before,sizeof(snapshot))==0);
    snapshot.last_raw_at_ms=UINT32_MAX-3; clock_us=2000;
    at_wake_status();
    assert(calls==4 && replies==4);
    return 0;
}
'''.replace("@PRODUCTION@", production)
with tempfile.TemporaryDirectory(prefix="wt99-wake-diag-") as folder:
    folder = Path(folder)
    (folder / "esp_err.h").write_text("typedef int esp_err_t;\n", encoding="ascii")
    c = folder / "wake.c"
    c.write_text(harness, encoding="utf-8")
    for agc in (0, 1):
        binary = folder / f"wake-{agc}"
        subprocess.run(["cc", "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        f"-DCONFIG_XIAOTAI_WAKE_CAPTURE_AGC={agc}", f"-I{folder}",
                        f"-I{root / 'components/starter_voice/include'}", str(c), "-o", str(binary)], check=True)
        out = subprocess.check_output([str(binary)], text=True)
        assert "ready=0,listening=0,init_error=1,threshold=800" in out
        assert "last=0,at_ms=0,age_ms=4294967295" in out
        assert "inference=7,raw_hits=2,accepted=1" in out
        assert "last=923,at_ms=1000,age_ms=50" in out
        assert "age_ms=6" in out
        assert f"frontend={'aec-clean-agc' if agc else 'aec-clean'}," in out
print("PASS: actual AT wake query is read-only; unready/active/paused snapshots, score age/wrap, AGC labels and counters preserved")
