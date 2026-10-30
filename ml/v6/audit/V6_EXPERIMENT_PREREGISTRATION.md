# V6 experiment pre-registration

Written 2026-10-26 (IST) **before** any V6 data was generated, any V6 feature was computed or any V6 model was
fitted. Hashed in `logs/preregistration_hash.txt`. Later changes go to `audit/PREREGISTRATION_AMENDMENTS.md`
with a reason and a timestamp. This file is never edited.

Inputs to this design:
- `audit/V4_V5_REQUIREMENTS_AUDIT.md` (re-verified V5-audit findings)
- `audit/REQUIREMENT_TEST_SPECIFICATION.md` (gates G1–G10)

## 1. Goal and priority

A requirements-compliant risk scorer: R1 passenger fare anomaly (with familiar drivers too), R2 day/night,
R3 10-minute rule, R4 cold start, R5 risk scoring only, R6 no GPS, R7 available data only.
**Requirements gate selection; average precision only ranks eligible candidates.**

## 2. Scope decisions (reasoning recorded)

| Decision | Reason |
|---|---|
| Inputs = transaction + this passenger's earlier ride payments **only** | R7: every V5 driver-ledger, annotation, market and tier-B feature needs new backend data or jobs |
| No driver-global features (V4) | They need a second query, are inflated by synthetic driver types, and V5's audit shows driver signals suppressing R1 |
| Passenger-view familiarity (has this passenger ridden with this driver; their usual fare with them) allowed **only** in candidate set `P6_fam`, with monotonic constraints | Computable from passenger history alone. Eligible only if gates G1/G2 still pass |
| No payment-method features | Ride payments are always `"QR"` in the backend (`qr.py:374`) |
| `log_amount` replaced by `micro_amount` = max(0, ln 30 − ln fare) | Absolute fare level is non-monotonic in risk (tiny card tests and big overcharges are both fraud). `micro_amount` is 0 for fares ≥ ₹30, so it cannot break fare monotonicity there |
| No location, trip type, airport, distance or route features, and none in the generator output | R6 |
| 100-ride boundary is authoritative (V1 brief) | Exposed as `history_stage` and `profile_active` |

## 3. Features (code: `features/feature_builder.py`; V3's verified stage-1/stage-2 code copied byte-identical as `features/v3_features.py`)

Definitions:
- **Shrinkage:** med_s = (n·median + 5·population median) / (n + 5); MAD likewise.
- **z:** z = (ln fare − med_s) / max(1.4826·MAD_s, 0.15).
- **Population priors:** fitted on D6_dev train rides only.
- **Night:** 22:00–05:59 Asia/Kolkata. Naive timestamps are refused.

**P6** (35 inputs):

| Group | Features |
|---|---|
| Amount anomaly | `z_log`, `log_ratio`, `abs_log_ratio`, `high_dev`, `low_dev`, `below_prior_min`, `above_prior_max`, `veh_log_ratio`, **`fare_variability`** (= shrunk MAD), **`micro_amount`** |
| Day/night | `is_night`, `hour_sin`, `hour_cos`, `night_share_s`, `night_rarity`, `night_amount_log_ratio`, `hourband_share_s`, `is_weekend`, `weekend_share_s` |
| History | `no_history`, `history_insufficient` (< 20), `profile_active` (≥ 100), `log1p_n_prior`, **`history_uncertainty`** (= 1/√(n+1)) |
| Velocity | `log_gap`, `cnt_1h`, `cnt_24h`, `cnt_7d`, `log1p_amt_1h`, `log1p_amt_24h`, `freq_ratio_7d`, **`log_prev_amount_ratio`** |
| Vehicle | `veh_auto_rickshaw`, `veh_taxi`, `veh_unknown`, `vehicle_share_s` |

**P6_fam** = P6 + `driver_seen`, `driver_share`, `distinct_driver_ratio`, `new_driver_rate_last10`, `prev_same_driver`,
`pair_fare_dev` (pair median shrunk to the passenger median with k = 3).

**Monotone non-decreasing constraints** (tree models that support them): `z_log`, `log_ratio`, `abs_log_ratio`,
`high_dev`, `above_prior_max`, `veh_log_ratio`, `night_amount_log_ratio`, `log_prev_amount_ratio`, `pair_fare_dev`.
For fares at or above max(₹30, passenger median, passenger minimum), every other fare-dependent input is constant.
So the score cannot fall as the fare rises.

## 4. Rules and explicit signals (outside the model, always returned)

