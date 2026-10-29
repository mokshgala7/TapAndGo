# Tap&Go Backend (coming next)

Nothing lives here yet. The frontend currently runs with no database and
no real API - login/register accept any values and are stored only in the
browser (localStorage) via `frontend/src/context/AuthContext.jsx`, and
wallet/transaction data is mocked in `frontend/src/context/WalletContext.jsx`.

Planned stack per the project spec: Python + FastAPI, Relational Database,
External Payment Gateway + Supported Withdrawal Provider, and the Random Forest fraud-detection model. This
folder is reserved for backend architecture.

## Fraud gate and payment OTP (environment)

Every ride payment (QR confirm, `POST /api/nfc/pay`, `POST /api/wallet/pay`) passes `app/services/fraud_gate.py`:
the plain 10-minute rule (no ML) plus the vendored V6 model (`app/services/tapgo_fraud_risk/`, read-only). In
`enforce` mode a flagged payment moves no money until the passenger enters a 6-digit code emailed to their
registered address (`app/services/payment_otp.py`). Decisions are stored in `fraud_assessments`, challenges in
`payment_otp_challenges`.

| Variable | Default | Meaning |
|---|---|---|
| `TAPGO_FRAUD_MODE` | unset = `shadow` | `off`: no checks. `shadow`: score and record, every payment proceeds unchanged. `enforce`: OTP when the model flags, the 10-minute rule fires, or the model cannot score. **Any other value stops the app at startup** (allowed: `off`, `shadow`, `enforce`). |
| `TAPGO_FRAUD_ENFORCE_USER_IDS` | empty | Comma-separated passenger user ids, e.g. `69,70` (one trailing comma allowed; anything else stops the app at startup). With `TAPGO_FRAUD_MODE` unset/`shadow`, those passengers get full enforcement (flag, 10-minute rule or ML failure -> email OTP, no money moves without a verified OTP) while everyone else stays in shadow. `off` ignores the list (kill switch wins); `enforce` already covers everyone. A non-empty list needs `PAYMENT_OTP_SECRET` like `enforce` does (not required in `off`). Each `fraud_assessments` row records the mode that applied (`mode`) and whether the list caused it (`enforced_by_allowlist`). |
| `PAYMENT_OTP_SECRET` | unset | Private random value that keys the HMAC of stored OTPs. **Required for `enforce`**: the app refuses to start if it is unset or equals the committed dev `SECRET_KEY` default. In `off`/`shadow` a missing value only logs a warning. Changing it invalidates pending challenges (they simply expire). |
| `TAPGO_RISK_DISABLED` | unset | `1`/`true`/`yes`/`on` switches ML scoring off (kill switch). The 10-minute rule still applies. |
| `TAPGO_RISK_DB_TIMEZONE` | `UTC` | Timezone of the naive `transactions.created_at` values. |
| `TAPGO_OTP_EMAIL_TIMEOUT_SECONDS` | `10` | How long a payment request waits for the mail provider before an enforced payment is declined. |
| `TAPGO_OTP_DEMO_REDIRECT_EMAIL` | unset | **Demo only.** Sends the payment OTPs of the listed demo users to one inbox; see `docs/FRAUD_V6_DEPLOY.md`. Remove it after the demo. |
| `TAPGO_NEWUSER_POLICY` | unset = `off` | `off` / `enforce`. With `enforce`, passengers NOT in the list use the fixed new-account policy (email OTP above `TAPGO_NEWUSER_OTP_ABOVE`, entered on the POS). Needs `PAYMENT_OTP_SECRET`. See `docs/FRAUD_V6_DEPLOY.md` section 8. |
| `TAPGO_NEWUSER_OTP_ABOVE` | `300` | Rupees; exclusive (300 passes, 301 asks for an OTP). |

Render checklist for turning the gate on:

1. Set `PAYMENT_OTP_SECRET` (e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Leave `TAPGO_FRAUD_MODE` unset (shadow).
2. Run `migrations/2026_10_fraud_gate_payment_otp.sql` in the Supabase SQL editor (two new tables, safe to re-run), then deploy.
2b. To try OTP on a few accounts first, set `TAPGO_FRAUD_ENFORCE_USER_IDS=69,70` (keep `TAPGO_FRAUD_MODE` unset) and redeploy. After deploying, `scripts/check_fraud_users_69_70.sql` gives read-only checks for those two users.
3. Watch `tapgo.fraud_gate` / `fraud_assessments` in shadow mode and check the share of payments that would need an OTP.
4. Set `TAPGO_FRAUD_MODE=enforce` and redeploy. To roll back, set it to `shadow` (or `off`); pending challenges just expire.

The POS can look up the outcome of a tap after a timeout with `GET /api/nfc/pay/status?idempotency_key=...`.

Full deploy guide, demo cards, rollback and limitations: `docs/FRAUD_V6_DEPLOY.md`.
