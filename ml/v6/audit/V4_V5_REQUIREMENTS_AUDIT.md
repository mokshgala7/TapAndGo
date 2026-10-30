# V4/V5 requirements audit (V6 Phase 1)

Date 2026-10-26. Read-only with respect to V1–V5. The V5 audit
(`passenger_fraud_v5/audit/requirements_compliance/`) was treated as evidence and **re-verified** against the
frozen artifacts with a new V6-owned script, `audit/scripts/verify_v4_v5_claims.py`, whose output is
`audit/v4_v5_verification.json`. No V4/V5 file was written.

## 1. Repository state

- `~/Desktop/tap and go-ml` (git root), branch `updated_ml`, HEAD `ae862f6`.
- The experiments folder is untracked; it holds `passenger_fraud_v4/` and `passenger_fraud_v5/`.
- V1–V3 exist only in `~/Desktop/TapGo_ML_V1_V3_archive.zip`; V4 holds byte-identical V3 references in `v3_reference/`.
- Backend `~/Desktop/Tap@Go Hosted` at HEAD `6f80cb4`, clean.
- Protected snapshot: `audit/protected_files_manifest.json`, 404 files (all of V4 and V5 plus the legacy project).

## 2. Artifacts and schemas

| | V4 | V5 |
|---|---|---|
| Selected | `xgboost__A4_no_rules` (54 inputs) | `xgboost__A5__D4_DR` (65 inputs = V4's 54 + 11) |
| Threshold | 0.074426 (validation FPR ≤ 2%) | 0.075498 |
| Bundle | `passenger_fraud_v4/artifacts/passenger_fraud_v4_bundle.joblib` (`7d32ce01…`) | `passenger_fraud_v5/artifacts/passenger_fraud_v5_bundle.joblib` (`ff5f30de…`) |
| Inference inputs | transaction, passenger history, driver history (last 200) | + per-ride stored annotation, + nightly market median |
| Rule outputs | 10-minute, amount anomaly, night behaviour | **10-minute only** (`v5/inference.py:290`) |
| Status | final reports complete | evaluation complete (`evaluation/final_metrics.json`); `reports/` **empty** (final report never written) |

## 3. Re-verified claims (deterministic probes; passenger normally pays ≈ ₹100, auto-rickshaw, 80 rides)

| Probe | V5 score (flag) | V4 score (flag) | Verdict |
|---|---|---|---|
| Familiar driver ₹100 / 200 / 300 / 500 | 0.001 / 0.015 / 0.008 / 0.070 (none flagged) | 0.002 / 0.174 / 0.132 / 0.450 (₹200+ flagged) | **V5 fails R1.** V4 flags but is **not monotonic** (₹200 > ₹300) |
| Unfamiliar driver ₹100 / 200 / 300 / 500 | 0.031 / 0.468 / 0.292 / 0.603 | 0.027 / 0.681 / 0.711 / 0.802 | V5 is non-monotonic |
| V4 amount-rule output, familiar ₹200/300/500 | (not returned) | True / True / True | the rule recognises the anomaly; V5 dropped it |
| Day commuter vs night traveller at 02:00, ₹100 | 0.000 vs 0.001 | 0.001 vs 0.003; **night rule True vs False** | personal night anomaly visible only through V4's rule output |
| 3× fare at history n = 0 / 1 / 5 / 19 / 50 / 150 | none flagged | flagged at 0, 19, 50, 150; **missed at 1 and 5** | both weak in sparse history; V4's amount rule needs ≥ 20 rides |
| 10-minute rule 599 / 600 / 601 s | T / T / F | T / T / F | correct in both |
| Failed ride 8 min after a completed one, new ride at 13 min | not triggered | not triggered | correct: a failed ride never replaces the reference |
| Naive timestamp `2026-09-02 09:00:00` | invalid_input, no score, fallback | same | correct: never assumed UTC |

## 4. Driver familiarity and synthetic artefacts (confirmed)

- **Weight of driver signals.** In V5's model, driver-related features carry about 45% of total gain
  (`driver_share` alone 11.8%); day/night features carry about 3% (`FEATURE_INVENTORY.csv`).
- **Familiar drivers look legitimate by construction.** In V4's generator (also V5's), 45.9% of fraud is on
  "ring" drivers, who serve 3.6% of legitimate rides. Fraud uses a familiar driver 28% of the time, legitimate
  rides 72%. A fare at ≥ 2× the passenger median with a familiar driver is fraud only 2.8% of the time.
  Source: `generator_v4.py:222-226` and the scenario calls at `:329-373`.

**Conclusion:** the "familiar driver ⇒ legitimate" shortcut comes from the generator.

## 5. Feature availability in the backend (read-only inspection)

| Signal | Available? | Evidence |
|---|---|---|
| amount, driver_id, passenger_id, status | yes | `backend/app/models.py:163-194` |
| timestamp | yes, but `created_at` is a **naive** `DateTime` | `models.py:194` (the caller must attach Asia/Kolkata explicitly) |
| vehicle type | nullable, on the driver's user row | `models.py:21` |
| payment method | ride payments always `"QR"` | `routes/qr.py:374` |
| failed/declined attempts | not persisted (rolled back) | V4 audit |
| driver history of other passengers | derivable (extra query), but V5's annotation columns do not exist | V5 contract §5 |
| trip type / airport / any location | **not available**; out of scope | GPS audit |
| ML scoring / 10-minute rule in the ride flow | **absent**: rides are written `otp_verified=True, fraud_status="clear"` | `routes/qr.py:368-382` |

## 6. The 100-ride boundary

The V1 brief (the authoritative requirement source) states: "At least 100 eligible historical completed rides:
personalised profile activation threshold", next to "fewer than 20: insufficient history". V3–V5 implement
this as the indicator `profile_active` (≥ 100) plus continuous shrinkage toward population priors
(`v3_features.py:27-29`). **V6 keeps both boundaries as authoritative** and exposes the stage explicitly
(none / insufficient < 20 / developing 20–99 / personal ≥ 100).

## 7. What V6 must correct

1. A passenger-fare anomaly must stay visible and monotonic in fare, whatever the driver (V5 fails; V4 is
   non-monotonic).
2. The amount-anomaly and night-behaviour rule outputs must be restored.
3. Sparse history needs an explicit anomaly basis: V4's rule needs ≥ 20 rides, and the model missed 3× fares at
   n = 1–5.
4. Inputs must be limited to what the backend has: no driver-ledger annotations, nightly jobs, tier B or location.
5. The synthetic generator must not let driver identity or familiarity act as a label proxy.