| Output | Definition |
|---|---|
| `passenger_fare_anomaly` | z, ratio = exp(ln fare − med_s), `basis` (population_prior if n = 0, else personal_shrunk), `history_stage`, level: **high** if z ≥ 3 and ratio ≥ 1.8; **elevated** if z ≥ 2 and ratio ≥ 1.4; else none |
| `rapid_repeat_10min` | V3 rule: 0 ≤ whole seconds since the previous **completed** ride ≤ 600 |
| `amount_anomalous` | `passenger_fare_anomaly.level == "high"` (V6 definition; works at any history length) |
| `night_behaviour_anomalous` | V3 rule unchanged: night ride, ≥ 20 rides, and (night share < 15% or fare > 2× night median) |

Policy: `recommended_action = step_up_verification` if model flag or the 10-minute rule fires (V1 design).
The amount and night rules join the policy only if the validation cost analysis shows ≤ 20 extra legitimate
challenges per extra fraud caught. Decided on **validation**, before any test data exists. Otherwise they are
reported only.

Duplicate requests: a transaction whose `idempotency_key` appears in the history, or which is identical in
(timestamp, amount, driver) to a history ride, returns `duplicate_request` with no score.

## 5. Synthetic data (generator `data/generator_v6.py`, derived from V4's with the changes below)

Changes from V4, to remove the audited shortcuts:
1. **No "ring" drivers.** Driver types: local 0.88, hub 0.07 (legitimate airport/station queue), dishonest 0.05.
2. **Fraud driver choice is no longer concentrated on special drivers.** Each passenger scenario picks the
   passenger's **familiar** driver with a scenario-specific probability, otherwise a random non-hub driver:

   | Scenario | P(familiar driver) |
   |---|---|
   | amount anomaly | 0.5 |
   | quiet compromised | 0.5 |
   | gradual compromise | 0.4 |
   | off-pattern time | 0.4 |
   | velocity spree | 0.2 |
   | card testing | 0.2 |
   | unfamiliar takeover | 0 (by definition) |

   Fraudulent new accounts pick random drivers.
3. **Dishonest drivers** overcharge 4% of their rides at ×1.4–2.6, regular passengers included.
4. Legitimate expensive journeys are kept: 5% long trips (12–25 km) and 1.2% airport trips, with familiar and
   unfamiliar drivers.
5. Distances (`km`) and zones remain internal to the generator. **No location, trip-type, airport or zone column
   reaches any feature.** `trip_type`, `driver_type` and `scenario` are written to events as **metadata only**
   (subgroup reporting), never to the ledger or features.
6. IDs prefixed `V6`.

Pre-training diagnostics are recorded before any model is fitted, and they gate data use:
- fraud share by driver type
- familiar-driver share (fraud vs legit)
- fraud rate of ≥ 2× fares with familiar vs unfamiliar drivers

If one driver type holds > 40% of fraud while carrying < 10% of legitimate rides, the generator is fixed
**before** training and the fix recorded as an amendment.

| Universe | Seed | Passengers | Use | When |
|---|---|---|---|---|
| D6_dev | 61001 (groups 61002) | 3,000 | train = panel before 2026-07-01; validation = panel July + heldout_val; **sealed** T1 temporal = panel August; T2 unseen = heldout_test | before training |
| D6_valshift | 61501 | 1,200 | selection robustness (fare ×1.10, night +0.15, more missing vehicle) | before training |
| D6_dr1, D6_dr2 | 62001, 62002 | 1,000 each | extra training worlds; parameters drawn once (seed 62000) from V5's pre-registered ranges; no collusive mechanism | before training |
| D6_fresh | 64001 | 3,000 | T3 | **after freeze** |
| D6_shift | 65001 | 2,500 | T4: V4's SHIFT parameters, including the unseen `collusive_regular_driver` | **after freeze** |
| D6_scenario | 66001 | 2,500 | T5: boosted amount anomaly, overcharge, first-ride, off-pattern, spree, gradual; dedicated subsets | **after freeze** |

Dedicated test subsets (all post-freeze or sealed):
- **fare anomaly:** `passenger_amount_anomaly` + `driver_overcharge`, split by familiar/unfamiliar driver, plus legit long/airport trips for the FP side
- **cold start:** history buckets
- **day/night:** daypart × archetype
- **repeat/multi-leg:** `legit_multi_leg`, `legit_retry`, `velocity_spree`

## 6. Candidates (small, justified)

