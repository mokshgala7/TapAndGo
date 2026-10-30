# Tap & Go ML: final freeze report

Date 2026-10-27. Scope: verification, documentation consistency and demonstration only.
**No training, retraining, threshold change, new feature, backend change, commit or deployment took place.**

## 1. Selected model

| Item | Value |
|---|---|
| Model | V6 reference candidate `passenger_fraud_v6.1.0.0` (candidate C9: XGBoost with monotone constraints, 39 passenger-history inputs, set `P6c_fam`) |
| Artifact | `TapGo-ML/experiments/passenger_fraud_v6/artifacts/passenger_fraud_v6_bundle.joblib` |
| SHA-256 | `154e0afd6dc978467d2cbdc000de6a50473b4f92cda383bf641fb564dd261680` (matches the `.sha256` sidecar) |
| Threshold | 0.063318 (highest-recall threshold with validation FPR ≤ 2%) |
| Interface | `integration/inference.py` (`FraudScorerV6.score_safe(transaction, passenger_history)`) |
| Status | **Reference candidate** (decision D1). Research only. **Not production-ready.** **Not integrated with the backend.** |

It loads, scores offline with network access blocked, exposes the explicit `passenger_fare_anomaly` signal and
the three rule flags, needs no location data, and never returns a score on failure (`verify_model.json`).

## 2. Verified final-test metrics (synthetic data only)

Every value below was re-derived from saved artifacts with **0 discrepancies** against the reports
(`VERIFIED_METRICS.json`).

| Set | Rows | AP | Precision | Recall | FPR | TP / FP / FN / TN | Flagged |
|---|---|---|---|---|---|---|---|
| **T3 fresh universe** | 238,790 (= raw file) | **0.440** | **22.6%** | **49.1%** | **2.17%** | **1,493 / 5,127 / 1,547 / 230,623** (sum 238,790) | 2.77% |
| T4 distribution shift | 188,941 | **0.199** | 7.2% | 33.3% | **3.25%** | 471 / 6,101 / 944 / 181,425 | 3.48% |
| T1 temporal | 38,165 | 0.493 | 26.0% | 52.5% | 2.19% | 289 / 822 / 262 / 36,792 | 2.91% |
| T2 unseen passengers | 23,895 | 0.389 | 20.0% | 45.1% | 2.28% | 134 / 537 / 163 / 23,061 | 2.81% |
| T5 scenario-focused | 187,186 | 0.389 | 28.9% | 40.8% | 2.94% | 2,177 / 5,347 / 3,154 / 176,508 | 4.02% |

**No real-world validation exists:** there are no real transactions or confirmed fraud outcomes. These numbers
describe behaviour on generated data, whose assumptions shape the results.

## 3. Functional tests

All 10 mandatory requirements **PASS** (`REQUIREMENTS_CHECKLIST.md`):
1. fare anomaly visible with a familiar driver
2. monotone in fare
3. day/night windows
4. cold start
5. 599/600/601 s
6. failed-ride reference
7. safe failures
8. no GPS
9. training/inference parity
10. risk scoring only

Test suites (`FINAL_TEST_RESULTS.md`):

| Suite | Result |
|---|---|
| V6 | 34/34 |
| V5 | 63/63 |
| V4 | 69/69 |
| Legacy | 57/57 |

Nothing failed or was skipped.

## 4. Remaining performance limitations (honest)

- **Two pre-registered criteria FAIL:**
  - AC-FA2: familiar-driver fare-anomaly recall is V6 13.4% vs V4 19.5% and V5 25.5%
  - AC-FP: T3 legitimate FPR 2.17% vs V4 1.55% + 0.5 pp

  Previous numeric targets (validation AP ≥ 0.72, shift AP ≥ 0.55, airport FPR ≤ 10%, overcharge recall ≥ 85%) all FAIL.
