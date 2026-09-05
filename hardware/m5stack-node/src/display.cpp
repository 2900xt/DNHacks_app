// The M5Stack Core's LCD, as the depot node's instrument face.
//
// Everything M5Stack-specific is contained here. main.cpp calls display::*
// unconditionally; on the headless esp32dev fallback the whole implementation
// collapses to empty functions at the bottom of this file.
//
// Two rules this file follows, both of them load-bearing:
//
//   1. It draws MEASUREMENTS, never a verdict. No green "COMPLIANT" banner. The
//      API owns bands, dwell and MKT (services/api/depot.py) so they can change
//      without a reflash — and a device that renders its own pass/fail will
//      eventually contradict the dashboard behind it while a judge is watching.
//      The one threshold here is XCHECK_HINT_C, and it colours a number the
//      device already measured. It does not decide anything.
//
//   2. It never repaints the whole screen. fillScreen() every 2 s is a visible
//      black flash, which on a table reads as "it crashed and came back". Static
//      chrome is drawn once; values are printed with an opaque background so
//      each glyph overwrites its predecessor, which is why every format string
//      below is fixed-width.

#include "display.h"

#ifdef USE_M5STACK

#include <M5Stack.h>
#include <WiFi.h>
#include <math.h>
#include <stdarg.h>

#include "config.h"

