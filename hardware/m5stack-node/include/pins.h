#pragma once
//
// Pin map, with the guards that catch the mistakes this board actually invites.
//
// ESP32 (classic) ADC:
//   ADC1  GPIO 32 33 34 35 36 37 38 39   <- usable while WiFi is up
//   ADC2  GPIO 0 2 4 12 13 14 15 25 26 27 <- NOT usable while WiFi is up
// Everything else has no ADC at all. analogRead() on such a pin compiles
// cleanly and returns garbage, which is the worst possible failure mode.

// --- I2C: BME680 -----------------------------------------------------------
// Port A is NOT the same two pins on every M5 board, and assuming it was cost
// us an evening:
//
//     Core Basic / Gray / Fire   Port A 21/22   internal 21/22 (IP5306 0x75)
//     Core2                      Port A 32/33   internal 21/22 (AXP192 0x34)
//     StickC Plus                Port A 32/33   internal 21/22
//     bare DevKit                       21/22   (Wire default)
//
// On a Core2 the old hardcoded 21/22 aimed Wire at the INTERNAL bus, where no
// BME680 has ever been. The tell was not "BME680 missing" — it was five
// `i2cWriteReadNonStop returned Error -1` lines before our banner, which is the
// library failing to read a PMIC soldered to the board. When a chip that cannot
// be unplugged does not answer, the fault is the bus, not the sensor.
//
// So stop hardcoding it. M5Unified knows which board it booted on; ask it.
// VALID ONLY AFTER M5.begin() — i.e. after display::begin() in setup().
#ifdef USE_M5STACK
#include <M5Unified.h>
static inline int i2cSdaPin() { int8_t p = M5.Ex_I2C.getSDA(); return p >= 0 ? p : 21; }
static inline int i2cSclPin() { int8_t p = M5.Ex_I2C.getSCL(); return p >= 0 ? p : 22; }
#else
static inline int i2cSdaPin() { return 21; }   // bare DevKit Wire default
static inline int i2cSclPin() { return 22; }
#endif
#define BME680_ADDR      0x77   // Adafruit breakouts; clones usually strap 0x76

// --- DHT11 -----------------------------------------------------------------
// Single-wire digital. Needs a 4.7k-10k pull-up to 3V3 on the data line; most
// breakout boards have it fitted, bare 4-pin parts do not.
// GPIO27 is free on a Core2 and on a DevKit, but it is TFT_DC on a Core Basic /
// Gray / Fire, where bit-banging a DHT on it fights the LCD for the bus. So the
// wire moves with the board. (Core2 keeps 27; Port B's 26 is free on a Basic.)
#if defined(ARDUINO_M5Stack_Core_ESP32)
#define DHT_PIN          26
#else
#define DHT_PIN          27
#endif
#define DHT_KIND         DHT11
// DHT11 samples at 1 Hz max. Reading faster returns the cached previous value,
// so a "stuck" reading is expected behaviour, not a fault.
#define DHT_MIN_PERIOD_MS 1000

// --- MQ-2 ------------------------------------------------------------------
// AOUT swings to VCC and the heater needs 5V, so this MUST come through a
// divider: 10k from AOUT to the pin, 15k from the pin to GND -> 3.0V full scale.
#define MQ2_ANALOG_PIN   35     // ADC1_CH7, input-only, survives WiFi
#define MQ2_DIVIDER      (25.0f / 15.0f)   // (R1+R2)/R2 for the 10k/15k pair

// Compile-time guard. If someone moves this to a non-ADC1 pin the build fails
// here instead of shipping a sensor that silently reads noise.
#if !(MQ2_ANALOG_PIN == 32 || MQ2_ANALOG_PIN == 33 || MQ2_ANALOG_PIN == 34 || \
      MQ2_ANALOG_PIN == 35 || MQ2_ANALOG_PIN == 36 || MQ2_ANALOG_PIN == 37 || \
      MQ2_ANALOG_PIN == 38 || MQ2_ANALOG_PIN == 39)
#error "MQ2_ANALOG_PIN must be on ADC1 (GPIO 32-39). ADC2 pins stop working the \
moment WiFi comes up, and pins outside both ADCs return noise from analogRead() \
without any error. GPIO35 is the recommended choice."
#endif

#if MQ2_ANALOG_PIN == DHT_PIN
#error "MQ2_ANALOG_PIN and DHT_PIN collide."
#endif

// The same guard idea, for the collisions that are board-specific. These are
// silent at runtime — a bit-banged DHT on the LCD's D/C line just corrupts the
// panel intermittently — so they have to fail at compile time or not at all.
#if defined(ARDUINO_M5Stack_Core_ESP32) && DHT_PIN == 27
#error "GPIO27 is TFT_DC on a Core Basic/Gray/Fire: bit-banging the DHT on it \
fights the LCD. Free on a Core2, taken here. Use GPIO26 or GPIO5."
#endif


// --- status ----------------------------------------------------------------
// Headless build ONLY, and deliberately undefined elsewhere so that a stray
// digitalWrite(STATUS_LED, ...) in shared code fails to compile rather than
// misbehaving: an M5 has no user LED on a GPIO you own, and on a Core2 GPIO2 is
// the I2S data line to the amplifier — writing it is audible, not visible.
// The portable spelling is display::health().
#ifndef USE_M5STACK
#define STATUS_LED       2      // onboard LED on most DevKits
#endif
