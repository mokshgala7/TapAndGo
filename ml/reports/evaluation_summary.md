# V6 evaluation summary

> **Every number below is synthetic/demo-derived, not real-world performance.** The data is generated (see `ml/data/README.md`).
> They show how the model behaves on the generator's world, not how it will behave on real passengers.

Source of every figure: `ml/v6/evaluation/final_metrics.json` (full detail) and `ml/reports/evaluation_metrics.json` (this
summary, produced by `ml/reports/make_report_assets.py`). Nothing is re-rounded by hand.

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
