#pragma once
#include "reading.h"

// The M5Stack LCD as a live instrument face: what the sensors read right now,
// plus a short rolling history so you can see the trend move under your thumb.
//
// This is the ONLY file that knows M5Stack exists. main.cpp calls these five
// functions unconditionally; when USE_M5STACK is not defined (the headless
// esp32dev fallback) they compile to empty bodies, so main.cpp stays free of
// #ifdefs and both boards build from identical source.
//
// It draws measurements, never a verdict — see the note in reading.h.
namespace display {

// Bring up the LCD and paint the static chrome. Call after Serial.begin().
void begin(const char *nodeId);

// A line of boot progress, while sensors are still coming up. Scrolls; replaced
// by the live face on the first update().
void boot(const char *line);

// Hold the boot report on screen long enough to read it — longer when something
// is wrong, because that is when you need it. No-op on the headless build, where
// this must not cost a delay for a panel that isn't there.
void bootHold(bool healthy);

// Repaint the live values. Call once per sample cycle.
//   httpCode: the POST result. 202 is success; <0 is "no radio".
void update(const Reading &r, int httpCode, uint32_t seq);

// The one-bit health indicator, because "which LED" is a per-board question:
// the AXP192 power LED on a Core2 (GPIO2, the DevKit's onboard LED, is that
// board's I2S amp data line), and STATUS_LED on the headless build.
void health(bool ok);

// Button + housekeeping poll. Call every loop() iteration, not every sample —
// buttons are read far faster than the 2 s sample period.
void tick();

}  // namespace display