namespace {

// --- palette ---------------------------------------------------------------
// Built with color565 rather than the library's BLACK/RED/... macros so the
// scheme is one block to edit, and so nothing depends on which display driver
// M5Stack ships this week.
uint16_t C_BG, C_INK, C_DIM, C_BAR, C_GRID, C_TEMP, C_RH, C_GOOD, C_BAD;

// --- layout (the panel is 320x240) -----------------------------------------
constexpr int W = 320, H = 240;
constexpr int HEADER_H = 24;
constexpr int BIG_Y    = 32;                 // size 5 -> 30x40 per glyph
constexpr int UNIT_X   = 162, UNIT_Y = 48;
constexpr int RH_Y     = 80;                 // size 3 -> 18x24
constexpr int COL_X    = 186;                // right-hand cross-check column
constexpr int XLBL_Y   = 32,  XVAL_Y = 44;
constexpr int DLBL_Y   = 66,  DVAL_Y = 78;
constexpr int PLOT_X   = 8,   PLOT_Y = 108, PLOT_W = 304, PLOT_H = 66;
constexpr int STATUS_Y = 184;
constexpr int MQ2_Y    = 206;
constexpr int BTN_Y    = 228;

// Bench hint only. The real tolerance lives in DEPOT_XCHECK_TOLERANCE_C on the
// server; this exists so a diverging DHT11 is obvious on the desk before the
// API has enough samples to raise sensor_fault.
constexpr float XCHECK_HINT_C = 3.0f;

// --- history ---------------------------------------------------------------
// One pixel column per 4 px of plot: 76 samples, which at SAMPLE_MS = 2000 is
// about two and a half minutes of context. Long enough to watch a thumb warm
// the part and the trace come back down; short enough to redraw whole.
constexpr int PLOT_STEP = 4;
constexpr int HIST_N    = PLOT_W / PLOT_STEP;

Reading hist[HIST_N];
int      histCount = 0;   // saturates at HIST_N
int      histHead  = 0;   // next write index

const Reading &histAt(int i) {          // i = 0 is the oldest kept sample
  int start = (histCount < HIST_N) ? 0 : histHead;
  return hist[(start + i) % HIST_N];
}

void histPush(const Reading &r) {
  hist[histHead] = r;
  histHead = (histHead + 1) % HIST_N;
  if (histCount < HIST_N) histCount++;
}

// --- plottable series ------------------------------------------------------
// Each carries a minimum span. Without one, autoscale on a stable bin amplifies
// ADC noise into a seismograph and the trace looks broken.
struct Metric {
  const char *label;
  const char *fmt;
  float (*get)(const Reading &);
  float minSpan;
  uint16_t *color;
};

float mTemp(const Reading &r) { return r.bmeValid ? r.tempC  : NAN; }
float mRh  (const Reading &r) { return r.bmeValid ? r.rhPct  : NAN; }
float mGas (const Reading &r) { return r.bmeValid ? r.gasOhms / 1000.0f : NAN; }
float mMq2 (const Reading &r) { return r.mq2Mv; }

const Metric METRICS[] = {
  {"TEMP C",   "%.1f", mTemp, 2.0f,   &C_TEMP},
  {"RH %",     "%.0f", mRh,   5.0f,   &C_RH},
  {"GAS kOhm", "%.0f", mGas,  10.0f,  &C_DIM},
  {"MQ-2 mV",  "%.0f", mMq2,  100.0f, &C_DIM},
};
constexpr int N_METRICS = sizeof(METRICS) / sizeof(METRICS[0]);
int metric = 0;

const uint8_t BRIGHT[] = {80, 160, 255};
int brightIdx = 2;

bool  live     = false;   // has the boot screen been replaced yet
int   bootY    = 0;
Reading lastReading{};
int   lastCode = -1;
uint32_t lastSeq = 0;

// --- helpers ---------------------------------------------------------------

void text(int x, int y, int size, uint16_t fg, uint16_t bg, const char *s) {
  M5.Lcd.setTextSize(size);
  M5.Lcd.setTextColor(fg, bg);
  M5.Lcd.setCursor(x, y);
  M5.Lcd.print(s);
}

void textf(int x, int y, int size, uint16_t fg, uint16_t bg, const char *fmt, ...) {
  char buf[48];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  text(x, y, size, fg, bg, buf);
}

void drawChrome() {
  M5.Lcd.fillScreen(C_BG);

  M5.Lcd.fillRect(0, 0, W, HEADER_H, C_BAR);
  text(6, 5, 2, C_INK, C_BAR, NODE_ID);

  text(UNIT_X, UNIT_Y, 3, C_DIM, C_BG, "C");
  text(COL_X, XLBL_Y, 1, C_DIM, C_BG, "CROSS-CHECK");
  text(COL_X, DLBL_Y, 1, C_DIM, C_BG, "DIVERGENCE");

  M5.Lcd.drawRect(PLOT_X - 1, PLOT_Y - 1, PLOT_W + 2, PLOT_H + 2, C_GRID);

  // Button legend. The caps sit under the physical buttons, so the thirds line
  // up with A / B / C left to right.
  M5.Lcd.drawFastHLine(0, BTN_Y - 6, W, C_GRID);
  text(14,  BTN_Y, 1, C_DIM, C_BG, "A series");
  text(126, BTN_Y, 1, C_DIM, C_BG, "B bright");
  text(232, BTN_Y, 1, C_DIM, C_BG, "C redraw");
}

void drawPlot() {
  const Metric &m = METRICS[metric];

  M5.Lcd.fillRect(PLOT_X, PLOT_Y, PLOT_W, PLOT_H, C_BG);

  float lo = INFINITY, hi = -INFINITY;
  int valid = 0;
  for (int i = 0; i < histCount; i++) {
    float v = m.get(histAt(i));
    if (isnan(v)) continue;
    lo = fminf(lo, v);
    hi = fmaxf(hi, v);
    valid++;
  }

  text(PLOT_X + 3, PLOT_Y + 2, 1, *m.color, C_BG, m.label);

  if (valid < 2) {
    text(PLOT_X + 8, PLOT_Y + PLOT_H / 2 - 4, 1, C_DIM, C_BG, "collecting...");
    return;
  }

  // Widen a too-narrow window symmetrically about its centre.
  if (hi - lo < m.minSpan) {
    float mid = (hi + lo) / 2.0f;
    lo = mid - m.minSpan / 2.0f;
    hi = mid + m.minSpan / 2.0f;
  }

  M5.Lcd.drawFastHLine(PLOT_X, PLOT_Y + PLOT_H / 2, PLOT_W, C_GRID);
  char buf[16];
  snprintf(buf, sizeof(buf), m.fmt, hi);
  textf(PLOT_X + PLOT_W - 6 * (int)strlen(buf) - 2, PLOT_Y + 1, 1, C_DIM, C_BG, "%s", buf);
  snprintf(buf, sizeof(buf), m.fmt, lo);
  textf(PLOT_X + PLOT_W - 6 * (int)strlen(buf) - 2, PLOT_Y + PLOT_H - 9, 1, C_DIM, C_BG, "%s", buf);

  auto yOf = [&](float v) {
    float f = (v - lo) / (hi - lo);
    return PLOT_Y + PLOT_H - 1 - (int)(f * (PLOT_H - 2));
  };

  // Right-align the trace so the newest sample is always at the right edge and
  // a partly-filled history grows leftward instead of stretching.
  int x0 = PLOT_X + PLOT_W - histCount * PLOT_STEP;
  if (x0 < PLOT_X) x0 = PLOT_X;

  bool havePrev = false;
  int px = 0, py = 0;
  for (int i = 0; i < histCount; i++) {
    float v = m.get(histAt(i));
    int x = x0 + i * PLOT_STEP;
    if (isnan(v)) { havePrev = false; continue; }   // a gap is a gap; do not bridge it
    int y = yOf(v);
    if (havePrev) M5.Lcd.drawLine(px, py, x, y, *m.color);
    else          M5.Lcd.drawPixel(x, y, *m.color);
    px = x; py = y; havePrev = true;
  }
}

void drawValues(const Reading &r, int code, uint32_t seq) {
  textf(W - 6 * 7 - 4, 9, 1, C_DIM, C_BAR, "#%06lu", (unsigned long)seq);

  if (r.bmeValid) textf(8, BIG_Y, 5, C_TEMP, C_BG, "%5.1f", r.tempC);
  else            text (8, BIG_Y, 5, C_BAD,  C_BG, " --.-");

  if (r.bmeValid) textf(8, RH_Y, 3, C_RH,  C_BG, "%3.0f%% RH", r.rhPct);
  else            text (8, RH_Y, 3, C_DIM, C_BG, " --% RH");

  if (r.dhtValid) textf(COL_X, XVAL_Y, 2, C_INK, C_BG, "%5.1f C", r.tempXcheck);
  else            text (COL_X, XVAL_Y, 2, C_DIM, C_BG, " --.- C");

  // Divergence is the honest headline number on this screen: it is the one
  // thing the device can say about whether its own reading deserves trust.
  if (r.bmeValid && r.dhtValid) {
    float d = fabsf(r.tempC - r.tempXcheck);
    textf(COL_X, DVAL_Y, 2, d > XCHECK_HINT_C ? C_BAD : C_GOOD, C_BG, "%5.1f C", d);
  } else {
    text(COL_X, DVAL_Y, 2, C_DIM, C_BG, " --.- C");
  }

  bool up = (code == 202);
  textf(8, STATUS_Y, 2, up ? C_GOOD : C_BAD, C_BG, "api %-4s", up ? "ok" : "DOWN");
  if (WiFi.status() == WL_CONNECTED)
    textf(190, STATUS_Y, 2, C_DIM, C_BG, "%4ddBm", WiFi.RSSI());
  else
    text (190, STATUS_Y, 2, C_BAD, C_BG, "no wifi");

  if (!isnan(r.mq2Mv)) textf(8, MQ2_Y, 1, C_DIM, C_BG, "mq-2 %5.0f mV  (trend only, uncalibrated)", r.mq2Mv);
  else                 text (8, MQ2_Y, 1, C_DIM, C_BG, "mq-2  ---- mV  (trend only, uncalibrated)");
}

void repaint() {
  drawChrome();
  drawValues(lastReading, lastCode, lastSeq);
  drawPlot();
}

}  // namespace