- **Lower synthetic AP than V4/V5 on every set** (T3 0.440 vs 0.474 / 0.501).
- **Expensive legitimate rides.** V6 challenges **23.3%** of legitimate long/airport trips (V4 9.4%, V5 6.9%).
  Without trip context, which is out of scope, they look like overcharges. **Accepted by decision D1:** OTP is
  cheap for genuine passengers.
- **Distribution shift:** AP drops to 0.199, and FPR rises to 3.25% under 20% fare inflation. Unseen
  collusive-driver fraud is caught at 2.3%.
- **New passengers:** fares are compared only against the population. A ₹300 first ride is not flagged (demo 4b).
- Subtle overcharges (×1.4–2.6, recall 15.2%) and "quiet" compromised accounts (2.6%) are largely undetectable from
  passenger history alone.

## 5. OTP policy for the 10-minute rule: open product decision (D2)

Nothing was changed: the bundle still encodes model + rule.

| T3 | A. Model-only | B. Model + 10-minute rule (current bundle policy) |
|---|---|---|
| Rides sent to OTP | 2.77% | 5.20% |
| Legitimate rides challenged | 2.17% | 4.62% |
| Fraud recall | 49.1% | 50.2% |
| Cost of the rule | — | 5,766 extra legitimate challenges for 33 extra frauds, **≈175 per extra fraud** |

The rule flag is returned in every response under either option. The choice needs an explicit product decision and
separately authorised backend work (`reports/DECISIONS.md` D2).

## 6. Protected files

**None changed** (`PROTECTED_ARTIFACT_MANIFEST.json`):
- 171 model and evaluation artifacts across V4–V6, plus legacy models, hashed before and after
- the V6 404-file snapshot covering all of V4/V5 and the legacy project
- the V1–V3 archive
- ML repo HEAD and status unchanged
- backend HEAD unchanged

The backend working tree contains someone else's uncommitted edits (`wallet.py`, `test_wallet_security.py`, from
2026-10-26 19:49–19:53 IST). They predate this freeze and were not touched.

Six documents were edited for consistency, with no metric changed:
- `FINAL_REPORT.md`
- `NEXT_STEPS.md`
- `V4_V5_V6_COMPARISON.md`
- `REQUIREMENTS_COMPLIANCE_REPORT.md`
- `DECISIONS.md` (D2 added)
- `INTEGRATION_CONTRACT.md`

## 7. Before shadow-mode evaluation

All backend items need separate authorisation:
1. The product decision on the 10-minute rule policy (D2).
2. Timezone-aware timestamps: `transactions.created_at` is naive (`backend/app/models.py:194`).
3. A passenger-history query per ride payment; pass `idempotency_key`.
4. Call the scorer in **log-only** mode. Today rides are written `otp_verified=True, fraud_status="clear"`
   (`backend/app/routes/qr.py:368-382`).
5. A fallback policy for failures (step-up, never approval) and monitoring.

## 8. Before any production deployment

1. Real confirmed fraud outcomes from shadow mode (reviewed disputes and fraud cases), measuring real precision,
   recall and OTP burden.
2. Threshold re-selection and calibration on real data.
3. Integration, security and privacy review. No new personal or location data is needed or should be collected.
4. A rollback / kill switch and ongoing drift monitoring.

## 9. Deliverables (`reports/final_freeze/`)

| File | Contents |
|---|---|
| `FINAL_FREEZE_REPORT.md` | this report |
| `VERIFIED_METRICS.json` | metrics re-derived from artifacts, with discrepancy check |
| `REQUIREMENTS_CHECKLIST.md` | the 10 mandatory requirements and the criteria results |
| `DEMO_GUIDE.md` | how to run the demo and what each case shows |
| `FINAL_TEST_RESULTS.md` | test and integrity results |
| `PROTECTED_ARTIFACT_MANIFEST.json` | pre- and post-edit hashes and git state |
| Scripts and outputs | `verify_model.py` / `verify_model.json`, `verify_metrics.py`, `run_demo.py` / `demo_output.json` / `demo_output.txt`, `test_output_v6.txt` |
