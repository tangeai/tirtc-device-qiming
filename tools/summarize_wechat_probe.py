"""Summarize captured AT evidence; never infer network loss from video FPS.

FPS uses host timestamps over consecutive active snapshots, not call setup or
teardown time. Gap counters come from the firmware's monotonic clock. 'show'
is renderer handoff, not physical LCD completion. Missing evidence stays null.
"""

import argparse
import datetime
import json
import re
from pathlib import Path

from c61_udp_regression import fields


def pair(value):
    return [int(part) for part in value.split("/")]


def summarize(lines):
    periods = []
    active = None
    counters = {"C61HEAP": [], "C61TX": [], "MEM": []}
    events = {"transport_stalls": 0, "geometry_changes": 0,
              "awb_warnings": 0, "panic": 0}
    first_packet_wait = []
    for raw in lines:
        stamp, _, text = raw.strip().partition(" ")
        try:
            seconds = datetime.datetime.fromisoformat(stamp).timestamp()
        except ValueError:
            continue
        events["transport_stalls"] += "VRX stall stage=transport" in text
        events["geometry_changes"] += "MJPEG downlink geometry changed" in text
        events["awb_warnings"] += "AWB" in text and "W (" in text
        events["panic"] += bool(re.search(r"Guru Meditation|assert failed|Stack protection fault", text))
        if "remote video first packet media=" in text:
            match = re.search(r"accepted_ms=(\d+)", text)
            if match:
                first_packet_wait.append(int(match[1]))
        if text.startswith("+MEDIA_DOWN:"):
            data = fields(text)
            if data["run"] != "1":
                active = None
                continue
            if active is None or int(data["rx"]) < int(active["samples"][-1]["rx"]):
                active = {"samples": [], "vrx": []}
                periods.append(active)
            active["samples"].append({"seconds": seconds, **data})
        elif text.startswith("+VRX:") and active is not None:
            # A MEDIA reply is a transaction; do not attach unrelated old VRX.
            if 0 <= seconds - active["samples"][-1]["seconds"] <= 1:
                active["vrx"].append(fields(text))
        for name in counters:
            if text.startswith("+" + name + ":"):
                counters[name].append(fields(text))

    results = []
    for period in periods:
        samples = period["samples"]
        positive = [s for s in samples if int(s["rx"]) > 0]
        first, last = (positive[0], positive[-1]) if positive else (None, None)
        span = last["seconds"] - first["seconds"] if first else 0
        item = {"active_snapshots": len(samples), "observed_media_seconds": round(span, 3),
                "rx_fps": None, "handoff_fps": None,
                "latest": {k: v for k, v in samples[-1].items() if k != "seconds"},
                "vrx": period["vrx"][-1] if period["vrx"] else None}
        if span > 0:
            item["rx_fps"] = round((int(last["rx"]) - int(first["rx"])) / span, 3)
            item["handoff_fps"] = round((int(last["show"]) - int(first["show"])) / span, 3)
        item["max_observed_queue"] = [max(pair(s["q"])[i] for s in samples) for i in range(2)]
        results.append(item)
    ends = {}
    for name, values in counters.items():
        ends[name] = {"samples": len(values), "first": values[0] if values else None,
                      "last": values[-1] if values else None,
                      "failure_delta": int(values[-1]["fail"]) - int(values[0]["fail"])
                      if len(values) > 1 else None}
    return {"periods": results, "counters": ends, "events": events,
            "first_video_after_accept_ms": first_packet_wait,
            "limits": "Snapshots do not prove physical display quality, loss location or a full pass."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.logs:
        with path.open(encoding="utf-8") as handle:
            result = summarize(handle)
        print(json.dumps({"log": str(path.resolve()), **result}, ensure_ascii=True))


if __name__ == "__main__":
    main()
