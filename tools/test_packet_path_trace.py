"""Compile the real packet-path wrappers with bounded clock/network mocks."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = root / "components/wifi_manager/src/wifi_path_trace.c"
assert '"-Wl,--wrap=esp_netif_receive" "-Wl,--wrap=lwip_recvfrom"' in (
    root / "components/wifi_manager/CMakeLists.txt").read_text(encoding="utf-8")
mocks = {
    "sdkconfig.h": "#pragma once\n",
    "esp_err.h": "#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n#define ESP_ERR_INVALID_STATE 259\n#define ESP_ERR_NOT_SUPPORTED 262\n",
    "esp_attr.h": "#pragma once\n#define EXT_RAM_BSS_ATTR\n",
    "esp_netif.h": "#pragma once\ntypedef struct { int marker; } esp_netif_t;\n",
    "esp_timer.h": "#pragma once\n#include <stdint.h>\nint64_t esp_timer_get_time(void);\n",
    "lwip/sockets.h": "#pragma once\n#include <sys/socket.h>\n#include <netinet/in.h>\n",
    "freertos/FreeRTOS.h": "#pragma once\ntypedef int portMUX_TYPE;\n#define portMUX_INITIALIZER_UNLOCKED 0\nvoid trace_lock(void);\nvoid trace_unlock(void);\n#define taskENTER_CRITICAL(p) do { (void)(p); trace_lock(); } while (0)\n#define taskEXIT_CRITICAL(p) do { (void)(p); trace_unlock(); } while (0)\n",
}
harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include "@SOURCE@"
static int64_t clock_us;
static unsigned locks, net_calls, socket_calls;
static ssize_t mock_socket_result=80;
int64_t esp_timer_get_time(void) { errno=EAGAIN; return clock_us; }
void trace_lock(void) { assert(locks++==0); }
void trace_unlock(void) { assert(locks--==1); }
esp_err_t __real_esp_netif_receive(esp_netif_t *netif, void *data, size_t length, void *owner) {
    assert(netif && data && length && owner); assert(!locks); net_calls++; return 73;
}
ssize_t __real_lwip_recvfrom(int socket, void *data, size_t length, int flags,
                           struct sockaddr *from, socklen_t *from_length) {
    assert(socket==17 && data && length==20 && flags==3 && !locks);
    if(from && from_length) {
        struct sockaddr_in address={.sin_family=AF_INET, .sin_addr.s_addr=htonl(0x08080808U)};
        memcpy(from,&address,sizeof(address)); *from_length=sizeof(address);
    }
    socket_calls++; errno=ECHILD; return mock_socket_result;
}
static void be16_write(uint8_t *p, unsigned value) { p[0]=value>>8; p[1]=value; }
static void sequence_write(uint8_t *p, uint32_t value) {
    p[46]=value>>24; p[47]=value>>16; p[48]=value>>8; p[49]=value;
}
int main(void) {
    uint8_t packet[50]={0};
    be16_write(packet+12,0x0800); packet[14]=0x45; be16_write(packet+16,36);
    packet[23]=17; packet[26]=8; packet[27]=8; packet[28]=8; packet[29]=8;
    be16_write(packet+36,49162); be16_write(packet+38,16); memcpy(packet+42,"XTLN",4);
    esp_netif_t netif={0};
    assert(!wifi_path_trace_active());
    assert(__wrap_esp_netif_receive(&netif,packet,sizeof(packet),&netif)==73);
    assert(net_calls==1 && !s_used);
    assert(wifi_path_trace_start()==ESP_OK);
#ifdef CONFIG_APP_PACKET_PATH_TRANSPORT_STATS
    assert(wifi_path_trace_transport_active());
#else
    assert(!wifi_path_trace_transport_active());
#endif
    assert(wifi_path_trace_start()==ESP_ERR_INVALID_STATE);
    assert(wifi_path_trace_dump()==ESP_ERR_INVALID_STATE);
    for(size_t len=0;len<sizeof(packet);len++) note_network(packet,len);
    assert(!s_used);
    clock_us=100000;
    note_network(packet,sizeof(packet));
    clock_us=300000;
    sequence_write(packet,2); note_network(packet,sizeof(packet));
    sequence_write(packet,1); note_network(packet,sizeof(packet));
    sequence_write(packet,3); note_network(packet,sizeof(packet));
    assert(s_bins[0].net_wan==4 && s_bins[0].probe==4 && s_bins[0].probe_gaps==1);
    assert(s_bins[0].probe_duplicate==1 && s_probe_last==3 && s_bins[0].net_gap_ms==200);
    packet[26]=192; packet[27]=168;
    sequence_write(packet,4); note_network(packet,sizeof(packet));
    assert(s_bins[0].net_lan==1);
    uint8_t buffer[20]; struct sockaddr_storage peer; socklen_t peer_size=sizeof(peer);
    assert(__wrap_lwip_recvfrom(17,buffer,20,3,(struct sockaddr*)&peer,&peer_size)==80);
    assert(errno==ECHILD && socket_calls==1 && s_bins[0].socket_wan==1);
    assert(__wrap_lwip_recvfrom(17,buffer,20,3,NULL,NULL)==80 && errno==ECHILD);
    assert(socket_calls==2 && s_bins[0].socket_wan==1);
    mock_socket_result=-1;
    assert(__wrap_lwip_recvfrom(17,buffer,20,3,(struct sockaddr*)&peer,&peer_size)==-1);
    assert(errno==ECHILD && socket_calls==3 && s_bins[0].socket_wan==1);
    wifi_path_trace_media(false); wifi_path_trace_media(true);
    wifi_path_trace_transport(1,55,2,3,4,5); wifi_path_trace_transport(2,40,0,1,0,2);
    assert(s_bins[0].audio==1 && s_bins[0].video==1 && s_bins[0].tp_audio==1 && s_bins[0].tp_video==1);
    assert(s_bins[0].rtt_ms==55 && s_bins[0].nack==2 && s_bins[0].retx==3);
    clock_us=2500000; wifi_path_trace_media(false);
    assert(s_used==3 && s_bins[2].audio_gap_ms==2200 && !s_bins[1].audio);
    wifi_path_trace_stop(); wifi_path_trace_media(false);
    assert(s_bins[2].audio==1 && !wifi_path_trace_active() && !wifi_path_trace_transport_active() && !locks);
    assert(wifi_path_trace_start()==ESP_OK && !s_used);
    clock_us+=(int64_t)PATH_TRACE_SECONDS*1000000;
    wifi_path_trace_media(false); assert(!wifi_path_trace_active() && !s_used);
    assert(wifi_path_trace_start()==ESP_OK);
    clock_us+=20000; wifi_path_trace_media(false); wifi_path_trace_stop();
    assert(s_bins[0].audio==1 && s_bins[0].audio_gap_ms==0);
    assert(wifi_path_trace_dump()==ESP_OK);
    puts("PASS: actual netif/socket passthrough, errno, truncated packets, LAN probe, gaps, bounded capture and rearm");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="packet-path-trace-") as directory:
    directory = Path(directory)
    for name, content in mocks.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="ascii")
    test = directory / "test.c"
    test.write_text(harness.replace("@SOURCE@", source.as_posix()), encoding="ascii")
    binary = directory / "test"
    for transport in (False, True):
        options = ["-DCONFIG_APP_PACKET_PATH_TRANSPORT_STATS=1"] if transport else []
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", *options,
                        "-DCONFIG_APP_PACKET_PATH_TRACE=1", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", "-I", str(directory), "-I",
                        str(root / "components/wifi_manager/include"), str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
