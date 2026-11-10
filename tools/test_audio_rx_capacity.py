"""Replay real arrival timing through the production PCM queue/controller."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--trace", type=Path)
args = parser.parse_args()
media = (ROOT / "components/starter_media/src/starter_media.c").read_text(encoding="utf-8")
sink = media[media.index("static void audio_sink_task("):media.index("static void camera_task(")]
assert sink.index("bool pcm_room = p4_audio_playout_has_room") < sink.index("xQueueReceive(")
assert sink.count("p4_audio_playout_has_room(") == 2
assert sink.index("xQueueSend(s_audio_rx_free_queue") < sink.index("play_audio_chunk(")
assert "sizeof(s_decode_pcm) / sizeof(s_decode_pcm[0])" in sink

trace = []
if args.trace:
    records = json.loads(args.trace.read_text(encoding="utf-8"))["records"]
    first_arrival, first_source = records[0]["arrival_ms"], records[0]["source_ms"]
    for record in records:
        assert record["samples"] == 320
        trace.append((record["arrival_ms"] - first_arrival,
                      (record["source_ms"] - first_source) & 0xffffffff, 320))

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "p4_audio_playout.h"
typedef struct {uint32_t arrival, source; size_t samples;} packet_t;
static p4_audio_playout_t pcm;
static packet_t packets[2000];
static int16_t decoded[1500], output[P4_PLAYOUT_CHUNK];
static const packet_t real_trace[] = {@TRACE@ {0,0,0}};

static unsigned replay(const packet_t *input, unsigned count, bool bounded,
                       audio_playout_profile_t profile, bool expect_complete) {
    p4_audio_playout_init(&pcm, profile);
    packet_t ready[32];
    unsigned head=0, queued=0, incoming=0, played=0, dropped=0, waits=0, decoded_count=0;
    uint32_t next_write=0;
    for(uint32_t now=0;now<input[count-1].arrival+10000;now++) {
        while(incoming<count && input[incoming].arrival<=now) {
            if(queued==32) dropped++;
            else { ready[(head+queued)%32]=input[incoming]; queued++; }
            incoming++;
        }
        if(now>=next_write) {
            unsigned drained=0;
            while(queued && drained<32 &&
                  (!bounded || p4_audio_playout_has_room(&pcm,1500))) {
                packet_t p=ready[head]; head=(head+1)%32; queued--; drained++;
                assert(p.samples<=1500);
                for(size_t i=0;i<p.samples;i++) decoded[i]=(int16_t)(decoded_count+1);
                decoded_count++;
                if(!p4_audio_playout_push(&pcm,decoded,p.samples,p.source,p.arrival)) dropped++;
            }
            if(queued && bounded && !p4_audio_playout_has_room(&pcm,1500)) waits++;
            p4_playout_block_t block;
            if(p4_audio_playout_prepare(&pcm,now,output,&block)) {
                /* All encoded slots used by this iteration were returned before
                 * the mock hardware takes ownership of the output quantum. */
                played+=p4_audio_playout_commit(&pcm,&block,now,true);
                next_write=now+15;
            }
        }
        if(now && now%1000==0) p4_audio_playout_update_window(&pcm);
        assert(queued<=32 && pcm.count<=P4_PLAYOUT_CAPACITY);
        if(incoming==count && !queued && !pcm.count) break;
    }
    printf("bounded=%u profile=%u input=%u decoded=%u played=%u drops=%u overflow=%u waits=%u\n",
           bounded,profile,count,decoded_count,played,dropped,pcm.overflow_samples,waits);
    if(expect_complete) {
        assert(dropped==0 && pcm.overflow_samples==0 && decoded_count==count && played==count);
    }
    return dropped;
}

int main(void) {
    assert(!p4_audio_playout_has_room(NULL,1));
    p4_audio_playout_init(&pcm,AUDIO_PLAYOUT_PROFILE_JITTER_SAFE);
    assert(!p4_audio_playout_has_room(&pcm,0));
    assert(!p4_audio_playout_has_room(&pcm,P4_PLAYOUT_CAPACITY+1));
    pcm.count=P4_PLAYOUT_CAPACITY-1500;
    assert(p4_audio_playout_has_room(&pcm,1500));
    pcm.count++;
    assert(!p4_audio_playout_has_room(&pcm,1500));
    pcm.count=P4_PLAYOUT_CAPACITY+1;
    assert(!p4_audio_playout_has_room(&pcm,1));
    /* A normal 320 ms lead followed by 1040 ms of burst speech. The input
     * pool itself is sufficient; old eager decode loses PCM after freeing it. */
    for(unsigned i=0;i<16;i++) packets[i]=(packet_t){i*20,i*20,320};
    for(unsigned i=16;i<68;i++) packets[i]=(packet_t){320+(i-16),i*20,320};
    assert(replay(packets,68,false,AUDIO_PLAYOUT_PROFILE_JITTER_SAFE,false)>0);
    replay(packets,68,true,AUDIO_PLAYOUT_PROFILE_JITTER_SAFE,true);
    for(unsigned profile=0;profile<4;profile++) {
        for(unsigned i=0;i<500;i++) packets[i]=(packet_t){i*20,i*20,320};
        replay(packets,500,true,profile,true);
    }
    for(unsigned i=0;i<150;i++) packets[i]=(packet_t){i*94,i*94,1500};
    replay(packets,150,true,AUDIO_PLAYOUT_PROFILE_LOW_LATENCY,true);
    unsigned real_count=sizeof(real_trace)/sizeof(real_trace[0])-1;
    if(real_count) {
        unsigned lost=replay(real_trace,real_count,false,AUDIO_PLAYOUT_PROFILE_JITTER_SAFE,false);
        replay(real_trace,real_count,true,AUDIO_PLAYOUT_PROFILE_JITTER_SAFE,true);
        printf("real arrival replay: old drops=%u; bounded decode preserves all packets\n",lost);
    }
    return 0;
}
'''.replace("@TRACE@", "".join(f"{{{arrival},{source},{samples}}}," for arrival, source, samples in trace))
with tempfile.TemporaryDirectory(prefix="audio-rx-capacity-") as directory:
    test = Path(directory) / "test.c"
    binary = Path(directory) / "test"
    test.write_text(harness, encoding="ascii")
    source = ROOT / "components/starter_media/src"
    subprocess.run(["cc", "-std=c11", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(source), str(test), str(source / "p4_audio_playout.c"),
                    str(source / "audio_playout_controller.c"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
