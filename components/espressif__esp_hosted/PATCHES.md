# Local ESP-Hosted Contract

- Upstream package: `espressif/esp_hosted 2.12.12`
- Upstream commit: `098525357e19c81099f2c3769938bd877190a8f5`
- Target: ESP32-P4 host with ESP32-C61 over SDIO
- Upstream `sdio_drv.c` SHA-256: `e45c99b5a1c8735eaaab635ab404ee6e34ae98c7f5b92de3db134c95b37ab86d`

Only `host/drivers/transport/sdio/sdio_drv.c` changes runtime behavior. The
local implementation keeps the 2.12.12 bus-fault and pending-read semantics,
then adds the board-proven host-side policies below:

- preallocate two cache-aligned PSRAM DMA streaming buffers;
- use explicit free/ready ownership queues so a completed RX batch cannot be
  overwritten while the splitter is still consuming it;
- preserve pending slave data and retry transient RX allocation failures;
- keep the SDIO bus lock out of RX-buffer backpressure waits;
- retain persistent mempool backing across transport restarts;
- use PSRAM for copied streaming packets and hand zero-copy buffers to the
  Wi-Fi remote receive path;
- validate register snapshots before clearing interrupts and rate-limit
  memory, queue and backpressure diagnostics.

The vendored tree intentionally contains only the host runtime, generated RPC
sources, required headers and licenses. Upstream examples, coprocessor source,
CI files and documentation are excluded from the application repository.