Trained on D6_dev train + D6_dr1/2. Hyper-parameters chosen on the inner split (train before 2026-06-01 → June
train rows). Seed 42.

| ID | Model | Features | Grid |
|---|---|---|---|
| C0 | transparent logistic regression (standardised) | 6: `z_log`, `high_dev`, `night_rarity`, `history_uncertainty`, `cnt_1h`, `log_gap` | C ∈ {0.1, 1} |
| C1 | logistic regression (standardised, balanced) | P6 | C ∈ {0.1, 1} |
| C2 | Extra Trees (300 trees, balanced_subsample) | P6 | min_samples_leaf ∈ {3, 10} |
| C3 | XGBoost with the monotone constraints | P6 | depth ∈ {4, 6}, trees ∈ {300, 600}, lr 0.05, subsample/colsample 0.8 |
| C4 | XGBoost with the monotone constraints | P6_fam | same |

## 7. Selection

1. **Stage A:** gates G1–G10 at each candidate's own threshold (highest recall with validation FPR ≤ 2%). Any failure → ineligible, with reasons recorded.
2. **Stage B** (eligible only, validation data):
   - shortlist = within 0.01 of the best validation AP
   - drop candidates whose D6_valshift AP is > 0.03 below the shortlist best
   - pick the highest validation recall at FPR ≤ 2%
   - within 0.005, prefer fewer features, then lower latency
3. If no candidate is eligible: report that, freeze nothing as "selected", and list the blockers.
4. Freeze bundle, threshold, `selection.json` (`post_freeze_data_generated: false`, `sealed_read: false`) before
   generating D6_fresh/shift/scenario or reading T1/T2.

## 8. Metrics

- **Primary:** AP (`sklearn average_precision_score`).
- **Also:** ROC-AUC, precision, recall, F1, FPR, specificity, confusion matrix, flagged %, OTP challenges per 10k rides, recall at FPR 0.5/1/2/5%, latency.
- **Uncertainty:** passenger-cluster bootstrap (500); paired bootstrap for V6 − V4 and V6 − V5 on identical rows.
- **References:** V4 and V5 frozen models are scored on the same V6 rows. V5's driver annotation and market inputs are rebuilt from each V6 ledger by V5's own code.

## 9. Acceptance criteria (fixed now)

| ID | Criterion | PASS if |
|---|---|---|
| AC-G | Selected model passes every mandatory gate G1–G10, re-run on the frozen bundle by the test suite | all pass |
| AC-GPS | No location dependency (G7) | pass |
| AC-FA1 | Deterministic fare-anomaly probes (G1): V6 passes; report V4/V5 on the same probes | V6 passes all |
| AC-FA2 | Dedicated fare-anomaly subset of D6_scenario, **familiar-driver** `passenger_amount_anomaly` + `driver_overcharge` rows: V6 recall at its frozen threshold > V4's and > V5's on the same rows | both comparisons higher |
| AC-FP | D6_fresh legitimate FPR at the frozen threshold ≤ 2.5% **and** ≤ V4's FPR on the same rows + 0.5 pp | both |
| AC-REP | Data regeneration identical; refit of the selected model bit-identical on validation | pass |
| AC-PAR | Interface vs batch: features ≤ 1e-9 on 25 rows; scores equal (6 d.p.) on 300 rows | pass |
| AC-PROT | No protected file (404) changed; backend HEAD and status unchanged | pass |

**Previous numeric targets, kept as hypotheses** (not achievements). They are not comparable to V4/V5 numbers
because D6 removes the ring-driver shortcut:

| ID | Hypothesis |
|---|---|
| H-AC1 | validation AP ≥ 0.72 |
| H-AC2 | D6_shift AP ≥ 0.55 |
| H-AC3 | D6_fresh legit-airport FPR ≤ 10% |
| H-AC4 | D6_fresh driver-overcharge recall ≥ 85% |

Prior expectation: H-AC1, H-AC2 and H-AC4 FAIL. V5's latent-context ceiling (0.694 AP; 83% overcharge) already
fell short with richer inputs, and V6 deliberately uses fewer inputs.

Status vocabulary: PASS / FAIL / INCONCLUSIVE (support below 300 fraud, or below 100 cases for a subset) / NOT EVALUABLE.

## 10. Failure conditions

- **F1:** no candidate passes Stage A. Report the blockers.
- **F2:** the selected model's D6_fresh recall < 30% or FPR > 3%: threshold unusable.
- **F3:** any protected file changes: stop and report.
