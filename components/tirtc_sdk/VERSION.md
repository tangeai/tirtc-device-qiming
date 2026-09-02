# TiRTC SDK Version

| Item | Value |
| --- | --- |
| Package channel | ESP32-P4 release candidate |
| TiRTC version | 2.3.0 |
| Target | ESP32-P4 / FreeRTOS / ESP-IDF |
| ESP-IDF | 5.5.4 |
| Toolchain | riscv32-esp-elf-gcc-14.2.0_20260121 |
| Nano commit | 13e34c3e3e3dc6776be4713b5c1e3c17bd282766 |
| TGWebRTC baseline | e39114731ad488c88573d16f0855a1326d97c989 |
| TGWebRTC closure | 24ccd07e124ef0503dd5ed2d79a1bbf5e46e780a |
| TGTRP interface | v1.5.10 |
| Transport | service-negotiated TGTRP or KCP / noSCTP / noDTLS |
| Build date | 2026-09-02 |

## Build Contract

- `CONFIG_FREERTOS_HZ=1000`
- FreeRTOS trace facility, stats formatting and runtime stats disabled
- `CONFIG_LWIP_MAX_SOCKETS=10`
- lower layer built with `ARCH=esp32p4 RELEASE=y nosctp=y nodtls=y`
- Nano built with `ARCH=esp32p4 RELEASE=y p2p=kcp`
- `libwebrtc_nosctp.a` is bundled into `libTiRTC.a`
- active-connect setup failures reclaim the SDK-owned connection before
  reporting `error + NULL hconn`
- P4 connection RTC thread stack is 12288 bytes; signal thread remains 8192
  bytes
- TURN lookup uses lightweight address keys instead of placing a complete
  allocation object on the RTC thread stack
- TGTRP NACK batch scratch storage is allocated once per object and the real
  packet capacity is passed to the encoder
- temporary `MRX/TRX/TTX/JTL/KG/KR/IRX/NET`, socket, ICE and TGTRP poll
  diagnostics are not present in this archive

## Integration Contract

- Set `TIRTC_OPT_DEVICE_SECRET_KEY` and a stable physical
  `TIRTC_OPT_CLIENT_ID` before `TiRtcStart()`.
- Register `TiRtcConnSetVideoBitrateParams()` only after a connection is
  accepted and handle a non-zero return as an unsupported or rejected update.
- Treat `on_update_bitrate()` as an SDK-thread callback: post the absolute
  target bitrate to an application worker and return immediately.
- Keep `TIRTC_OPT_TGTRP_POLL_TIMEOUT` at its default `1 ms`.
- This package passed clean lower-layer and Nano builds plus archive, object,
  symbol and diagnostic-string audits. Application linking, flashing and
  device runtime remain separate verification gates.

This component contains only the ESP32-P4 archive linked by the application.
