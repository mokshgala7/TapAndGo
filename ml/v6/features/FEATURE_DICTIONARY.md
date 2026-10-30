# V6 feature dictionary

Code: `features/feature_builder.py`, which builds on `features/v3_features.py` (a byte-identical copy of V3's verified builder,
SHA-256 `46717495…`).

**Temporal rule.** History uses only this passenger's rides with status `completed` and a timestamp strictly earlier
than the current ride (nanosecond comparison). Failed rides count only for the 10-minute rule's "previous completed
ride" logic, and they never become the reference.

**Source fields:** `timestamp` (must carry an offset), `amount`, `driver_id`, `payment_method`, `vehicle_type`,
`status`. All already exist in the backend `transactions` table (`vehicle_type` is on the driver's user row).

**Shrinkage** (k = 5 pseudo-rides of the train-period population prior): med_s, MAD_s.
**Night** = 22:00–05:59 Asia/Kolkata.

## Selected model inputs (`P6c_fam`, 39, in order)

| # | Feature | Definition | Monotone | Requirement |
|---|---|---|---|---|
| 1 | `z_log` | (ln fare − med_s) / max(1.4826·MAD_s, 0.15) | ↑ | R1 |
| 2 | `log_ratio` | ln fare − med_s | ↑ | R1 |
| 3 | `abs_log_ratio` | \|log_ratio\| | ↑ | R1 |
| 4 | `high_dev` | max(0, log_ratio) | ↑ | R1 |
| 5 | `low_dev` | max(0, −log_ratio) (0 above the median) | – | R1 (micro-fares) |
| 6 | `below_prior_min` | min(0, ln fare − ln min earlier fare) | – | R1 |
| 7 | `above_prior_max` | max(0, ln fare − ln max earlier fare) | ↑ | R1 |
| 8 | `veh_log_ratio` | ln fare − shrunk same-vehicle median | ↑ | R1 |
| 9 | `micro_amount` | max(0, ln 30 − ln fare) (0 for fares ≥ ₹30; card testing) | – | R1 |
| 10 | `is_night` | ride at 22:00–05:59 local | ↑ | R2 |
| 11 | `night_share_s` | shrunk share of earlier rides at night | – | R2 |
| 12 | `night_rarity` | is_night × (1 − night_share_s) | ↑ | R2 |
| 13 | `hourband_share_s` | shrunk share of earlier rides within ±1 h of this hour | ↓ | R2 |
| 14 | `is_weekend` | Sat/Sun local | – | R5 |
| 15 | `weekend_share_s` | shrunk weekend share | – | R5 |
| 16 | `no_history` | n = 0 | ↑ | R4 |
| 17 | `history_insufficient` | n < 20 | ↑ | R4 |
| 18 | `profile_active` | n ≥ 100 (V1 boundary) | – | R4 |
| 19 | `log1p_n_prior` | ln(1 + n) | ↓ | R4 |
| 20 | `history_uncertainty` | 1/√(n + 1) | ↑ | R4 |
| 21 | `log_gap` | ln(1 + seconds since the previous completed ride); sentinel 365 days | – | R3/R5 |
| 22–24 | `cnt_1h`, `cnt_24h`, `cnt_7d` | earlier completed rides in the window | – | R5 |
| 25–26 | `log1p_amt_1h`, `log1p_amt_24h` | ln(1 + ₹ in the window) | – | R5 |
| 27 | `freq_ratio_7d` | (cnt_7d + 1) / (usual daily rate × 7 + 1) | – | R5 |
| 28 | `log_prev_amount_ratio` | ln fare − ln previous completed fare | ↑ | R1 |
| 29–31 | `veh_auto_rickshaw`, `veh_taxi`, `veh_unknown` | vehicle one-hot | – | R5 |
| 32 | `vehicle_share_s` | shrunk share of earlier rides with this vehicle type | – | R5 |
| 33 | `night_amount_high` | at night: max(0, ln fare − night reference), where the reference is the night median if ≥ 3 night rides, else med_s; 0 by day | ↑ | R2 |
| 34 | `driver_seen` | this passenger has ridden with this driver before | – | familiarity (optional) |
| 35 | `driver_share` | share of the passenger's earlier rides with this driver | – | optional |
| 36 | `distinct_driver_ratio` | distinct drivers / n | – | optional |
| 37 | `new_driver_rate_last10` | share of first-time drivers in the last 10 rides | – | optional |
| 38 | `prev_same_driver` | previous completed ride was with this driver | – | optional |
| 39 | `pair_fare_dev` | ln fare − pair median (shrunk to med_s, k = 3) | ↑ | R1 (familiar-driver anomaly) |

↑ = non-decreasing and ↓ = non-increasing (XGBoost `monotone_constraints`). For fares at or above max(₹30, passenger
median, passenger minimum), every fare-dependent input is non-decreasing in the fare and constrained ↑. **The risk score
therefore cannot fall as the fare rises, whatever the driver.** Gate G1 verifies this.

## Explicit outputs (outside the model)

| Output | Definition |
|---|---|
| `passenger_fare_anomaly.level` | **high**: z ≥ 3 and ratio ≥ 1.8; **elevated**: z ≥ 2 and ratio ≥ 1.4; else none |
| `passenger_fare_anomaly.basis` | `population_prior` if n = 0, else `personal_shrunk` |
| `passenger_fare_anomaly.history_stage` | none (0) / insufficient (< 20) / developing (20–99) / personal (≥ 100) |
| `rules.rapid_repeat_10min` | 0 ≤ whole seconds since the previous **completed** ride ≤ 600 |
| `rules.amount_anomalous` | level = high |
| `rules.night_behaviour_anomalous` | V3 rule: night ride, ≥ 20 rides, and (night share < 15% or fare > 2× night median) |

## Excluded (and why)

| Excluded | Reason |
|---|---|
| `log_amount` | non-monotonic risk; replaced by the explicit micro-fare and relative features |
| `hour_sin`, `hour_cos` | let the model learn population-level "night is safe", which suppressed the personal night anomaly (round-1 G3 failure) |
| `night_amount_log_ratio` | made cheaper-than-usual night fares look safer (round-2 G3 failure); replaced by `night_amount_high` |
| `fare_variability` | double-counted variability already inside `z_log` and discounted anomalies in sparse histories (G4 failure) |
| `pay_*`, `method_share_s` | constant `"QR"` for ride payments in the backend (`qr.py:374`) |
| driver-ledger features (V4 `driver_*`, V5 `drv_*`, market, annotations) | need extra queries, new stored columns or nightly jobs (R7); synthetic-dependent; suppressed R1 in V5 |
| tier B (declines, confirmed reports, airport flag) | not available in the backend |
| any location, route, distance, zone, airport, GPS | out of scope (R6); refused at inference |
