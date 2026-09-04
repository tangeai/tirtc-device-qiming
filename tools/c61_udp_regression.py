"""Measure sequenced UDP loss without the media SDK or a cloud server.

Requires the existing AT+UDPRX commands. Opening the serial port does not
toggle reset. All profiles share one boot and Wi-Fi association.
"""

import argparse
import datetime
import json
import select
import socket
import struct
import threading
import time
from pathlib import Path

import serial


MAGIC = 0x43363144
PACKET_BYTES = 1200
FPS = 15
PROFILES = {
    "smooth-1m73": (12, True),
    "burst-1m73": (12, False),
    "smooth-4m90": (34, True),
    "burst-4m90": (34, False),
    "burst-7m20": (50, False),
}


def fields(line):
    return dict(item.split("=", 1) for item in line.split(":", 1)[1].split(",")
                if "=" in item)


def extract_prefixed_line(line, prefix):
    """Recover an AT response even when an asynchronous log shares its line."""
    offset = line.find(prefix)
    return line[offset:] if offset >= 0 else None


def media_is_idle(media_line, media_down_line):
    """Return whether media hardware and the downlink renderer are inactive.

    The configured local-video preference may remain enabled between calls, so
    the `send` field is not a runtime ownership signal.
    """
    media = fields(media_line)
    media_down = fields(media_down_line)
    return (media.get("call") == "0" and media.get("camera") == "0" and
            media_down.get("run") == "0")


def c61_command(console, command):
    reply = console.query(f"AT+C61={command}", f"+C61:cmd={command},", terminal_ok=False)
    if fields(reply).get("ret") != "0":
        raise RuntimeError(reply)
    return reply


def missing_count(sent, receiver):
    unique = int(receiver["unique"])
    if not 0 <= unique <= sent:
        raise ValueError("Receiver unique count is outside the sent range")
    if int(receiver["overflow"]) != 0:
        raise ValueError("Sequence bitmap overflow invalidates loss measurement")
    return sent - unique


def echo_unrecovered(receiver):
    """Return final echo failures while accepting older firmware output."""
    return int(receiver.get("echo_unrecovered", receiver.get("echo_fail", "0")))


def profile_failures(result):
    failures = []
    if not result["zero_loss"]:
        failures.append("packet_loss")
    receiver = result["receiver"]
    for key in ("invalid", "overflow", "rxerr", "longgap"):
        if int(receiver[key]):
            failures.append("p4_" + key)
    c61 = result.get("c61")
    if c61:
        if int(c61["overflow"]):
            failures.append("c61_sequence_outside_window")
        if int(c61["maxgap_us"]) >= 250000:
            failures.append("c61_longgap")
        if result["measurement_endpoint"] == "P4" and c61["unique"] != receiver["unique"]:
            failures.append("c61_p4_count_mismatch")
    for prefix in ("c61_heap", "c61_tx"):
        before, after = result.get(prefix + "_before"), result.get(prefix + "_after")
        if before and after and int(after["fail"]) != int(before["fail"]):
            failures.append(prefix + "_failure_delta")
    hosted_before = result.get("hosted_before")
    hosted_after = result.get("hosted_after")
    if (hosted_before and hosted_after and "af" in hosted_before and
            int(hosted_after["af"]) != int(hosted_before["af"])):
        failures.append("p4_heap_failure_delta")
    return failures


class Console:
    def __init__(self, port, path):
        self.device = serial.Serial()
        self.device.port = port
        self.device.baudrate = 115200
        self.device.timeout = 0.05
        self.device.write_timeout = 2
        self.device.dtr = False
        self.device.rts = False
        self.device.open()
        self.log = path.open("x", encoding="utf-8")
        self.lines = []
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        pending = bytearray()
        try:
            while not self.stopping.is_set():
                pending.extend(self.device.read(4096))
                while b"\n" in pending:
                    raw, _, pending = pending.partition(b"\n")
                    line = raw.decode("utf-8", errors="replace").strip()
                    stamp = datetime.datetime.now().isoformat(timespec="milliseconds")
                    self.log.write(f"{stamp} {line}\n")
                    self.log.flush()
                    with self.lock:
                        self.lines.append(line)
        except Exception as exc:
            with self.lock:
                self.lines.append(f"CONSOLE_ERROR:{exc}")

    def query(self, command, prefix, timeout=10, terminal_ok=True):
        with self.lock:
            cursor = len(self.lines)
        self.device.write((command + "\r\n").encode("ascii"))
        self.device.flush()
        deadline = time.monotonic() + timeout
        response = None
        while time.monotonic() < deadline:
            with self.lock:
                new = self.lines[cursor:]
                cursor = len(self.lines)
            for line in new:
                if line.startswith("CONSOLE_ERROR:"):
                    raise RuntimeError(line)
                matched = extract_prefixed_line(line, prefix)
                if matched:
                    response = matched
                    if not terminal_ok:
                        # Coprocessor replies are asynchronous and have no
                        # trailing OK. Let the AT worker finish before the next
                        # command so it is not silently dropped.
                        time.sleep(0.05)
                        return response
                if line == "OK" and response:
                    return response
            time.sleep(0.01)
        raise TimeoutError(f"No complete response to {command}: {response}")

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=2)
        self.device.close()
        self.log.close()


