#pragma once
#include <Arduino.h>

// One sample cycle, as MEASURED. Shared by main.cpp (which fills it and encodes
// it) and display.cpp (which draws it).
//
// Deliberately carries no verdict — no ok/excursion/breach field. Compliance is
// the API's call (services/api/depot.py), because bands and dwell have to be
// editable at 4am without a reflash. A device that renders its own pass/fail
// will eventually disagree with the screen behind it, on stage.
// Members carry their own defaults so that `Reading r{};` is always a fully
// NAN-initialised sample. The old positional brace list had to be edited in
// lockstep every time a field was added, and getting that wrong silently
// shifts every value one slot to the left.
struct Reading {
  float tempC       = NAN;  // BME680 — authoritative
  float rhPct       = NAN;  // BME680 — authoritative
  float pressureHpa = NAN;
  float gasOhms     = NAN;  // BME680 VOC plate resistance; lower = more VOC
  float tempXcheck  = NAN;  // DHT11
  float rhXcheck    = NAN;  // DHT11
  float mq2Mv       = NAN;  // divider-corrected millivolts at the MQ-2 AOUT

  // --- volatiles, as an INDEX -----------------------------------------------
  // Both sensing elements are resistive and both fall as volatiles rise, so one
  // formula — 100*(1 - R/R_clean) — turns either into the same 0-100
  // contamination score, and they can be blended into one trace. 0 is the air
  // the node booted in; 100 would be the element pulled to zero resistance.
  //
  // NOT a concentration. Neither part is calibrated against a gas standard and
  // R_clean is just "whatever the room smelled like at boot". Trend only.
  float vocIndex    = NAN;  // 0-100 blended; the plotted series
  float vocBme      = NAN;  // 0-100 from the BME680 plate alone
  float vocMq2      = NAN;  // 0-100 from the MQ-2 alone
  float mq2RsR0     = NAN;  // MQ-2 Rs/R0, datasheet convention; ~9.8 clean air

  bool  bmeValid    = false;
  bool  dhtValid    = false;
};
