"""Install a WT99P461-S1 1V1 C61 OTA APP through the P4 UART0 console."""

import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
import re
import struct
from threading import Thread
import time


APP_LIMIT = 0x180000
PROJECT = b"xiaotai_wt99p461_c61"
LAN_NETWORKS = tuple(map(IPv4Network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))


def lan_ip(value):
    address = IPv4Address(value)
    if not any(address in network for network in LAN_NETWORKS):
        raise argparse.ArgumentTypeError("use a private IPv4 address")
    return str(address)


def check_image(data, expected_sha256):
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("OTA APP SHA-256 mismatch")
    if not 288 <= len(data) <= APP_LIMIT or data[0] != 0xE9:
        raise ValueError("expected a C61 OTA APP, not a full flash image")
    chip = struct.unpack_from("<H", data, 12)[0]
    min_rev, max_rev = struct.unpack_from("<HH", data, 15)
    magic = struct.unpack_from("<I", data, 32)[0]
    project = data[80:112].split(b"\0", 1)[0]
    if chip != 20 or not min_rev <= 100 <= max_rev or magic != 0xABCD5432 or project != PROJECT:
        raise ValueError("image is not for the WT99P461-S1 C61 rev1.0")
    elf = data[176:208]
    if not any(elf):
        raise ValueError("missing application ELF identity")
    return digest, elf.hex()


@contextmanager
def serve_app(data, bind_ip, device_ip, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.client_address[0] != device_ip or self.path != "/c61-ota.bin":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer((bind_ip, port), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://{bind_ip}:{server.server_port}/c61-ota.bin"
        finally:
            server.shutdown()
            thread.join()


class Console:
    def __init__(self, port):
        self.port = port
        self.pending = bytearray()

    def send(self, command):
        self.port.write((command + "\r\n").encode("ascii"))
        self.port.flush()

    def wait_for(self, predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if b"\n" not in self.pending:
                self.pending.extend(self.port.read(min(self.port.in_waiting or 1, 4096)))
                if len(self.pending) > 8192 and b"\n" not in self.pending:
                    self.pending.clear()
            while b"\n" in self.pending:
                raw, _, rest = self.pending.partition(b"\n")
                self.pending = rest
                line = raw.decode("utf-8", errors="replace").strip()
                if predicate(line):
                    return line
        return ""


def run_update(console, url, digest, elf, activation_timeout=600, boot_timeout=150):
    status = {}

    def idle_snapshot(line):
        if line.startswith("+STATUS:"):
            status["idle"] = (
                "wifi=1," in line and ",connected=0,state=waiting," in line
            )
        elif line.startswith("+MEDIA:"):
            status["media_idle"] = line.startswith("+MEDIA:active=0,")
        return len(status) == 2

    console.send("AT+STATUS?")
    if not console.wait_for(idle_snapshot, 6) or not all(status.values()):
        raise RuntimeError("P4 must be online and idle on its UART0 console")
    console.send(f"AT+CPOTA={url},{digest}")
    activation = console.wait_for(
        lambda line: any(marker in line for marker in
                         ("C61 OTA activated", "C61 OTA failed:", "ERROR,CPOTA")),
        activation_timeout,
    )
    if "C61 OTA activated" not in activation:
        raise RuntimeError("C61 OTA activation was not confirmed; check UART0 before retrying")
    deadline = time.monotonic() + boot_timeout
    if not console.wait_for(
        lambda line: "C61 SPI / Hosted 3.0.7; read-only check passed" in line, boot_timeout
    ):
        raise RuntimeError("OTA activated, but the C61 restart was not confirmed")
    while time.monotonic() < deadline:
        console.send("AT+STATUS?")
        if console.wait_for(
            lambda line: line.startswith("+STATUS:wifi=1,"),
            min(5, max(0, deadline - time.monotonic())),
        ):
            break
    else:
        raise RuntimeError("OTA activated, but P4 Wi-Fi recovery was not verified")
    console.send("AT+C61=INFO")
    identity = console.wait_for(lambda line: line.startswith("+C61:elf="), 12)
    if not identity.startswith(f"+C61:elf={elf},"):
        raise RuntimeError("OTA activated, but the expected C61 application is not running")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument("--sha256", required=True, help="OTA APP digest from the Release page")
    parser.add_argument("--serial", required=True, help="P4 UART0, not the C61 port")
    parser.add_argument("--bind-ip", required=True, type=lan_ip, help="computer's LAN IPv4 address")
    parser.add_argument("--device-ip", required=True, type=lan_ip, help="P4 LAN IPv4 address")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9A-Fa-f]{64}", args.sha256):
        parser.error("--sha256 must be 64 hexadecimal characters")
    if args.bind_ip == args.device_ip:
        parser.error("computer and P4 must use different addresses")
    try:
        import serial
    except ImportError:
        parser.exit(2, "Install pyserial before running this tool.\n")
    try:
        if not 288 <= args.firmware.stat().st_size <= APP_LIMIT:
            raise ValueError("expected a C61 OTA APP, not a full flash image")
        data = args.firmware.read_bytes()
        digest, elf = check_image(data, args.sha256)
        with serve_app(data, args.bind_ip, args.device_ip, 8768) as url:
            port = serial.Serial(baudrate=115200, timeout=0.2, write_timeout=2)
            port.port = args.serial
            port.dtr = port.rts = False
            port.open()
            try:
                run_update(Console(port), url, digest, elf)
            finally:
                port.close()
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
    print("C61 OTA complete: running application and Wi-Fi verified.")


if __name__ == "__main__":
    main()
