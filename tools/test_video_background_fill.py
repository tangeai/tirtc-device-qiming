"""Check the production DMA background clear, fallback, and error semantics."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "main/media/video_frame_converter.c").read_text(encoding="utf-8")
start = source.index("static esp_err_t video_frame_clear_rgb565(")
end = source.index("\nstatic esp_err_t video_frame_convert_rgb565_ppa(", start)
function = source[start:end]
rgb = source[end:source.index("\nstatic esp_err_t video_frame_convert_rgb565_scaled(", end)]
assert "video_frame_clear_rgb565(handle, output," in rgb
assert "memset(output" not in rgb
assert "ppa_unregister_client(handle->ppa_fill_client)" in source

harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef int esp_err_t;
#define PPA_FILL_COLOR_MODE_RGB565 2
#define PPA_TRANS_MODE_BLOCKING 1
#define ESP_CACHE_MSYNC_FLAG_DIR_C2M 1
struct video_frame_converter { void *ppa_fill_client; };
typedef struct video_frame_converter *video_frame_converter_handle_t;
typedef struct {
    struct { void *buffer; size_t buffer_size; unsigned pic_w, pic_h;
             unsigned block_offset_x, block_offset_y, fill_cm; } out;
    unsigned fill_block_w, fill_block_h, fill_color_val, mode;
} ppa_fill_oper_config_t;
static unsigned dma_calls, cache_calls;
static int dma_result, cache_result;
static int ppa_do_fill(void *client, const ppa_fill_oper_config_t *fill) {
    assert(client && fill->mode==PPA_TRANS_MODE_BLOCKING);
    assert(fill->out.fill_cm==PPA_FILL_COLOR_MODE_RGB565);
    assert(fill->out.block_offset_x==0 && fill->out.block_offset_y==0);
    assert(fill->fill_block_w==fill->out.pic_w && fill->fill_block_h==fill->out.pic_h);
    assert(fill->out.buffer_size==2u*fill->out.pic_w*fill->out.pic_h);
    assert(fill->fill_color_val==0);
    dma_calls++;
    if (!dma_result) memset(fill->out.buffer, 0, fill->out.buffer_size);
    return dma_result;
}
static int esp_cache_msync(void *buffer, size_t size, unsigned flags) {
    assert(buffer && size && flags==ESP_CACHE_MSYNC_FLAG_DIR_C2M);
    cache_calls++; return cache_result;
}
@FUNCTION@
int main(void) {
    const unsigned dims[][2]={{1024,600},{512,300},{448,600},{16,2}};
    for (unsigned i=0;i<sizeof(dims)/sizeof(dims[0]);i++) {
        size_t count=(size_t)dims[i][0]*dims[i][1];
        uint16_t *p=malloc((count+2)*sizeof(*p)); assert(p);
        for (unsigned dma=0;dma<2;dma++) {
            struct video_frame_converter c={.ppa_fill_client=dma?&c:NULL};
            memset(p,0xab,(count+2)*sizeof(*p));
            unsigned old_dma=dma_calls, old_cache=cache_calls;
            assert(video_frame_clear_rgb565(&c,p+1,dims[i][0],dims[i][1])==0);
            assert(p[0]==0xabab && p[count+1]==0xabab);
            for (size_t n=1;n<=count;n++) assert(p[n]==0);
            assert(dma_calls==old_dma+dma && cache_calls==old_cache+!dma);
        }
        free(p);
    }
    struct video_frame_converter c={.ppa_fill_client=&c};
    uint16_t p[32]; memset(p,0xab,sizeof(p)); dma_result=-7;
    unsigned old_cache=cache_calls;
    assert(video_frame_clear_rgb565(&c,p,16,2)==-7);
    assert(cache_calls==old_cache && p[0]==0xabab);
    c.ppa_fill_client=NULL; cache_result=-9;
    assert(video_frame_clear_rgb565(&c,p,16,2)==-9);
    return 0;
}
'''.replace("@FUNCTION@", function)

with tempfile.TemporaryDirectory(prefix="video-bg-fill-") as directory:
    c_file = Path(directory) / "test.c"
    binary = Path(directory) / "test"
    c_file.write_text(harness, encoding="ascii")
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    str(c_file), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("DMA background clear: 8 geometries/paths, guards and failures passed")
