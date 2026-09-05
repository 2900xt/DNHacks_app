# firmware/

Embedded / device-side code.

**Stack:** _TBD_ — candidates: bare-metal C, ESP-IDF, Zephyr, Arduino/PlatformIO,
Rust + `embassy`. Pick for flash speed, not elegance; you will reflash 50 times.

## Contract

Emits `Telemetry` (see [`../contracts/schemas/telemetry.schema.json`](../contracts/schemas/telemetry.schema.json))
to `POST /telemetry`. If the device can't do HTTP, emit newline-delimited JSON over
serial and let a 20-line bridge script in this directory forward it.

## Before you touch hardware

- Get the **replay path** working first: a script that plays recorded telemetry into
  the API. That is the demo's insurance policy, and it unblocks everyone downstream
  while you're still fighting the toolchain.
- Note the exact board, pinout, and flash command here. At 4am you will not remember.

## Notes

_Board:_
_Flash command:_
_Serial port:_