// ---------------------------------------------------------------------------

namespace display {

void begin(const char *nodeId) {
  // SD off: there is no card, and probing it costs a second of boot on a shared
  // SPI bus. Serial off: main.cpp already called Serial.begin, and letting M5
  // re-init it mid-stream truncates the first NDJSON lines. I2C off: we drive
  // Wire ourselves with the explicit 21/22 pins from pins.h.
  M5.begin(/*LCD*/ true, /*SD*/ false, /*Serial*/ false, /*I2C*/ false);
  M5.Power.begin();
  M5.Speaker.begin();
  M5.Speaker.mute();      // the Core's amp idles with an audible hiss otherwise

  C_BG   = M5.Lcd.color565(  8,  10,  14);
  C_INK  = M5.Lcd.color565(232, 236, 242);
  C_DIM  = M5.Lcd.color565(120, 128, 142);
  C_BAR  = M5.Lcd.color565( 22,  30,  46);
  C_GRID = M5.Lcd.color565( 44,  50,  64);
  C_TEMP = M5.Lcd.color565(255, 190,  70);
  C_RH   = M5.Lcd.color565( 90, 200, 225);
  C_GOOD = M5.Lcd.color565( 70, 205, 120);
  C_BAD  = M5.Lcd.color565(240,  80,  70);

  M5.Lcd.setBrightness(BRIGHT[brightIdx]);
  M5.Lcd.fillScreen(C_BG);
  M5.Lcd.fillRect(0, 0, W, HEADER_H, C_BAR);
  text(6, 5, 2, C_INK, C_BAR, nodeId);
  text(8, 40, 1, C_DIM, C_BG, "CHOKEPOINT depot-node");
  bootY = 56;
  live  = false;
}

void boot(const char *line) {
  if (live || bootY > 210) return;
  text(8, bootY, 1, C_DIM, C_BG, line);
  bootY += 12;
}

void update(const Reading &r, int httpCode, uint32_t seq) {
  histPush(r);
  lastReading = r;
  lastCode    = httpCode;
  lastSeq     = seq;

  if (!live) { live = true; drawChrome(); }

  drawValues(r, httpCode, seq);
  drawPlot();
}

void tick() {
  M5.update();

  if (M5.BtnA.wasPressed()) {
    metric = (metric + 1) % N_METRICS;
    if (live) drawPlot();
  }
  if (M5.BtnB.wasPressed()) {
    brightIdx = (brightIdx + 1) % (int)(sizeof(BRIGHT) / sizeof(BRIGHT[0]));
    M5.Lcd.setBrightness(BRIGHT[brightIdx]);
  }
  // A garbled panel is usually one dropped SPI frame, not a crash. Redrawing is
  // cheaper than power-cycling a node someone is about to demo.
  if (M5.BtnC.wasPressed() && live) repaint();
}

}  // namespace display

#else   // ---------------------------------------------------------------------
// Headless build (esp32dev). Same source, no panel: the node still emits NDJSON
// on serial and still POSTs, which is the whole fallback path.

namespace display {
void begin(const char *) {}
void boot(const char *) {}
void update(const Reading &, int, uint32_t) {}
void tick() {}
}  // namespace display

#endif