def wait_until(deadline):
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        time.sleep(max(remaining - 0.0002, 0))


def warm_echo_path(ip, bind_ip):
    """Resolve the L2 path before measured traffic without hiding its failure."""
    payload = bytes(PACKET_BYTES - 12)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((bind_ip, 0))
        sock.settimeout(0.2)
        for attempt in range(1, 21):
            packet = struct.pack("!III", MAGIC, attempt - 1, 0) + payload
            started = time.perf_counter()
            sock.sendto(packet, (ip, 5005))
            try:
                echoed, peer = sock.recvfrom(2048)
            except socket.timeout:
                continue
            if peer == (ip, 5005) and echoed == packet:
                return {"attempts": attempt,
                        "rtt_ms": round((time.perf_counter() - started) * 1000, 3)}
        raise RuntimeError("ARP/data-path warm-up did not receive an echo")


def send(ip, bind_ip, count_per_frame, smooth, seconds, echo=False):
    payload = bytes((i * 17 + 31) & 255 for i in range(PACKET_BYTES - 12))
    sent = 0
    max_late_ms = 0
    echoed = set()
    rtt_ms = []
    receive_errors = []
    send_times = [None] * (FPS * seconds * count_per_frame) if echo else []
    stop = threading.Event()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((bind_ip, 0))
        sock.settimeout(2)
        if echo:
            # Keep the PC collector from dropping a complete video-sized burst.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        receive_buffer = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        endpoint = sock.getsockname()

        def receive():
            try:
                while not stop.is_set():
                    if not select.select([sock], [], [], 0.1)[0]:
                        continue
                    try:
                        packet, peer = sock.recvfrom(2048)
                    except socket.timeout:
                        continue
                    now = time.perf_counter()
                    if peer != (ip, 5005) or len(packet) != PACKET_BYTES:
                        raise RuntimeError("Unexpected echo source or length")
                    magic, sequence, _ = struct.unpack_from("!III", packet)
                    if magic != MAGIC or sequence >= len(send_times) or send_times[sequence] is None:
                        raise RuntimeError("Unexpected echo sequence")
                    if sequence not in echoed:
                        echoed.add(sequence)
                        rtt_ms.append((now - send_times[sequence]) * 1000)
            except Exception as exc:
                receive_errors.append(repr(exc))

        thread = threading.Thread(target=receive, daemon=True) if echo else None
        if thread:
            thread.start()
        start = time.perf_counter()
        try:
            for frame in range(FPS * seconds):
                for part in range(count_per_frame):
                    deadline = start + ((sent / count_per_frame) if smooth else frame) / FPS
                    if smooth or part == 0:
                        wait_until(deadline)
                        max_late_ms = max(max_late_ms, (time.perf_counter() - deadline) * 1000)
                    packet = struct.pack("!III", MAGIC, sent, frame) + payload
                    if echo:
                        send_times[sent] = time.perf_counter()
                    if sock.sendto(packet, (ip, 5005)) != len(packet):
                        raise RuntimeError("Partial UDP send")
                    sent += 1
            elapsed = time.perf_counter() - start
            if echo:
                time.sleep(2)
        finally:
            stop.set()
            if thread:
                thread.join(timeout=3)
                if thread.is_alive():
                    raise RuntimeError("Echo receiver did not stop")
    if receive_errors:
        raise RuntimeError(receive_errors)
    result = {"sent": sent, "bytes": sent * PACKET_BYTES, "seconds": elapsed,
              "source": endpoint, "max_schedule_late_ms": round(max_late_ms, 3),
              "pc_receive_buffer": receive_buffer}
    if echo:
        rtt_ms.sort()
        result["echo"] = {"unique": len(echoed), "roundtrip_missing": sent - len(echoed),
                          "rtt_p95_ms": round(rtt_ms[int((len(rtt_ms) - 1) * .95)], 3) if rtt_ms else None,
                          "rtt_max_ms": round(max(rtt_ms), 3) if rtt_ms else None}
    return result


