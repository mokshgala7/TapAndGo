# Tap & Go passenger fraud detection: V6 final report

Date 2026-10-26. Location `TapGo-ML/experiments/passenger_fraud_v6/`.

**Status: reference candidate.** The project owner accepted the legitimate-expensive-trip OTP trade-off (`reports/DECISIONS.md`, D1); the acceptance results are unchanged.

**All evidence is synthetic.** No real transactions, labels or users were used. **V6 is not production-ready:** that
needs real confirmed outcomes, shadow-mode evaluation and an integration review.

## Answers

1. **Does V6 meet the actual Tap & Go requirements?**
   **Functionally, yes:**
   - every mandatory requirement gate passes (G1–G10, re-run on the frozen bundle by the tests)
   - R1 fare anomaly, R2 day/night, R3 10-minute rule, R4 cold start, R5 risk-scoring only, R6 no GPS and R7
     available data only are all implemented and tested

   **Two pre-registered performance criteria fail:**
   - AC-FA2: familiar-driver fare-anomaly recall on the scenario set is lower than V4/V5
   - AC-FP: legitimate FPR of 2.17% exceeds V4's 1.55% + 0.5 pp

   Both have one cause. Enforcing R1 strictly, without trip context, means challenging many legitimately
   expensive trips.
2. **Does the passenger fare-anomaly test pass?** Yes (gate G1, every profile). A ₹100 passenger charged
   ₹100/200/300/500 by a familiar driver scores 0.004 / 0.336 / 0.351 / 0.351 (corrected 2026-10-27 from the frozen model's gate results; the earlier figures 0.006 / 0.511 / 0.618 / 0.618 were round-1 candidate C4's), with levels none / high / high /
   high. ₹200 and above are flagged.
3. **Can a familiar driver suppress a clear fare anomaly?** No:
   - the explicit `passenger_fare_anomaly` signal is identical for familiar and unfamiliar drivers (G1e)
   - the model is monotone non-decreasing in every fare-dependent input, including the pair fare deviation
   - familiar ×3/×5 fares are flagged

   Familiarity may still lower the score of an *ordinary* fare: familiar ₹100 scores 0.004, unfamiliar ₹100 0.019.
4. **Does V6 preserve day/night behaviour?** Yes (G3):
   - the night rule separates a day commuter's 02:00 ride (fires) from a night traveller's (does not)
   - the model scores the commuter ≥ the traveller at 02:00, and 02:00 ≥ 13:00 for the commuter
   - night travellers are not flagged for ordinary rides
   - boundaries 05:59/06:00/21:59/22:00 are correct; naive timestamps are refused, never assumed UTC
   - below 20 rides the night rule cannot fire (documented)
5. **Are the 10-minute boundaries correct?** Yes:
   - 599 s and 600 s trigger; 601 s does not
   - failed rides never replace the reference
   - duplicate requests return `duplicate_request` with no score

   **The backend still has no such rule** (`qr.py:368-382`); V6 did not change the backend.
