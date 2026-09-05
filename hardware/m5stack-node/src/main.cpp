// CHOKEPOINT depot-node
// Storage-condition monitor for a Strategic API Reserve bin (EO 14336).
//
// Emits Telemetry (contracts/schemas/telemetry.schema.json) to POST /telemetry.
// The API owns all policy — bands, dwell, MKT, sensor-agreement tolerance — so
// changing what counts as an excursion never requires a reflash. This device
// measures and reports. At 4am you want to edit JSON, not C++ over USB.
//
// Sensor roles are NOT symmetric:
//
//   BME680 (I2C 0x77)  AUTHORITATIVE. +/-1 C, +/-3% RH. Every compliance
//                      determination is made from this part.
//   DHT11  (GPIO27)    CROSS-CHECK ONLY. +/-2 C on a 5 C-wide band is 40% of
//                      the band — it cannot certify anything by itself. What it
//                      is good for is disagreeing: two independent sensors that
//                      diverge means one has failed, and a bin whose reading you
//                      cannot trust is not a compliant bin. The API turns that
//                      into `sensor_fault`.
//   MQ-2   (GPIO35)    Trend only. Uncalibrated, no burn-in. Warehouse-fire
//                      signal, not a storage criterion.
//
// Serial always carries newline-delimited JSON at 115200 whether or not WiFi is
// up. That is the fallback path: if the radio is dead on stage, pipe it through
// `./replay.py serial` and the demo still runs.

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Adafruit_BME680.h>
#include <DHT.h>

#include "pins.h"
#include "config.h"
#include "reading.h"
#include "display.h"

static Adafruit_BME680 bme;
static DHT             dht(DHT_PIN, DHT_KIND);

static bool     bmeOk    = false;
static uint32_t seq      = 0;
static char     deviceId[24];

// ---------------------------------------------------------------------------

static void buildDeviceId() {
  // eFuse MAC, not an index — per the contract. Two devices sharing an id
  // silently overwrite each other's readings, which is a miserable 4am bug.
  uint64_t mac = ESP.getEfuseMac();
  snprintf(deviceId, sizeof(deviceId), "depot-%04x%08x",
           (uint16_t)(mac >> 32), (uint32_t)mac);
}

static bool initBme() {
  // Both straps. Adafruit breakouts sit at 0x77, most clones at 0x76, and which
  // one is in the box tonight is not worth a reflash to find out.
  // (The second argument is `bool initSettings`, NOT a bus pointer — passing
  // &Wire here compiled, meant `true`, and selected nothing. The bus comes from
  // the constructor, which defaults to Wire.)
  if (!bme.begin(BME680_ADDR, true) && !bme.begin(0x76, true)) return false;

  // 1x oversampling and filter off. The BME680 self-heats when oversampled
  // hard, and on a 20-25 C band a 1-2 C offset is the difference between
  // "compliant" and "excursion". We are making a storage claim, so the reading
  // has to be defensible rather than smooth.
  bme.setTemperatureOversampling(BME680_OS_1X);
  bme.setHumidityOversampling(BME680_OS_1X);
  bme.setPressureOversampling(BME680_OS_1X);
  bme.setIIRFilterSize(BME680_FILTER_SIZE_0);

  // Gas heater: 320 C for 150 ms. This is what makes the part self-heat, so the
  // temperature reading is taken from the same conversion that ran BEFORE the
  // plate got hot — see sample(). Keep it on: warehouse smoke is a real depot
  // failure mode and it costs one register write.
  bme.setGasHeater(320, 150);
  return true;
}

static bool connectWifi(uint32_t timeoutMs) {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) delay(200);
  return WiFi.status() == WL_CONNECTED;
}

// ---------------------------------------------------------------------------

static Reading sample() {
  Reading r{NAN, NAN, NAN, NAN, NAN, NAN, NAN, false, false};

  if (bmeOk && bme.performReading()) {
    r.tempC       = bme.temperature;
    r.rhPct       = bme.humidity;
    r.pressureHpa = bme.pressure / 100.0f;
    r.gasOhms     = (float)bme.gas_resistance;
    // A detached BME680 returns plausible-looking values rather than failing
    // loudly. Bound-check before we let it drive a compliance claim.
    r.bmeValid = !isnan(r.tempC) && r.tempC > -50.0f && r.tempC < 100.0f;
  }

  // DHT11 returns NAN on a checksum failure, which is common and not fatal —
  // it is a cross-check, so a miss just means no cross-check this cycle.
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t) && !isnan(h)) {
    r.tempXcheck = t;
    r.rhXcheck   = h;
    r.dhtValid   = true;
  }

