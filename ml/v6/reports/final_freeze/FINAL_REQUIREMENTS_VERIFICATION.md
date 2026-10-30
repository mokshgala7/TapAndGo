# Final requirements verification: passenger-learning lifecycle and day/night personalisation

Date 2026-10-27. Scope: verify the frozen V6 reference candidate against the passenger-learning and day/night
requirements, and correct genuine gaps **inside the isolated V6 experiment only**.

- Evidence: `lifecycle_probe.py` / `lifecycle_probe.json` (this folder) and the new test file
  `tests/test_passenger_lifecycle.py`, both against the frozen bundle `154e0afd…1680`.
- No model was trained or retrained; no threshold, OTP policy or business rule changed.
- **All data is synthetic.**

Status key:
- **PASS:** verified by implementation and a meaningful test.
- **FAIL:** the implementation does not meet the requirement.
- **NOT VERIFIED:** insufficient evidence.
- **BLOCKED:** needs a prohibited change.

## 1. Training provenance and the two initial passengers

| Fact | Evidence |
|---|---|
| The two initial passengers are **IDs 69 and 70**: 1,000 synthetic rides (500 each), 700 used for training | `TapGo-ML/data/synthetic_passenger_driver_v1/` (`synth_pd_v1_train.csv`, `passenger_profiles_summary.csv`) |
| Only **V1** (and V2's re-selection) were trained on them | V1 final report (archive): "two passengers (IDs 69 and 70)" |
| **V6 was not trained on them.** V6's shared model was trained on **4,049 fictional synthetic passengers**: 2,066 in the D6_dev train split (113,852 rides) plus 1,983 in two extra training worlds (147,532 rides). Passengers 69/70 do not appear | `artifacts/model_metadata.json` `trained_on`; `data/synthetic/D6_dev`, `D6_dr1/2` |
| Why it changed | V1 showed two passengers cannot represent passenger diversity: V1/V2 collapsed to PR-AUC ≈ 0.15 on diverse passengers. Your V3 brief asked for "more diverse passengers"; V3–V6 followed it |

| Requirement | Status |
|---|---|
| A shared model learns general ordinary vs suspicious patterns from the training population | **PASS** (one model, `C9_xgb_mono2_P6c_fam`, scores every passenger) |
| The model is not limited to its training passengers at inference | **PASS** (inference takes any passenger's history; T2 evaluates 297-fraud unseen passengers) |
| "Two initial passengers as the starting source of learned patterns" | **FAIL as literally stated.** V6's training provenance is the 4,049-passenger synthetic population, not passengers 69/70. Changing it would require retraining, so it is **BLOCKED** and left unchanged. Passengers 69/70 remain preserved in the repository |

## 2. New passengers: transactions 1–99 (actual implementation)

There is **one shared model**; no per-passenger model is trained at any point. Each passenger's history is turned into
features at scoring time:
- **Typical fare and spread:** med_s = (n·personal median + 5·population median)/(n + 5), with MAD likewise.
  Fare deviation z = (ln fare − med_s)/max(1.4826·MAD_s, 0.15).
- **Day/night shares:** night share, hour band and weekend share are shrunk to population shares in the same way.
- **History indicators:** `no_history`, `history_insufficient` (< 20), `history_uncertainty` = 1/√(n+1). The model
  is monotone, so less history can never lower risk.

| Requirement | Result | Status |
|---|---|---|
| Shared patterns are used for a passenger with no history | n = 0 → `basis = population_prior`; typical fare = the population median (₹131.0). ₹500 flagged (0.184); ₹100 not (0.006) | **PASS** (`test_new_passenger_uses_shared_population_baseline`) |
| Personal history is used from the first ride | typical fare moves from the population value toward the passenger's own with every ride (n = 1, 5, 20, 99) | **PASS** (`test_personal_history_blends_in_from_the_first_rides`) |
| Suspicious fares assessed from the first transaction | fare deviation and anomaly level are computed at every n. ₹500 is flagged at n = 0, 1, 5, 19 and 50. **₹300 is not flagged at n = 0 or 1** (0.061 / 0.052, threshold 0.0633); it is flagged from n = 5 | **PASS**, with the stated limit (`G4` gate; `lifecycle_probe.json`) |
| Missing history is not treated as safe | monotone constraints: `history_uncertainty`, `history_insufficient`, `no_history` ↑ and `log1p_n_prior` ↓ | **PASS** (`test_missing_history_is_not_treated_as_safe`) |
| No per-passenger model is claimed | correct: personalisation is feature-level | **PASS** |

## 3. The 99 / 100 / 101 transition (actual behaviour)

| n eligible rides | `history_stage` | `profile_active` input | Contribution of `profile_active` | Score at ₹300 (familiar driver) |
|---|---|---|---|---|
| 98 | developing | 0 | −0.012 | 0.356 |
| **99** | developing | **0** | −0.013 | **0.362** |
| **100** | **personal** | **1** | **+0.080** | **0.425** |
| **101** | personal | 1 | +0.082 | 0.440 |

Contributions are XGBoost log-odds from `pred_contribs`.

- The threshold is exactly **100**: `PROFILE_ACTIVATION_MIN = 100` (`features/v3_features.py:28`), and `profile_active = n_prior >= 100`.
- The switch happens at 100, not 99 or 101.
- It is a **personalisation stage of the shared model**: an input flag plus the reported `history_stage`. It is
  **not** a separately trained model.
- The flag genuinely changes the frozen model's score: flipping only `profile_active` changes the output (test). Its
  weight is small, 0.1% of total gain.
- Most personalisation is continuous, through the shrinkage blend from ride 1. By n = 100, personal history
  carries 95% of the weight.

**Status: PASS** (`test_profile_activation_exactly_at_100[...]`, `test_activation_changes_the_model_score`). It
cannot become a hard switch to a different scoring regime without retraining; that is not required, and
documented as such.

## 4. How eligible transactions are counted

Eligible = this passenger's rides with status `completed` and a timestamp strictly earlier than the current ride
(`features/v3_features.py` stage 1, `k_before` over completed rows).

| Case | Behaviour | Status |
|---|---|---|
| Failed rides | not counted (99 completed + 10 failed → 99, stage developing) | **PASS** (`test_failed_rides_do_not_count`) |
| The current transaction | never counted | **PASS** (causality gate G9) |
| A history row repeating an `idempotency_key` (same payment recorded twice) | **was counted twice (gap found)**: 99 rides + 1 duplicate → 100, wrongly activating the personal stage. **Corrected**: the later copy is ignored, with warning `duplicate_history_rows_ignored` | **PASS after correction** (`test_duplicate_history_rows_do_not_count`, `test_identical_duplicate_row_with_key_counts_once`) |
| An identical row without a key (same timestamp) | refused: `invalid_input`, no score, fallback; never counted | **PASS** (`test_identical_duplicate_row_without_key_is_refused_safely`) |
| A transaction that duplicates a history request | `duplicate_request`, no score | **PASS** (gate G5c/G5d) |

## 5. Day/night profiles: how they are built and used

- **Classification:** night = 22:00–05:59 Asia/Kolkata (`v3_features.py:24-25`), applied after converting any offset
  to Asia/Kolkata. Naive timestamps are refused, never assumed UTC.
- **Built from the passenger's earlier completed rides:**
  - shrunk night share `night_share_s`
  - `night_rarity` = is_night × (1 − night share)
  - hour-band share
  - the passenger's **night median fare**, once they have ≥ 3 night rides, feeding `night_amount_high` = max(0, ln fare − night reference)
- **Night rule** (an explicit output, needs ≥ 20 rides): fires for a night ride when night share < 15% or fare > 2× night median.
- **The rule flag is not an OTP challenge.** The step-up policy is model flag or the 10-minute rule only.

| # | Required test | Result (frozen model) | Status |
|---|---|---|---|
| 1 | Ordinary daytime ride not flagged | day-only passenger, ₹100 at 13:07: 0.004, not flagged | **PASS** |
| 2 | Expensive daytime fare assessed against normal behaviour | ₹250 at 13:07: 0.362, flagged, amount rule True | **PASS** |
| 3 | Regular night traveller not flagged for riding at night | ₹100 at 23:07: 0.002, not flagged, night rule False | **PASS** |
| 4 | Expensive night fare assessed against **night** behaviour | for a passenger whose nights cost ≈ ₹200: night ₹400 → 0.165 (flagged) > night ₹200 → 0.097. Night ₹200 scores **lower** for that passenger than for one whose nights cost ₹100 (0.146); `night_amount_high` = 0 at their usual night fare | **PASS** (direction verified), with the limitation below |
| 5 | New passenger assessed with shared patterns and limited history | see §2 | **PASS** |
| 6 | Personalisation changes as history accumulates | the day-only passenger's night share falls from the population 0.19 (n = 0) to 0.095 (5), 0.038 (20) and 0.009 (100). The night rule becomes active at n = 20 (False at 19, True at 20) | **PASS** (`test_night_profile_evolves_with_history`) |
| 7 | Boundaries 05:59 night, 06:00 day, 21:59 day, 22:00 night | correct, also for UTC-offset input | **PASS** (`test_day_night_boundaries`, gate G3e) |
| 8 | Timestamps interpreted safely | naive → `invalid_input`, no score | **PASS** (gate G3f) |

**Limitation (test 4), stated honestly.** A passenger whose *ordinary* night fare is about twice their day fare is still
flagged at that ordinary night fare (0.097 vs threshold 0.063). The night-specific baseline enters the model only
through `night_amount_high`, while `z_log`, `veh_log_ratio` and `pair_fare_dev` compare against the passenger's
**overall** typical fare. Making every fare feature period-specific would need retraining, so it is **BLOCKED** and
left unchanged. The behaviour is directionally correct but can over-challenge passengers with pricier night travel.

Personalisation genuinely influences scores. The same ₹250 fare scores **0.337 (flagged)** for a ₹100 passenger and
**0.004 (not flagged)** for a ₹250 passenger (`test_personal_typical_fare_changes_the_assessment`). The night
examples above differ only in the passenger's own history. **PASS.**

## 6. Fare-anomaly results (familiar and unfamiliar drivers)

Passenger who usually pays ₹100, 80 rides, gate G1 fixtures:

| Fare | Familiar driver: score / flag | Unfamiliar driver: score / flag | Explicit anomaly level (both) |
|---|---|---|---|
| ₹100 | 0.004 / no | 0.019 / no | none |
| ₹200 | 0.336 / yes | 0.485 / yes | high |
| ₹300 | 0.351 / yes | 0.485 / yes | high |
| ₹500 | 0.351 / yes | 0.485 / yes | high |

- The score never falls as the fare rises, and the explicit signal is identical for both drivers.
- A familiar driver lowers the score somewhat, as permitted context, but **cannot make the anomaly look safe**.
- The fare-anomaly signal, the model score and the OTP decision are separate fields.
- No threshold guarantee is claimed beyond what the tests show.

**PASS** (gate G1, `test_g1_familiar_driver_cannot_suppress_fare_anomaly`).

## 7. Ten-minute rule

| Check | Result | Status |
|---|---|---|
| 599 s / 600 s / 601 s | trigger / trigger / no trigger, with exact `elapsed_seconds` | **PASS** (gate G5a) |
| Failed ride does not reset the reference | completed at 0, failed at +8 min, new ride at +13 min → 780 s, not triggered | **PASS** (G5b) |
| Duplicate requests | `duplicate_request`, no score, fallback | **PASS** (G5c/G5d) |
| Where it exists | **only in the V6 offline inference.** The production backend does not implement it: ride payments are written `otp_verified=True, fraud_status="clear"` (`backend/app/routes/qr.py:368-382`) | integration **BLOCKED** (needs authorised backend work) |
| Whether it should trigger OTP | open product decision **D2** (`reports/DECISIONS.md`); unchanged | — |

## 8. Tests executed

See §11: V6 60/60 (26 new lifecycle tests), V5 63/63, V4 69/69, legacy 57/57; 0 failed, 0 skipped.

## 9. Code changes (isolated V6 only)

| File | Change | Effect on frozen results |
|---|---|---|
| `experiments/passenger_fraud_v6/integration/inference.py` | History rows repeating an `idempotency_key` already seen in the same history are counted once; warning `duplicate_history_rows_ignored`. Pre-correction copy: `reports/final_freeze/inference_pre_correction.py.txt` | **None on any reported metric.** Metrics come from the batch builder, and batch data has no idempotency keys. Inference/batch score parity re-checked on 300 T3 rides: 0 mismatches (`post_correction_parity.json`). It changes scoring **only** for histories that contain duplicate payment records (they previously over-counted history) |
| `experiments/passenger_fraud_v6/tests/test_passenger_lifecycle.py` | **new** (26 tests); no existing test modified | — |
| `reports/final_freeze/lifecycle_probe.py`, `lifecycle_probe.json`, `post_correction_parity.json`, this report | new | — |
| `reports/FINAL_REPORT.md`, `REQUIREMENTS_COMPLIANCE_REPORT.md`, `V4_V5_V6_COMPARISON.md` | **documentation correction**: the familiar-driver probe scores quoted there (0.006 / 0.511 / 0.618 / 0.618) were round-1 candidate C4's, not the selected C9's. Replaced with C9's verified values 0.004 / 0.336 / 0.351 / 0.351 (`evaluation/gate_results.json`); the PASS verdicts are unaffected | none |

Not changed: the model bundle, threshold, policy, training data, evaluation outputs, every other source file, V1–V5,
the backend.

## 10. Frozen metrics (unchanged, synthetic only; T3, 238,790 rides)

| Metric | Value |
|---|---|
| AP | 0.440 |
| Precision | 22.6% |
| Recall | 49.1% |
| FPR | 2.17% |
| TP / FP / FN / TN | 1,493 / 5,127 / 1,547 / 230,623 |
| Shifted universe (T4) | AP 0.199, FPR 3.25% |

**Accuracy discrepancy, corrected:** the brief quoted "≈ 97.16%". The saved artifact gives
**97.21%** ((1,493 + 230,623) / 238,790 = 0.97205; `evaluation/final_metrics.json` `accuracy`). Accuracy is not a
selection metric for this imbalanced problem: an all-legit model would score 98.73%.

These are synthetic results, not real-world performance.

## 11. Test results and integrity

| Suite | Result |
|---|---|
| **V6, full** (`tests/`: 34 existing + **26 new** in `test_passenger_lifecycle.py`) | **60 passed, 0 failed, 0 skipped** (`test_output_v6_requirements_verification.txt`) |
| V5 (protected) | 63 passed |
| V4 (protected) | 69 passed |
| Legacy pipeline | 57 passed |
| Inference vs batch scores after the correction, 300 T3 rides | 0 mismatches (`post_correction_parity.json`) |
| Demo output after the correction | byte-identical to the final-freeze run |

During development one new test failed once (`test_identical_duplicate_row_is_refused_safely`). Its fixture gave
every row an `idempotency_key`, so the corrected code rightly counted the copy once instead of refusing it. The
test was split into the key-less case (refused) and the keyed case (counted once). No existing test was changed.

**Integrity** (against `PROTECTED_ARTIFACT_MANIFEST.json`, after all edits):
- 171 model/evaluation artifacts: **0 changed**
- V6 404-file snapshot: **0 changed**
- ML repo HEAD and status: **unchanged**
- Backend HEAD and status: **unchanged** since the freeze

The backend's pre-existing external edits to `wallet.py` and `test_wallet_security.py` (2026-10-26 19:49–19:53 IST,
not made by this project) were not touched. Nothing was committed, pushed or deployed. No `__pycache__` or
`.pytest_cache` was left behind.

## 12. Remaining limitations and decisions needing approval

1. **The two-passenger provenance is not V6's.** Training V6 on passengers 69/70 would need retraining (BLOCKED, and
   not advisable given V1/V2's results).
2. **Night fares are judged partly against the overall typical fare** (§5, test 4). Fully period-specific baselines
   need retraining (BLOCKED).
3. **A new passenger's moderate fare (₹300) is not flagged at 0–1 rides,** because it is compared with the population.
4. **D2: whether the 10-minute rule triggers OTP** (≈ 175 legitimate challenges per extra fraud). Product decision.
5. **Backend integration** (scorer call, 10-minute rule, timezone-aware `created_at`, passing `idempotency_key`)
   needs separate authorisation.
6. **Real confirmed outcomes** are required before production. V6 is a reference candidate, not production-ready.
