# Tap&Go Fraud Detection — Synthetic Dataset Documentation

> **This dataset is synthetically generated for academic development and testing of the
> Tap&Go fraud detection system and does not represent real Tap&Go customer data.**

## 1. Purpose

This dataset supports training and evaluation of an ML-based *risk-scoring* layer for the
Tap&Go NFC/QR cashless fare payment platform. Per the project's design, the model's
output is **never** an automatic block — a transaction flagged as high-risk triggers an
OTP step-up challenge; only an incorrect OTP actually stops the payment. Consequently
`is_fraud` should be read as **"ground-truth fraudulent"**, and the trained models'
scores are a **suspicion signal**, not a verdict.

Intended models: Logistic Regression, Random Forest, XGBoost, Isolation Forest.

## 2. Scale

| | |
|---|---|
| Users | 10,000 generated; **8,495** appear in the final data (users with zero sampled transactions are naturally absent) |
| Transactions | **51,162** (full dataset, includes short "velocity-burst" rows injected as part of fraud pattern A/G — see §7) |
| Time period | **2026-03-18 → 2026-09-15** (~6 months) |
| Overall fraud rate | **3.16%** (target band was 2–5%) |

## 3. Feature Descriptions

| Column | Description |
|---|---|
| `transaction_id` | Unique transaction identifier (`TXN########`) |
| `user_id` | Unique passenger identifier (`USR######`) |
| `transaction_amount` | Fare amount in ₹ for this transaction |
| `payment_method` | `NFC` or `QR` |
| `transaction_timestamp` | ISO timestamp of the transaction |
| `transaction_hour` | Hour of day (0–23), derived from timestamp |
| `transaction_day_of_week` | 0 = Monday … 6 = Sunday |
| `account_age_days` | Days since the user's account signup, as of this transaction |
| `previous_transaction_count` | Count of this user's transactions strictly before this one |
| `previous_fraud_count` | Count of this user's *confirmed-fraud* transactions strictly before this one |
| `transactions_last_5min` / `_1hour` / `_24hours` | Rolling count of this user's transactions in the preceding window |
| `amount_last_1hour` / `amount_last_24hours` | Rolling ₹ sum of this user's transactions in the preceding window |
| `new_device` | 1 if this device has never been used by this user before; else 0 |
| `previous_device_used` | 1 if this device matches the device used in the user's immediately preceding transaction; else 0 |
| `device_transaction_count` | Count of this user's prior transactions from this exact device |
| `failed_otp_attempts` | Number of failed OTP attempts associated with this transaction (0–3, occasionally higher under fraud patterns) |
| `failed_login_attempts` | Number of failed login attempts associated with this transaction |
| `distance_from_previous_transaction_km` | Haversine distance (km) between this transaction's location and the user's immediately preceding transaction location |
| `location_change_rate` | `distance_from_previous_transaction_km` ÷ hours since the previous transaction (km/h) |
| `average_transaction_amount` | Running mean of this user's transaction amounts strictly before this one (falls back to the user's underlying "typical fare" for a user's first transaction) |
| `max_transaction_amount_last_30days` | Max transaction amount for this user in the preceding 30 days |
| `transactions_last_7days` | Count of this user's transactions in the preceding 7 days |
| `is_fraud` | **Target.** 1 = fraudulent, 0 = legitimate |

All rolling/history features are computed **causally** — only from transactions that
occurred strictly before the current one in simulated time — so none of them leak
future information.

## 4. Data Generation Methodology

1. **User population** (10,000 synthetic users): each is assigned a home city (weighted
   across Mumbai, Delhi, Bengaluru, Pune, Hyderabad, Chennai, Kolkata), a home
   lat/lon, a signup date (72% pre-dating the observation window, 28% signing up
   during it — giving genuine "new account" cases), a right-skewed daily transaction
   propensity (lognormal), a typical fare amount (lognormal), an NFC/QR preference,
   and a small device pool (1–2 devices).
2. **Base event timeline**: for every user, transaction timestamps are drawn from a
   Poisson process over their active window, with an hour-of-day weighting that
   favours morning/evening commute peaks while still allowing round-the-clock taxi
   activity (including late night).
3. **Fraud allocation**: each user is pre-assigned a `fraud_profile`
   (`none` 84%, `occasional` 9%, `takeover` 2.5%, `cluster` 2.5%, `isolated` 2%).
   A target fraud count (~3.5% of base events) is distributed across non-`none`
   profiles, weighted so `cluster` users can contribute short bursts of 2–4 fraud
   transactions and other profiles contribute isolated single fraud transactions.
4. **Causal simulation pass**: all events are processed in timestamp order. For each
   transaction, every rolling/history feature (§3) is computed from that user's
   history *as it existed at that moment* — never from future transactions. Fraud
   pattern perturbations (§6) are applied at generation time, sometimes adding
   extra genuine "burst" rows to the timeline (pattern A) so velocity features
   reflect real events rather than a relabeled single row.
5. **Noise / overlap injection** (§7): a controlled fraction of fraud rows are left
   unperturbed, and a controlled fraction of legitimate rows are given anomaly-like
   values, so the classes are not linearly/perfectly separable.
6. **Stratified split** into train/validation/test (§10).

Fixed random seed: **42** (`numpy` and `random` both seeded) — rerunning
`scripts/generate_dataset.py` reproduces the same dataset exactly.

## 5. Fraud-Generation Scenarios (Patterns A–G)