#if MQ2_ENABLED
  // analogReadMilliVolts() applies the per-chip eFuse ADC calibration, which
  // matters here: the raw ESP32 ADC is badly non-linear and uncalibrated counts
  // are not comparable between two boards. Undo the divider to recover the
  // voltage actually present at AOUT.
  r.mq2Mv = analogReadMilliVolts(MQ2_ANALOG_PIN) * MQ2_DIVIDER;
#endif

  return r;
}

static void encode(char *buf, size_t n, const Reading &r) {
  size_t off = snprintf(buf, n,
      "{\"device_id\":\"%s\",\"node_id\":\"%s\",\"seq\":%lu,\"readings\":{",
      deviceId, NODE_ID, (unsigned long)seq);

  if (r.bmeValid) {
    off += snprintf(buf + off, n - off,
        "\"temp_c\":%.2f,\"rh_pct\":%.2f,\"pressure_hpa\":%.2f,\"gas_ohms\":%.0f",
        r.tempC, r.rhPct, r.pressureHpa, r.gasOhms);
  } else {
    // Say so explicitly rather than omitting the key. A missing authoritative
    // sensor must read as a fault upstream, not as "no data yet".
    off += snprintf(buf + off, n - off,
        "\"temp_c\":null,\"rh_pct\":null,\"pressure_hpa\":null,\"gas_ohms\":null");
  }

  if (r.dhtValid && off < n) {
    off += snprintf(buf + off, n - off,
        ",\"temp_c_xcheck\":%.1f,\"rh_pct_xcheck\":%.1f", r.tempXcheck, r.rhXcheck);
  }
#if MQ2_ENABLED
  if (!isnan(r.mq2Mv) && off < n) {
    off += snprintf(buf + off, n - off, ",\"mq2_mv\":%.0f", r.mq2Mv);
  }
#endif
  if (off < n) snprintf(buf + off, n - off, "}}");
}

static int post(const char *body) {
  if (!connectWifi(WIFI_TIMEOUT_MS)) return -1;
  HTTPClient http;
  http.setTimeout(3000);          // never let the radio stall the sample loop
  http.begin(String(API_BASE) + "/telemetry");
  http.addHeader("Content-Type", "application/json");
  int code = http.POST((uint8_t *)body, strlen(body));
  http.end();
  return code;
}

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(200);

  display::begin(NODE_ID);   // M5.begin() lives in here, and Port A's pins and
                             // its 5V rail are only valid once it has run.

#if MQ2_ENABLED
  analogSetPinAttenuation(MQ2_ANALOG_PIN, ADC_11db);  // full ~0-3.1V span
#endif

  buildDeviceId();
  const int sda = i2cSdaPin(), scl = i2cSclPin();
  Wire.begin(sda, scl);
  bmeOk = initBme();
  dht.begin();

  // Print the pins we actually used, not the ones we meant to. The whole reason
  // this line exists is that the two were different for an evening.
  Serial.printf("# depot-node %s node=%s bme680=%s i2c=SDA%d/SCL%d dht11=GPIO%d mq2=GPIO%d\n",
                deviceId, NODE_ID, bmeOk ? "ok" : "MISSING", sda, scl, DHT_PIN,
                MQ2_ENABLED ? MQ2_ANALOG_PIN : -1);
  display::boot(bmeOk ? "bme680  ok" : "bme680  MISSING");
  display::boot("dht11   init");   // begin() has no failure to report
  if (!bmeOk) {
    Serial.printf("# BME680 not found on SDA=%d SCL=%d at 0x77/0x76. If this is a\n"
                  "# Core2, Port A is 32/33 — 21/22 is the internal bus.\n", sda, scl);
    Serial.println("# Without it this node cannot certify anything — the DHT11 is");
    Serial.println("# a cross-check, not a fallback.");
    display::boot("cannot certify without bme680");
  }

  display::boot("wifi    connecting...");
  bool wifiUp = connectWifi(WIFI_TIMEOUT_MS);
  display::boot(wifiUp ? "wifi    ok" : "wifi    DOWN (serial fallback)");
  display::boot(API_BASE);
  display::bootHold(bmeOk && wifiUp);
}

void loop() {
  // Polled every iteration, not every sample: the buttons must feel immediate
  // even though a reading is only taken every SAMPLE_MS.
  display::tick();

  static uint32_t last = 0;
  if (millis() - last < SAMPLE_MS) return;
  last = millis();

  Reading r = sample();

  if (!r.bmeValid) {
    display::health(false);
    bmeOk = initBme();   // hot-replug recovery; a jostled Grove cable is the
                         // single most likely hardware failure tonight
  }

  char body[384];
  encode(body, sizeof(body), r);

  Serial.println(body);      // NDJSON fallback path — always, unconditionally
  int code = post(body);

  display::health(code == 202);
  display::update(r, code, seq);   // the seq just sent, before it advances
  seq++;
  if (code != 202) Serial.printf("# post failed: %d\n", code);
}
