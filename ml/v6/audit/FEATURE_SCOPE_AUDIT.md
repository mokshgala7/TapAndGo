# Feature scope audit (V6)

Every candidate feature set was checked for scope before training, and again by the tests:
`tests/test_data_features.py::test_feature_sets_have_no_forbidden_or_location_columns` and gates G7/G8.

| Category | V6 status | Evidence |
|---|---|---|
| GPS, latitude/longitude, coordinates, geofence, route, distance, zone, airport | **absent** from features, inference inputs and every generated file. Location-like inputs are **refused** at inference | `LOCATION_TOKENS` in `features/feature_builder.py`; gate G7; `test_no_location_columns_in_any_generated_file` |
| Driver ledger (other passengers' rides), V5 per-ride annotations, market aggregates | absent | gate G8: the scorer signature is `(transaction, passenger_history)` only |
| Tier B (declined attempts, confirmed reports, airport flag) | absent | `FEATURE_SETS` |
| Payment-method one-hots | absent (constant in production) | `qr.py:374` |
| Scenario/driver-type/trip-type metadata | written to `events.csv` for subgroup reporting only; never in the ledger or features | `FORBIDDEN`; `test_ledger_is_label_free_and_manifests_match` |
| Future information | none (causal-mutation gate G9: 0 changed columns over 7,113 rows) | `evaluation/gate_results.json` |
| Passenger-view familiarity (driver_seen, driver_share, pair_fare_dev, …) | **kept**, computed from the passenger's own history, `pair_fare_dev` monotone ↑ | Kept because C9 with these features passes every gate, including the familiar-driver anomaly gate G1e. It is the only candidate that passes G2/G3: C8, without familiarity, fails them |

## Essential / optional / excluded

| | Features |
|---|---|
| **Essential** (R1–R4) | passenger amount deviation (`z_log`, `log_ratio`, `abs_log_ratio`, `high_dev`, `above_prior_max`, `veh_log_ratio`, `low_dev`, `below_prior_min`, `micro_amount`, `log_prev_amount_ratio`); day/night (`is_night`, `night_share_s`, `night_rarity`, `hourband_share_s`, `night_amount_high`); history (`no_history`, `history_insufficient`, `profile_active`, `log1p_n_prior`, `history_uncertainty`); repeat/velocity (`log_gap`, counts, sums, `freq_ratio_7d`); the three rule outputs and the explicit anomaly signal |
| **Optional** (kept, justified by the gates) | passenger-view familiarity (6); vehicle (4); weekend (2) |
| **Excluded** | see `features/FEATURE_DICTIONARY.md` "Excluded" |
