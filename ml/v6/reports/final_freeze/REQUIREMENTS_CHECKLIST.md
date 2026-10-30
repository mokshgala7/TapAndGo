# Requirements checklist (final freeze, 2026-10-27)

Every item was checked by tests or scripts run during the final freeze against the frozen bundle
(`artifacts/passenger_fraud_v6_bundle.joblib`, SHA-256 `154e0afd…1680`). Raw test output: `test_output_v6.txt`.

| # | Requirement | Result | Verified by |
|---|---|---|---|
| 1 | Passenger-specific fare anomaly stays visible with a familiar driver | **PASS** | `test_model_gate[G1]`, `test_g1_familiar_driver_cannot_suppress_fare_anomaly`. Demo case 3: familiar ₹500 → level `high`, flagged |
| 2 | A higher fare does not lower the score because the driver is familiar | **PASS** | G1a monotonicity at ₹60/₹100/₹250 × {1, 2, 3, 5}, familiar and unfamiliar drivers. Demo: 0.004 → 0.336 → 0.351 → 0.351 |
| 3 | Day/night follows 06:00–21:59 / 22:00–05:59 (Asia/Kolkata) | **PASS** | `test_model_gate[G3]`: boundaries 05:59/06:00/21:59/22:00 in IST and UTC input; commuter vs night traveller; naive timestamps refused. Demo cases 5/5b, 7 |
| 4 | Explicit cold-start handling | **PASS** | `test_model_gate[G4]`: n = 0 scored with `basis = population_prior` and a warning; stages none / insufficient / developing / personal at 0 / < 20 / 20–99 / ≥ 100. Demo cases 4/4b |
| 5 | 10-minute rule: 599 and 600 s trigger, 601 s does not | **PASS** | `test_model_gate[G5]`; demo 6/6b/6c |
| 6 | Failed rides do not reset the previous completed-ride reference | **PASS** | G5b: a failed ride at +8 min, new ride at +13 min → elapsed 780 s, not triggered |
| 7 | Scoring failures never become low-risk approvals | **PASS** | `test_model_gate[G6]`, `test_missing_corrupt_mismatched_bundle`, `test_schema_mismatch_and_bad_threshold`; `verify_model.json` (`invalid_inputs_never_low_risk: true`); demo 7–7d |
| 8 | No GPS required | **PASS** | `test_model_gate[G7]`, `test_feature_sets_have_no_forbidden_or_location_columns`, `test_no_location_columns_in_any_generated_file`; location fields refused (demo 7c) |
| 9 | Training and inference feature calculations agree | **PASS** | `test_g10_interface_batch_parity` (max diff 0.0); `evaluation/inference_benchmark.json` (0 mismatches over 300 rides) |
| 10 | Risk assessment, not payment authorisation | **PASS** | `test_no_side_effect_methods`, `test_never_approves_or_rejects`; `verify_model.json` (`no_authorisation_methods: true`) |
| + | Offline inference needs no network or database | **PASS** | `verify_model.py` scored with every network socket blocked |
| + | No future-data leakage | **PASS** | `test_g9_no_future_leakage` |

## Pre-registered performance criteria (unchanged; synthetic)

6 PASS, **2 FAIL**:
- **AC-FA2 FAIL:** familiar-driver fare-anomaly recall on T5 is V6 13.4% vs V4 19.5% and V5 25.5%.
- **AC-FP FAIL:** T3 legitimate FPR is 2.17%, above V4's 1.55% + 0.5 pp.

Accepted as a trade-off by decision D1; not re-graded. Previous numeric targets (hypotheses H-AC1 to H-AC4) all FAIL.
