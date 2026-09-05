#pragma once
// Edit these, reflash. Deliberately not read from ../.env — you will be
// reflashing this from a laptop that is not the one running the API.

// --- network ---------------------------------------------------------------
#define WIFI_SSID       "DNHacks"
#define WIFI_PASS       "ExceptionalAmbition"

// The Pi's AP address, not localhost. When the venue wifi dies at 13:00 this is
// the line you will be glad is configurable.
#define API_BASE  "http://192.168.9.66:8000"

// --- identity --------------------------------------------------------------
// node_id is the BIN. Devices are swappable; bins are not. Must match a node_id
// in services/api/seed/depot_bins.json, or the API registers it as
// "Unregistered — <id>" (a warning sign, not a crash).
#define NODE_ID         "sns-depot-01-bin-a"

// --- timing ----------------------------------------------------------------
#define SAMPLE_MS       2000    // >= DHT_MIN_PERIOD_MS
#define WIFI_TIMEOUT_MS 10000

// --- MQ-2 ------------------------------------------------------------------
// The heater needs roughly 24h burn-in before its readings mean anything in
// absolute terms, and calibration needs a known gas concentration we do not
// have. So we report raw millivolts and read them as a TREND ONLY. Never put a
// ppm number on a slide.
#define MQ2_ENABLED     1
