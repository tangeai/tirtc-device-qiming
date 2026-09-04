"""Serve one verified C61 image and install it through the existing P4 CPOTA command."""

import argparse
import hashlib
import http.server
import json
import threading
import time
from pathlib import Path

from c61_udp_regression import Console, fields, media_is_idle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--elf-sha256", required=True,
                        help="Expected C61 runtime ELF hash from this build")
    parser.add_argument("--bind-ip", required=True)
    parser.add_argument("--port", default="COM7")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    firmware = args.firmware.read_bytes()
    actual = hashlib.sha256(firmware).hexdigest()
    if actual.lower() != args.sha256.lower():
        raise ValueError("Firmware SHA-256 mismatch")
    if len(args.elf_sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in args.elf_sha256):
        raise ValueError("ELF SHA-256 must be 64 hexadecimal characters")
    args.output.mkdir(parents=True, exist_ok=False)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/c61-probe.bin":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(firmware)))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(firmware)

        def log_message(self, fmt, *values):
            print("HTTP " + fmt % values, flush=True)

    server = http.server.ThreadingHTTPServer((args.bind_ip, 8768), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    console = None
    result = {"firmware": str(args.firmware.resolve()), "sha256": actual,
              "expected_elf_sha256": args.elf_sha256.lower(),
              "bytes": len(firmware), "activated": False, "verified": False}
    try:
        console = Console(args.port, args.output / "serial.log")
        media = console.query("AT+MEDIA?", "+MEDIA:")
        media_down = console.query("AT+MEDIA?", "+MEDIA_DOWN:")
        print(media, flush=True)
        print(media_down, flush=True)
        if not media_is_idle(media, media_down):
            raise RuntimeError("Stop media before installing a coprocessor image")
        response = console.query(f"AT+CPOTA=http://{args.bind_ip}:8768/c61-probe.bin",
                                 "+CPOTA:", terminal_ok=False)
        print(response, flush=True)
        if "ret=ESP_OK" not in response:
            raise RuntimeError(response)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            with console.lock:
                lines = list(console.lines)
            failures = [line for line in lines if "C61 OTA failed:" in line or
                        "C61 OTA activate failed:" in line]
            if failures:
                raise RuntimeError(failures[-1])
            if any("C61 OTA activated" in line for line in lines):
                result["activated"] = True
                break
            time.sleep(0.1)
        if not result["activated"]:
            raise TimeoutError("C61 OTA activation was not observed; do not claim success")
        time.sleep(20)
        with console.lock:
            panics = [line for line in console.lines if "assert failed:" in line or
                      "Guru Meditation Error:" in line]
        if panics:
            raise RuntimeError("P4 failed during restart: " + panics[-1])
        console.close()
        console = None
        console = Console(args.port, args.output / "verify.log")
        result["hosted"] = console.query("AT+HOSTED?", "+HOSTED:", timeout=30)
        result["info"] = console.query("AT+C61=INFO", "+C61I:", timeout=30, terminal_ok=False)
        if fields(result["info"]).get("elf", "").lower() != args.elf_sha256.lower():
            raise RuntimeError("Activated C61 ELF does not match the declared build")
        result["verified"] = True
        print(json.dumps(result, indent=2), flush=True)
    except Exception as exc:
        result["error"] = repr(exc)
        raise
    finally:
        if console:
            console.close()
        server.shutdown()
        server.server_close()
        server_thread.join()
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
