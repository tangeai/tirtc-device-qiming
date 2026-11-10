"""Compile the production call-release function against its protocol contract."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "components/starter_runtime/src/starter_runtime.c").read_text(encoding="utf-8")
function = "static void reject_or_hangup_call(bool reject)" + source.split(
    "static void reject_or_hangup_call(bool reject)", 1
)[1].split("static bool ai_network_ready", 1)[0]
stub = """#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_INVALID_STATE 259
"""
harness = r'''
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "starter_runtime.h"
#define CALL_COMMAND_HANGUP 0x2001U
#define PLATFORM_SERVICE_CALL 1
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while (0)
static atomic_int s_public_state;
static bool s_call_wechat, s_call_outgoing, connected;
static const char *TAG = "test";
static char s_call_room_id[32], s_call_wx_app_id[32]="app", s_call_wx_model_id[32]="model";
static char s_call_wx_session_token[32]="fixture", s_call_wx_payload[32]="fixture";
static unsigned sends, finishes, rejects, requests, payload_size;
static char payload[64], path[64], body[1200];
static int finish_error;
static const char *starter_runtime_state_name_mock(int state) { (void)state; return "state"; }
#define starter_runtime_state_name starter_runtime_state_name_mock
static bool starter_tirtc_connected(void) { return connected; }
static int starter_tirtc_send_command(uint32_t command,const void *data,uint32_t length) {
    if (command != CALL_COMMAND_HANGUP || length >= sizeof(payload)) exit(2);
    sends++; payload_size=length;
    if (length) memcpy(payload,data,length);
    return (int)(12U+length);
}
static void reject_wechat_values(const char *app,const char *model,const char *token,
                                const char *room,const char *value,int reason) {
    if (!app[0] || !model[0] || !token[0] || !room || !value[0] || reason!=7) exit(2);
    rejects++;
}
static int platform_client_request(int service,const char *url,const char *value,void *cb,void *user) {
    if (service != PLATFORM_SERVICE_CALL || cb || user) exit(2);
    requests++; snprintf(path,sizeof(path),"%s",url); snprintf(body,sizeof(body),"%s",value); return 0;
}
static void finish_session(int error) { finishes++; finish_error=error; }
static const char *esp_err_to_name(int error) { (void)error; return "result"; }
static void mock_log(const char *format,...) { (void)format; }
#define ESP_LOGI(tag,...) do { (void)(tag); mock_log(__VA_ARGS__); } while (0)
#define ESP_LOGW(tag,...) do { (void)(tag); mock_log(__VA_ARGS__); } while (0)
@FUNCTION@
int main(void) {
    unsigned cases=0;
    for (int state=STARTER_RUNTIME_WAITING; state<=STARTER_RUNTIME_ROOM_ACTIVE; state++) {
        for (unsigned flags=0; flags<32; flags++) {
            s_call_wechat=(flags&1)!=0; s_call_outgoing=(flags&2)!=0;
            bool reject=(flags&4)!=0; connected=(flags&8)!=0;
            snprintf(s_call_room_id,sizeof(s_call_room_id),"%s",(flags&16)?"fixture-room":"");
            atomic_store(&s_public_state,state);
            sends=finishes=rejects=requests=payload_size=0; finish_error=-1;
            memset(payload,0,sizeof(payload)); path[0]=body[0]=0;
            reject_or_hangup_call(reject); cases++;
            bool owns=state==STARTER_RUNTIME_CALL_INCOMING || state==STARTER_RUNTIME_CALL_CONNECTING || state==STARTER_RUNTIME_CALL_ACTIVE;
            if (!owns) { CHECK(!sends && !finishes && !rejects && !requests); continue; }
            CHECK(finishes==1 && finish_error==0);
            CHECK(sends==(unsigned)connected);
            if (connected && s_call_wechat) {
                CHECK(payload_size==strlen("{\"reason\":0}"));
                CHECK(!strcmp(payload,"{\"reason\":0}"));
            } else { CHECK(payload_size==0); }
            CHECK(rejects==(unsigned)(s_call_wechat && reject && !s_call_outgoing));
            CHECK(requests==(unsigned)(!s_call_wechat && s_call_room_id[0]));
            if (requests) {
                const char *expected=state==STARTER_RUNTIME_CALL_INCOMING?"/v1/call/reject":
                    (state==STARTER_RUNTIME_CALL_CONNECTING && s_call_outgoing?"/v1/call/cancel":"/v1/call/hangup");
                CHECK(!strcmp(path,expected));
                CHECK(strstr(body,"fixture-room")!=NULL);
                if (!strcmp(path,"/v1/call/cancel")) CHECK(!strcmp(body,"{\"room_id\":\"fixture-room\"}"));
                else CHECK(strstr(body,reject?"decline":"hangup")!=NULL);
            }
        }
    }
    printf("PASS: %u production call-release cases; WeChat reason payload, device-call contract and owner guards\n",cases);
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="wt99-voip-hangup-") as directory:
    directory = Path(directory)
    (directory / "esp_err.h").write_text(stub, encoding="utf-8")
    test = directory / "test.c"
    test.write_text(harness.replace("@FUNCTION@", function), encoding="utf-8")
    binary = directory / "test"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "-fno-omit-frame-pointer", "-I", str(directory), "-I",
                    str(root / "components/starter_runtime/include"), str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
