"""Exercise the actual UART maintenance dispatcher with the public runtime ABI."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "components/starter_at/src/regression_controls.c").read_text(encoding="utf-8")
source = re.sub(r"^#include[^\n]*\n", "", source, flags=re.MULTILINE)
stub = """#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_ERR_NO_MEM 1
#define ESP_ERR_TIMEOUT 2
#define ESP_ERR_INVALID_ARG 3
#define ESP_ERR_INVALID_STATE 4
"""
harness = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "starter_runtime.h"
#include "starter_product.h"
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
#define pdMS_TO_TICKS(n) (n)
typedef struct { bool active; } starter_media_status_t;
typedef struct { char project_name[32], version[32], idf_ver[32]; uint8_t app_elf_sha256[32]; } esp_app_desc_t;
static starter_runtime_status_t state = {.state=STARTER_RUNTIME_WAITING,.session_generation=7,.connection_generation=9};
static bool media, connected, updating, pressed;
static int op, index_arg;
static char text_arg[128];
enum { CONTACTS=1, CALL, VIDEO, ACCEPT, REJECT, HANGUP, MUTE, CAMERA, OPEN, CLOSE,
       CREATE, JOIN, LEAVE, REFRESH, PTT, DISCONNECT, REBOOT, TX_START, TX_STOP, TX_DUMP, DOOR };
static starter_product_door_control_t door_arg;
esp_err_t starter_product_door_control(starter_product_door_control_t control) {
    op=DOOR;door_arg=control;return ESP_OK;
}
esp_err_t starter_product_ui_inspect(void) { op=DOOR;return ESP_OK; }
esp_err_t starter_product_ui_pointer(uint16_t x,uint16_t y,bool down) {
    op=DOOR;index_arg=x;pressed=down;assert(y==200);return ESP_OK;
}
static const char *esp_err_to_name(int error) { (void)error; return "error"; }
static void *heap_caps_calloc(size_t n, size_t size, unsigned caps) { (void)caps; return calloc(n,size); }
static void heap_caps_free(void *p) { free(p); }
static starter_runtime_status_t starter_runtime_status_mock(void) { return state; }
#define starter_runtime_status starter_runtime_status_mock
static starter_media_status_t starter_media_status(void) { return (starter_media_status_t){media}; }
static bool starter_tirtc_connected(void) { return connected; }
static bool coprocessor_update_busy(void) { return updating; }
static int starter_media_tx_timing_start(void) { op=TX_START;return ESP_OK; }
static int starter_media_tx_timing_stop(void) { op=TX_STOP;return ESP_OK; }
static int starter_media_tx_timing_dump(void) { op=TX_DUMP;return ESP_OK; }
const char *starter_runtime_state_name(starter_runtime_state_t s) { (void)s; return "state"; }
bool starter_runtime_try_product_snapshot(starter_runtime_product_snapshot_t *p) { memset(p,0,sizeof(*p));return true; }
bool starter_runtime_room_read(unsigned n,starter_room_snapshot_t *p) { (void)n;memset(p,0,sizeof(*p));return true; }
void starter_runtime_copy_device_id(char *p,size_t n) { snprintf(p,n,"TEST_ONLY"); }
static const esp_app_desc_t *esp_app_get_description(void) { static esp_app_desc_t app;return &app; }
esp_err_t starter_runtime_contacts_refresh(void) { op=CONTACTS;return ESP_OK; }
esp_err_t starter_runtime_call_contact(uint8_t n) { op=CALL;index_arg=n;return ESP_OK; }
esp_err_t starter_runtime_call_contact_video(uint8_t n) { op=VIDEO;index_arg=n;return ESP_OK; }
esp_err_t starter_runtime_call_accept(void) { op=ACCEPT;return ESP_OK; }
esp_err_t starter_runtime_call_reject(void) { op=REJECT;return ESP_OK; }
esp_err_t starter_runtime_call_hangup(void) { op=HANGUP;return ESP_OK; }
esp_err_t starter_runtime_call_set_microphone_muted(bool v) { op=MUTE;pressed=v;return ESP_OK; }
esp_err_t starter_runtime_call_set_camera_enabled(uint32_t g,bool v) { assert(g==7);op=CAMERA;pressed=v;return ESP_OK; }
void starter_runtime_room_set_open(bool v) { op=v?OPEN:CLOSE; }
esp_err_t starter_runtime_room_create(const char *p) { op=CREATE;snprintf(text_arg,sizeof(text_arg),"%s",p);return ESP_OK; }
esp_err_t starter_runtime_room_join(const char *c,const char *p) { op=JOIN;snprintf(text_arg,sizeof(text_arg),"%s/%s",c,p);return ESP_OK; }
esp_err_t starter_runtime_room_leave(void) { op=LEAVE;return ESP_OK; }
esp_err_t starter_runtime_room_refresh(void) { op=REFRESH;return ESP_OK; }
bool starter_runtime_room_ptt(uint32_t g,bool p) { assert(g==9);op=PTT;pressed=p;return false; }
static bool wifi_manager_connected(void) { return true; }
static bool wifi_manager_provisioning(void) { return false; }
static bool wifi_manager_manually_disconnected(void) { return false; }
static bool wifi_manager_control_pending(void) { return false; }
static int wifi_manager_control_error(void) { return ESP_OK; }
static int wifi_manager_disconnect(void) { op=DISCONNECT;return ESP_OK; }
static void vTaskDelay(unsigned n) { assert(n==150); }
static void esp_restart(void) { op=REBOOT; }
@SOURCE@
static void check(const char *command,int expected) {
    char line[320];snprintf(line,sizeof(line),"%s",command);op=0;
    assert(starter_at_regression_command(line));assert(op==expected);
}
int main(void) {
    for (unsigned i=0;i<8;i++) {
        char c[32];snprintf(c,sizeof(c),"AT+CALL=%u",i);check(c,CALL);assert(index_arg==(int)i);
        snprintf(c,sizeof(c),"AT+VIDCALL=%u",i);check(c,VIDEO);assert(index_arg==(int)i);
    }
    const char *invalid[]={"","-1","8","9","10","256","1x","1,0"," 1","0 "};
    for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        char c[80];snprintf(c,sizeof(c),"AT+CALL=%s",invalid[i]);check(c,0);
    }
    check("AT+CONTACTS=REFRESH",CONTACTS);check("AT+CALL=ACCEPT",ACCEPT);
    check("AT+CALL=REJECT",REJECT);check("AT+CALL=HANGUP",HANGUP);
    check("AT+CALL ACCEPT",ACCEPT);check("AT+CALL REJECT",REJECT);check("AT+CALL HANGUP",HANGUP);
    reply_result(ESP_ERR_INVALID_STATE, true);
    result(ESP_ERR_INVALID_STATE);
    check("AT+CALL=MUTE,0",MUTE);assert(!pressed);
    check("AT+CALL=MUTE,1",MUTE);assert(pressed);
    check("AT+CALL=CAMERA,0",CAMERA);assert(!pressed);
    check("AT+CALL=CAMERA,1",CAMERA);assert(pressed);
    check("AT+CALL=MUTE,2",0);check("AT+CALL=CAMERA,-1",0);
    check("AT+ROOM=OPEN",OPEN);check("AT+ROOM=CLOSE",CLOSE);
    check("AT+ROOM=CREATE",CREATE);assert(!text_arg[0]);
    check("AT+ROOM=CREATE,1234",CREATE);assert(!strcmp(text_arg,"1234"));
    check("AT+ROOM=JOIN,123456",JOIN);assert(!strcmp(text_arg,"123456/"));
    check("AT+ROOM=JOIN,123456,1234",JOIN);assert(!strcmp(text_arg,"123456/1234"));
    check("AT+ROOM=LEAVE",LEAVE);check("AT+ROOM=REFRESH",REFRESH);
    check("AT+ROOM=PTT,0",PTT);assert(!pressed);
    check("AT+ROOM=PTT,1",PTT);assert(pressed);
    check("AT+NET=DISCONNECT",DISCONNECT);
    check("AT+DEVICE?",0);check("AT+CONTACTS?",0);check("AT+CALL?",0);check("AT+ROOM?",0);check("AT+NET?",0);
    const char *door_commands[]={"AT+DOOR?","AT+DOOR=HOME","AT+DOOR=NEXT",
        "AT+DOOR=PREVIOUS","AT+DOOR=VIEWER","AT+DOOR=SENDER","AT+DOOR=DEVICES","AT+DOOR=BACK"};
    for(unsigned i=0;i<sizeof(door_commands)/sizeof(door_commands[0]);i++) {
        check(door_commands[i],DOOR);assert(door_arg==(starter_product_door_control_t)(i+1));
    }
    check("AT+UI?",DOOR);check("AT+UI",DOOR);check("AT+CONTACTS",0);
    check("AT+UI=POINTER,100,200,1",DOOR);assert(index_arg==100 && pressed);
    check("AT+UI=POINTER,100,200,0",DOOR);assert(!pressed);
    check("AT+UI=POINTER,65536,200,1",0);
    check("AT+UI=POINTER,100,200,2",0);
    check("AT+UI=POINTER,100,200,1x",0);
    char forbidden_door[]="AT+DOOR=UNLOCK";assert(!starter_at_regression_command(forbidden_door));
    char unknown[]="AT+UNKNOWN";assert(!starter_at_regression_command(unknown));
    char trailing[]="AT+CALL ACCEPT extra";assert(!starter_at_regression_command(trailing));
    for(unsigned flags=0;flags<16;flags++) {
        state.state=(flags&1)?STARTER_RUNTIME_AI_ACTIVE:STARTER_RUNTIME_WAITING;
        media=flags&2;connected=flags&4;updating=flags&8;
        check("AT+REBOOT",flags?0:REBOOT);
        check("AT+TXTRACE=START",flags?0:TX_START);
        check("AT+TXTRACE?",flags?0:TX_DUMP);
        check("AT+TXTRACE=STOP",TX_STOP);
    }
    fprintf(stderr,"PASS: actual UART dispatcher, contact bounds, boolean parameters, room payloads, readback and 16 reboot guards (host mocks only)\n");
}
"""
with tempfile.TemporaryDirectory(prefix="xiaotai-regression-control-") as directory:
    directory = Path(directory)
    (directory / "esp_err.h").write_text(stub, encoding="utf-8")
    test = directory / "test.c"
    test.write_text(harness.replace("@SOURCE@", source), encoding="utf-8")
    binary = directory / "test"
    subprocess.run(["cc", "-D_POSIX_C_SOURCE=200809L", "-DCONFIG_IDF_TARGET_ESP32P4=1",
                    "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "-fno-omit-frame-pointer", "-I", str(directory),
                    "-I", str(root / "components/starter_runtime/include"),
                    "-I", str(root / "components/starter_product/include"),
                    "-I", str(root / "components/starter_voice/include"),
                    str(test), "-o", str(binary)], check=True)
    run = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert "ERROR: error" in run.stdout and "ERROR,INTENT,error" in run.stdout
    print(run.stderr, end="")
