# hardware/m5stack-node/

Embedded / device-side code. The thing on the table.

**Board:** M5Stack **Core2** (`pio run -e core2`, the default). The same source
builds for a Core Basic with `-e m5stack` and for a bare DevKit with `-e esp32dev`.
**Stack:** PlatformIO + Arduino-ESP32 + M5Unified, chosen for flash speed rather
than elegance.

## What this builds

**depot-node** — a storage-condition monitor for a Strategic API Reserve bin
(EO 14336). It is the only node in CHOKEPOINT whose health is *physical* rather
than geopolitical: every other node fails because of who owns it, this one fails
because a warehouse got hot.

**Sensor roles are not symmetric.** This matters more than the wiring:

| Part | Bus / pin | Role |
|---|---|---|
| **BME680** | I2C `0x77`, Grove **Port A** (Core2 32/33, Core Basic 21/22 — resolved at runtime) | **Authoritative.** ±1 °C, ±3 % RH. Every compliance determination comes from this part. Also gives VOC plate resistance |
| **DHT11** | GPIO **27** (Core2) / **26** (Core Basic, where 27 is TFT_DC) | **Cross-check only.** ±2 °C is 40 % of a 20–25 °C band — it cannot certify anything alone. Its job is to *disagree*: two independent sensors diverging is how a failed part announces itself |
| **MQ-2** | GPIO **35** (ADC1_CH7), analog | Trend only. Uncalibrated, no burn-in. Warehouse-smoke signal, never a storage criterion |

Sensor disagreement past `DEPOT_XCHECK_TOLERANCE_C` (default 3.0 °C = 2 + 1 worst
case) raises `sensor_fault` — neither a pass nor a fail. A bin whose reading you
cannot trust is not a bin you can certify, and saying so is the honest answer.

## Contract

Emits `Telemetry` ([`../../contracts/schemas/telemetry.schema.json`](../../contracts/schemas/telemetry.schema.json))
to `POST /telemetry`, with `node_id` naming the **bin** — devices are swappable,
bins are not. The API turns that into a `DepotNode`
([`../../contracts/schemas/depot.schema.json`](../../contracts/schemas/depot.schema.json))
for the graph.

**All policy lives server-side.** Bands, dwell, and the MKT ceiling are in
`../../services/api/depot.py` and `seed/depot_bins.json`. Changing what counts as an
excursion never requires a reflash — at 4am you want to edit JSON, not C++.

## Board, flash command, serial port

| | |
|---|---|
| Board | M5Stack Core2 — `pio run -t upload` (it is the default env) |
| Other Core | Core Basic / Gray / Fire — `pio run -e m5stack -t upload`. Same source |
| Fallback board | Bare ESP32 DevKit — `pio run -e esp32dev -t upload`. Insurance only; no screen |
| Serial | `pio device monitor -b 115200` (usually `/dev/ttyUSB0`) |
| I2C | Grove **Port A**, and its pins are **not** the same on every M5 board: **32/33** on a Core2 and a StickC Plus, **21/22** on a Core Basic and a DevKit. `include/pins.h` asks M5Unified at runtime rather than hardcoding either. The boot banner prints what it actually used |
| BME680 addr | tries `0x77` then `0x76`. Adafruit ships 0x77, clones strap 0x76 |
| DHT11 | GPIO **27** on a Core2; **26** on a Core Basic, where 27 is the LCD's D/C line. Needs a 4.7k–10k pull-up to 3V3 on the data line — breakout boards have it, bare 4-pin parts do not. 1 Hz max sample rate, so a repeated value is cached, not stuck |
| MQ-2 | GPIO **35**, ADC1_CH7. Guarded by `#error` in `include/pins.h` |

### MQ-2 needs a divider — do not skip this

The heater runs at 5 V and AOUT swings to VCC. Straight into GPIO35 that is 5 V on
a 3.3 V pin.

```
MQ-2 AOUT ──[10k]──┬── GPIO35
                   │
                  [15k]
                   │
                  GND
```

