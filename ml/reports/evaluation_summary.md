# V6 evaluation summary

> **Every number below is synthetic/demo-derived, not real-world performance.** The data is generated (see `ml/data/README.md`).
> They show how the model behaves on the generator's world, not how it will behave on real passengers.

Source of every figure: `ml/v6/evaluation/final_metrics.json` (full detail) and `ml/reports/evaluation_metrics.json` (this
summary, produced by `ml/reports/make_report_assets.py`). Nothing is re-rounded by hand.

## Which evaluation set is which

| Set | Role | Rides (fraud) | Threshold 0.0633: chosen on it, or sealed? | Precision | Recall | False-positive rate | Legitimate night rides that get an OTP | Source |
|---|---|---|---|---|---|---|---|---|
| **D6 validation** | selection data for V6 | 58,512 (759) | **used for choosing** the model and the threshold (rule: highest recall with FPR <= 2%) | 21.96% | 42.82% | 2.00% | not reported | `ml/v6/evaluation/final_metrics.json` (`validation`) |
| **T3 `D6_fresh`** (seed 64001) | **the final held-out test of V6** | 238,790 (3,040) | **sealed**: generated after V6 was frozen, scored once, threshold fixed beforehand | 22.55% | 49.11% | 2.17% | **4.32%** (daytime 1.70%) | `ml/v6/evaluation/final_metrics.json` (`T3_fresh`) |
| **`F_fresh` T3** (seed 84001) | an additional check of the deployed V6 file, made during the deployment test | 231,940 (3,163) | not used to choose V6 (V6's selection used only `D6_*` data; `F_fresh` was generated for the earlier "final" experiment, after that experiment's freeze, by that experiment's older generator) | 21.22% | 48.88% | 2.51% | **not found in the files, so not stated here** | `TapGo-ML/deployment/validation/DEPLOYED_MODEL_TEST.md` and `deployed_model_test.json` (`B_heldout_T3_batch`), in the author's ML folder; not copied into this repository |

All figures in this table: synthetic/demo-derived, not real-world performance. The 231,940-ride set is a **different** synthetic world from the 238,790-ride set (different seed and generator version), so
their figures are not directly comparable, and **neither is a measurement on real passengers**. The 238,790-ride set is the one the V6 reports (`ml/v6/reports/FINAL_REPORT.md`) use for the final result,
and the figures elsewhere in this folder come from it. For `F_fresh` the source also lists 7,285 rides flagged (3.14%), true/false positives 1,546 / 5,739, false/true negatives 1,617 / 223,038, ROC-AUC 0.890, PR-AUC 0.426.
(A third, smaller check in the same source, a brand-new universe of 72,724 rides, seed 97001, scored through the backend's own code: precision 21.6%, recall 47.5%, false-positive rate 2.35%; synthetic/demo-derived, not real-world performance.)

## Model

* XGBoost with monotone constraints, **39 features**, selected candidate `C9_xgb_mono2_P6c_fam`; model version `passenger_fraud_v6.1.0.0`.
* **Decision threshold 0.0633** (rule: highest recall with validation false-positive rate at most 2%).
  A payment whose score is at or above it is "flagged". **The score is uncalibrated**: it ranks risk, it is not a probability of fraud.

## Final held-out result: T3 (a fresh universe generated after the model was frozen)

238,790 rides, 3,040 fraud (1.27%).

| Metric | V6 | V5 (frozen) | V4 (frozen) |
|---|---|---|---|
| Precision | 22.55% | 33.38% | 30.51% |
| Recall | 49.11% | 53.45% | 52.83% |
| F1 | 0.309 | 0.411 | 0.387 |
| PR-AUC (average precision) | 0.440 | 0.501 | 0.474 |
| ROC-AUC | 0.891 | 0.894 | 0.890 |
| False-positive rate | 2.17% | 1.38% | 1.55% |
| Rides flagged | 2.77% | 2.04% | 2.20% |

V6 confusion matrix (TP / FP / FN / TN): 1,493 / 5,127 / 1,547 / 230,623.
Cluster-bootstrap 95% intervals are in `evaluation_metrics.json` (`v6_cluster_bootstrap95`).
**V6 scores lower synthetic PR-AUC than V4 and V5**: it deliberately uses only passenger history (no driver ledger, no GPS), and
legitimate long or airport trips then look unusual. V6 is the only one that passes the project's requirement tests
(`ml/v6/reports/FINAL_REPORT.md`).

With the 10-minute rule added (an OTP when the previous ride was 600 s ago or less): 5.20% of rides flagged,
false-positive rate 4.62%, recall 50.20%.

## How many legitimate rides get an OTP (T3)

| Group | Legitimate rides | Get an OTP | Share (false-positive rate) |
|---|---|---|---|
| All | 235,750 | 5,127 | 2.17% |
| Daytime | 192,887 | 3,275 | 1.70% |
| **Night (22:00-05:59 IST)** | 42,863 | 1,852 | **4.32%** |
| Ordinary legitimate rides | 192,841 | - | 0.81% |
| Legitimate expensive long / airport trips | 12,976 | - | 23.27% |

The last row is the accepted trade-off (decision D1 in `ml/v6/reports/DECISIONS.md`): a genuinely expensive trip is challenged
about one time in four, because V6 will not let a familiar driver hide an unusual fare.

## Recall at a fixed false-positive cap (T3)

| FPR cap | Recall | Precision |
|---|---|---|
| 0.5% | 38.91% | 50.11% |
| 1% | 42.89% | 35.62% |
| 2% | 48.26% | 23.73% |
| 5% | 59.57% | 13.32% |
| 10% | 72.30% | 8.53% |

## Selection data (validation) and the other held-out sets

Validation (used to choose the model and the threshold): precision 21.96%, recall 42.82%, false-positive rate 2.00%,
PR-AUC 0.393. T1 temporal, T2 unseen passengers, T4 distribution shift and T5 scenario sets are in
`evaluation_metrics.json` (`other_held_out_sets`); under shift (T4) PR-AUC drops (V6 0.199).

## Recall by fraud scenario (T3)

| Scenario | Fraud rows | Recall |
|---|---|---|
| card_testing | 679 | 99.41% |
| driver_overcharge | 409 | 15.16% |
| first_ride_fraud | 86 | 38.37% |
| gradual_compromise | 478 | 19.46% |
| indistinguishable | 146 | 0.00% |
| off_pattern_time | 234 | 41.03% |
| passenger_amount_anomaly | 203 | 61.08% |
| quiet_compromised | 156 | 2.56% |
| unfamiliar_driver_takeover | 159 | 32.08% |
| velocity_spree | 490 | 72.45% |

Some fraud kinds are caught almost always (`card_testing`) and some barely at all (`driver_overcharge` by a familiar driver, `indistinguishable`
by design). That is the honest picture.

## The 39 features

`z_log`, `log_ratio`, `abs_log_ratio`, `high_dev`, `low_dev`, `below_prior_min`, `above_prior_max`, `veh_log_ratio`, `micro_amount`, `is_night`, `night_share_s`, `night_rarity`, `hourband_share_s`, `is_weekend`, `weekend_share_s`, `no_history`, `history_insufficient`, `profile_active`, `log1p_n_prior`, `history_uncertainty`, `log_gap`, `cnt_1h`, `cnt_24h`, `cnt_7d`, `log1p_amt_1h`, `log1p_amt_24h`, `freq_ratio_7d`, `log_prev_amount_ratio`, `veh_auto_rickshaw`, `veh_taxi`, `veh_unknown`, `vehicle_share_s`, `night_amount_high`, `driver_seen`, `driver_share`, `distinct_driver_ratio`, `new_driver_rate_last10`, `prev_same_driver`, `pair_fare_dev`.

## Charts

`v6_confusion_matrix_T3.png`, `v4_v5_v6_comparison_T3.png`, `v6_recall_vs_fpr_T3.png` (generated from the numbers above).
The seven PNGs under `ml/legacy_v1/reports/` belong to the earlier baseline pipeline, not to V6.

**All figures: synthetic/demo-derived, not real-world performance.**
