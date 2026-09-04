"""Exercise the actual SDIO zero-copy ownership branch with a host callback stub."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "components/espressif__esp_hosted/host/drivers/transport/sdio/sdio_drv.c"
OUTPUT = ROOT / "build/c61-investigation/hosted-ownership-check"


def wsl_path(path):
    path = path.resolve()
    return f"/mnt/{path.drive[0].lower()}/{path.as_posix()[3:]}"


def branch(source):
    start = source.index("if (buf_handle->payload_zcopy) {", source.index("static void sdio_process_rx_task"))
    end = source.index("/* TODO : Need to abstract heap_caps_malloc */", start)
    return source[start:end]


HARNESS = r"""
#include <stddef.h>
#include <stdio.h>
#define ESP_WIFI_REMOTE_VERSION_VAL(a,b,c) (((a) << 16) | ((b) << 8) | (c))
#define unlikely(x) (x)
#define H_FREE_PTR_WITH_FUNC(fn, ptr) do { if ((fn) && (ptr)) { (fn)(ptr); (ptr)=NULL; } } while (0)
static int frees, requested_ret;
static void release(void *ptr) { (void)ptr; frees++; }
static int rx(void *chan, void *payload, void *owner, size_t len) {
    (void)chan; (void)payload; (void)len;
    if (requested_ret && MODERN_OWNER) release(owner);
    return requested_ret;
}
static struct channel { void *api_chan; int (*rx)(void *,void *,void *,size_t); } ch = {NULL,rx};
static struct channel *chan_arr[] = {&ch};
static int run(int failure) {
    int owner, ret = 0;
    struct buffer { int payload_zcopy, if_type; void *payload,*priv_buffer_handle;
                    size_t payload_len; void (*free_buf_handle)(void *); } handle =
        {1,0,&owner,&owner,42,release};
    struct buffer *buf_handle = &handle;
    frees = 0;
    requested_ret = failure;
    do {
    @BRANCH@
    } while (0);
    if (frees != (failure ? 1 : 0)) return 1;
    if (!failure) release(&owner);
    return frees != 1;
}
int main(void) { return run(0) || run(-1); }
"""


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text(encoding="utf-8")
    generated = OUTPUT / "current.c"
    generated.write_text(HARNESS.replace("@BRANCH@", branch(current)), encoding="utf-8")
    for version, modern in ((None, 0), (0x010300, 0), (0x010603, 1)):
        exe = OUTPUT / f"current-{version or 0}"
        command = ["wsl", "-d", "Ubuntu", "--", "gcc", "-std=c11", "-Wall", "-Wextra",
                   "-Werror", f"-DMODERN_OWNER={modern}"]
        if version:
            command.append(f"-DESP_WIFI_REMOTE_VERSION={version}")
        subprocess.run(command + [wsl_path(generated), "-o", wsl_path(exe)], check=True)
        ret = subprocess.run(["wsl", "-d", "Ubuntu", "--", wsl_path(exe)]).returncode
        print(f"current remote={version or 'undefined'} result={ret} expected=0")
        if ret != 0:
            raise RuntimeError("RX ownership contract regression")


if __name__ == "__main__":
    main()