`MQ2_DIVIDER` in `pins.h` (25/15) undoes it in software, so the reported millivolts
are the voltage actually at AOUT. Change the resistors, change that constant.

**GPIO19 does not work for this.** On a classic ESP32, ADC1 is GPIO 32–39 and ADC2
is GPIO 0/2/4/12–15/25–27; GPIO19 is VSPI MISO with no ADC attached, and
`analogRead(19)` compiles cleanly while returning noise. ADC2 pins are no good
either — they stop working the moment WiFi comes up. `include/pins.h` fails the
build with an explanation if anyone moves the pin off ADC1.

Edit [`include/config.h`](include/config.h) for WiFi, `API_BASE`, and `NODE_ID`.

**Verified compiling** on both envs: `m5stack` 1040 KB flash / 50 KB RAM,
`esp32dev` 957 KB / 48 KB. Untested against real hardware — nobody has flashed a
board yet. Expect the first bring-up problem to be I2C, not code.

### Arch gotcha: system `pio` cannot install its own toolchain

`/usr/bin/pio` fails with `No module named pip` partway through installing
`tool-esptoolpy`, then dies on `MissingPackageManifestError`. Arch's system Python
has no pip, which PlatformIO needs for that package's install step. Use a venv:

```bash
python3 -m venv ~/.pio-venv && ~/.pio-venv/bin/pip install platformio
rm -rf ~/.platformio/packages/tool-esptoolpy   # clear the half-installed one
~/.pio-venv/bin/pio run -t upload
```

## The screen

`src/display.cpp` is the only file that knows M5Stack exists. `main.cpp` calls
four functions — `begin` / `boot` / `update` / `tick` — and contains no `#ifdef`
at all; on the headless fallback env the whole implementation compiles to empty
bodies. That is the point of the split: one source, two boards, no conditional
logic in the measurement path.

```
 sns-depot-01-bin-a                    #000412   <- node id (the BIN), sequence
                          CROSS-CHECK
  23.4 C                   22.9 C                <- BME680 big, DHT11 beside it
                          DIVERGENCE
  57% RH                    0.5 C                <- green under 3 C, red over
 ┌──────────────────────────────────────────┐
 │TEMP C                              24.1  │   <- ~2.5 min of rolling history,
 │        ╭──╮                              │      autoscaled, newest at the right
 │────────╯──╰──────────────────────  22.1  │
 └──────────────────────────────────────────┘
 api ok                            -52dBm
 mq-2   812 mV  (trend only, uncalibrated)
 ─────────────────────────────────────────────
   A series        B bright       C redraw
```

**It shows measurements, never a verdict.** No green COMPLIANT banner. Bands,
dwell and MKT live in `../../services/api/depot.py` so they can change without a
reflash, and a device that renders its own pass/fail will eventually contradict
the dashboard behind it while a judge is watching. The single threshold on this
screen is a 3 °C divergence hint, and it only colours a number the device
already measured.

**Why the trace matters more than the number.** A thumb on the BME680 moves the
big digits, but the plot is what makes the movement legible from three feet away
— and it autoscales with a *minimum span* (2 °C for temperature), because
without one a stable bin turns ADC noise into a seismograph and the trace reads
as broken hardware.

Buttons: **A** cycles the plotted series (temp / RH / gas kΩ / MQ-2 mV), **B**
cycles backlight brightness — bright for a lit demo table, dim to save the pack —
and **C** forces a full repaint, because a garbled panel is usually one dropped
SPI frame and redrawing beats power-cycling a node you are about to demo.

Nothing here repaints the whole screen. `fillScreen()` every 2 s is a visible
black flash that reads as a crash-and-recover on a table; the chrome is drawn
once and values print with an opaque background, which is why every format
string in that file is fixed-width.

## The replay path — get this working first

Per the rule that saved us last time: **the replay path is the insurance policy.**
Neither mode needs a working radio.