| Pattern | Behaviour simulated |
|---|---|
| A — Velocity | A burst of 2–5 rapid transactions injected shortly before the flagged transaction |
| B — Unusual amount | Amount set to 3–9× the user's typical fare |
| C — New device | Transaction moved to a freshly generated device the user has never used |
| D — Account takeover-like | Combines new device + unusual/far location + elevated amount |
| E — Rapid/unusual location | Transaction relocated to a different city or a location far (25–80+ km) from the user's usual area |
| F — Authentication anomalies | Elevated `failed_otp_attempts` / `failed_login_attempts` (1–3) |
| G — Combined weak signals | A blend of moderate versions of the above, rather than one strong signal |

Pattern selection per fraud transaction is weighted by the user's `fraud_profile`
(e.g. `cluster` users mostly produce velocity bursts; `takeover` users mostly
produce the takeover-like combination).

**~18%** of transactions labelled `is_fraud = 1` receive **no** pattern perturbation
at all — they keep ordinary feature values ("fraud that looks normal").

## 6. Legitimate Behaviour Scenarios ("looks suspicious but isn't")

**~7%** of legitimate transactions are independently passed through the same
perturbation logic (large amount, new device, distant location, or failed-auth
attempts) **without** flipping `is_fraud`. This represents real situations such as:
a passenger using a new phone, traveling to a different city, paying an unusually
large fare, or mistyping an OTP digit — all ordinary and non-fraudulent. This is
what justifies the platform's OTP-step-up design rather than an automatic block.

## 7. Class Distribution

| Dataset | Rows | Legitimate | Fraud | Fraud % |
|---|---|---|---|---|
| Full | 51,162 | 49,543 | 1,619 | 3.164% |
| Train | 35,813 | 34,680 | 1,133 | 3.164% |
| Validation | 7,673 | 7,431 | 242 | 3.154% |
| Test | 7,676 | 7,432 | 244 | 3.179% |

## 8. Train / Validation / Test Methodology

- **Split ratios:** 70% train / 15% validation / 15% test.
- **Method used: stratified random split** on `is_fraud`, so the fraud ratio is
  consistent (~3.15–3.18%) across all three files.
- **Why not a strict time-based split:** transactions ARE temporal, and a
  time-based split (e.g. earliest 70% of dates → train) is generally preferable in
  production because it prevents any subtle "future leaks into past" issue and
  mirrors real deployment (train on history, evaluate on what comes next). It was
  considered here, but with only ~1,600 fraud rows spread unevenly across 6 months,
  a strict chronological cut risks a validation/test slice with too few (or
  disproportionately many) fraud examples to evaluate reliably. The stratified
  split was chosen for this academic dataset to guarantee stable class balance in
  every split. **If a time-based evaluation is wanted later**, it can be
  reconstructed directly from `tapgo_transactions_full.csv` by sorting on
  `transaction_timestamp` and cutting at the 70th/85th percentile date — the
  column is preserved in full for exactly this purpose.
- No row appears in more than one split (`transaction_id` is disjoint across
  train/validation/test — verified, see §11).

## 9. Leakage Prevention

- No column directly encodes or is a deterministic function of `is_fraud`
  (no `fraud_reason`, `fraud_score`, `is_known_fraud`, etc.).
- All rolling/history features are computed **causally** (only from transactions
  strictly earlier in simulated time than the row being described).
- Perturbations used to construct fraud patterns are applied probabilistically and
  with noise, and are also applied to a subset of legitimate rows (§6), so no
  single feature or fixed threshold perfectly separates the classes.
- Train/validation/test sets are disjoint by `transaction_id` (verified: 0 overlap
  in all three pairwise comparisons).

## 10. Limitations

- This is **entirely synthetic** — behavioural distributions (fare amounts, city
  mix, device/location patterns) are modeled from the project author's domain
  assumptions about Indian taxi/auto-rickshaw fares, not from real transaction logs.
- Fraud patterns are hand-designed (A–G); real-world fraud may include modes not
  represented here (e.g. collusive driver/passenger fraud, refund abuse, card
  cloning across the NTAG/Mifare NFC layer itself).
- `payment_method` only distinguishes NFC vs QR; it does not model card-present
  vs. card-not-present style risk differences.
- Geographic modeling uses 7 Indian metro hubs only; it does not reflect Tap&Go's
  actual planned launch city/cities.
- The dataset intentionally avoids being "too easy" (see project brief §15) — this
  means expected model performance should be realistic (e.g. ROC-AUC in a
  reasonably strong-but-not-perfect range), not nearly perfect. A model that
  achieves ~99.9% accuracy on this data should be treated as a sign of a
  methodology bug (e.g. leakage), not genuine skill.

## 11. Data Quality — Final Validation Results

```
Total rows: 51,162
Duplicate transaction_ids: 0
Duplicate full rows: 0
Missing values total: 0
Negative amounts: 0
Invalid payment_method values: 0
Velocity monotonicity violations (5min > 1hr): 0
Velocity monotonicity violations (1hr > 24hr): 0
Amount monotonicity violations (1hr amt > 24hr amt): 0
Negative account_age_days: 0
Train/Validation overlap (transaction_id): 0
Train/Test overlap (transaction_id): 0
Validation/Test overlap (transaction_id): 0
Same schema (26 columns) across full/train/validation/test: confirmed
```

## 12. Synthetic Data Statement

This dataset, all user records, all transaction records, and all derived features
are **synthetically generated** using `scripts/generate_dataset.py` (fixed seed = 42)
for the sole purpose of academic development and testing of the Tap&Go fraud
detection prototype. It does not contain, and was not derived from, any real
Tap&Go user, driver, or transaction data.
