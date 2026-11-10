"""Exercise the production endpoint resolver in both transport profiles."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "components/platform_client/src/platform_client.c").read_text(encoding="utf-8")
checks = "static bool url_uses_scheme" + source.split("static bool url_uses_scheme", 1)[1].split(
    "static esp_err_t discover_services", 1
)[0]
resolver = "esp_err_t platform_client_resolve_tirtc_endpoint" + source.split(
    "esp_err_t platform_client_resolve_tirtc_endpoint", 1
)[1].split("static void clock_log_failure", 1)[0]
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
typedef int esp_err_t;
enum {ESP_OK=0,ESP_ERR_INVALID_ARG=1,ESP_ERR_INVALID_SIZE=2};
#define PLATFORM_DEFAULT_DISCOVERY "https://fixture.invalid/services"
typedef struct {char device[256],ai[256],call[256],voip[256],mqtt[256],tirtc[256];} platform_services_t;
static platform_services_t s_services;
static bool s_services_ready;
static int clock_error,discovery_error,discoveries;
static esp_err_t platform_client_sync_clock(void) { return clock_error; }
static esp_err_t discover_services(const char *url) {
    assert(!strcmp(url,PLATFORM_DEFAULT_DISCOVERY));discoveries++;
    s_services_ready=!discovery_error;return discovery_error;
}
@CHECKS@
@RESOLVER@
int main(void) {
    strcpy(s_services.device,"https://device.invalid");
    strcpy(s_services.ai,"https://ai.invalid");
    strcpy(s_services.call,"https://call.invalid");
    strcpy(s_services.voip,"https://voip.invalid");
    strcpy(s_services.mqtt,"mqtts://mq.invalid");
    char output[256];unsigned cases=0;
    const char *inputs[]={"https://ep-tirtc.tange365.com","https://custom.invalid/path?q=1","HTTPS://UPPER.invalid:8080/path"};
    const char *http[]={"http://ep-tirtc.tange365.com","http://custom.invalid/path?q=1","http://UPPER.invalid:8080/path"};
    for(unsigned i=0;i<3;i++) {
        strcpy(s_services.tirtc,inputs[i]);platform_services_t before=s_services;
        assert(services_use_authenticated_transports(&s_services));
        s_services_ready=false;discoveries=0;
        assert(platform_client_resolve_tirtc_endpoint(NULL,output,sizeof(output))==ESP_OK);
        assert(!strcmp(output,CONFIG_XIAOTAI_TIRTC_HTTP?http[i]:inputs[i]));
        assert(discoveries==1&&!memcmp(&before,&s_services,sizeof(before)));
        assert(platform_client_resolve_tirtc_endpoint("",output,sizeof(output))==ESP_OK);
        assert(discoveries==1);
        size_t exact=strlen(output)+1;
        assert(platform_client_resolve_tirtc_endpoint(NULL,output,exact)==ESP_OK);
        assert(platform_client_resolve_tirtc_endpoint(NULL,output,exact-1)==ESP_ERR_INVALID_SIZE&&output[0]==0);
        cases+=4;
    }
    assert(platform_client_resolve_tirtc_endpoint(NULL,NULL,10)==ESP_ERR_INVALID_ARG);cases++;
    output[0]='x';assert(platform_client_resolve_tirtc_endpoint(NULL,output,0)==ESP_ERR_INVALID_ARG&&output[0]=='x');cases++;
    clock_error=71;assert(platform_client_resolve_tirtc_endpoint(NULL,output,sizeof(output))==71&&output[0]==0);clock_error=0;cases++;
    s_services_ready=false;discovery_error=72;
    assert(platform_client_resolve_tirtc_endpoint(NULL,output,sizeof(output))==72&&output[0]==0);discovery_error=0;cases++;
    strcpy(s_services.tirtc,"http://untrusted.invalid");
    assert(!services_use_authenticated_transports(&s_services));cases++;
    strcpy(s_services.tirtc,"https://trusted.invalid");
    strcpy(s_services.ai,"http://untrusted.invalid");
    assert(!services_use_authenticated_transports(&s_services));cases++;
    printf("PASS: %u resolver profiles, HTTP policy=%d, shared HTTPS/MQTTS services unchanged\n",cases,CONFIG_XIAOTAI_TIRTC_HTTP);
}
'''
with tempfile.TemporaryDirectory(prefix="wt99-endpoint-") as directory:
    tmp = Path(directory)
    code = tmp / "test.c"
    code.write_text(harness.replace("@CHECKS@", checks).replace("@RESOLVER@", resolver), encoding="utf-8")
    for http in (0, 1):
        binary = tmp / ("test" + str(http))
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                        "-DCONFIG_XIAOTAI_TIRTC_HTTP=" + str(http), str(code), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
