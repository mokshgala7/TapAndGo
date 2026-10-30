# Firmware: Tap&Go POS (ESP32-S3 + DWIN DGUS II + PN532)

| Folder | What |
|---|---|
| `TapGo_DWIN_Screen00_01/` | the earlier POS sketch (amount entry and payment method screens) |
| `TapGo_DWIN_OTP/` | the POS sketch with the OTP step (screens 00-08, QR and NFC payment, OTP page 06) |

**Credentials are placeholders.** Before flashing, edit the four constants near the top of the sketch:
`WIFI_SSID` (`YOUR_WIFI_NAME`), `WIFI_PASS` (`YOUR_WIFI_PASSWORD`), `DRIVER_ACCOUNT` (`YOUR_DRIVER_ACCOUNT`),
`DRIVER_PASSWORD` (`YOUR_DRIVER_PASSWORD`). Never commit real values.

## Arduino IDE settings

* Board: **ESP32S3 Dev Module** (ESP32 Arduino core 2.x or 3.x); library **Adafruit PN532** (with Adafruit BusIO).
* **USB CDC On Boot: Enabled**.
* **Serial Monitor: 115200 baud, line ending "Newline"**.

## DGUS page 06 (OTP Verification)

* The backend answers `otp_required`; the sketch shows **page 06** and the emailed 6-digit code is entered for this payment.
  In this version the page has **no keypad yet**: the code is typed in the Arduino Serial Monitor (115200, Newline). Serial commands on page 06: `RESEND` (email a new code) and `CANCEL` (go home).
* Page 06 shows the masked email hint and a countdown; the code expires after 5 minutes and allows 3 wrong attempts.
* All other DGUS screen and button settings the sketch expects are listed in the comment block at the top of the `.ino`.

**Note on this sketch version.** `TapGo_DWIN_OTP.ino` as committed here is the version found on the author's machine on 2026-10-30. In it the NFC code is typed in the Serial Monitor on the POS,
while the **QR code is still typed on the website**; it does not use the driver-scoped QR/wallet POS endpoints described in `backend/docs/FRAUD_V6_DEPLOY.md` (branch `pos-otp-newuser-ui`), and wallet pay is not in the sketch.
A newer sketch in which QR and NFC both ask for the code on the POS was requested but **was not found** (the file in Downloads was unchanged), so this README describes the committed version. Replace the sketch and this note when the newer one is available.
