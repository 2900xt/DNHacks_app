#pragma once
// Edit these, reflash. Deliberately not read from ../.env — you will be
// reflashing this from a laptop that is not the one running the API.

// --- network ---------------------------------------------------------------
#define WIFI_SSID       "ahat_phone"
#define WIFI_PASS       "sigma1234"

// The Pi's AP address
#define API_BASE  "http://172.20.10.2:8000"

// --- identity --------------------------------------------------------------
// node_id is the BIN. Devices are swappable; bins are not. Must match a node_id
// in services/api/seed/depot_bins.json, or the API registers it as
// "Unregistered — <id>" (a warning sign, not a crash).
#define NODE_ID         "sns-depot-01-bin-a"

// --- timing ----------------------------------------------------------------
#define SAMPLE_MS       2000    // >= DHT_MIN_PERIOD_MS
#define WIFI_TIMEOUT_MS 10000

// --- air quality -----------------------------------------------------------
// A baseline capture at boot, NOT a calibration against a gas standard. It buys
// comparability with itself over the next few hours and nothing else: move the
// node to a different room and it is void. Never put a ppm on a slide.
//
// The assumption this rests on is that boot air is clean. On a demo table that
// is true right up until someone tests it with a lighter, which is the point.
#define AQ_CAL_MS         6000  // baseline window
#define AQ_CAL_PERIOD_MS   250
// The BME680 plate resistance CLIMBS toward its clean-air value over the first
// few heater cycles, so early samples read dirty. Drop them, then keep the
// maximum — a settling plate only ever reads low.
#define AQ_CAL_BME_DISCARD   4

// The MQ-2 is assumed already warm: heater on for minutes at least, ideally the
// 24h the datasheet wants. A cold element reads high, which would anchor the
// baseline high and make everything measured afterwards look clean. If the
// baseline looks implausible, that is the first thing to suspect.
#define MQ2_VCC_MV        5000.0f  // MQ-2 heater/divider supply, not the ESP32's 3V3
#define MQ2_CLEAN_AIR_RATIO  9.8f  // datasheet Rs/R0 in clean air, for reporting only

// Blend weights. The BME680 leads because it is the part this firmware trusts
// everywhere else. The MQ-2 still gets a real vote: it sees combustibles — LPG,
// CO, smoke — that a VOC plate barely registers, and a warehouse fire is the
// failure mode where being early matters more than being accurate.
#define AQ_W_BME          0.6f
#define AQ_W_MQ2          0.4f

// --- MQ-2 ------------------------------------------------------------------
// The heater needs roughly 24h burn-in before its readings mean anything in
// absolute terms, and calibration needs a known gas concentration we do not
// have. So we report raw millivolts and read them as a TREND ONLY. Never put a
// ppm number on a slide.
#define MQ2_ENABLED     1
