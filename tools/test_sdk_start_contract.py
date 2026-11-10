"""Compile the production SDK start path against the delivered public headers."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "components/starter_tirtc/src/starter_tirtc.c").read_text(encoding="utf-8")
production = "int starter_tirtc_start(const starter_tirtc_config_t *config)" + source.split(
    "int starter_tirtc_start(const starter_tirtc_config_t *config)", 1
)[1].split("bool starter_tirtc_started", 1)[0]
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "starter_tirtc.h"
#include "tirtc/tiRTC.h"
#include "tirtc/tgtrp.h"
#define TIRTC_TGTRP_POLL_TIMEOUT_MS 20
#define ESP_LOGI(...) ((void)0)
static bool s_initialized, media_enabled, initialized, started;
static unsigned step, fail_step, enables, init_step, enable_step, rollbacks, probes;
static TIRTCCALLBACKS s_callbacks;
static const char *endpoint;
static int result(void) { return ++step == fail_step ? -123 : 0; }
static void sdk_log(const char *message,uint32_t size) { (void)message;(void)size; }
static void sdk_transport_log(const char *format,va_list args) { (void)format;(void)args; }
static void sdk_transport_probe(bool enable) { probes=enable; }
static void log_start_memory(const char *stage) { (void)stage; }
static void log_start_failure(const char *stage,int error) { (void)stage;(void)error; }
static int rollback_start(const char *stage,int error) {
    (void)stage;rollbacks++;initialized=false;s_initialized=false;probes=0;return error;
}
void TiRtcLogSetCallback(TIRTCLOGCALLBACK callback) { (void)callback; }
void TiRtcLogSetLevel(int level) { assert(level>=1); }
void tgtrp_set_log_callback(tgtrp_log_cb_t callback) { (void)callback; }
void tgtrp_enable_media_transport(void) {
    assert(!initialized&&!started);media_enabled=true;enables++;enable_step=step;
}
const char *TiRtcGetVersion(void) { return "fixture"; }
int TiRtcSetOption(TIRTCOPTION option,const void *value,uint32_t bytes) {
    assert(value&&bytes);
    if(option==TIRTC_OPT_MAX_SEND_BUFFER) assert(!initialized);
    else assert(initialized);
    return result();
}
int TiRtcInit(void) {
    assert(media_enabled&&!started);init_step=step;
    int error=result();if(!error) initialized=true;return error;
}
static int set_string_option(TIRTCOPTION option,const char *value) {
    assert(initialized);
    if(option==TIRTC_OPT_SERVICE_ENDPOINT) endpoint=value;
    return result();
}
int TiRtcStart(const char *id,const TIRTCCALLBACKS *callbacks) {
    assert(media_enabled&&initialized&&id&&callbacks==&s_callbacks);
    assert(endpoint&&!strcmp(endpoint,"https://fixture.invalid"));
    int error=result();if(!error) started=true;return error;
}
@FUNCTION@
int main(void) {
    starter_tirtc_config_t config={.device_id="TEST_ONLY",.device_secret="fixture",
        .client_id="fixture",.service_endpoint="https://fixture.invalid",.max_send_buffer_bytes=2097152};
    unsigned cases=0;
    for(unsigned fail=0;fail<=10;fail++) {
        step=enables=rollbacks=probes=init_step=enable_step=0;fail_step=fail;
        initialized=started=media_enabled=s_initialized=false;endpoint=NULL;
        int error=starter_tirtc_start(&config);
        if(fail==0 || fail>step) { assert(error==0&&started&&s_initialized&&enables==1); }
        else { assert(error==-123&&!started); }
        if(enables) assert(enable_step<=init_step);
        if(rollbacks) assert(!initialized&&!s_initialized&&!probes);
        cases++;
    }
    initialized=started=media_enabled=s_initialized=false;step=enables=0;
    assert(starter_tirtc_start(NULL)==TIRTC_E_INVALID_PARAMETER&&!enables&&!step);
    config.device_id="";
    assert(starter_tirtc_start(&config)==TIRTC_E_INVALID_PARAMETER&&!enables&&!step);
    config.device_id="TEST_ONLY";s_initialized=true;
    assert(starter_tirtc_start(&config)==TIRTC_E_INVALID_PARAMETER&&!enables&&!step);
    printf("PASS: %u SDK start/failure profiles, explicit media before init, HTTPS preserved, invalid/repeated start guards\n",cases+3);
}
'''
with tempfile.TemporaryDirectory(prefix="wt99-sdk-start-") as directory:
    tmp = Path(directory)
    code = tmp / "test.c"
    code.write_text(harness.replace("@FUNCTION@", production), encoding="utf-8")
    command = ["cc", "-std=c11", "-DCONFIG_IDF_TARGET_ESP32P4=1", "-fsanitize=address,undefined",
               "-I", str(root / "components/starter_tirtc/include"),
               "-I", str(root / "components/tirtc_sdk/include"), str(code), "-o", str(tmp / "test")]
    build = subprocess.run(command, capture_output=True, text=True)
    if build.returncode:
        raise RuntimeError(build.stdout + build.stderr)
    subprocess.run([str(tmp / "test")], check=True)
