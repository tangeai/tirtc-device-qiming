"""Check the production call-close text against the delivered SDK error contract."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
runtime = (root / "components/starter_runtime/src/starter_runtime.c").read_text(encoding="utf-8")
adapter = (root / "components/starter_tirtc/src/starter_tirtc.c").read_text(encoding="utf-8")
policy = "static const char *call_connection_close_result(" + runtime.split(
    "static const char *call_connection_close_result(", 1)[1].split(
        "static void handle_connection(", 1)[0]
signature = "bool starter_tirtc_error_is_remote_close(int error)"
classifier = signature + adapter.split(signature, 1)[1].split("\n}\n", 1)[0] + "\n}\n"
assert "finish_call_session(event->error, call_connection_close_result(state, event->error));" in runtime
harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "tirtc/tiRTC.h"
#include "starter_runtime.h"
@CLASSIFIER@
@POLICY@
int main(void) {
    const int errors[] = {0, TIRTC_E_CONN_REMOTECLOSE, TIRTC_E_TIMEOUTED,
        TIRTC_E_CONN_TIMEOUTCLOSE, TIRTC_E_CONN_OTHER_ERROR, TIRTC_E_LACK_OF_RESOURCE,
        TIRTC_E_SERVER_ERROR, TIRTC_E_INTERNAL_ERROR};
    unsigned cases = 0;
    for (unsigned i = 0; i < sizeof(errors)/sizeof(errors[0]); ++i) {
        int error = errors[i];
        assert(starter_tirtc_error_is_remote_close(error) == (error == TIRTC_E_CONN_REMOTECLOSE));
        for (int state = STARTER_RUNTIME_CALL_INCOMING; state <= STARTER_RUNTIME_CALL_ACTIVE; ++state) {
            const char *expected = "网络中断";
            if (error == 0 || error == TIRTC_E_CONN_REMOTECLOSE) {
                expected = state == STARTER_RUNTIME_CALL_INCOMING ? "来电已结束" :
                    state == STARTER_RUNTIME_CALL_CONNECTING ? "呼叫已结束" : "对方已挂断";
            }
            assert(!strcmp(call_connection_close_result(state, error), expected));
            cases++;
        }
    }
    printf("PASS: %u actual call-close policies; SDK remote close is not a network failure; raw errors retained\n", cases);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="call-close-result-") as directory:
    directory = Path(directory)
    (directory / "esp_err.h").write_text("#pragma once\ntypedef int esp_err_t;\n", encoding="ascii")
    source = directory / "test.c"
    source.write_text(harness.replace("@CLASSIFIER@", classifier).replace("@POLICY@", policy), encoding="utf-8")
    binary = directory / "test"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(directory), "-I", str(root / "components/tirtc_sdk/include"),
                    "-I", str(root / "components/starter_runtime/include"), str(source),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
