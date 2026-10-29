# Fraud model V6 + email-OTP step-up: deploy guide

**Status: built and tested locally. Nothing in this guide has been deployed or verified in production.**
All model numbers below are **synthetic/demo-derived, not real-world performance**.

## 1. What it is

Every ride payment (QR confirm, `POST /api/nfc/pay`, `POST /api/wallet/pay`) goes through one gate
(`app/services/fraud_gate.py`):

* **V6 model**: an XGBoost classifier (39 features, monotone constraints) shipped as a vendored, hash-verified package
  (`app/services/tapgo_fraud_risk/`, read-only; `MANIFEST.json` lists every file's SHA-256). It was trained on
  4,049 *fictional synthetic* passengers. It outputs an **uncalibrated risk score**, not a probability. Threshold
  **0.0633** was chosen on synthetic validation data. The personal profile activates at **100** completed rides;
  before that the shared model + the passenger's growing history are used.
* **10-minute rule** (plain SQL, no ML): a payment initiated 599 s or 600 s after the passenger's previous *completed*
  ride requires OTP; 601 s does not. Failed rides never reset the reference.
* **Email OTP step-up** (`app/services/payment_otp.py`): when a payment is flagged, **no money moves** until the passenger
  enters a 6-digit code emailed to them. Stored as an HMAC; 5-minute expiry; 3 attempts (enforced atomically in the
  database); 2 resends 30 s apart; single use; bound to passenger, driver, amount, channel and idempotency key.
  Wrong x3 / expiry / cancel records a failed payment (`OTP_FAILED` / `OTP_EXPIRED` / `OTP_CANCELLED`).
  A passenger with no email, or a mail provider that is down/slow (10 s timeout), is **declined**, never approved.
  A balance below the fare is declined *before* any OTP is sent.

Modes: `TAPGO_FRAUD_MODE` unset = **shadow** (everything is scored and recorded, nothing is blocked).
`TAPGO_FRAUD_ENFORCE_USER_IDS` upgrades just the listed passengers to full enforcement.

## 2. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `TAPGO_FRAUD_MODE` | unset = `shadow` | `off` (nothing runs) / `shadow` / `enforce` (everyone). Any other value stops the app at startup. |
| `TAPGO_FRAUD_ENFORCE_USER_IDS` | empty | Comma-separated passenger ids, e.g. `4,69,70` (one trailing comma allowed; anything else stops the app). Listed passengers are enforced while mode is `shadow`. `off` ignores it; `enforce` already covers everyone. **No id is hard-coded anywhere.** |
| `PAYMENT_OTP_SECRET` | unset | Private random value keying the OTP HMAC. **Required** when mode is `enforce` or the list is non-empty (the app refuses to start if it is unset or equals the dev `SECRET_KEY` default). |
| `TAPGO_RISK_DISABLED` | unset | `1` turns ML scoring off (kill switch). The 10-minute rule still applies. |
| `TAPGO_RISK_DB_TIMEZONE` | `UTC` | Timezone of the naive `transactions.created_at` values. |
| `TAPGO_OTP_EMAIL_TIMEOUT_SECONDS` | `10` | How long a request waits for the mail provider before declining an enforced payment. |
| `TAPGO_OTP_DEMO_REDIRECT_EMAIL` | unset | **Demo only.** Sends the payment OTPs of the *listed* demo users to this one address instead of their own. Never applies to withdrawals, receipts or other mail; ignored (with a warning) in mode `off`/`enforce` or with an empty list; must be one valid address or the app refuses to start (the value is never echoed). The address is never logged, stored or returned by an API; the website/POS hint refers to it. **Remove it after the demo.** |

Recommended for the demo: `TAPGO_FRAUD_MODE` unset (shadow), `TAPGO_FRAUD_ENFORCE_USER_IDS=4,69,70`,
`PAYMENT_OTP_SECRET=<private random value>`, `TAPGO_OTP_DEMO_REDIRECT_EMAIL=<an inbox you can open>`.

> The root `Procfile`/`nixpacks.toml` install from the **root** `requirements.txt` (`--app-dir backend`), the Dockerfile
> from `backend/requirements.txt`. They must stay identical (a test enforces it); both pin `numpy`, `pandas`, `xgboost>=3.1,<4`.

## 3. Deploy order

1. **Read, then run the migration on Supabase:** `backend/migrations/2026_10_fraud_gate_payment_otp.sql`. It creates two
   new tables (`payment_otp_challenges`, `fraud_assessments`) and their indexes; it changes no existing table or row; it
   is safe to run twice. (The app would also create them at startup, but run it first so you control the timing.)
2. Set `PAYMENT_OTP_SECRET` to a private random value (e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`) and
   **rotate the database password** if it was ever shared.
3. Set the fraud variables above, and the demo redirect to an inbox you can open.
4. **Merge the branch to `main`** to deploy (nothing deploys from the branch itself unless your host is configured to).
5. Run the read-only checks: `backend/scripts/check_fraud_users_69_70.sql` (edit the ids for user 4) and
   `backend/scripts/audit_users_69_70_readonly.sql`.
6. **User 4 demo history** (optional but needed for his card): his seed files are kept **outside this repo** (they hold data and
   write to production): `user4_seed.sql`, `user4_undo.sql`, `user4_check.sql`. Order: migration first -> run `user4_seed.sql` as a
   **dry run** (it ends in `ROLLBACK`; any `ABORT:` error means nothing was written) -> change the last `ROLLBACK;` to `COMMIT;` and run
   it -> run `user4_check.sql` (expect wallet = ledger = Rs600.00, 100 completed rides, 109 seeded rows) -> after the demo run
   `user4_undo.sql` (dry run, then `COMMIT`). Every seeded row has the reference prefix `DEMS4`, payment_source `demo_seed`, no driver and no
   idempotency key. Verified on a local copy of his exact ledger state: apply, check, undo restores the exact original state, a second seed
   run aborts. The audit found no triggers, rules, webhooks, cron jobs, pg_net/pg_cron/http extensions, or functions that notify, so the
   INSERTs and the single wallet UPDATE cannot send anything.
7. Fund wallets 69/70 through the website **Add Money** flow (their wallets were Rs1.00 / Rs0.00 when last read; they need at
   least Rs550 / Rs1,210 for the cards below). Rehearse the demo card once (section 5), then flash the POS (section 6).

## 4. Rollback

* Immediate: set `TAPGO_FRAUD_MODE=off`, or empty `TAPGO_FRAUD_ENFORCE_USER_IDS` (then everyone is back in shadow).
  Pending challenges simply expire; no money is ever held.
* The migration is additive and may stay.
* Remove `TAPGO_OTP_DEMO_REDIRECT_EMAIL` after the demo.

## 5. Demo cards (synthetic/demo-derived numbers, local test copy, driver vehicle type "unknown")

Driver 27 (the POS driver) has `vehicle_type = 'Luxury Taxi'`. The model's vehicle mapping is exact (`taxi`/`cab`/`car` = taxi, any text
containing `auto` = auto rickshaw), so **"Luxury Taxi" is read as `unknown`** (the score is identical to a driver with no vehicle type, and the result
carries the warning `vehicle_type_missing_or_unknown`). All numbers below are for that setting. Run the steps **in this order**; history grows as payments complete and scores change.
(a) normal fare. (b) a second small payment **2 minutes later** (10-minute rule only, model not flagging). (c) a normal fare
again **more than 10 minutes after b completes**. (d) the flagged fare, **within an hour of a**: a wrong OTP leaves 2
attempts and moves no money; the correct OTP completes it once. (e) a normal fare at **23:00 IST** (night alone never
triggers an OTP). Declines for low balance happen *before* any OTP, so load at least the totals below.

| User | a | b | c | d (flagged) | e (23:00) | Wallet total | Scores a / b / c / d / e |
|---|---|---|---|---|---|---|---|
| 69 (demo rides, no drivers) | Rs100 | Rs50 | Rs100 | **Rs200** | Rs100 | Rs550 | 0.0031 / 0.0005 / 0.0022 / 0.8133 / 0.0048 |
| 70 (demo rides, no drivers) | Rs270 | Rs50 | Rs270 | **Rs350** | Rs270 | Rs1,210 | 0.0061 / 0.0006 / 0.0162 / 0.3879 / 0.0033 |
| 4 (low-spend, usual fare about Rs35; seeded to 100 rides) | Rs35 | Rs30 | Rs35 | **Rs80** | Rs35 | **Rs215** (his Rs600 covers it twice) | 0.0079 / 0.0021 / 0.0031 / 0.8090 / 0.0018 |

* Scores are the same on QR, NFC and wallet pay (the demo redirect on: both OTP mails of the card went only to the redirect inbox).
  User 4's card was measured on his **real ledger plus the exact seed plan** (100 completed rides, median Rs35, Rs32-42, about 4% at night,
  rides at least 7 hours apart, 0 within 10 minutes). His 101st payment is the first with the personal profile active.
* The smallest flagged fares depend on **time of day, the driver's vehicle value and rides in the previous hour**. Under "Luxury Taxi" (= unknown)
  user 4's lowest flagged fare is Rs55 (14:00) / Rs60 (23:00) standalone and Rs45 after a few recent rides, so **Rs60, 70, 80 and 100 all ask
  for OTP in every tested context with the model alone**. A normal Rs30-40 ride was never flagged in any of 16 tested settings (max score 0.047);
  the only fares in Rs25-45 that flag are Rs44-45 right after three rides in the previous 30 minutes, so keep the "normal" demo fares at Rs35.
* If driver 27's vehicle type is ever changed to `Taxi` or an auto value, Rs60-100 stop flagging when paid alone (an auto first flags at about Rs110,
  a taxi at about Rs225+). That is the only case where the **optional own-median rule** matters (it makes Rs70 and above ask for OTP):
  decision for the demo: **not needed, not in this branch**; the separate patch is kept outside the repo.
* Fares under about Rs25 always flag (micro-fare penalty).
* Load at least the totals above; add one rehearsal's worth.

## 6. POS firmware (`firmware/TapGo_DWIN_Screen00_01/`)

* Re-enter `WIFI_PASS` and `DRIVER_PASSWORD` (committed as `YOUR_WIFI_PASSWORD` / `YOUR_DRIVER_PASSWORD`), compile for
  *ESP32S3 Dev Module* in the Arduino IDE (needs "Adafruit PN532"). It compiled with ESP32 core 3.3.12 (80% flash, 14% RAM).
  Nothing here was flashed or run on hardware.
* **DGUS page 06 (OTP Verification)**, generated from the sketch constants. Keys: Return Key Code, VP `0x1000`, Int,
  auto-upload ON, page switching -1.

| Control | Code / VP | Notes |
|---|---|---|
| Digits 1-9 | `0x000A`-`0x0012` | same codes as page 01 |
| Digit 0 | `0x0014` | |
| DELETE / SUBMIT / CANCEL / RESEND | `0x0017` / `0x0018` / `0x0019` / `0x001A` | |
| Typed digits (Text Display, ASCII) | VP `0x1200`, 12 bytes | |
| Email hint | VP `0x1220`, 28 bytes | masked, e.g. `d***@e***.org` |
| Status line | VP `0x1260`, 28 bytes | |
| Countdown | VP `0x1280`, 20 bytes | |
| Page 04 waiting text (optional) | VP `0x1400`, 28 bytes | "Waiting for passenger OTP" |
| Page 08 message line 1 / 2 | VP `0x1420` 28 bytes / VP `0x1440` 40 bytes | "Could not confirm payment" / "Check with passenger before retrying" |

Existing VPs are unchanged (key `0x1000`, amount `0x1100`, QR `0x1300`, loader `0x1500`). Positions are for the 480x272
screen and must be adapted to the background art.

## 7. Troubleshooting

* **OTP email not arriving:** check spam; check `email_logs` (type `payment_otp`) and the mail provider; remember the
  redirect (if set) sends listed users' codes to the demo inbox, not their own. A provider outage declines the payment
  (`OTP_UNAVAILABLE`), it never approves it.
* **`ml_status` = `model_unavailable` (or other non-`scored`):** xgboost missing/incompatible or the model file hash
  failed. The app still starts: shadow users pay normally; enforced users get an OTP. Fix `requirements.txt` pins (both
  files) and redeploy. Check `scripts/check_fraud_users_69_70.sql` block 3.
* **POS shows "Could not confirm payment / Check with passenger before retrying":** the POS lost the answer from the
  backend. It looked the payment up for 20 s with the same idempotency key. Check the passenger's wallet history before
  charging again; never start a second charge for the same fare without checking.
* **App refuses to start:** read the error: it names the variable (`TAPGO_FRAUD_MODE`, `TAPGO_FRAUD_ENFORCE_USER_IDS`,
  `PAYMENT_OTP_SECRET`, `TAPGO_OTP_DEMO_REDIRECT_EMAIL`) without echoing secrets.

## 8. Limitations (honest)

* All metrics are synthetic/demo-derived (held-out synthetic set: about 4.8% of legitimate rides get an OTP at threshold
  0.0633, recall 0.50, precision 0.13). They are **not** evidence of real-world performance.
* Users 69/70 are demo accounts with 48 demo-seed rides each and no drivers (those rides are used, each with its own
  placeholder driver). They are in the *developing* stage; the personal profile switches on at 100 completed rides.
  User 4's 100 rides are **seeded demo data** (his real ledger had one Rs5 test deposit and no rides); remove them with `user4_undo.sql` after the demo.
* Memory/latency measured on macOS arm64, Python 3.11: peak RSS about 183 MB after the first score, first score about
  7 ms, steady state about 4 ms. Linux numbers on your host may differ. Also loads on Python 3.12 and 3.13.
* SMS OTP is not implemented (TRAI DLT registration). Passengers without an email are declined when enforced.
* A mail provider accepting a message does not prove delivery. The OTP window is 5 minutes.
* Scores are not monotone in the fare for low scores, and fares far *below* the usual can flag in rapid sequences;
  the flag itself is monotone above Rs30 in the tested settings (one exception class: user 70 in rapid sequences).
* Not verified in production, and not tested on real hardware.
