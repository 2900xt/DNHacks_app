# hardware/esp32-node/

Embedded / device-side code. The thing on the table.

**Stack:** PlatformIO + Arduino-ESP32. Chosen for flash speed, not elegance.

## What this builds

**depot-node** — a storage-condition monitor for a Strategic API Reserve bin
(EO 14336). It is the only node in CHOKEPOINT whose health is *physical* rather
than geopolitical: every other node fails because of who owns it, this one fails
because a warehouse got hot.

**Sensor roles are not symmetric.** This matters more than the wiring:

| Part | Bus / pin | Role |
|---|---|---|
| **BME680** | I2C `0x77`, SDA 21 / SCL 22 | **Authoritative.** ±1 °C, ±3 % RH. Every compliance determination comes from this part. Also gives VOC plate resistance |
| **DHT11** | GPIO **27** | **Cross-check only.** ±2 °C is 40 % of a 20–25 °C band — it cannot certify anything alone. Its job is to *disagree*: two independent sensors diverging is how a failed part announces itself |
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
| Board (bare) | ESP32 DevKit — `pio run -e esp32dev -t upload` |
| Board (LCD) | M5Stack Core — `pio run -e m5stack -t upload` |
| Serial | `pio device monitor -b 115200` (usually `/dev/ttyUSB0`) |
| I2C | SDA **21**, SCL **22** — the DevKit default *and* the M5Stack Grove A port, which is why one pinout covers both |
| BME680 addr | tries `0x77` then `0x76`. Adafruit ships 0x77, clones strap 0x76 |
| DHT11 | GPIO **27**. Needs a 4.7k–10k pull-up to 3V3 on the data line — breakout boards have it, bare 4-pin parts do not. 1 Hz max sample rate, so a repeated value is cached, not stuck |
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

**Verified compiling** on both envs: `esp32dev` 943 KB flash / 47 KB RAM,
`m5stack` 1022 KB / 48 KB. Untested against real hardware — nobody has flashed a
board yet. Expect the first bring-up problem to be I2C, not code.

### Arch gotcha: system `pio` cannot install its own toolchain

`/usr/bin/pio` fails with `No module named pip` partway through installing
`tool-esptoolpy`, then dies on `MissingPackageManifestError`. Arch's system Python
has no pip, which PlatformIO needs for that package's install step. Use a venv:

```bash
python3 -m venv ~/.pio-venv && ~/.pio-venv/bin/pip install platformio
rm -rf ~/.platformio/packages/tool-esptoolpy   # clear the half-installed one
~/.pio-venv/bin/pio run -e esp32dev -t upload
```

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
  overwrite each other's readings.
