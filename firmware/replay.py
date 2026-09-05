#!/usr/bin/env python3
"""
The demo's insurance policy. Two modes, neither needs a working radio:

    ./replay.py synth --scenario excursion     # no hardware at all
    ./replay.py serial --port /dev/ttyUSB0     # real sensor, no wifi

`synth` fabricates a storage history and plays it into the API faster than real
time, so you can rehearse the excursion beat without waiting for a room to warm
up. `serial` is the 20-line bridge from firmware/README.md: the device prints
NDJSON unconditionally, this forwards it.

Scenarios:
  nominal    22 C, flat. The bin is fine. Use it to show a green baseline.
  excursion  drifts above the 25 C ceiling near the end and stays there.
  fault      BME680 and DHT11 diverge past tolerance. Neither a pass nor a
             fail — the bin simply cannot be certified, which is the honest
             answer and the one an auditor actually wants.
  breach     one hot hour in an otherwise clean 24, then a full recovery to
             23 C. The LAST reading is comfortably in band and the arithmetic
             mean is 23.9 C — a naive dashboard shows green — but the time-
             weighted MKT has already crossed 25 C and the stock is condemned.
             This is the one to demo.

`synth` sends real timestamps spanning --span-h hours, played back in seconds.
The API only honours them when DEPOT_TRUST_DEVICE_TS=1; without it every sample
collapses onto receipt time and you get an MKT computed over four seconds, which
is not a storage claim you want to make in front of a judge.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API = "http://localhost:8000"
DEFAULT_NODE = "sns-depot-01-bin-a"


def post(api: str, payload: dict) -> str:
    req = urllib.request.Request(
        f"{api}/telemetry",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read()).get("status", "?")
    except urllib.error.URLError as e:
        return f"ERR {e}"


def temps_for(scenario: str, n: int) -> list[float]:
    if scenario == "nominal":
        return [22.0 + 0.3 * (i % 3) for i in range(n)]

    if scenario == "excursion":
        # Slow HVAC failure over the last fifth of the window, then held.
        out = []
        knee = int(n * 0.8)
        for i in range(n):
            out.append(22.0 if i < knee else min(22.0 + 0.9 * (i - knee), 31.5))
        return out

    if scenario == "breach":
        # One hot hour at 45 C at the 80% mark, then a clean recovery. Ends in
        # band on purpose: the point is that the current reading looks fine.
        out = [23.0] * n
        hot_start = int(n * 0.80)
        hot_len = max(1, int(n * 0.042))          # ~1h of a 24h window
        for i in range(hot_start, min(hot_start + hot_len, n)):
            out[i] = 45.0
        return out

    if scenario == "fault":
        return [22.0] * n

    raise SystemExit(f"unknown scenario: {scenario}")


def cmd_synth(a: argparse.Namespace) -> int:
    temps = temps_for(a.scenario, a.samples)
    span_s = a.span_h * 3600.0
    step = span_s / max(1, len(temps) - 1)
    # End the history at "now" so the bin does not immediately read as stale.
    t0 = time.time() - span_s
    mean = sum(temps) / len(temps)
    print(f"→ {a.scenario}: {len(temps)} samples over {a.span_h}h "
          f"into {a.api} as {a.node}")
    print(f"  arithmetic mean {mean:.2f} C — this is what a naive dashboard shows")
    for i, t in enumerate(temps):
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 + i * step))
        # RH tracks temperature inversely at fixed absolute humidity; close
        # enough to look real, and it makes the beta-lactam humidity ceiling
        # trip on its own during the excursion scenario.
        rh = max(20.0, min(95.0, 55.0 + (t - 22.0) * 1.8))
        status = post(a.api, {
            "device_id": "replay-synth",
            "node_id": a.node,
            "ts": ts,
            "seq": i,
            "readings": {
                "temp_c": round(t, 2),
                "rh_pct": round(rh, 1),
                "pressure_hpa": 1013.2,
                "gas_ohms": 52000,
                # The DHT11 tracks until the last fifth of the `fault` run, then
                # walks off — a slow sensor failure, not a dropout.
                "temp_c_xcheck": round(
                    t + (9.0 if a.scenario == "fault" and i > len(temps) * 0.8 else 0.4),
                    1,
                ),
                "rh_pct_xcheck": round(rh - 2.0, 1),
                "mq2_mv": 410,
            },
        })
        print(f"  [{i:3d}] {t:5.1f} C  {rh:4.0f}% RH  → {status}")
        time.sleep(a.interval)
    return 0


def cmd_serial(a: argparse.Namespace) -> int:
    try:
        import serial  # pyserial
    except ImportError:
        print("pip install pyserial", file=sys.stderr)
        return 1
    with serial.Serial(a.port, a.baud, timeout=2) as ser:
        print(f"→ bridging {a.port} @ {a.baud} to {a.api}")
        while True:
            line = ser.readline().decode(errors="replace").strip()
            if not line or line.startswith("#"):
                if line:
                    print(f"  {line}")
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                print(f"  ! unparseable: {line[:80]}")
                continue
            r = payload.get("readings", {})
            print(f"  {r.get('temp_c')} C  {r.get('rh_pct')}% RH  → {post(a.api, payload)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default=DEFAULT_API)
    p.add_argument("--node", default=DEFAULT_NODE)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synth", help="play a fabricated history — no hardware")
    s.add_argument("--scenario", default="excursion",
                   choices=["nominal", "excursion", "breach", "fault"])
    s.add_argument("--samples", type=int, default=288,
                   help="288 over 24h = one sample every 5 minutes")
    s.add_argument("--span-h", type=float, default=24.0,
                   help="hours of history this represents (NOT playback time)")
    s.add_argument("--interval", type=float, default=0.01,
                   help="playback delay between samples, in seconds")
    s.set_defaults(func=cmd_synth)

    b = sub.add_parser("serial", help="forward NDJSON from a real device")
    b.add_argument("--port", default="/dev/ttyUSB0")
    b.add_argument("--baud", type=int, default=115200)
    b.set_defaults(func=cmd_serial)

    a = p.parse_args()
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
