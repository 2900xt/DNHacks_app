# hardware/

Everything physical, plus the machine the physical thing talks to.

| Path | What it is | State |
|---|---|---|
| [`m5stack-node/`](m5stack-node/) | The ESP32 / M5Stack depot node — BME680 + DHT11 + MQ-2, posts `Telemetry` | Compiles both envs. **Never flashed.** |
| [`laptop-server/`](laptop-server/) | Runs the API off a laptop, reachable by the node | **Use this now.** |
| [`pi-server/`](pi-server/) | Runs the API off a Raspberry Pi acting as its own AP | Planned. No Pi exists yet. |

## The boundary that matters

**The two `*-server/` directories contain no server.** The server is
[`../services/api/`](../services/api/) — one codebase, one contract, one place
where policy lives. What lives here is the *host*: how that codebase gets onto a
machine, which address it listens on, and how the node finds it.

If you ever find yourself writing depot logic under `hardware/`, stop. It belongs
in `services/api/depot.py`, where it can be changed without a reflash.

## The one line that joins them

```c
// hardware/m5stack-node/include/config.h
#define API_BASE  "http://192.168.4.1:8000"
```

That address is the *only* coupling between the node and its host. Moving the
API from a laptop to a Pi is a one-line edit and a reflash — which is exactly why
`laptop-server/` is not a throwaway and `pi-server/` is not a rewrite.

- On the laptop: whatever `laptop-server/up.sh` prints (a LAN IP, or `192.168.4.1`
  if you brought up the hotspot).
- On the Pi: `192.168.4.1`, pinned deliberately in `pi-server/setup.sh` so the
  firmware constant stays true across the swap.

## Which one am I running?

Right now, the laptop. The Pi is the venue-day insurance policy: it removes the
last dependency on wifi you do not control. Neither is needed for
`make depot-demo`, which replays 24h of history with no radio at all — see
[`m5stack-node/README.md`](m5stack-node/README.md).
