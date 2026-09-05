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
// 21/22 is both the DevKit default and the M5Stack Grove A port, so one map
// covers both boards.
#define I2C_SDA          21
#define I2C_SCL          22
#define BME680_ADDR      0x77   // Adafruit breakouts; clones usually strap 0x76

// --- DHT11 -----------------------------------------------------------------
// Single-wire digital. Needs a 4.7k-10k pull-up to 3V3 on the data line; most
// breakout boards have it fitted, bare 4-pin parts do not.
#define DHT_PIN          27
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

// --- status ----------------------------------------------------------------
#define STATUS_LED       2      // onboard LED on most DevKits