6. **Cold start:**
   - **0 rides:** compared with population priors (`basis = population_prior`) plus explicit uncertainty inputs
   - **1–99 rides:** blended with shrinkage
   - **≥ 100 rides:** fully personal (`history_stage`, V1's authoritative 100-ride boundary)
   - less history can never lower risk (monotone)
   - ₹500 is flagged and ₹100 not at n = 1, 5, 19, 50 and 150
   - first-ride fraud recall on T3: **40.0%**, vs V4 27.3% and V5 29.1%
7. **Does the system require GPS?** **No.** No location feature, input or generated column exists, and
   location-like fields are refused at inference (G7).
8. **Essential, optional, excluded:**
   - **essential:** passenger amount deviation, day/night, history, repeat/velocity, the three rules and the
     explicit anomaly signal
   - **optional, kept:** passenger-view familiarity, vehicle, weekend
   - **excluded:** location, driver ledger, V5 annotations and market median, tier B, payment method,
     `log_amount`, cyclic hour terms, `night_amount_log_ratio`, `fare_variability`

   Full list: `features/FEATURE_DICTIONARY.md`, `audit/FEATURE_SCOPE_AUDIT.md`.
9. **Versus V4 and V5** on identical rows (`reports/V4_V5_V6_COMPARISON.md`):
   - V6 is the only one passing the requirement probes
   - V6 scores **lower** synthetic AP everywhere: T3 0.440 vs 0.474 / 0.501. Most of the gap comes from
     legitimate long/airport trips, which V4/V5 recognise through driver-ledger data
   - V6 has fewer false alarms on ordinary rides (0.81% vs 1.02%) and better first-ride detection
10. **Verified metrics, T3 fresh universe** (238,790 rides, 3,040 fraud, frozen threshold 0.063318):

    | Metric | Value |
    |---|---|
    | AP | 0.440 [0.408, 0.472] |
    | ROC-AUC | 0.891 |
    | Precision | 22.6% [20.8, 24.4] |
    | Recall | 49.1% [46.4, 51.7] |
    | F1 | 0.309 |
    | FPR | 2.17% |
    | Specificity | 97.8% |
    | Confusion matrix (TP / FP / FN / TN) | 1,493 / 5,127 / 1,547 / 230,623 |
    | Rides flagged | 2.77% (≈ 277 OTP challenges per 10,000 rides) |
    | With the 10-minute rule (policy) | 5.2% flagged, FPR 4.62% |

    Validation (selection data): AP 0.393, recall 42.8% at FPR 2.0%.
11. **Distribution shift** (`evaluation/DISTRIBUTION_SHIFT_REPORT.md`):
    - T4 AP 0.199 (V4 0.220, V5 0.257)
    - FPR rises to 3.25% under 20% fare inflation
    - the unseen collusive-driver fraud is caught at 2.3%
    - gains are consistent across T1–T5, at a lower level than V4/V5
12. **Mandatory tests:** all V6 tests pass (34/34), including every gate. Development failures were recorded (C0–C8
    ineligible) and fixed by model changes, never by editing gates (`reports/TEST_REPORT.md`,
    `audit/PREREGISTRATION_AMENDMENTS.md`).
13. **Protected files preserved?** Yes, for everything V6 could touch. All 404 protected TapGo-ML files are
    unchanged; V4 (69) and V5 (63) tests still pass. Backend: backend HEAD unchanged; **the backend working tree changed during this session** (`backend/app/routes/wallet.py` modified 19:49 IST, `backend/tests/test_wallet_security.py` 19:53 IST, +571/−2 lines). V6 issued no backend command (its only backend access was read-only inspection during the earlier audit), so this was another session or person; V6 did not touch or revert it (`reports/REPRODUCIBILITY_MANIFEST.json`).
14. **Before shadow mode:**
    - the R1 / legitimate-expensive-trip trade-off is **decided** (D1, accepted)
    - the 10-minute rule's operational policy is **still open** (D2 in `reports/DECISIONS.md`: model-only vs model + rule)
    - backend: timezone-aware timestamps, a passenger-history query, passing `idempotency_key`, calling the scorer
      in log-only mode
15. **Needs separate backend authorisation:** any change to `backend/` (scorer call, 10-minute rule, timestamp
    timezone, logging, outcome review). **No new data collection is required by V6.**

## Process summary

1. Audited V4/V5 (`audit/V4_V5_REQUIREMENTS_AUDIT.md`; every V5-audit claim reproduced).
2. Wrote the gates (`audit/REQUIREMENT_TEST_SPECIFICATION.md`) and pre-registration (hash `466c8016…`).
3. De-biased the generator: no ring drivers, fraud uses familiar drivers too. The shortcut gate passes on D6; D4
   violated it.
4. Trained 10 candidates over three rounds. Each round fixed a gate failure through model structure (amendments
   A3–A5, all before any test data). One candidate (C9) passed every gate and was frozen.
5. Generated test universes after the freeze; scored V4/V5 on the same rows; ran all checks.

Final-freeze verification (2026-10-27): `reports/final_freeze/FINAL_FREEZE_REPORT.md`.

## Files

| What | Path |
|---|---|
| Model | `artifacts/passenger_fraud_v6_bundle.joblib` (+ `.sha256`, `model_metadata.json`) |
| Inference | `integration/inference.py`; contract `integration/INTEGRATION_CONTRACT.md`; errors `integration/ERROR_HANDLING.md` |
| Features and gates | `features/feature_builder.py`, `training/gates.py` |
| Tests | `tests/` |
| Metrics | `evaluation/final_metrics.json`, `metrics_summary.json`, `model_comparison.csv`, `threshold_analysis.csv`, `confusion_matrices/` |
| Reports | `reports/` (this file, `REQUIREMENTS_COMPLIANCE_REPORT.md`, `V4_V5_V6_COMPARISON.md`, `TEST_REPORT.md`, `NEXT_STEPS.md`, `REPRODUCIBILITY_MANIFEST.json`) |
