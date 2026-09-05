#pragma once
#include <Arduino.h>

// One sample cycle, as MEASURED. Shared by main.cpp (which fills it and encodes
// it) and display.cpp (which draws it).
//
// Deliberately carries no verdict — no ok/excursion/breach field. Compliance is
// the API's call (services/api/depot.py), because bands and dwell have to be
// editable at 4am without a reflash. A device that renders its own pass/fail
// will eventually disagree with the screen behind it, on stage.
struct Reading {
  float tempC;        // BME680 — authoritative
  float rhPct;        // BME680 — authoritative
  float pressureHpa;
  float gasOhms;      // BME680 VOC plate resistance; lower = more VOC
  float tempXcheck;   // DHT11
  float rhXcheck;     // DHT11
  float mq2Mv;        // divider-corrected millivolts at the MQ-2 AOUT
  bool  bmeValid;
  bool  dhtValid;
};
