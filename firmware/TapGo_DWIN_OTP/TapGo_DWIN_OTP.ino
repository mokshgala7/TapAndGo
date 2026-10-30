/*
 * Tap & Go POS — ESP32-S3 + DWIN DGUS II + PN532  (screens 00-08, QR and NFC payment)
 * ---------------------------------------------------------------------------
 * Board   : ESP32-S3 Dev Module (Arduino IDE, ESP32 core 2.x or 3.x)
 *           USB CDC On Boot: Enabled  (Serial monitor at 115200)
 * Display : DWIN DMG48270C043_05WTC, 480x272, TTL mode (pads bridged, 3.3 V)
 * Device  : logs in as the configured POS driver account at boot
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
 *   network error -> the SAME request is retried (same idempotency key, so it can
 *                    never charge twice) until NFC_GIVEUP_MS, then page 08
 *   BACK -> page 02 (fare kept)   CANCEL -> home (fare cleared)
 *
 * Fraud check / OTP step (the ML model and the 10-minute rule run on the backend):
 *   backend answers "otp_required" -> page 06 (OTP Verification)
 *   the passenger gets a 6-digit code by email
 *   TEMPORARY: page 06 has no keypad yet, so the code is typed in the Arduino
 *   Serial Monitor (115200 baud, line ending "Newline") and Enter is pressed
 *     correct code -> page 05 for 3 s -> page 07 (paid) -> home
 *     wrong code   -> the OTP is cancelled on the backend (no money moves)
 *                     -> page 05 for 3 s -> page 08 (failed) -> home
 *     code expired -> cancelled on the backend -> page 05 -> page 08 -> home
 *   Serial commands on page 06: RESEND (send the email again), CANCEL (go home)
 *   The typed code is never printed or logged; it only goes in the verify request.
 *
 * QR + OTP: the passenger types the code on the website. While the backend says
 *   "AwaitingOtp" the QR is cleared and page 04 stays, BACK/CANCEL still work.
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

const char* WIFI_SSID = "YOUR_WIFI_NAME";   // set before flashing
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";   // set before flashing

const char* API_BASE        = "https://tap-go-backend.onrender.com";
const char* DRIVER_ACCOUNT  = "YOUR_DRIVER_ACCOUNT";   // set before flashing
const char* DRIVER_PASSWORD = "YOUR_DRIVER_PASSWORD";   // set before flashing


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
const uint32_t NFC_RETRY_MS        = 2000;   // retry a pay call that hit a network error
const uint32_t NFC_GIVEUP_MS       = 45000;  // no answer from the backend after this -> failed
const uint32_t OTP_GRACE_MS        = 5000;   // extra time after the backend's OTP expiry before we give up
const uint32_t OTP_VERIFY_GIVEUP_MS = 45000; // verify call with no definite answer after this -> failed
const uint32_t OTP_STATUS_RETRY_MS = 2000;   // status lookup retry after a network problem
// =================================================================

// VP addresses
const uint16_t VP_KEY       = 0x1000;
const uint16_t VP_AMOUNT    = 0x1100;   // text, 18 bytes
const uint16_t VP_QR        = 0x1300;   // QR text
const uint16_t VP_LOADER    = 0x1500;   // animation icon on page 05
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

// Pages
const uint8_t PAGE_HOME           = 0;
const uint8_t PAGE_ENTER_AMOUNT   = 1;
const uint8_t PAGE_PAYMENT_METHOD = 2;
const uint8_t PAGE_NFC_TAP        = 3;
const uint8_t PAGE_QR_CODE        = 4;
const uint8_t PAGE_PROCESSING     = 5;
const uint8_t PAGE_OTP            = 6;   // OTP Verification (code typed in the Serial Monitor for now)
const uint8_t PAGE_SUCCESS        = 7;
const uint8_t PAGE_FAILED         = 8;

enum PayMethod : uint8_t { PAY_NONE, PAY_NFC, PAY_QR };
PayMethod payMethod = PAY_NONE;

// Types for the network task. They must stay ABOVE the first function:
// Arduino IDE inserts automatic function declarations there.
enum JobType : uint8_t { JOB_CREATE_QR, JOB_QR_STATUS, JOB_QR_CANCEL, JOB_NFC_PAY,
                         JOB_NFC_VERIFY, JOB_NFC_RESEND, JOB_NFC_CANCEL_OTP, JOB_NFC_STATUS };

struct NetJob {
  JobType  type;
  uint32_t session;      // which QR / NFC attempt this belongs to
  uint32_t paise;
  char     token[48];    // QR token, or the idempotency key for JOB_NFC_PAY
  char     uid[16];      // card UID for JOB_NFC_PAY (uppercase hex)
  char     challenge[40];// OTP challenge id (JOB_NFC_VERIFY / RESEND / CANCEL_OTP)
  char     otp[8];       // 6-digit code (JOB_NFC_VERIFY only) - never logged
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
  char     challenge[40];// NFC: OTP challenge id when status is otp_required
  char     hint[40];     // NFC: masked email the code was sent to, e.g. m***@g***.com
  int16_t  attempts;     // NFC: OTP attempts left (-1 if not in the reply)
};

enum NfcState : uint8_t { NFC_IDLE, NFC_WAITING, NFC_PAYING, NFC_OTP, NFC_VERIFYING, NFC_RESULT };

enum QrState : uint8_t { QR_IDLE, QR_CREATING, QR_SHOWING, QR_PROCESSING, QR_RESULT };

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
      strlcpy(r.code, jsonString(resp, "code").c_str(), sizeof(r.code));
      strlcpy(r.name, jsonString(resp, "passenger_name").c_str(), sizeof(r.name));
      strlcpy(r.challenge, jsonString(resp, "challenge_id").c_str(), sizeof(r.challenge));
      strlcpy(r.hint, jsonString(resp, "email_hint").c_str(), sizeof(r.hint));
      r.expiresIn = (uint16_t)jsonNumber(resp, "expires_in_seconds", 300);
      r.attempts = (int16_t)jsonNumber(resp, "attempts_left", -1);
    } else if (job.type == JOB_NFC_VERIFY) {
      char body[200];
      snprintf(body, sizeof(body), "{\"challenge_id\":\"%s\",\"otp\":\"%s\",\"idempotency_key\":\"%s\"}",
               job.challenge, job.otp, job.token);
      r.http = authedCall("POST", "/api/nfc/pay/verify-otp", body, resp);
      memset(body, 0, sizeof(body));        // drop the code from memory
      r.ok = (r.http == 200 && resp.indexOf("\"success\":true") >= 0);
      strlcpy(r.code, jsonString(resp, "code").c_str(), sizeof(r.code));
      strlcpy(r.name, jsonString(resp, "passenger_name").c_str(), sizeof(r.name));
      r.attempts = (int16_t)jsonNumber(resp, "attempts_left", -1);
    } else if (job.type == JOB_NFC_RESEND || job.type == JOB_NFC_CANCEL_OTP) {
      char body[80];
      snprintf(body, sizeof(body), "{\"challenge_id\":\"%s\"}", job.challenge);
      r.http = authedCall("POST", job.type == JOB_NFC_RESEND ? "/api/nfc/pay/resend-otp" : "/api/nfc/pay/cancel-otp",
                          body, resp);
      r.ok = (r.http == 200);
      strlcpy(r.code, jsonString(resp, "code").c_str(), sizeof(r.code));
      strlcpy(r.hint, jsonString(resp, "email_hint").c_str(), sizeof(r.hint));
      r.expiresIn = (uint16_t)jsonNumber(resp, "expires_in_seconds", 0);
      r.attempts = (int16_t)jsonNumber(resp, "attempts_left", -1);
    } else if (job.type == JOB_NFC_STATUS) {
      r.http = authedCall("GET", String("/api/nfc/pay/status?idempotency_key=") + job.token, "", resp);
      r.ok = (r.http == 200);
      strlcpy(r.code, jsonString(resp, "failure_code").c_str(), sizeof(r.code));
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

void sendNfcPayJob(uint32_t session, uint32_t paise, const char* uid, const char* key) {
  NetJob j = {};
  j.type = JOB_NFC_PAY; j.session = session; j.paise = paise;
  strlcpy(j.token, key, sizeof(j.token));
  strlcpy(j.uid, uid, sizeof(j.uid));
  xQueueSend(netJobs, &j, 0);
}

void sendNfcOtpJob(JobType type, uint32_t session, const char* challenge, const char* otp, const char* key) {
  NetJob j = {};
  j.type = type; j.session = session;
  if (key) strlcpy(j.token, key, sizeof(j.token));
  if (challenge) strlcpy(j.challenge, challenge, sizeof(j.challenge));
  if (otp) strlcpy(j.otp, otp, sizeof(j.otp));
  xQueueSend(netJobs, &j, 0);
  memset(j.otp, 0, sizeof(j.otp));
}

// ======================= QR payment (UI side, core 1) =======================

QrState  qrState     = QR_IDLE;
uint32_t qrSession   = 0;        // bumps on every new attempt; stale replies are ignored
char     qrToken[48] = "";
bool     qrBusy      = false;    // a create/status call is in flight
uint32_t qrNextAt    = 0;        // next create retry / status poll
uint32_t qrPhaseAt   = 0;        // when page 05 / 07 / 08 was shown
uint8_t  qrOutcome   = 0;        // 0 unknown, 1 paid, 2 failed
bool     qrAwaitingOtp = false;  // passenger is typing an emailed OTP on the website

void qrStart() {                 // entering page 04
  qrSession++;
  qrToken[0] = '\0';
  qrBusy = false;
  qrOutcome = 0;
  qrAwaitingOtp = false;
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
  dwinClearQR();
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
  qrNextAt = millis() + QR_POLL_GAP_MS;
  if (!r.ok) return;              // network hiccup: just poll again
  const char* s = r.status;

  if (qrState == QR_SHOWING) {
    if (!strcmp(s, "Completed"))       qrShowProcessing(1);
    else if (!strcmp(s, "Failed"))     qrShowProcessing(2);
    else if (!strcmp(s, "Processing")) qrShowProcessing(0);
    else if (!strcmp(s, "AwaitingOtp")) {
      if (!qrAwaitingOtp) {
        qrAwaitingOtp = true;
        dwinClearQR();
        Serial.println("[QR] fraud check: OTP sent to the passenger's email - waiting for them to enter it on the website");
      }
    }
    else if (!strcmp(s, "Expired") || !strcmp(s, "Cancelled")) {
      Serial.println("[QR] expired -> new QR for the same fare");
      qrToken[0] = '\0';
      qrState = QR_CREATING;
      qrNextAt = millis();
      dwinClearQR();
    }
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

    case QR_PROCESSING:
      if (qrOutcome == 0 && !qrBusy && (int32_t)(now - qrNextAt) >= 0) {
        qrBusy = true;
        sendJob(JOB_QR_STATUS, qrSession, 0, qrToken);
      }
      if (qrOutcome == 0 && now - qrPhaseAt > PROCESSING_GIVEUP_MS) qrOutcome = 2;
      if (qrOutcome != 0 && now - qrPhaseAt >= PROCESSING_MS) {
        Serial.printf("[PAY] %s\n", qrOutcome == 1 ? "PAYMENT SUCCESSFUL" : "PAYMENT FAILED");
        dwinWriteWord(VP_LOADER, 0);
        dwinSetPage(qrOutcome == 1 ? PAGE_SUCCESS : PAGE_FAILED);
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

void cancelTransaction();   // defined further down

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
uint32_t nfcNextAt     = 0;        // next retry
uint32_t nfcPhaseAt    = 0;        // when page 05 / 07 / 08 was shown
uint8_t  nfcOutcome    = 0;        // 0 unknown, 1 paid, 2 failed

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

void nfcAbort() {                 // BACK / CANCEL on page 03, or CANCEL during the OTP step
  nfcSession++;
  nfcState = NFC_IDLE;
  nfcBusy = false;
}

void nfcSendPay() {
  nfcBusy = true;
  sendNfcPayJob(nfcSession, farePaise, nfcUid, nfcKey);
}

// ---------- OTP step (page 06, code typed in the Serial Monitor for now) ----------
char     nfcChallenge[40] = "";    // OTP challenge id from the backend
char     nfcOtp[8]        = "";    // code being verified (kept only for a retry, wiped after)
uint32_t nfcOtpDeadline   = 0;     // when the emailed code stops working (+ grace)
uint32_t nfcLastCountdown = 0;     // last countdown line printed
bool     nfcWantStatus    = false; // verify hit a network problem: look the result up

// Reads one line from the Serial Monitor without blocking. Returns true when a line is ready.
bool readSerialLine(char* out, size_t outSize) {
  static char buf[20];
  static uint8_t n = 0;
  static bool overflow = false;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (n == 0 && !overflow) continue;            // empty line / second half of CRLF
      buf[n] = '\0';
      bool bad = overflow;
      n = 0; overflow = false;
      if (bad) { strlcpy(out, "#", outSize); return true; }   // too long -> invalid
      char* s = buf;                                  // trim spaces
      while (*s == ' ' || *s == '\t') s++;
      char* e = s + strlen(s);
      while (e > s && (e[-1] == ' ' || e[-1] == '\t')) *--e = '\0';
      if (!*s) continue;
      strlcpy(out, s, outSize);
      memset(buf, 0, sizeof(buf));
      return true;
    }
    if (n < sizeof(buf) - 1) buf[n++] = c; else overflow = true;
  }
  return false;
}

void flushSerialInput() { while (Serial.available()) Serial.read(); }

// 'D' six digits, 'R' RESEND, 'C' CANCEL, 'X' anything else
char classifyOtpLine(const char* s) {
  if (strlen(s) == 6) {
    bool digits = true;
    for (uint8_t i = 0; i < 6; i++) if (s[i] < '0' || s[i] > '9') digits = false;
    if (digits) return 'D';
  }
  if (!strcasecmp(s, "RESEND")) return 'R';
  if (!strcasecmp(s, "CANCEL")) return 'C';
  return 'X';
}

void nfcClearOtp() {
  memset(nfcOtp, 0, sizeof(nfcOtp));
  nfcChallenge[0] = '\0';
  nfcWantStatus = false;
}

// Show page 05 for PROCESSING_MS, then 07 (paid) or 08 (failed).
void nfcFinishWith(uint8_t outcome) {
  nfcOutcome = outcome;
  if (nfcState != NFC_VERIFYING && nfcState != NFC_PAYING) {
    nfcState = NFC_VERIFYING;
    nfcPhaseAt = millis();
    dwinWriteWord(VP_LOADER, 1);
    dwinSetPage(PAGE_PROCESSING);
  }
}

void nfcEnterOtp(const NetResult& r) {
  strlcpy(nfcChallenge, r.challenge, sizeof(nfcChallenge));
  uint32_t secs = r.expiresIn ? r.expiresIn : 300;
  nfcOtpDeadline = millis() + secs * 1000UL + OTP_GRACE_MS;
  nfcLastCountdown = millis();
  nfcState = NFC_OTP;
  nfcBusy = false;
  dwinWriteWord(VP_LOADER, 0);
  dwinSetPage(PAGE_OTP);
  flushSerialInput();
  Serial.println("--------------------------------------------------------------");
  Serial.println("[OTP] FRAUD CHECK: this payment needs an OTP (ML risk or 10-minute rule).");
  Serial.printf("[OTP] Page 06 open. Code emailed to %s. Expires in %lu s. Attempts left: %d.\n",
                r.hint[0] ? r.hint : "the passenger", (unsigned long)secs, (int)r.attempts);
  Serial.println("[OTP] Type the 6-digit code here and press Enter.  Commands: RESEND, CANCEL");
  Serial.println("[OTP] A wrong code cancels the payment (page 08). No money moves without the right code.");
  Serial.println("--------------------------------------------------------------");
}

// Wrong code / expiry: close the challenge on the backend, then page 05 -> 08.
void nfcFailOtp(const char* why) {
  Serial.printf("[OTP] %s -> payment cancelled, no money moved\n", why);
  if (nfcChallenge[0]) sendNfcOtpJob(JOB_NFC_CANCEL_OTP, nfcSession, nfcChallenge, nullptr, nullptr);
  memset(nfcOtp, 0, sizeof(nfcOtp));
  nfcWantStatus = false;
  nfcFinishWith(2);
}

void nfcHandleResult(const NetResult& r) {
  if (r.session != nfcSession) return;   // stale

  // ---- the first pay call ----
  if (r.type == JOB_NFC_PAY) {
    if (nfcState != NFC_PAYING) return;
    nfcBusy = false;
    if (r.ok && !strcmp(r.status, "Completed")) {
      Serial.printf("[NFC] paid by %s (fraud check passed)\n", r.name[0] ? r.name : "passenger");
      nfcOutcome = 1;
      return;
    }
    if (r.http == 200 && !strcmp(r.status, "otp_required")) {
      if (!r.challenge[0]) { Serial.println("[OTP] otp_required without a challenge id -> failed"); nfcOutcome = 2; return; }
      nfcEnterOtp(r);
      return;
    }
    // A definite answer from the backend (card unknown/blocked, low balance, ...) -> failed.
    if (r.http == 200 || r.http == 400 || r.http == 403 || r.http == 409 || r.http == 422) {
      Serial.printf("[NFC] payment refused: %s (HTTP %d)\n", r.code[0] ? r.code : "?", r.http);
      nfcOutcome = 2;
      return;
    }
    // No usable answer (Wi-Fi down, timeout, Render 5xx): retry the same request later.
    Serial.printf("[NFC] network problem (HTTP %d) - retrying with the same key\n", r.http);
    nfcNextAt = millis() + NFC_RETRY_MS;
    return;
  }

  // ---- RESEND (only meaningful while page 06 waits) ----
  if (r.type == JOB_NFC_RESEND) {
    if (nfcState != NFC_OTP) return;
    if (r.http == 200 && !strcmp(r.status, "otp_required")) {
      if (r.expiresIn) nfcOtpDeadline = millis() + r.expiresIn * 1000UL + OTP_GRACE_MS;
      Serial.printf("[OTP] new code emailed to %s (expires in %u s)\n", r.hint[0] ? r.hint : "the passenger", r.expiresIn);
    } else if (r.http == 429) {
      Serial.println("[OTP] resend refused: wait a few seconds and try RESEND again");
    } else if (r.http > 0) {
      Serial.printf("[OTP] resend refused (%s, HTTP %d)\n", r.code[0] ? r.code : r.status, r.http);
    } else {
      Serial.println("[OTP] resend failed: network problem, try again");
    }
    return;
  }

  // ---- CANCEL reply: nothing to do, the screen already moved on ----
  if (r.type == JOB_NFC_CANCEL_OTP) {
    Serial.printf("[OTP] cancel acknowledged (HTTP %d)\n", r.http);
    return;
  }

  if (nfcState != NFC_VERIFYING || nfcOutcome != 0) return;
  nfcBusy = false;

  // ---- VERIFY ----
  if (r.type == JOB_NFC_VERIFY) {
    if (r.ok && !strcmp(r.status, "Completed")) {
      Serial.println("[OTP] correct code -> payment completed");
      memset(nfcOtp, 0, sizeof(nfcOtp));
      nfcOutcome = 1;
      return;
    }
    if (r.http == 200 && !strcmp(r.status, "otp_invalid")) { nfcFailOtp("wrong code"); return; }
    if (r.http == 200 || r.http == 400 || r.http == 403 || r.http == 404 || r.http == 409) {
      Serial.printf("[OTP] failed: %s (HTTP %d)\n", r.code[0] ? r.code : r.status, r.http);
      memset(nfcOtp, 0, sizeof(nfcOtp));
      nfcOutcome = 2;
      return;
    }
    Serial.printf("[OTP] network problem during verify (HTTP %d) - checking the result\n", r.http);
    nfcWantStatus = true;
    nfcNextAt = millis() + OTP_STATUS_RETRY_MS;
    return;
  }

  // ---- STATUS lookup after a lost verify reply ----
  if (r.type == JOB_NFC_STATUS) {
    if (!r.ok) { nfcNextAt = millis() + OTP_STATUS_RETRY_MS; return; }
    if (!strcmp(r.status, "completed")) {
      Serial.println("[OTP] backend confirms: payment completed");
      memset(nfcOtp, 0, sizeof(nfcOtp)); nfcWantStatus = false; nfcOutcome = 1;
    } else if (!strcmp(r.status, "failed") || !strcmp(r.status, "not_found")) {
      Serial.printf("[OTP] backend confirms: not paid (%s)\n", r.code[0] ? r.code : r.status);
      memset(nfcOtp, 0, sizeof(nfcOtp)); nfcWantStatus = false; nfcOutcome = 2;
    } else {   // otp_pending: our verify never arrived -> send the same code again
      Serial.println("[OTP] verify did not reach the backend - sending it again");
      nfcWantStatus = false;
      nfcBusy = true;
      sendNfcOtpJob(JOB_NFC_VERIFY, nfcSession, nfcChallenge, nfcOtp, nfcKey);
    }
  }
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
        nfcNextAt = now;
        dwinWriteWord(VP_LOADER, 1);
        dwinSetPage(PAGE_PROCESSING);
        nfcSendPay();
      }
      break;
    }

    case NFC_PAYING:
      if (nfcOutcome == 0 && !nfcBusy && (int32_t)(now - nfcNextAt) >= 0) nfcSendPay();   // retry
      if (nfcOutcome == 0 && now - nfcPhaseAt > NFC_GIVEUP_MS) {
        Serial.println("[NFC] no answer from the backend - showing failed (check the wallet history!)");
        nfcOutcome = 2;
      }
      if (nfcOutcome != 0 && now - nfcPhaseAt >= PROCESSING_MS) {
        Serial.printf("[PAY] %s\n", nfcOutcome == 1 ? "PAYMENT SUCCESSFUL" : "PAYMENT FAILED");
        dwinWriteWord(VP_LOADER, 0);
        dwinSetPage(nfcOutcome == 1 ? PAGE_SUCCESS : PAGE_FAILED);
        nfcState = NFC_RESULT;
        nfcPhaseAt = now;
      }
      break;

    case NFC_OTP: {
      if ((int32_t)(now - nfcOtpDeadline) >= 0) { nfcFailOtp("code expired"); break; }
      if (now - nfcLastCountdown >= 30000UL) {
        nfcLastCountdown = now;
        uint32_t remain = nfcOtpDeadline - now;
        Serial.printf("[OTP] still waiting for the code (%lu s left)\n",
                      (unsigned long)(remain > OTP_GRACE_MS ? (remain - OTP_GRACE_MS) / 1000UL : 0));
      }
      char line[20];
      if (!readSerialLine(line, sizeof(line))) break;
      char kind = classifyOtpLine(line);
      if (kind == 'D') {
        strlcpy(nfcOtp, line, sizeof(nfcOtp));
        memset(line, 0, sizeof(line));
        Serial.println("[OTP] code received, verifying...");
        nfcState = NFC_VERIFYING;
        nfcOutcome = 0;
        nfcPhaseAt = now;
        nfcWantStatus = false;
        nfcBusy = true;
        dwinWriteWord(VP_LOADER, 1);
        dwinSetPage(PAGE_PROCESSING);
        sendNfcOtpJob(JOB_NFC_VERIFY, nfcSession, nfcChallenge, nfcOtp, nfcKey);
      } else if (kind == 'R') {
        Serial.println("[OTP] asking the backend to email the code again...");
        sendNfcOtpJob(JOB_NFC_RESEND, nfcSession, nfcChallenge, nullptr, nullptr);
      } else if (kind == 'C') {
        Serial.println("[OTP] cancelled by the driver -> home, no money moved");
        if (nfcChallenge[0]) sendNfcOtpJob(JOB_NFC_CANCEL_OTP, nfcSession, nfcChallenge, nullptr, nullptr);
        nfcClearOtp();
        cancelTransaction();
      } else {
        Serial.println("[OTP] enter exactly 6 digits, or RESEND / CANCEL");
      }
      break;
    }

    case NFC_VERIFYING:
      if (nfcOutcome == 0 && nfcWantStatus && !nfcBusy && (int32_t)(now - nfcNextAt) >= 0) {
        nfcBusy = true;
        sendNfcOtpJob(JOB_NFC_STATUS, nfcSession, nullptr, nullptr, nfcKey);
      }
      if (nfcOutcome == 0 && now - nfcPhaseAt > OTP_VERIFY_GIVEUP_MS) {
        Serial.println("[OTP] could not confirm the result - showing failed. CHECK the passenger's wallet before retrying!");
        nfcOutcome = 2;
      }
      if (nfcOutcome != 0 && now - nfcPhaseAt >= PROCESSING_MS) {
        Serial.printf("[PAY] %s\n", nfcOutcome == 1 ? "PAYMENT SUCCESSFUL" : "PAYMENT FAILED");
        dwinWriteWord(VP_LOADER, 0);
        dwinSetPage(nfcOutcome == 1 ? PAGE_SUCCESS : PAGE_FAILED);
        nfcState = NFC_RESULT;
        nfcPhaseAt = now;
      }
      break;

    case NFC_RESULT:
      if (now - nfcPhaseAt >= RESULT_MS) {
        nfcState = NFC_IDLE;
        nfcSession++;
        nfcClearOtp();
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
      if (key == KEY_QR_BACK)        backToPaymentMethod();
      else if (key == KEY_QR_CANCEL) cancelTransaction();
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
