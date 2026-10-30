# V6 error handling

| Condition | Status | Score | Recommended action |
|---|---|---|---|
| Missing, garbage or **naive** timestamp (no offset) | `invalid_input` | none | `apply_fallback_policy` |
| Amount ≤ 0, > ₹100,000, NaN, inf, bool, non-numeric | `invalid_input` | none | fallback |
| Missing or empty `driver_id`; non-string payment method or vehicle | `invalid_input` | none | fallback |
| History not a list, row without status, rides at or after the transaction, duplicate timestamps | `invalid_input` | none | fallback |
| Any location-like field in the transaction or history | `invalid_input` ("location data is not accepted") | none | fallback |
| Same `idempotency_key` in the history, or identical (timestamp, amount, driver) | `duplicate_request` | none | fallback (the backend already handles the original request) |
| Bundle missing, no sidecar, hash mismatch, corrupt or truncated | `model_unavailable` (raised by `load`) | none | fallback |
| Library versions differ from training | `model_unavailable` | none | fallback |
| Feature list or width differs from the code | `schema_mismatch` | none | fallback |
| Model raises, or returns NaN or the wrong shape | `prediction_error` | none | fallback |

`score()` raises an `InferenceError` subclass. `score_safe()` never raises and returns the failure object.
**No failure path returns a risk score, `model_flag=False` or "low" risk.** Tests: gates G5/G6
(`training/gates.py`) and `tests/test_inference.py`.

Sparse history is **not** an error. With zero rides the passenger is scored against population priors
(`basis = population_prior`, warning `new_passenger_no_completed_history`). Below 20 rides the warning is
`passenger_history_insufficient_lt20`, and the night rule (which needs ≥ 20 rides) cannot fire.