```bash
# No hardware at all. 24h of history, played back in ~3 seconds.
DEPOT_TRUST_DEVICE_TS=1 make -C ../.. depot-demo

# Real sensor, dead WiFi: the device prints NDJSON unconditionally, this forwards it.
./replay.py serial --port /dev/ttyUSB0 --api http://localhost:8000
```

## Two demo beats, both honest

1. **Live, on the table.** Thumb on the BME280 → the bin goes amber (`excursion`)
   in ~8s. This is real-time and real. It does *not* reach `mkt_breach`, and it
   shouldn't: MKT is a multi-hour metric and the service refuses to latch a breach
   on a window shorter than `DEPOT_MIN_WINDOW_S`.
2. **Replayed, on screen.** `--scenario breach` plays a genuine 24-hour history:
   one hot hour, then a full recovery. **The last reading is 23.0 C and the
   arithmetic mean is 23.9 C — a naive dashboard shows green — but the
   time-weighted MKT is 25.9 C against a 25 C ceiling, and the stock is condemned.**

Beat 2 is the one that lands. Beat 1 is what makes a judge believe beat 2.

## Gotchas already handled

- BME680 runs at **1x oversampling, IIR filter off**. Oversampling hard makes the
  part self-heat, and on a 20–25 C band a 1–2 C offset is the difference between
  compliant and not. Defensible beats smooth.
- A disconnected BME680 returns plausible garbage rather than failing. Readings are
  bound-checked before they drive a compliance claim, and the driver re-inits on
  bad samples — a jostled Grove cable is tonight's most likely hardware failure.
- Missing BME680 readings are sent as explicit `null`, not omitted. A silent
  authoritative sensor has to read as a fault upstream, not as "no data yet".
- MQ-2 uses `analogReadMilliVolts()`, which applies the per-chip eFuse ADC
  calibration. Raw ESP32 ADC counts are non-linear and not comparable between two
  boards.
- `device_id` is the eFuse MAC, not an index. Two devices sharing an id silently
  overwrite each other's readings. It is prefixed `depot-`, not `esp32-`:
  the same binary builds for two boards, so the id should not name a chip.
- **M5Unified, not the M5Stack library.** `M5Stack@0.4.x` is Core Basic/Gray/Fire
  only. It compiles clean for a Core2 and then talks to an IP5306 that is not
  there — a Core2 has an AXP192 — so a board-model mismatch reaches you as five
  `i2cWriteReadNonStop returned Error -1` lines at boot instead of a build error.
  If you ever see those: the bus is dead, not the sensor. A PMIC soldered to the
  board does not answer either.
- **`M5.begin()` is called with Serial, speaker, mic, IMU and RTC off**, via
  `M5.config()` in `display::begin()`. Serial because `main.cpp` already opened
  it and letting M5 re-init mid-stream truncates the first NDJSON lines; the
  speaker because the amp idles with an audible hiss and that is the first thing
  anyone notices when the room goes quiet for your pitch; the rest because
  nothing here uses them.
- **`cfg.output_power` must stay true.** On a Core2 the 5 V on Grove Port A is
  boosted by the AXP192 rather than fed straight from USB. Turn it off and the
  BME680 is simply unpowered — which looks identical to a wrong pin map.
- **The health indicator is `display::health()`, not a GPIO.** A Core2 has no
  user LED; the green power LED hangs off the AXP192. GPIO2 — the DevKit's
  onboard LED — is the I2S data line to the Core2's amplifier, so `STATUS_LED`
  is deliberately left undefined on M5 builds and a stray `digitalWrite()` to it
  will not compile.
- **The Core2's A/B/C buttons are touch zones on the bezel**, not switches. The
  on-screen legend still lines up with them; `M5.BtnA.wasPressed()` is unchanged.
- **Power it from a USB battery pack, not the Core's internal cell.** ~150 mAh
  will not survive the demo, and the backlight is the biggest draw on the board —
  button **B** dims it if you are running long.
