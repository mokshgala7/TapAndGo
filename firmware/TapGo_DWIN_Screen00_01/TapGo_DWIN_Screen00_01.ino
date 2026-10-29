/*
 * Tap & Go POS — ESP32-S3 + DWIN DGUS II + PN532  (screens 00-08, QR and NFC payment)
 * ---------------------------------------------------------------------------
 * Board   : ESP32-S3 Dev Module (Arduino IDE, ESP32 core 2.x or 3.x)
 *           USB CDC On Boot: Enabled  (Serial monitor at 115200)
 * Display : DWIN DMG48270C043_05WTC, 480x272, TTL mode (pads bridged, 3.3 V)
 * Device  : assigned to one driver account — logs in as that driver at boot
 *
 * Wiring (UART1):
 *   DWIN TX2 -> GPIO9 (RX)   DWIN RX2 -> GPIO8 (TX)   common GND   DWIN 5V -> 5 V rail
 * Wiring (PN532, SPI, mode switch 1 = OFF / 2 = ON, VCC 3.3 V):
 *   SCK -> GPIO12   MISO -> GPIO13   MOSI -> GPIO11   SS -> GPIO10
 * Library: "Adafruit PN532" (Library Manager, with its Adafruit BusIO dependency)
 *
 * DGUS configuration this code expects:
 *   All buttons : Return Key Code, VP 0x1000, Int, auto-upload ON, page switching -1
 *   Screen 00: 0x0001 ENTER AMOUNT
 *   Screen 01: 0x000A..0x0012 digits 1..9, 0x0014 digit 0, 0x0013 backspace,
 *              0x0015 decimal point, 0x0002 BACK, 0x0003 NEXT
 *   Screen 02: 0x0004 TAP NFC CARD -> 03   0x0005 SCAN QR -> 04   0x0016 BACK -> 01
 *   Screen 03: 0x0006 BACK -> 02   0x0007 CANCEL -> 00
 *   Screen 04: 0x0008 BACK -> 02   0x0009 CANCEL -> 00
 *   Screen 05: Processing (Animation icon, VP 0x1500, 1 = run) — no buttons
 *   Screen 06: OTP Verification (see "OTP step-up" below and the DGUS table in the delivery notes):
 *              digits 0x000A..0x0012 / 0x0014 (same codes as screen 01), 0x0017 DELETE,
 *              0x0018 SUBMIT, 0x0019 CANCEL, 0x001A RESEND   (all VP 0x1000, page switching -1)
 *              Text Display VP 0x1200 typed digits (12 bytes), 0x1220 email hint (28 bytes),
 *              0x1260 status line (28 bytes), 0x1280 countdown (20 bytes) — ASCII, same settings as VP 0x1100
 *   Screen 07: Payment successful — no buttons
 *   Screen 08: Payment failed     — no buttons
 *   Amount   : Text Display, VP 0x1100, GB2312 encoding, X/Y lattice 32/32, length 18
 *   QR code  : QR control, VP 0x1300 (ASCII text ending with 0xFFFF)
 *   RTC      : RTC display, fed by the ESP32 from NTP
 *
 * QR payment flow:
 *   SCAN QR -> page 04, QR appears after the backend answers (~4 s)
 *   status checked about every 3 s
 *   QR expires (120 s) -> a new QR is created automatically for the same fare
 *   paid    -> page 05 for 3 s (always) -> page 07 for 4 s -> home
 *   failed  -> page 05 for 3 s (always) -> page 08 for 4 s -> home
 *   BACK    -> QR cancelled on the backend -> page 02 (fare kept)
 *   CANCEL  -> QR cancelled on the backend -> home (fare cleared)
 *
 * NFC payment flow (PN532 reads cards only while page 03 is showing):
 *   TAP NFC CARD -> page 03, waits for a card
 *   card read -> page 05 at once, POST /api/nfc/pay {card_uid, amount, idempotency_key}
 *   paid   -> page 05 for 3 s (always) -> page 07 for 4 s -> home
 *   failed -> page 05 for 3 s (always) -> page 08 for 4 s -> home
 *   network error -> status lookup with the SAME idempotency key (see "Timeout safety"), never page 08 on a guess
 *   BACK -> page 02 (fare kept)   CANCEL -> home (fare cleared)
 *
 * OTP step-up (fraud gate, backend TAPGO_FRAUD_MODE=enforce):
 *   NFC : /api/nfc/pay may answer status "otp_required" instead of paying. The passenger gets a 6-digit
 *         code by email; the POS shows page 06 (masked email hint + countdown). SUBMIT -> POST
 *         /api/nfc/pay/verify-otp (page 05, then 07 / 08). Wrong code -> back to page 06 with the attempts
 *         left. CANCEL -> POST /api/nfc/pay/cancel-otp, home. RESEND -> POST /api/nfc/pay/resend-otp.
 *         Expiry, 3 wrong codes or a cancelled challenge -> page 08. No money moves before a correct code.
 *         The POS gives up on an OTP at the 5-minute expiry (hard ceiling 6 min) and asks the backend.
 *   QR  : status "AwaitingOtp" means the passenger is entering the code on their phone. The POS stays on
 *         page 04 (QR cleared, not regenerated), so BACK / CANCEL still work: they cancel the QR request and its
 *         OTP challenge on the backend and go home. Ceiling 6 min, then a final status lookup, then 07 / 08.
 *
 * Timeout safety (never show "failed" for a payment that may have gone through):
 *   A pay or verify-otp call that ends in a network error / timeout / 5xx does NOT show page 08. The POS asks
 *   GET /api/nfc/pay/status?idempotency_key=... every 2 s for up to 20 s and shows 07 / 08 only from a
 *   definitive backend answer (completed / failed). If it is still unknown the failure page shows
 *   "Could not confirm payment / Check with passenger before retrying" (text VPs 0x1420, 0x1440). The same
 *   idempotency key is kept for the whole fare: the POS never starts a second charge on its own.
 *
 * All network calls run in a background task on core 0, so the touchscreen
 * never freezes while Render is slow.
 *
 * Display CFG: auto-upload ON (byte 05 = 0x38), backgrounds in 24.ICL (byte 08 = 0x18). CRC OFF.
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include <Adafruit_PN532.h>

// ========================= User settings =========================
#define DWIN_RX_PIN   9
#define DWIN_TX_PIN   8

#define PN532_SCK     12
#define PN532_MISO    13
#define PN532_MOSI    11
#define PN532_SS      10
#define DWIN_BAUD     115200

const char* WIFI_SSID = "YOUR_WIFI_SSID";            // set before flashing (redacted in the repo copy)
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";      // set before flashing (redacted in the repo copy)

const char* API_BASE        = "https://tap-go-backend.onrender.com";
const char* DRIVER_ACCOUNT  = "YOUR_DRIVER_EMAIL_OR_PHONE";   // the POS driver account (redacted in the repo copy)
const char* DRIVER_PASSWORD = "YOUR_DRIVER_PASSWORD"; // set before flashing (redacted in the repo copy)


const uint32_t MAX_PAISE = 1000000;    // Rs 10,000.00 — highest fare accepted
const uint32_t MIN_PAISE = 100;        // Rs 1.00     — NEXT is refused below this
const uint8_t  MAX_INT_DIGITS = 5;
const uint8_t  MAX_DEC_DIGITS = 2;

const uint8_t  SCREEN_BRIGHTNESS = 90;   // DWIN backlight, 0-100 %

// Timings (ms)
const uint32_t QR_POLL_GAP_MS      = 1500;   // pause after each status reply (~3 s cycle on Render)
const uint32_t QR_RETRY_MS         = 3000;   // retry a failed QR create
const uint32_t PROCESSING_MS       = 3000;   // page 05 — always shown this long
const uint32_t RESULT_MS           = 4000;   // page 07 / 08
const uint32_t PROCESSING_GIVEUP_MS = 30000; // no final answer after this -> failed
const uint16_t NFC_READ_TIMEOUT_MS = 50;     // each card check on page 03 (keeps touch responsive)
const uint32_t NFC_CONFIRM_GAP_MS  = 2000;   // status lookup every 2 s after an unclear pay / verify call
const uint32_t NFC_CONFIRM_MS      = 20000;  // ... for up to 20 s, then "could not confirm"
const uint32_t NFC_WATCHDOG_MS     = 90000;  // a pay / verify call still unanswered after this -> status lookups
const uint32_t OTP_CEILING_MS      = 360000; // 6 min: the OTP lives 5 min on the backend; never wait longer
const uint32_t QR_OTP_CEILING_MS   = 360000; // same ceiling for a QR payment AwaitingOtp
// =================================================================

// VP addresses
const uint16_t VP_KEY       = 0x1000;
const uint16_t VP_AMOUNT    = 0x1100;   // text, 18 bytes
const uint16_t VP_QR        = 0x1300;   // QR text
const uint16_t VP_LOADER    = 0x1500;   // animation icon on page 05
const uint16_t VP_OTP_CODE  = 0x1200;   // page 06: typed digits, 12 bytes
const uint16_t VP_OTP_HINT  = 0x1220;   // page 06: masked email, 28 bytes
const uint16_t VP_OTP_MSG   = 0x1260;   // page 06: status line, 28 bytes
const uint16_t VP_OTP_TIME  = 0x1280;   // page 06: countdown, 20 bytes
const uint16_t VP_QR_WAIT   = 0x1400;   // page 04: "Waiting for passenger OTP", 28 bytes (optional control)
const uint16_t VP_FAIL_MSG1 = 0x1420;   // page 08: line 1, 28 bytes ("Could not confirm payment")
const uint16_t VP_FAIL_MSG2 = 0x1440;   // page 08: line 2, 40 bytes ("Check with passenger before retrying")
const uint8_t  QR_WAIT_FIELD = 28, FAIL_MSG1_FIELD = 28, FAIL_MSG2_FIELD = 40;
const uint8_t  OTP_CODE_FIELD = 12, OTP_HINT_FIELD = 28, OTP_MSG_FIELD = 28, OTP_TIME_FIELD = 20;
const uint8_t  OTP_LEN = 6;
const uint8_t  AMOUNT_FIELD_CHARS = 18;

// Key values
const uint16_t KEY_ENTER_AMOUNT = 0x0001;
const uint16_t KEY_BACK         = 0x0002;
const uint16_t KEY_NEXT         = 0x0003;
const uint16_t KEY_DIGIT_1      = 0x000A;
const uint16_t KEY_DIGIT_9      = 0x0012;
const uint16_t KEY_BACKSPACE    = 0x0013;
const uint16_t KEY_DIGIT_0      = 0x0014;
const uint16_t KEY_DECIMAL      = 0x0015;
const uint16_t KEY_PAY_NFC      = 0x0004;
const uint16_t KEY_PAY_QR       = 0x0005;
const uint16_t KEY_PAY_BACK     = 0x0016;
const uint16_t KEY_NFC_BACK     = 0x0006;
const uint16_t KEY_NFC_CANCEL   = 0x0007;
const uint16_t KEY_QR_BACK      = 0x0008;
const uint16_t KEY_QR_CANCEL    = 0x0009;
const uint16_t KEY_OTP_DELETE   = 0x0017;
const uint16_t KEY_OTP_SUBMIT   = 0x0018;
const uint16_t KEY_OTP_CANCEL   = 0x0019;
const uint16_t KEY_OTP_RESEND   = 0x001A;

// Pages
const uint8_t PAGE_HOME           = 0;
const uint8_t PAGE_ENTER_AMOUNT   = 1;
const uint8_t PAGE_PAYMENT_METHOD = 2;
const uint8_t PAGE_NFC_TAP        = 3;
const uint8_t PAGE_QR_CODE        = 4;
const uint8_t PAGE_PROCESSING     = 5;
const uint8_t PAGE_OTP            = 6;
const uint8_t PAGE_SUCCESS        = 7;
const uint8_t PAGE_FAILED         = 8;

enum PayMethod : uint8_t { PAY_NONE, PAY_NFC, PAY_QR };
PayMethod payMethod = PAY_NONE;

// Types for the network task. They must stay ABOVE the first function:
// Arduino IDE inserts automatic function declarations there.
enum JobType : uint8_t { JOB_CREATE_QR, JOB_QR_STATUS, JOB_QR_CANCEL,
                         JOB_NFC_PAY, JOB_NFC_VERIFY, JOB_NFC_RESEND, JOB_NFC_CANCEL_OTP, JOB_NFC_STATUS };

struct NetJob {
  JobType  type;
  uint32_t session;      // which QR / NFC attempt this belongs to
  uint32_t paise;
  char     token[48];    // QR token, or the idempotency key for JOB_NFC_PAY
  char     uid[16];      // card UID for JOB_NFC_PAY (uppercase hex)
  char     challenge[40];// OTP challenge id (JOB_NFC_VERIFY / RESEND / CANCEL_OTP)
  char     otp[8];       // typed code (JOB_NFC_VERIFY). Never printed to the serial log.
};

struct NetResult {
  JobType  type;
  uint32_t session;
  bool     ok;           // HTTP 200 and success:true
  int      http;
  char     status[16];   // Pending / Processing / Completed / Failed / Expired / Cancelled
  char     token[48];
  char     url[96];
  uint16_t expiresIn;
  char     code[32];     // NFC failure code, e.g. INSUFFICIENT_BALANCE
  char     name[24];     // NFC: passenger first name
  char     challenge[40];// NFC OTP: challenge id
  char     hint[28];     // NFC OTP: masked email, e.g. m***@g***.com
  int8_t   attemptsLeft; // NFC OTP
  int8_t   resendsLeft;  // NFC OTP
  char     msg[32];      // NFC OTP: short text from the backend (resend refusals)
};

enum NfcState : uint8_t { NFC_IDLE, NFC_WAITING, NFC_PAYING, NFC_OTP, NFC_VERIFYING, NFC_CONFIRMING, NFC_RESULT };

enum QrState : uint8_t { QR_IDLE, QR_CREATING, QR_SHOWING, QR_AWAITING, QR_PROCESSING, QR_RESULT };

HardwareSerial dwin(1);
uint8_t currentPage = PAGE_HOME;

char     amountText[12] = "";
uint8_t  amountLen      = 0;
uint32_t farePaise      = 0;

// ======================= DWIN low-level =======================

void dwinWriteVP(uint16_t vp, const uint8_t* data, uint8_t n) {
  uint8_t hdr[6] = {0x5A, 0xA5, (uint8_t)(3 + n), 0x82,
                    (uint8_t)(vp >> 8), (uint8_t)(vp & 0xFF)};
  dwin.write(hdr, 6);
  dwin.write(data, n);
}

void dwinWriteWord(uint16_t vp, uint16_t v) {
  uint8_t d[2] = {(uint8_t)(v >> 8), (uint8_t)v};
  dwinWriteVP(vp, d, 2);
}

void dwinSetPage(uint8_t page) {
  uint8_t d[4] = {0x5A, 0x01, 0x00, page};
  dwinWriteVP(0x0084, d, 4);
  currentPage = page;
  Serial.printf("[%lu ms] [DWIN] -> page %02u\n", (unsigned long)millis(), page);
}

// Backlight (VP 0x0082): brightness 0-100 % in use, 0-100 % in standby, standby delay in 10 ms units
void dwinSetBrightness(uint8_t active, uint8_t standby) {
  uint8_t d[4] = {active, standby, 0x0B, 0xB8};   // 0x0BB8 = 3000 x 10 ms = 30 s
  dwinWriteVP(0x0082, d, 4);
}

void dwinWriteTime(const struct tm& t, bool alsoHardwareRTC) {
  uint8_t d[8] = {(uint8_t)(t.tm_year % 100), (uint8_t)(t.tm_mon + 1),
                  (uint8_t)t.tm_mday, (uint8_t)t.tm_wday,
                  (uint8_t)t.tm_hour, (uint8_t)t.tm_min,
                  (uint8_t)t.tm_sec,  0x00};
  dwinWriteVP(0x0010, d, 8);
  if (alsoHardwareRTC) {
    uint8_t h[8] = {0x5A, 0xA5, d[0], d[1], d[2], d[4], d[5], d[6]};
    dwinWriteVP(0x009C, h, 8);
  }
}

// QR text: ASCII followed by 0xFFFF, padded to an even length.
void dwinShowQR(const char* text) {
  uint8_t buf[128];
  size_t n = strlen(text);
  if (n > sizeof(buf) - 3) n = sizeof(buf) - 3;
  memcpy(buf, text, n);
  buf[n++] = 0xFF; buf[n++] = 0xFF;
  if (n & 1) buf[n++] = 0xFF;
  dwinWriteVP(VP_QR, buf, (uint8_t)n);
}

void dwinClearQR() {
  uint8_t blank[2] = {0xFF, 0xFF};
  dwinWriteVP(VP_QR, blank, 2);
}

// ======================= Amount logic =======================

uint32_t textToPaise(const char* s) {
  uint32_t rupees = 0, paise = 0;
  uint8_t decs = 0;
  bool afterDot = false;
  for (; *s; s++) {
    if (*s == '.') { afterDot = true; continue; }
    if (!afterDot) rupees = rupees * 10 + (*s - '0');
    else if (decs < 2) { paise = paise * 10 + (*s - '0'); decs++; }
  }
  if (decs == 1) paise *= 10;
  return rupees * 100 + paise;
}

void showAmount() {
  const char* shown = amountLen ? amountText : "0";
  uint8_t len  = strlen(shown);
  uint8_t left = (AMOUNT_FIELD_CHARS - len) / 2;
  uint8_t buf[AMOUNT_FIELD_CHARS];
  memset(buf, ' ', sizeof(buf));
  memcpy(buf + left, shown, len);
  dwinWriteVP(VP_AMOUNT, buf, sizeof(buf));
}

void resetAmount() { amountText[0] = '\0'; amountLen = 0; showAmount(); }

bool hasDot()       { return strchr(amountText, '.') != nullptr; }
uint8_t decDigits() { const char* d = strchr(amountText, '.'); return d ? strlen(d + 1) : 0; }
uint8_t intDigits() { const char* d = strchr(amountText, '.'); return d ? (d - amountText) : amountLen; }

void tryAppend(char c) {
  char candidate[12];
  strcpy(candidate, amountText);
  if (c == '.') {
    if (hasDot()) return;
    if (amountLen == 0) strcpy(candidate, "0.");
    else strcat(candidate, ".");
  } else {
    if (hasDot()) {
      if (decDigits() >= MAX_DEC_DIGITS) return;
    } else {
      if (amountLen == 1 && amountText[0] == '0') candidate[0] = '\0';
      else if (intDigits() >= MAX_INT_DIGITS) return;
    }
    size_t n = strlen(candidate);
    candidate[n] = c; candidate[n + 1] = '\0';
  }
  if (textToPaise(candidate) > MAX_PAISE) { Serial.println("[AMT] rejected: above maximum fare"); return; }
  strcpy(amountText, candidate);
  amountLen = strlen(amountText);
  showAmount();
}

void backspace() {
  if (amountLen == 0) return;
  amountText[--amountLen] = '\0';
  if (amountLen == 1 && amountText[0] == '0') { amountText[0] = '\0'; amountLen = 0; }
  showAmount();
}

// ======================= Network task (core 0) =======================
// The UI sends jobs into netJobs; the task answers into netResults.

QueueHandle_t netJobs, netResults;   // (JobType / NetJob / NetResult are defined near the top)

String jsonString(const String& json, const char* key) {
  String k = String("\"") + key + "\":\"";
  int p = json.indexOf(k);
  if (p < 0) return "";
  p += k.length();
  int e = json.indexOf('"', p);
  return e < 0 ? "" : json.substring(p, e);
}

long jsonNumber(const String& json, const char* key, long def) {
  String k = String("\"") + key + "\":";
  int p = json.indexOf(k);
  if (p < 0) return def;
  return json.substring(p + k.length()).toInt();
}

// --- everything below runs only inside the network task ---
static WiFiClientSecure netTls;
static String sessionToken;          // driver login token (lives only in the task)
static uint32_t lastLoginTry = 0;

int httpCall(const char* method, const String& path, const String& body, String& resp) {
  HTTPClient http;
  http.setTimeout(30000);
  http.setConnectTimeout(20000);
  if (!http.begin(netTls, String(API_BASE) + path)) { resp = ""; return -1; }
  http.addHeader("Content-Type", "application/json");
  if (sessionToken.length()) http.addHeader("Authorization", "Bearer " + sessionToken);
  uint32_t t0 = millis();
  int code = (strcmp(method, "POST") == 0) ? http.POST(body) : http.GET();
  resp = (code > 0) ? http.getString() : String("");
  http.end();
  Serial.printf("[NET] %s %s -> %d (%lu ms)\n", method, path.c_str(), code, (unsigned long)(millis() - t0));
  return code;
}

bool driverLogin() {
  lastLoginTry = millis();
  if (strlen(DRIVER_ACCOUNT) == 0) { Serial.println("[NET] no driver login set in sketch"); return false; }
  sessionToken = "";
  String body = String("{\"account\":\"") + DRIVER_ACCOUNT + "\",\"password\":\"" + DRIVER_PASSWORD + "\"}";
  String resp;
  int code = httpCall("POST", "/api/auth/login", body, resp);
  String tok = jsonString(resp, "token");
  if (code == 200 && resp.indexOf("\"success\":true") >= 0 && tok.length()) {
    sessionToken = tok;
    Serial.println("[NET] driver login OK");
    return true;
  }
  Serial.println("[NET] driver login FAILED");
  return false;
}

// Calls an authenticated endpoint; logs in first if needed and once more on 401.
int authedCall(const char* method, const String& path, const String& body, String& resp) {
  if (!sessionToken.length() && !driverLogin()) return -2;
  int code = httpCall(method, path, body, resp);
  if (code == 401) {
    Serial.println("[NET] 401 -> logging in again");
    if (!driverLogin()) return 401;
    code = httpCall(method, path, body, resp);
  }
  return code;
}

void netTask(void*) {
  netTls.setInsecure();   // demo: no certificate pinning yet
  NetJob job;
  for (;;) {
    // Log in early in the background so the first QR is fast.
    if (WiFi.status() == WL_CONNECTED && !sessionToken.length() &&
        (lastLoginTry == 0 || millis() - lastLoginTry > 30000)) {
      driverLogin();
    }

    if (xQueueReceive(netJobs, &job, pdMS_TO_TICKS(200)) != pdTRUE) continue;

    NetResult r = {};
    r.type = job.type;
    r.session = job.session;
    strlcpy(r.token, job.token, sizeof(r.token));

    if (WiFi.status() != WL_CONNECTED) {
      r.ok = false; r.http = -3;
      xQueueSend(netResults, &r, portMAX_DELAY);
      continue;
    }

    String resp;
    if (job.type == JOB_CREATE_QR) {
      char body[40];
      snprintf(body, sizeof(body), "{\"amount\":%lu.%02lu}",
               (unsigned long)(job.paise / 100), (unsigned long)(job.paise % 100));
      r.http = authedCall("POST", "/api/qr/create-request", body, resp);
      strlcpy(r.token, jsonString(resp, "token").c_str(), sizeof(r.token));
      strlcpy(r.url, jsonString(resp, "payment_url").c_str(), sizeof(r.url));
      r.expiresIn = (uint16_t)jsonNumber(resp, "expires_in_seconds", 120);
      r.ok = (r.http == 200 && strlen(r.token) && strlen(r.url));
    } else if (job.type == JOB_QR_STATUS) {
      r.http = authedCall("GET", String("/api/qr/") + job.token + "/status", "", resp);
      r.ok = (r.http == 200);
    } else if (job.type == JOB_QR_CANCEL) {
      r.http = authedCall("POST", String("/api/qr/") + job.token + "/cancel", "", resp);
      r.ok = (r.http == 200);
    } else if (job.type == JOB_NFC_PAY) {
      char body[160];
      snprintf(body, sizeof(body),
               "{\"card_uid\":\"%s\",\"amount\":%lu.%02lu,\"idempotency_key\":\"%s\"}",
               job.uid, (unsigned long)(job.paise / 100), (unsigned long)(job.paise % 100), job.token);
      r.http = authedCall("POST", "/api/nfc/pay", body, resp);
      r.ok = (r.http == 200 && resp.indexOf("\"success\":true") >= 0);
    } else if (job.type == JOB_NFC_VERIFY) {
      char body[160];
      snprintf(body, sizeof(body), "{\"challenge_id\":\"%s\",\"otp\":\"%s\",\"idempotency_key\":\"%s\"}",
               job.challenge, job.otp, job.token);
      r.http = authedCall("POST", "/api/nfc/pay/verify-otp", body, resp);
      r.ok = (r.http == 200 && resp.indexOf("\"success\":true") >= 0);
    } else if (job.type == JOB_NFC_STATUS) {
      r.http = authedCall("GET", String("/api/nfc/pay/status?idempotency_key=") + job.token, "", resp);
      r.ok = (r.http == 200);
      strlcpy(r.code, jsonString(resp, "failure_code").c_str(), sizeof(r.code));
    } else if (job.type == JOB_NFC_RESEND || job.type == JOB_NFC_CANCEL_OTP) {
      char body[80];
      snprintf(body, sizeof(body), "{\"challenge_id\":\"%s\"}", job.challenge);
      r.http = authedCall("POST", job.type == JOB_NFC_RESEND ? "/api/nfc/pay/resend-otp" : "/api/nfc/pay/cancel-otp",
                          body, resp);
      r.ok = (r.http == 200);
    }
    if (job.type >= JOB_NFC_PAY) {
      if (job.type != JOB_NFC_STATUS) strlcpy(r.code, jsonString(resp, "code").c_str(), sizeof(r.code));
      strlcpy(r.name, jsonString(resp, "passenger_name").c_str(), sizeof(r.name));
      strlcpy(r.challenge, jsonString(resp, "challenge_id").c_str(), sizeof(r.challenge));
      strlcpy(r.hint, jsonString(resp, "email_hint").c_str(), sizeof(r.hint));
      strlcpy(r.msg, jsonString(resp, "message").c_str(), sizeof(r.msg));
      r.expiresIn = (uint16_t)jsonNumber(resp, "expires_in_seconds", 0);
      r.attemptsLeft = (int8_t)jsonNumber(resp, "attempts_left", -1);
      r.resendsLeft = (int8_t)jsonNumber(resp, "resends_left", -1);
    }
    strlcpy(r.status, jsonString(resp, "status").c_str(), sizeof(r.status));
    if (!r.ok && resp.length()) Serial.printf("[NET] reply: %s\n", resp.substring(0, 200).c_str());
    xQueueSend(netResults, &r, portMAX_DELAY);
  }
}

void sendJob(JobType type, uint32_t session, uint32_t paise, const char* token) {
  NetJob j = {};
  j.type = type; j.session = session; j.paise = paise;
  if (token) strlcpy(j.token, token, sizeof(j.token));
  xQueueSend(netJobs, &j, 0);
}

void sendNfcOtpJob(JobType type, uint32_t session, const char* challenge, const char* otp, const char* key) {
  NetJob j = {};
  j.type = type; j.session = session;
  strlcpy(j.challenge, challenge, sizeof(j.challenge));
  if (otp) strlcpy(j.otp, otp, sizeof(j.otp));
  if (key) strlcpy(j.token, key, sizeof(j.token));
  xQueueSend(netJobs, &j, 0);
}

void sendNfcStatusJob(uint32_t session, const char* key) {
  NetJob j = {};
  j.type = JOB_NFC_STATUS; j.session = session;
  strlcpy(j.token, key, sizeof(j.token));
  xQueueSend(netJobs, &j, 0);
}

void sendNfcPayJob(uint32_t session, uint32_t paise, const char* uid, const char* key) {
  NetJob j = {};
  j.type = JOB_NFC_PAY; j.session = session; j.paise = paise;
  strlcpy(j.token, key, sizeof(j.token));
  strlcpy(j.uid, uid, sizeof(j.uid));
  xQueueSend(netJobs, &j, 0);
}

// ======================= QR payment (UI side, core 1) =======================

QrState  qrState     = QR_IDLE;
uint32_t qrSession   = 0;        // bumps on every new attempt; stale replies are ignored
char     qrToken[48] = "";
bool     qrBusy      = false;    // a create/status call is in flight
uint32_t qrNextAt    = 0;        // next create retry / status poll
uint32_t qrPhaseAt   = 0;        // when page 05 / 07 / 08 was shown
uint8_t  qrOutcome   = 0;        // 0 unknown, 1 paid, 2 failed, 5 could not confirm
uint32_t qrAwaitSince = 0;       // when AwaitingOtp was first seen
uint32_t qrFinalAt    = 0;       // when the final status lookup began (0 = not yet)

void dwinText(uint16_t vp, const char* text, uint8_t field);   // defined with the OTP helpers below

void qrClearWaitText() { dwinText(VP_QR_WAIT, "", QR_WAIT_FIELD); }

void qrStart() {                 // entering page 04
  qrSession++;
  qrToken[0] = '\0';
  qrBusy = false;
  qrOutcome = 0;
  qrFinalAt = 0;
  qrClearWaitText();
  qrState = QR_CREATING;
  qrNextAt = millis();
  dwinClearQR();
  dwinSetPage(PAGE_QR_CODE);
}

// Leaves page 04 by BACK/CANCEL: cancel the QR on the backend so it can't be paid later.
void qrAbort() {
  if (qrState == QR_IDLE) return;
  if (qrToken[0]) sendJob(JOB_QR_CANCEL, qrSession, 0, qrToken);
  qrSession++;                   // any reply still in flight is now stale
  qrState = QR_IDLE;
  qrToken[0] = '\0';
  qrBusy = false;
  qrClearWaitText();
  dwinClearQR();
}

// Page 07 / 08. Outcome 5 = could not confirm: the failure page says so and tells the driver not to retry blindly.
void showResultPage(uint8_t outcome) {
  Serial.printf("[PAY] %s\n", outcome == 1 ? "PAYMENT SUCCESSFUL" : (outcome == 5 ? "PAYMENT NOT CONFIRMED" : "PAYMENT FAILED"));
  dwinWriteWord(VP_LOADER, 0);
  if (outcome == 5) {
    dwinText(VP_FAIL_MSG1, "Could not confirm payment", FAIL_MSG1_FIELD);
    dwinText(VP_FAIL_MSG2, "Check with passenger before retrying", FAIL_MSG2_FIELD);
  } else {
    dwinText(VP_FAIL_MSG1, "", FAIL_MSG1_FIELD);
    dwinText(VP_FAIL_MSG2, "", FAIL_MSG2_FIELD);
  }
  dwinSetPage(outcome == 1 ? PAGE_SUCCESS : PAGE_FAILED);
}

void qrShowProcessing(uint8_t outcome) {
  qrState = QR_PROCESSING;
  qrOutcome = outcome;
  qrPhaseAt = millis();
  qrNextAt = millis() + QR_POLL_GAP_MS;
  dwinClearQR();
  dwinWriteWord(VP_LOADER, 1);   // start the loader animation
  dwinSetPage(PAGE_PROCESSING);
}

void qrFinishTransaction() {
  Serial.println("[PAY] transaction finished -> home");
  qrState = QR_IDLE;
  qrToken[0] = '\0';
  qrClearWaitText();
  payMethod = PAY_NONE;
  farePaise = 0;
  resetAmount();
  dwinSetPage(PAGE_HOME);
}

void qrHandleResult(const NetResult& r) {
  // A cancel that discovers the passenger had already paid -> show success anyway.
  if (r.type == JOB_QR_CANCEL) {
    Serial.printf("[QR] cancel reply: %s\n", r.status);
    if (r.ok && strcmp(r.status, "Completed") == 0 && qrState == QR_IDLE) {
      Serial.println("[QR] passenger paid just before cancel -> success");
      qrSession++;
      qrShowProcessing(1);
    }
    return;
  }

  if (r.session != qrSession) {   // reply for an abandoned attempt
    if (r.type == JOB_CREATE_QR && r.ok) sendJob(JOB_QR_CANCEL, 0, 0, r.token);  // don't leave it payable
    return;
  }
  qrBusy = false;

  if (r.type == JOB_CREATE_QR) {
    if (!r.ok) {
      Serial.printf("[QR] create failed (%d) — retrying\n", r.http);
      qrNextAt = millis() + QR_RETRY_MS;
      return;
    }
    strlcpy(qrToken, r.token, sizeof(qrToken));
    dwinShowQR(r.url);
    Serial.printf("[QR] showing %s (expires in %u s)\n", r.url, r.expiresIn);
    qrState = QR_SHOWING;
    qrNextAt = millis() + QR_POLL_GAP_MS;
    return;
  }

  // JOB_QR_STATUS
  qrNextAt = millis() + (qrFinalAt ? NFC_CONFIRM_GAP_MS : QR_POLL_GAP_MS);
  if (!r.ok) return;              // network hiccup: just poll again
  const char* s = r.status;

  if (qrState == QR_SHOWING) {
    if (!strcmp(s, "Completed"))       qrShowProcessing(1);
    else if (!strcmp(s, "Failed"))     qrShowProcessing(2);
    else if (!strcmp(s, "Processing")) qrShowProcessing(0);
    else if (!strcmp(s, "AwaitingOtp")) {
      // Keep this payment alive: no new QR. Stay on page 04 so BACK / CANCEL still work.
      Serial.println("[QR] passenger is verifying an OTP -> waiting");
      qrState = QR_AWAITING;
      qrAwaitSince = millis();
      qrFinalAt = 0;
      dwinClearQR();                          // nobody can scan it again
      dwinText(VP_QR_WAIT, "Waiting for passenger OTP", QR_WAIT_FIELD);
    }
    else if (!strcmp(s, "Expired") || !strcmp(s, "Cancelled")) {
      Serial.println("[QR] expired -> new QR for the same fare");
      qrToken[0] = '\0';
      qrState = QR_CREATING;
      qrNextAt = millis();
      dwinClearQR();
    }
  } else if (qrState == QR_AWAITING) {
    if (!strcmp(s, "Completed"))                                   qrShowProcessing(1);
    else if (!strcmp(s, "Failed") || !strcmp(s, "Expired") || !strcmp(s, "Cancelled")) qrShowProcessing(2);
    else if (!strcmp(s, "Processing"))                             qrShowProcessing(0);
    // "AwaitingOtp": keep waiting (the ceiling is handled in qrTick)
  } else if (qrState == QR_PROCESSING && qrOutcome == 0) {
    if (!strcmp(s, "Completed")) qrOutcome = 1;
    else if (!strcmp(s, "Failed") || !strcmp(s, "Expired") || !strcmp(s, "Cancelled")) qrOutcome = 2;
  }
}

void qrTick() {
  uint32_t now = millis();
  switch (qrState) {
    case QR_CREATING:
      if (!qrBusy && (int32_t)(now - qrNextAt) >= 0) {
        qrBusy = true;
        sendJob(JOB_CREATE_QR, qrSession, farePaise, nullptr);
      }
      break;

    case QR_SHOWING:
      if (!qrBusy && (int32_t)(now - qrNextAt) >= 0) {
        qrBusy = true;
        sendJob(JOB_QR_STATUS, qrSession, 0, qrToken);
      }
      break;

    case QR_AWAITING:
      if (!qrFinalAt && now - qrAwaitSince >= QR_OTP_CEILING_MS) {
        Serial.println("[QR] OTP ceiling reached -> final status lookup");
        qrFinalAt = now;
        qrNextAt = now;
      }
      if (!qrBusy && (int32_t)(now - qrNextAt) >= 0) {
        qrBusy = true;
        sendJob(JOB_QR_STATUS, qrSession, 0, qrToken);
      }
      if (qrFinalAt && now - qrFinalAt >= NFC_CONFIRM_MS) {            // still not definitive: do not guess
        qrBusy = false;
        qrShowProcessing(5);
      }
      break;

    case QR_PROCESSING:
      if (qrOutcome == 0 && !qrBusy && (int32_t)(now - qrNextAt) >= 0) {
        qrBusy = true;
        sendJob(JOB_QR_STATUS, qrSession, 0, qrToken);
      }
      if (qrOutcome == 0 && now - qrPhaseAt > PROCESSING_GIVEUP_MS) qrOutcome = 5;   // no definitive answer
      if (qrOutcome != 0 && now - qrPhaseAt >= PROCESSING_MS) {
        showResultPage(qrOutcome);
        qrState = QR_RESULT;
        qrPhaseAt = now;
      }
      break;

    case QR_RESULT:
      if (now - qrPhaseAt >= RESULT_MS) qrFinishTransaction();
      break;

    default:
      break;
  }
}

// ======================= NFC payment (UI side, core 1) =======================
// The PN532 is polled only while page 03 waits for a card. One idempotency key is made per
// fare when page 03 opens and reused for every retry, so a retry can never charge twice.

Adafruit_PN532 nfc(PN532_SCK, PN532_MISO, PN532_MOSI, PN532_SS);
bool     nfcReady      = false;    // PN532 answered at boot
NfcState nfcState      = NFC_IDLE;
uint32_t nfcSession    = 0;
char     nfcKey[48]    = "";       // idempotency key for this fare
char     nfcUid[16]    = "";       // card being charged
bool     nfcBusy       = false;    // pay call in flight
uint32_t nfcNextAt     = 0;        // next status lookup
uint8_t  nfcConfirmFrom = 0;       // which call was unclear: 0 pay, 1 verify-otp
uint32_t nfcConfirmAt  = 0;        // when the status lookups began
uint32_t nfcPhaseAt    = 0;        // when page 05 / 07 / 08 was shown
uint8_t  nfcOutcome    = 0;        // 0 unknown, 1 paid, 2 failed, 3 OTP needed, 4 wrong OTP,
                                   // 5 could not confirm, 6 back to page 06 (verify not applied)
uint16_t nfcPendingExpires = 300;  // expires_in_seconds of the challenge waiting to be shown

// ---- OTP step-up state (page 06) ----
char     otpChallenge[40] = "";
char     otpHint[28]      = "";
char     otpDigits[OTP_LEN + 1] = "";
uint8_t  otpLen           = 0;
int8_t   otpAttemptsLeft  = 3;
int8_t   otpResendsLeft   = 2;
uint32_t otpDeadlineAt    = 0;      // millis() when the code expires
uint32_t otpStartedAt     = 0;      // when page 06 first opened for this payment (hard ceiling OTP_CEILING_MS)
uint32_t otpLastShown     = 0xFFFFFFFF;
uint32_t otpResendAt      = 0;      // earliest millis() for the next RESEND (30 s cooldown)
bool     otpResendBusy    = false;
const uint32_t OTP_RESEND_GAP_MS = 30000;

void dwinText(uint16_t vp, const char* text, uint8_t field) {
  uint8_t buf[32];
  uint8_t n = field > sizeof(buf) ? sizeof(buf) : field;
  memset(buf, ' ', n);
  size_t len = strlen(text);
  memcpy(buf, text, len > n ? n : len);
  dwinWriteVP(vp, buf, n);
}

void otpShowDigits() {
  char shown[OTP_LEN + 1];
  for (uint8_t i = 0; i < OTP_LEN; i++) shown[i] = (i < otpLen) ? otpDigits[i] : '-';
  shown[OTP_LEN] = '\0';
  char padded[OTP_CODE_FIELD + 1];
  memset(padded, ' ', OTP_CODE_FIELD);
  memcpy(padded + (OTP_CODE_FIELD - OTP_LEN) / 2, shown, OTP_LEN);
  padded[OTP_CODE_FIELD] = '\0';
  dwinText(VP_OTP_CODE, padded, OTP_CODE_FIELD);
}

void otpShowMsg(const char* m) { dwinText(VP_OTP_MSG, m, OTP_MSG_FIELD); }

void otpShowCountdown(uint32_t now) {
  int32_t left = (int32_t)(otpDeadlineAt - now);
  uint32_t secs = left > 0 ? (uint32_t)(left + 999) / 1000 : 0;
  if (secs == otpLastShown) return;
  otpLastShown = secs;
  char t[24];
  snprintf(t, sizeof(t), "Code expires in %lu:%02lu", (unsigned long)(secs / 60), (unsigned long)(secs % 60));
  dwinText(VP_OTP_TIME, t, OTP_TIME_FIELD);
}

void otpAttemptsMsg(const char* prefix) {
  char m[32];
  snprintf(m, sizeof(m), "%s, %d attempt%s left", prefix, otpAttemptsLeft, otpAttemptsLeft == 1 ? "" : "s");
  otpShowMsg(m);
}

// Shows page 06 for a challenge (fresh = new code window and cooldown; else keep the running ones).
// msg: status line to show; "" = the default for this case.
void otpEnter(uint32_t now, uint16_t expiresIn, bool fresh, const char* msg) {
  otpLen = 0; otpDigits[0] = '\0';
  if (fresh) {
    otpDeadlineAt = now + (uint32_t)(expiresIn ? expiresIn : 300) * 1000UL;
    otpResendAt = now + OTP_RESEND_GAP_MS;
    otpStartedAt = now;
  }
  otpResendBusy = false;
  otpLastShown = 0xFFFFFFFF;
  dwinWriteWord(VP_LOADER, 0);
  dwinSetPage(PAGE_OTP);
  dwinText(VP_OTP_HINT, otpHint, OTP_HINT_FIELD);
  otpShowDigits();
  if (msg[0])      otpShowMsg(msg);
  else if (fresh)  otpShowMsg("Enter the emailed code");
  else             otpAttemptsMsg("Wrong OTP");
  otpShowCountdown(now);
  nfcState = NFC_OTP;
}

// A pay / verify call gave no usable answer: ask the backend instead of guessing (same idempotency key).
void nfcBeginConfirm(uint8_t from) {
  Serial.printf("[NFC] unclear %s result -> asking the backend for the payment status\n", from ? "verify" : "pay");
  nfcState = NFC_CONFIRMING;
  nfcConfirmFrom = from;
  nfcConfirmAt = millis();
  nfcNextAt = millis();
  nfcBusy = false;
}

void nfcInit() {
  nfc.begin();
  uint32_t v = nfc.getFirmwareVersion();
  if (!v) {
    Serial.println("[NFC] PN532 NOT FOUND — NFC payments disabled (check wiring / SPI switch)");
    return;
  }
  nfc.SAMConfig();
  nfcReady = true;
  Serial.printf("[NFC] PN532 ready, firmware %u.%u\n",
                (unsigned)((v >> 16) & 0xFF), (unsigned)((v >> 8) & 0xFF));
}

void nfcStart() {                 // entering page 03
  dwinText(VP_FAIL_MSG1, "", FAIL_MSG1_FIELD);
  dwinText(VP_FAIL_MSG2, "", FAIL_MSG2_FIELD);
  nfcSession++;
  snprintf(nfcKey, sizeof(nfcKey), "pos-%08lx%08lx",
           (unsigned long)random(0x7FFFFFFF), (unsigned long)random(0x7FFFFFFF));   // ESP32 random() = hardware RNG
  nfcUid[0] = '\0';
  nfcBusy = false;
  nfcOutcome = 0;
  nfcState = NFC_WAITING;
  dwinSetPage(PAGE_NFC_TAP);
  Serial.printf("[NFC] waiting for card (key %s)%s\n", nfcKey, nfcReady ? "" : " — PN532 not ready!");
}

void nfcAbort() {                 // BACK / CANCEL on page 03 (no payment was sent yet)
  nfcSession++;
  nfcState = NFC_IDLE;
  nfcBusy = false;
}

void nfcSendPay() {
  nfcBusy = true;
  sendNfcPayJob(nfcSession, farePaise, nfcUid, nfcKey);
}

void nfcHandleResult(const NetResult& r) {
  if (r.type == JOB_NFC_CANCEL_OTP) { Serial.printf("[NFC] cancel-otp reply HTTP %d\n", r.http); return; }
  if (r.session != nfcSession) return;                              // stale

  if (r.type == JOB_NFC_STATUS) {
    nfcBusy = false;
    if (nfcState != NFC_CONFIRMING || nfcOutcome != 0) return;
    nfcNextAt = millis() + NFC_CONFIRM_GAP_MS;
    if (!r.ok) return;                                               // lookup itself failed: keep asking
    if (!strcmp(r.status, "completed"))      { Serial.println("[NFC] status lookup: completed"); nfcOutcome = 1; }
    else if (!strcmp(r.status, "failed"))    { Serial.printf("[NFC] status lookup: failed (%s)\n", r.code); nfcOutcome = 2; }
    else if (!strcmp(r.status, "otp_pending") || !strcmp(r.status, "not_found")) {
      if (nfcConfirmFrom == 0) {                                     // the pay call never answered: same request again
        nfcState = NFC_PAYING;
        nfcBusy = true;
        nfcSendPay();                                                // same key: replays the same challenge / payment
      } else if (nfcConfirmFrom == 1 && !strcmp(r.status, "otp_pending")) {
        nfcOutcome = 6;                                              // the verify did not land: enter the code again
      }
      // nfcConfirmFrom == 2 (the OTP ran out): keep asking until the cancel is recorded or 20 s pass
    }
    return;
  }

  if (r.type == JOB_NFC_RESEND) {
    otpResendBusy = false;
    if (nfcState != NFC_OTP) return;
    if (r.ok && !strcmp(r.status, "otp_required")) {
      otpDeadlineAt = millis() + (uint32_t)(r.expiresIn ? r.expiresIn : 300) * 1000UL;
      if (r.resendsLeft >= 0) otpResendsLeft = r.resendsLeft;
      otpResendAt = millis() + OTP_RESEND_GAP_MS;
      otpLastShown = 0xFFFFFFFF;
      otpShowMsg("New code sent");
    } else if (r.http == 429) {
      otpResendAt = millis() + 5000;
      otpShowMsg("Please wait, then resend");
    } else if (r.http == 400) {
      otpResendsLeft = 0;
      otpShowMsg("No more codes can be sent");
    } else if (r.http == 200) {                      // the challenge was already closed on the backend: definitive
      nfcOutcome = 2; nfcPhaseAt = millis() - PROCESSING_MS; nfcState = NFC_VERIFYING; nfcBusy = false;
      dwinWriteWord(VP_LOADER, 1); dwinSetPage(PAGE_PROCESSING);
    } else {
      otpShowMsg("Network problem, try again");
    }
    return;
  }

  if (nfcState != NFC_PAYING && nfcState != NFC_VERIFYING && nfcState != NFC_CONFIRMING) return;
  nfcBusy = false;
  if (nfcOutcome == 1 || nfcOutcome == 2) return;                    // already decided

  if (r.http == 200 && !strcmp(r.status, "otp_required") && r.challenge[0]) {
    Serial.println("[NFC] fraud check: passenger must verify an emailed OTP");
    strlcpy(otpChallenge, r.challenge, sizeof(otpChallenge));
    strlcpy(otpHint, r.hint, sizeof(otpHint));
    otpAttemptsLeft = r.attemptsLeft >= 0 ? r.attemptsLeft : 3;
    otpResendsLeft = r.resendsLeft >= 0 ? r.resendsLeft : 2;
    nfcPendingExpires = r.expiresIn ? r.expiresIn : 300;
    nfcOutcome = 3;                      // page 05 stays at least PROCESSING_MS, then page 06
    return;
  }
  if (r.http == 200 && !strcmp(r.status, "otp_invalid")) {
    otpAttemptsLeft = r.attemptsLeft >= 0 ? r.attemptsLeft : 0;
    nfcOutcome = 4;                      // wrong code: back to page 06 after PROCESSING_MS
    return;
  }

  if (r.ok && !strcmp(r.status, "Completed")) {
    Serial.printf("[NFC] paid by %s\n", r.name[0] ? r.name : "passenger");
    nfcOutcome = 1;
    return;
  }
  // A definite answer from the backend (card unknown/blocked, low balance, ...) -> failed.
  if (r.http == 200 || r.http == 400 || r.http == 403 || r.http == 409 || r.http == 422) {
    Serial.printf("[NFC] payment refused: %s (HTTP %d)\n", r.code[0] ? r.code : "?", r.http);
    nfcOutcome = 2;
    return;
  }
  // No usable answer (Wi-Fi down, timeout, Render 5xx): never show "failed" for this. Ask the backend.
  Serial.printf("[NFC] unclear answer (HTTP %d)\n", r.http);
  if (nfcState != NFC_CONFIRMING) nfcBeginConfirm(r.type == JOB_NFC_VERIFY ? 1 : 0);
}

void nfcTick() {
  uint32_t now = millis();
  switch (nfcState) {
    case NFC_WAITING: {
      if (!nfcReady) break;
      uint8_t uid[7];
      uint8_t len = 0;
      if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &len, NFC_READ_TIMEOUT_MS)) {
        if (len != 4 && len != 7) { Serial.printf("[NFC] ignored card with %u-byte UID\n", len); break; }
        for (uint8_t i = 0; i < len; i++) sprintf(nfcUid + i * 2, "%02X", uid[i]);
        Serial.printf("[NFC] card %s -> paying Rs %lu.%02lu\n", nfcUid,
                      (unsigned long)(farePaise / 100), (unsigned long)(farePaise % 100));
        nfcState = NFC_PAYING;
        nfcOutcome = 0;
        nfcPhaseAt = now;
        dwinWriteWord(VP_LOADER, 1);
        dwinSetPage(PAGE_PROCESSING);
        nfcSendPay();
      }
      break;
    }

    case NFC_PAYING:
    case NFC_VERIFYING:
    case NFC_CONFIRMING:
      if (nfcState == NFC_CONFIRMING && nfcOutcome == 0) {
        if (!nfcBusy && (int32_t)(now - nfcNextAt) >= 0) {
          nfcBusy = true;
          sendNfcStatusJob(nfcSession, nfcKey);
        }
        if (now - nfcConfirmAt > NFC_CONFIRM_MS) {                   // still unknown: do not guess, do not retry the charge
          Serial.println("[NFC] could not confirm the payment status");
          nfcOutcome = 5;
        }
      } else if (nfcOutcome == 0 && nfcBusy && now - nfcPhaseAt > NFC_WATCHDOG_MS) {
        nfcBeginConfirm(nfcState == NFC_VERIFYING ? 1 : 0);          // a call is stuck: stop waiting for it
      }
      if ((nfcOutcome == 3 || nfcOutcome == 4 || nfcOutcome == 6) && now - nfcPhaseAt >= PROCESSING_MS) {
        if (nfcOutcome == 6) {                                       // verify not applied: same challenge, keep the timers
          otpEnter(now, 0, false, "Not confirmed, enter again");
        } else if (nfcOutcome == 4) {
          otpEnter(now, 0, false, "");
        } else {
          otpEnter(now, nfcPendingExpires, true, "");
        }
        nfcOutcome = 0;
        break;
      }
      if ((nfcOutcome == 1 || nfcOutcome == 2 || nfcOutcome == 5) && now - nfcPhaseAt >= PROCESSING_MS) {
        showResultPage(nfcOutcome);
        nfcState = NFC_RESULT;
        nfcPhaseAt = now;
      }
      break;

    case NFC_OTP: {
      otpShowCountdown(now);
      if ((int32_t)(now - otpDeadlineAt) >= 0 || now - otpStartedAt >= OTP_CEILING_MS) {
        // The code ran out (5 min) or the 6 min ceiling hit: close the challenge, then trust the backend's answer.
        Serial.println("[NFC] OTP expired / ceiling -> cancel and ask the backend");
        sendNfcOtpJob(JOB_NFC_CANCEL_OTP, nfcSession, otpChallenge, nullptr, nullptr);
        nfcOutcome = 0; nfcPhaseAt = now;
        dwinWriteWord(VP_LOADER, 1); dwinSetPage(PAGE_PROCESSING);
        nfcBeginConfirm(2);
      }
      break;
    }

    case NFC_RESULT:
      if (now - nfcPhaseAt >= RESULT_MS) {
        nfcState = NFC_IDLE;
        nfcSession++;
        qrFinishTransaction();    // shared: clears the fare and returns home
      }
      break;

    default:
      break;
  }
}

// Network replies for both payment types arrive on one queue.
void drainNetResults() {
  NetResult r;
  while (xQueueReceive(netResults, &r, 0) == pdTRUE) {
    if (r.type >= JOB_NFC_PAY) nfcHandleResult(r);
    else                       qrHandleResult(r);
  }
}

// ======================= Transaction navigation =======================

void backToPaymentMethod() {
  if (payMethod == PAY_QR) qrAbort();
  if (payMethod == PAY_NFC) nfcAbort();
  payMethod = PAY_NONE;
  Serial.println("[PAY] back to payment method (fare kept)");
  dwinSetPage(PAGE_PAYMENT_METHOD);
}

void cancelTransaction() {
  if (payMethod == PAY_QR) qrAbort();
  if (payMethod == PAY_NFC) nfcAbort();
  Serial.printf("[PAY] cancelled (was Rs %lu.%02lu)\n",
                (unsigned long)(farePaise / 100), (unsigned long)(farePaise % 100));
  payMethod = PAY_NONE;
  farePaise = 0;
  resetAmount();
  dwinSetPage(PAGE_HOME);
}

// ======================= Key handling =======================

void handleKey(uint16_t key) {
  Serial.printf("[KEY] 0x%04X on page %u\n", key, currentPage);

  switch (currentPage) {
    case PAGE_HOME:
      if (key == KEY_ENTER_AMOUNT) { resetAmount(); dwinSetPage(PAGE_ENTER_AMOUNT); }
      break;

    case PAGE_ENTER_AMOUNT:
      if (key >= KEY_DIGIT_1 && key <= KEY_DIGIT_9) tryAppend('1' + (key - KEY_DIGIT_1));
      else if (key == KEY_DIGIT_0)   tryAppend('0');
      else if (key == KEY_DECIMAL)   tryAppend('.');
      else if (key == KEY_BACKSPACE) backspace();
      else if (key == KEY_BACK)      { resetAmount(); dwinSetPage(PAGE_HOME); }
      else if (key == KEY_NEXT) {
        uint32_t p = textToPaise(amountText);
        if (p >= MIN_PAISE && p <= MAX_PAISE) {
          farePaise = p;
          Serial.printf("[AMT] confirmed: Rs %lu.%02lu\n", (unsigned long)(p / 100), (unsigned long)(p % 100));
          dwinSetPage(PAGE_PAYMENT_METHOD);
        } else {
          Serial.println("[AMT] NEXT refused: enter at least Rs 1.00");
        }
      }
      break;

    case PAGE_PAYMENT_METHOD:
      if (key == KEY_PAY_NFC) {
        payMethod = PAY_NFC;
        Serial.printf("[PAY] NFC selected for Rs %lu.%02lu\n",
                      (unsigned long)(farePaise / 100), (unsigned long)(farePaise % 100));
        nfcStart();
      } else if (key == KEY_PAY_QR) {
        payMethod = PAY_QR;
        Serial.printf("[PAY] QR selected for Rs %lu.%02lu\n",
                      (unsigned long)(farePaise / 100), (unsigned long)(farePaise % 100));
        qrStart();
      } else if (key == KEY_PAY_BACK) {
        payMethod = PAY_NONE;
        showAmount();
        dwinSetPage(PAGE_ENTER_AMOUNT);
      }
      break;

    case PAGE_NFC_TAP:                       // card reading runs in nfcTick()
      if (nfcState != NFC_WAITING) break;    // a card was already read: payment in progress
      if (key == KEY_NFC_BACK)        backToPaymentMethod();
      else if (key == KEY_NFC_CANCEL) cancelTransaction();
      break;

    case PAGE_QR_CODE:
      if (qrState == QR_AWAITING) {          // passenger is entering an OTP: BACK and CANCEL both cancel it and go home
        if (key == KEY_QR_BACK || key == KEY_QR_CANCEL) {
          Serial.println("[QR] driver cancelled a payment that was awaiting OTP");
          cancelTransaction();               // qrAbort() -> POST /api/qr/{token}/cancel (cancels the OTP challenge too)
        }
        break;
      }
      if (key == KEY_QR_BACK)        backToPaymentMethod();
      else if (key == KEY_QR_CANCEL) cancelTransaction();
      break;

    case PAGE_OTP:                           // page 06: OTP entry (nfcState == NFC_OTP)
      if (nfcState != NFC_OTP) break;
      if ((key >= KEY_DIGIT_1 && key <= KEY_DIGIT_9) || key == KEY_DIGIT_0) {
        if (otpLen < OTP_LEN) {
          otpDigits[otpLen++] = (key == KEY_DIGIT_0) ? '0' : (char)('1' + (key - KEY_DIGIT_1));
          otpDigits[otpLen] = '\0';
          otpShowDigits();
        }
      } else if (key == KEY_OTP_DELETE) {
        if (otpLen) { otpDigits[--otpLen] = '\0'; otpShowDigits(); }
      } else if (key == KEY_OTP_SUBMIT) {
        if (otpLen != OTP_LEN) { otpShowMsg("Enter all 6 digits"); break; }
        nfcState = NFC_VERIFYING;
        nfcOutcome = 0; nfcBusy = true; nfcPhaseAt = millis();
        dwinWriteWord(VP_LOADER, 1);
        dwinSetPage(PAGE_PROCESSING);
        Serial.println("[NFC] verifying OTP");
        sendNfcOtpJob(JOB_NFC_VERIFY, nfcSession, otpChallenge, otpDigits, nfcKey);
      } else if (key == KEY_OTP_RESEND) {
        if (otpResendsLeft <= 0) otpShowMsg("No more codes can be sent");
        else if (otpResendBusy || (int32_t)(millis() - otpResendAt) < 0) otpShowMsg("Please wait to resend");
        else {
          otpResendBusy = true;
          otpLen = 0; otpDigits[0] = '\0'; otpShowDigits();
          otpShowMsg("Sending a new code...");
          sendNfcOtpJob(JOB_NFC_RESEND, nfcSession, otpChallenge, nullptr, nullptr);
        }
      } else if (key == KEY_OTP_CANCEL) {
        Serial.println("[NFC] OTP cancelled by the driver");
        sendNfcOtpJob(JOB_NFC_CANCEL_OTP, nfcSession, otpChallenge, nullptr, nullptr);
        nfcSession++;
        nfcState = NFC_IDLE;
        otpChallenge[0] = '\0'; otpLen = 0; otpDigits[0] = '\0';
        payMethod = PAY_NONE; farePaise = 0; resetAmount();
        dwinSetPage(PAGE_HOME);
      }
      break;

    default:                                 // pages 05 / 07 / 08 have no buttons
      break;
  }
}

// ======================= Frame parser =======================

void handleFrame(const uint8_t* f, uint8_t len) {
  if (len >= 6 && f[0] == 0x83) {
    uint16_t vp    = (f[1] << 8) | f[2];
    uint16_t value = (f[4] << 8) | f[5];
    if (vp == VP_KEY) handleKey(value);
  }
}

void pollDwin() {
  static uint8_t state = 0, len = 0, idx = 0;
  static uint8_t buf[64];
  while (dwin.available()) {
    uint8_t b = dwin.read();
    switch (state) {
      case 0: if (b == 0x5A) state = 1; break;
      case 1: state = (b == 0xA5) ? 2 : (b == 0x5A ? 1 : 0); break;
      case 2:
        if (b == 0 || b > sizeof(buf)) { state = 0; break; }
        len = b; idx = 0; state = 3; break;
      case 3:
        buf[idx++] = b;
        if (idx >= len) { handleFrame(buf, len); state = 0; }
        break;
    }
  }
}

// ======================= Touch auto-upload switch =======================

void enableAutoUpload() {
  while (dwin.available()) dwin.read();
  const uint8_t rd[] = {0x5A, 0xA5, 0x04, 0x83, 0x00, 0x80, 0x02};
  dwin.write(rd, sizeof(rd));
  uint8_t r[11]; uint8_t n = 0;
  uint32_t t0 = millis();
  while (millis() - t0 < 300 && n < sizeof(r)) {
    if (dwin.available()) {
      uint8_t b = dwin.read();
      if (n == 0 && b != 0x5A) continue;
      r[n++] = b;
    }
  }
  if (n < 11 || r[3] != 0x83 || r[4] != 0x00 || r[5] != 0x80) {
    Serial.println("[CFG] could not read 0x0080 — auto-upload not changed");
    return;
  }
  uint8_t cfg = r[10];
  Serial.printf("[CFG] system config 0x%02X  (auto-upload %s)\n", cfg, (cfg & 0x10) ? "ON" : "OFF");
  if (!(cfg & 0x10)) {
    uint8_t d[4] = {0x5A, 0x00, 0x00, (uint8_t)(cfg | 0x10)};
    dwinWriteVP(0x0080, d, 4);
    delay(50);
    while (dwin.available()) dwin.read();
    Serial.println("[CFG] auto-upload switched ON");
  }
}

// ======================= Wi-Fi / clock =======================

void serviceClock() {
  if (strlen(WIFI_SSID) == 0) return;
  static bool ntpStarted = false, hwSet = false;
  static uint32_t lastPush = 0;
  static wl_status_t lastStatus = WL_IDLE_STATUS;

  wl_status_t st = WiFi.status();
  if (st != lastStatus) {
    lastStatus = st;
    if (st == WL_CONNECTED) Serial.printf("[WiFi] connected, IP %s\n", WiFi.localIP().toString().c_str());
    else                    Serial.printf("[WiFi] status %d (not connected)\n", (int)st);
  }
  if (st != WL_CONNECTED && !ntpStarted) return;
  if (!ntpStarted) { configTime(19800, 0, "pool.ntp.org", "time.google.com"); ntpStarted = true; }

  if (millis() - lastPush < 20000UL && lastPush != 0) return;
  struct tm t;
  if (getLocalTime(&t, 10)) {
    dwinWriteTime(t, !hwSet);
    if (!hwSet) Serial.printf("[RTC] time set: %02d:%02d\n", t.tm_hour, t.tm_min);
    hwSet = true;
    lastPush = millis();
  }
}

// ======================= Setup / loop =======================

void setup() {
  Serial.begin(115200);
  dwin.begin(DWIN_BAUD, SERIAL_8N1, DWIN_RX_PIN, DWIN_TX_PIN);
  delay(500);

  Serial.println("\nTap & Go POS");
  enableAutoUpload();
  dwinSetBrightness(SCREEN_BRIGHTNESS, SCREEN_BRIGHTNESS);
  resetAmount();
  dwinClearQR();
  dwinSetPage(PAGE_HOME);

  nfcInit();

  netJobs    = xQueueCreate(6, sizeof(NetJob));
  netResults = xQueueCreate(6, sizeof(NetResult));
  xTaskCreatePinnedToCore(netTask, "net", 12288, nullptr, 1, nullptr, 0);

  if (strlen(WIFI_SSID) > 0) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.printf("[WiFi] connecting to %s ...\n", WIFI_SSID);
  } else {
    Serial.println("[WiFi] no SSID set — clock and payments will not work");
  }
}

void loop() {
  pollDwin();
  drainNetResults();
  qrTick();
  nfcTick();
  serviceClock();
}
