"""Exercise actual bounded PCM handoff and its separate drop counters."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "components/starter_media/src/starter_media.c").read_text(encoding="utf-8")
start = source.index("static bool enqueue_uplink_pcm(")
function = source[start:source.index("\n/* Keep TiRTC calls", start)]
item = re.search(r"typedef struct \{[^}]*\} audio_tx_item_t;", source)[0]
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <string.h>
#define AUDIO_PACKET_SAMPLES 320U
#define STARTER_TIRTC_ROOM 4
#define pdTRUE 1
typedef int starter_tirtc_mode_t;
@ITEM@
static int free_marker, ready_marker, free_count=1, ready_accept=1;
static void *s_audio_tx_free_queue=&free_marker, *s_audio_tx_ready_queue=&ready_marker;
static audio_tx_item_t s_audio_tx_pool[1];
static atomic_uint s_mute_epoch=3;
static atomic_bool s_microphone_muted;
static atomic_uint_fast32_t s_audio_dropped, s_audio_tx_pool_full, s_audio_tx_ready_full;
static bool room_open;
static bool starter_tirtc_room_transmitting(uint32_t generation) { assert(generation==7); return room_open; }
static int64_t esp_timer_get_time(void) { return 123456; }
static unsigned timing_faults;
static void audio_tx_timing_drop(uint32_t generation, uint32_t source_ms) {
    assert(generation==7 && source_ms==91); timing_faults++;
}
static int xQueueReceive(void *queue, uint8_t *slot, unsigned ticks) {
    assert(queue==s_audio_tx_free_queue && ticks==0);
    if (!free_count) return 0;
    free_count--; *slot=0; return pdTRUE;
}
static int xQueueSend(void *queue, const uint8_t *slot, unsigned ticks) {
    assert(*slot==0 && ticks==0);
    if (queue==s_audio_tx_ready_queue) return ready_accept;
    assert(queue==s_audio_tx_free_queue); free_count++; return pdTRUE;
}
@FUNCTION@
int main(void) {
    int16_t pcm[AUDIO_PACKET_SAMPLES];
    for (unsigned i=0; i<AUDIO_PACKET_SAMPLES; ++i) pcm[i]=(int16_t)i;
    atomic_store(&s_microphone_muted,true);
    assert(!enqueue_uplink_pcm(1,7,90,pcm,3));
    atomic_store(&s_microphone_muted,false);
    assert(!enqueue_uplink_pcm(1,7,90,pcm,2));
    assert(!enqueue_uplink_pcm(STARTER_TIRTC_ROOM,7,90,pcm,3));
    assert(atomic_load(&s_audio_dropped)==0 && free_count==1);
    assert(enqueue_uplink_pcm(1,7,90,pcm,3));
    assert(free_count==0 && s_audio_tx_pool[0].queued_at_ms==123);
    assert(s_audio_tx_pool[0].timestamp_ms==90 && s_audio_tx_pool[0].generation==7);
    assert(!memcmp(pcm,s_audio_tx_pool[0].pcm,sizeof(pcm)));
    assert(!enqueue_uplink_pcm(1,7,91,pcm,3));
    assert(atomic_load(&s_audio_tx_pool_full)==1 && atomic_load(&s_audio_dropped)==1);
    assert(timing_faults==1);
    free_count=1;
    assert(!enqueue_uplink_pcm(1,7,91,NULL,3));
    assert(atomic_load(&s_audio_tx_pool_full)==1 && atomic_load(&s_audio_dropped)==2);
    ready_accept=0;
    assert(!enqueue_uplink_pcm(1,7,91,pcm,3));
    assert(free_count==1 && atomic_load(&s_audio_tx_ready_full)==1);
    assert(atomic_load(&s_audio_dropped)==3);
    audio_tx_item_t zero={0};
    assert(!memcmp(&zero,&s_audio_tx_pool[0],sizeof(zero)));
    return 0;
}
'''.replace("@ITEM@", item).replace("@FUNCTION@", function)
with tempfile.TemporaryDirectory(prefix="p4-audio-tx-queue-") as folder:
    path = Path(folder)
    (path / "test.c").write_text(harness, encoding="ascii")
    binary = path / "test"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    str(path / "test.c"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("PASS: actual PCM copy, mute/PTT epochs, pool vs ready-queue pressure, invalid input, slot return")
