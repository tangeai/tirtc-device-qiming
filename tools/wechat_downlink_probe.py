"""Observe the existing AT console without resetting or changing Wi-Fi.

Calling is opt-in. A call started here is hung up in finally; an existing call
is never adopted or stopped. Raw serial evidence is retained in a unique file.
"""

import argparse
import datetime
import time
from pathlib import Path

from c61_udp_regression import Console, c61_command, fields


def query(console, command, prefix):
    # Query replies are multi-line and terminate in OK. Do not pipeline the next
    # request after just MEDIA_DOWN while the previous VRX/OK is still pending.
    print(datetime.datetime.now().isoformat(timespec="milliseconds") + " QUERY " + command,
          flush=True)
    result = console.query(command, prefix, terminal_ok=command.endswith("?"))
    print(result, flush=True)
    return result


def snapshot(console, coprocessor, errors=None, full=True):
    commands = [("AT+WX?", "+WX:")]
    if full:
        commands.append(("AT+WIFILINK?", "+WIFILINK:"))
    if full and coprocessor == "c61":
        commands += [("AT+C61=HEAP", "+C61HEAP:"), ("AT+C61=TXSTATS", "+C61TX:")]
    commands += [
        ("AT+MEM?", "+MEM:"),
        ("AT+MEDIA?", "+MEDIA_DOWN:"),
    ]
    for command, prefix in commands:
        try:
            query(console, command, prefix)
        except TimeoutError as error:
            if errors is None:
                raise
            # A missed diagnostic reply must not itself hang up a healthy call.
            # Keep the observation running, but fail the test after cleanup.
            errors.append(str(error))
            print("OBSERVATION_ERROR: " + str(error), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM7")
    parser.add_argument("--coprocessor", choices=("c61", "c6"), default="c61")
    parser.add_argument("--seconds", type=int, default=0)
    parser.add_argument("--call", action="store_true")
    parser.add_argument("--console-check", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 0 or (args.call and args.seconds < 30):
        parser.error("call observation must last at least 30 seconds")
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = args.out / ("wechat-" + args.port + "-" + stamp + ".log")
    console = Console(args.port, path)
    started_call = False
    entered_app = False
    observation_errors = []
    try:
        if args.console_check:
            for _ in range(20):
                query(console, "AT+MEDIA?", "+MEDIA_DOWN:")
                query(console, "AT+MEM?", "+MEM:")
            return
        snapshot(console, args.coprocessor, observation_errors)
        if args.call:
            status = fields(query(console, "AT+WX?", "+WX:"))
            if status.get("state") != "0":
                raise RuntimeError("Refusing to interrupt an existing WeChat call")
            if args.coprocessor == "c61":
                c61_command(console, "PROMISC=0")
                c61_command(console, "SINK=0")
            result = query(console, "AT+APP=WECHAT", "+APP:")
            if fields(result).get("ret") != "ESP_OK":
                raise RuntimeError(result)
            entered_app = True
            deadline = time.monotonic() + 20
            while True:
                status = fields(query(console, "AT+WX?", "+WX:"))
                if status.get("ready") == "1" and int(status.get("contacts", "0")) > 0:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("WeChat contacts/resources are not ready")
                time.sleep(1)
            result = query(console, "AT+WXCALL=FIRST", "+WXCALL:")
            if fields(result).get("ret") != "ESP_OK":
                raise RuntimeError(result)
            started_call = True
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            time.sleep(min(10, max(0, deadline - time.monotonic())))
            # Keep active-call sampling on the P4. Repeated Wi-Fi/C61 RPC
            # queries perturb the same Hosted control channel under test.
            snapshot(console, args.coprocessor, observation_errors, full=False)
    finally:
        try:
            if started_call:
                query(console, "AT+WXHANGUP", "+WXHANGUP:")
            if entered_app:
                query(console, "AT+APP=HOME", "+APP:")
                time.sleep(3)
                snapshot(console, args.coprocessor, observation_errors)
        finally:
            console.close()
            print("Evidence: " + str(path.resolve()), flush=True)
    if observation_errors:
        raise RuntimeError("Incomplete diagnostic observations: " + repr(observation_errors))


if __name__ == "__main__":
    main()
