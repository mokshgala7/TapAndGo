# V6 integration contract (reference candidate; research only; NOT production-ready; not integrated anywhere)

Code: `integration/inference.py` (`FraudScorerV6`). It recommends risk only: it never approves or rejects a payment,
touches wallets, sends OTPs, or opens a database or network connection. All supporting evidence is synthetic.

## 1. Identity

| Item | Value |
|---|---|
| Model version | `passenger_fraud_v6.1.0.0` (candidate C9: XGBoost, monotone constraints v2, 300 trees, depth 4) |
| Feature schema | `v6-features-1` (39 inputs, set `P6c_fam`) |
| Output schema | `passenger_fraud_inference/6` |
| Threshold | **0.063318** (0.0633183941245079), version `v6-thr-1`: the highest-recall threshold with validation FPR ≤ 2% |
| Bundle | `artifacts/passenger_fraud_v6_bundle.joblib`, SHA-256 `154e0afd6dc978467d2cbdc000de6a50473b4f92cda383bf641fb564dd261680` (also in the `.sha256` sidecar); refused on mismatch |

## 2. Call

```python
from integration.inference import FraudScorerV6
scorer = FraudScorerV6.load()                     # verifies hash and library versions
out = scorer.score_safe(transaction, passenger_history)
```

| Argument | Content |
|---|---|
| `transaction` | `timestamp` (ISO-8601 **with offset**; naive timestamps are refused, never assumed UTC), `amount` (₹, > 0, ≤ 100,000), `driver_id`, `payment_method` (or null), `vehicle_type` (or null), optional `idempotency_key` |
| `passenger_history` | this passenger's earlier ride payments (completed and failed): `timestamp`, `amount`, `driver_id`, `payment_method`, `vehicle_type`, `status`, optional `idempotency_key`; all strictly before the transaction |

That is all. **No driver ledger, no aggregates, no new backend columns, no location.** Any field whose name looks like
location data (gps, lat, lon, geo, location, coord, route, distance, zone, airport) is **refused** (`invalid_input`).

## 3. Output fields

| Field | Meaning |
|---|---|
| `schema_version` | output schema version |
| `scoring_status` | `scored`, `invalid_input`, `duplicate_request`, `schema_mismatch`, `model_unavailable` or `prediction_error` |
| `model_version`, `feature_schema_version` | the versions in section 1 |
| `risk_score` | uncalibrated, **not a probability** |
| `score_semantics` | text stating the above |
| `threshold` | value and version |
| `model_flag` | `risk_score ≥ threshold` |
| `passenger_fare_anomaly` | the explicit signal, independent of the model: `level` (none / elevated / high), `z`, `ratio_to_typical`, `typical_fare_inr`, `basis` (population_prior / personal_shrunk), `history_stage` (none / insufficient < 20 / developing 20–99 / personal ≥ 100) |
| `rules` | `rapid_repeat_10min` (0 ≤ whole seconds since the previous **completed** ride ≤ 600, with `elapsed_seconds`), `amount_anomalous`, `night_behaviour_anomalous` |
| `risk_tier` | low / elevated / high |
| `recommended_action` | `step_up_verification`, `no_additional_verification` or `apply_fallback_policy` |
| `step_up_reasons` | e.g. `model_flag`, `rapid_repeat_10min` |
| `history` | prior completed rides |
| `warnings` | data-quality warnings |
| `latency_ms` | scoring time |
| `policy_note` | the backend decides; a flag is not confirmed fraud |

The step-up policy is `model_flag` or `rapid_repeat_10min`. The amount and night rules are reported, not in the
policy: their validation cost was 27 and 59 legitimate challenges per extra fraud caught, above the limit of 20.

**Failure statuses** never carry a score and always say `apply_fallback_policy`. The backend must apply its own
fallback (e.g. step-up) and **never treat a failure as approval**. `duplicate_request` means the same request is
already in the history (same `idempotency_key`, or identical timestamp, amount and driver).

## 4. Inputs in order (39)

`z_log`, `log_ratio`, `abs_log_ratio`, `high_dev`, `low_dev`, `below_prior_min`, `above_prior_max`, `veh_log_ratio`,
`micro_amount`, `is_night`, `night_share_s`, `night_rarity`, `hourband_share_s`, `is_weekend`, `weekend_share_s`,
`no_history`, `history_insufficient`, `profile_active`, `log1p_n_prior`, `history_uncertainty`, `log_gap`, `cnt_1h`,
`cnt_24h`, `cnt_7d`, `log1p_amt_1h`, `log1p_amt_24h`, `freq_ratio_7d`, `log_prev_amount_ratio`, `veh_auto_rickshaw`,
`veh_taxi`, `veh_unknown`, `vehicle_share_s`, `night_amount_high`, `driver_seen`, `driver_share`,
`distinct_driver_ratio`, `new_driver_rate_last10`, `prev_same_driver`, `pair_fare_dev`

Definitions: `features/FEATURE_DICTIONARY.md`.

## 5. Backend prerequisites (none done; V6 changes no backend code)

1. Call the scorer in the ride-payment flow. Today the backend writes `otp_verified=True, fraud_status="clear"`
   for every ride (`backend/app/routes/qr.py:368-382`); start in shadow mode (log only).
2. Supply timezone-aware timestamps: `transactions.created_at` is a naive `DateTime` (`models.py:194`), so attach
   Asia/Kolkata (or store UTC with an offset) explicitly.
3. Query the passenger's earlier ride payments (completed, plus failed where available) for each scoring call.
4. Pass the request's `idempotency_key` (the backend already stores one, `models.py:181`).
5. Decide the OTP policy for the 10-minute rule: it alone added 1,429 legitimate challenges for 9 extra frauds on
   validation. The alternatives (model-only vs model + rule) are in `reports/DECISIONS.md` D2. The bundle currently
   encodes model + rule, unchanged pending that decision.
6. Review and record outcomes before any enforcement; re-select the threshold on real data.