def run_profile(console, ip, args, name, repeat):
    count, smooth = PROFILES[name]
    started = False
    try:
        if args.c61_mode:
            c61_command(console, f"SINK={int(args.c61_mode == 'sink')}")
            c61_command(console, "RESET")
        mode = "ECHO" if args.echo else "START"
        response = console.query(f"AT+UDPRX={mode}", f"+UDPRX:action={mode}", terminal_ok=False)
        if "ret=ESP_OK" not in response:
            raise RuntimeError(response)
        started = True
        time.sleep(0.5)
        initial = fields(console.query("AT+UDPRX?", "+UDPRX:run="))
        if initial.get("run") != "1" or initial.get("unique") != "0":
            raise RuntimeError(f"Receiver not ready or stale traffic: {initial}")
        arp_warmup = None
        if args.echo and not args.skip_arp_warmup:
            arp_warmup = warm_echo_path(ip, args.bind_ip)
            response = console.query("AT+UDPRX=STOP", "+UDPRX:action=STOP")
            if "ret=ESP_OK" not in response:
                raise RuntimeError(f"Warm-up receiver cleanup failed: {response}")
            started = False
            response = console.query("AT+UDPRX=ECHO", "+UDPRX:action=ECHO", terminal_ok=False)
            if "ret=ESP_OK" not in response:
                raise RuntimeError(response)
            started = True
            time.sleep(0.2)
            initial = fields(console.query("AT+UDPRX?", "+UDPRX:run="))
            if initial.get("run") != "1" or initial.get("unique") != "0":
                raise RuntimeError(f"Receiver did not reset after warm-up: {initial}")
            if args.c61_mode:
                c61_command(console, "RESET")
        before = console.query("AT+HOSTED?", "+HOSTED:")
        heap_before = (fields(console.query("AT+C61=HEAP", "+C61HEAP:", terminal_ok=False))
                       if args.c61_heap else None)
        tx_before = (fields(console.query("AT+C61=TXSTATS", "+C61TX:", terminal_ok=False))
                     if args.c61_tx else None)
        sender = send(ip, args.bind_ip, count, smooth, args.seconds, args.echo)
        time.sleep(2)
        received = fields(console.query("AT+UDPRX?", "+UDPRX:run="))
        after = console.query("AT+HOSTED?", "+HOSTED:")
        c61 = (fields(console.query("AT+C61=STATS", "+C61RX:", terminal_ok=False))
               if args.c61_mode else None)
        heap_after = (fields(console.query("AT+C61=HEAP", "+C61HEAP:", terminal_ok=False))
                      if args.c61_heap else None)
        tx_after = (fields(console.query("AT+C61=TXSTATS", "+C61TX:", terminal_ok=False))
                    if args.c61_tx else None)
        measured = c61 if args.c61_mode == "sink" else received
        missing = missing_count(sender["sent"], measured)
        if c61:
            missing_count(sender["sent"], c61)
        if args.c61_mode == "sink" and (
                c61["sink"] != "1" or c61["consumed"] != c61["packets"] or
                int(received["packets"]) != 0):
            raise RuntimeError("C61 sink isolation did not hold for the whole test")
        if args.c61_mode == "forward" and int(c61["consumed"]) != 0:
            raise RuntimeError("Unexpected C61 sink consumption during forwarding test")
        result = {"profile": name, "repeat": repeat,
                  "target_mbps": count * FPS * PACKET_BYTES * 8 / 1e6,
                  "sender": sender, "receiver": received,
                  "c61_heap_before": heap_before, "c61_heap_after": heap_after,
                  "c61_tx_before": tx_before, "c61_tx_after": tx_after,
                  "c61": c61, "measurement_endpoint": "C61" if args.c61_mode == "sink" else "P4",
                  "missing": missing, "loss_percent": round(missing * 100 / sender["sent"], 4),
                  "hosted_before": fields(before), "hosted_after": fields(after),
                  "hosted_before_raw": before, "hosted_after_raw": after,
                  "arp_warmup": arp_warmup,
                  "zero_loss": missing == 0 and (not args.echo or
                     (sender["echo"]["roundtrip_missing"] == 0 and
                      echo_unrecovered(received) == 0))}
        if args.echo:
            if received.get("echo") != "1":
                raise RuntimeError("Echo mode was not active")
            result["echo_upstream_missing"] = int(received["echo_sent"]) - sender["echo"]["unique"]
        result["failures"] = profile_failures(result)
        result["passed"] = not result["failures"]
        print(json.dumps(result, ensure_ascii=True), flush=True)
        return result
    finally:
        try:
            if started:
                response = console.query("AT+UDPRX=STOP", "+UDPRX:action=STOP")
                if "ret=ESP_OK" not in response:
                    raise RuntimeError(f"Receiver cleanup failed: {response}")
        finally:
            if args.c61_mode:
                c61_command(console, "SINK=0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--bind-ip", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--c61-mode", choices=["forward", "sink"],
                        help="Requires the isolated C61 probe firmware; sink bypasses SDIO/P4")
    parser.add_argument("--c61-heap", action="store_true",
                        help="Record the probe firmware's allocation-failure counters")
    parser.add_argument("--c61-tx", action="store_true",
                        help="Record the probe firmware's Hosted-to-Wi-Fi counters")
    parser.add_argument("--echo", action="store_true", help="Exercise both directions via P4 UDP echo")
    parser.add_argument("--skip-arp-warmup", action="store_true",
                        help="Include cold ARP resolution in the measured echo profile")
    parser.add_argument("--profiles", nargs="+", choices=PROFILES,
                        default=["smooth-1m73", "burst-1m73", "burst-4m90", "burst-7m20"])
    args = parser.parse_args()
    if args.echo and args.c61_mode == "sink":
        parser.error("Echo requires forwarding to P4, not the C61 sink")
    if not 1 <= args.seconds <= 300 or not 1 <= args.repeat <= 20:
        parser.error("seconds must be 1..300; repeat must be 1..20")
    if args.c61_mode and args.seconds > 60:
        parser.error("C61 probe profiles are limited to 60s / 65536 sequences")
    args.output.mkdir(parents=True, exist_ok=False)
    results = {"started": datetime.datetime.now().isoformat(), "port": args.port,
               "bind_ip": args.bind_ip, "packet_bytes": PACKET_BYTES, "fps": FPS,
               "scope": "PC UDP send -> AP -> C61 -> Hosted/SDIO -> P4 socket; no media SDK",
               "profiles": []}
    console = Console(args.port, args.output / "serial.log")
    try:
        results["hosted"] = console.query("AT+HOSTED?", "+HOSTED:")
        initial = fields(console.query("AT+UDPRX?", "+UDPRX:run="))
        if initial.get("run") != "0":
            raise RuntimeError("Another UDP test is active")
        ip = initial["ip"]
        if ip in ("-", "0.0.0.0"):
            raise RuntimeError("Device has no Wi-Fi address")
        results["ip"] = ip
        if args.c61_mode:
            # Promiscuous capture is a separate diagnostic load. Keep it out of
            # the data-path regression so packet counts describe forwarding,
            # not a second Wi-Fi RX consumer left enabled by an earlier probe.
            c61_command(console, "PROMISC=0")
            results["c61_info"] = console.query("AT+C61=INFO", "+C61I:", terminal_ok=False)
            results["wifi_link"] = console.query("AT+WIFILINK?", "+WIFILINK:")
            results["wifi_config"] = console.query("AT+WIFILINK?", "+WIFICFG:")
        results["memory_before"] = console.query("AT+MEM?", "+MEM:")
        results["media"] = console.query("AT+MEDIA?", "+MEDIA:")
        results["media_down"] = console.query("AT+MEDIA?", "+MEDIA_DOWN:")
        if not media_is_idle(results["media"], results["media_down"]):
            raise RuntimeError("Stop active media before independent network testing")
        results["wifi_before"] = console.query("AT+WIFISTATS", "+WIFISTATS:", terminal_ok=False)
        print(json.dumps({k: v for k, v in results.items() if k != "profiles"}), flush=True)
        for repeat in range(1, args.repeat + 1):
            for name in args.profiles:
                results["profiles"].append(run_profile(console, ip, args, name, repeat))
                (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        results["wifi_after"] = console.query("AT+WIFISTATS", "+WIFISTATS:", terminal_ok=False)
        results["memory_after"] = console.query("AT+MEM?", "+MEM:")
        results["all_passed"] = all(profile["passed"] for profile in results["profiles"])
    except Exception as exc:
        results["error"] = repr(exc)
        raise
    finally:
        results["finished"] = datetime.datetime.now().isoformat()
        (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        console.close()
    return 0 if results["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
