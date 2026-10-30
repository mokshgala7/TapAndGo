# Final test results (final freeze, 2026-10-27)

All suites were run with `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests` from each
directory. Nothing was skipped, no test was modified, and no cache files were written (0 `__pycache__` /
`.pytest_cache` found afterwards).

| Suite | Directory | Result |
|---|---|---|
| **V6** (requirement gates on the frozen bundle, data/feature integrity, inference) | `experiments/passenger_fraud_v6` | **34 passed, 0 failed, 0 skipped**. Verbose run saved in `test_output_v6.txt`. Run again after the documentation edits: 34 passed |
| V5 (protected) | `experiments/passenger_fraud_v5` | 63 passed |
| V4 (protected) | `experiments/passenger_fraud_v4` | 69 passed |
| Legacy pipeline | `TapGo-ML` | 57 passed |

| Smoke / integrity check | Result | Output |
|---|---|---|
| Model loads; hash matches sidecar; schema matches code; threshold and version match the reports | pass | `verify_model.json` |
| Inference returns the documented fields, including `passenger_fare_anomaly` and `rules` | pass | `verify_model.json`, `demo_output.json` |
| Inference with all network sockets blocked | pass | `verify_model.json` |
| Invalid inputs → no score, `apply_fallback_policy` | pass | `verify_model.json`, demo 7–7d |
| Reported metrics vs saved artifacts | **0 discrepancies**; confusion totals equal dataset rows for all six sets; recomputation from stored scores identical | `VERIFIED_METRICS.json` |
| Training/inference parity | pass (G10 in the V6 suite) | — |
| Reproducibility (existing check from the V6 run; the model was not retrained during the freeze) | regeneration identical; refit bit-identical | `evaluation/reproducibility.json` |
| Protected artifacts (171 hashed before edits) and the V6 404-file snapshot | **0 changed** | `PROTECTED_ARTIFACT_MANIFEST.json` (`post_edit_check`) |
| Git: ML repo HEAD `ae862f6` and status | unchanged | same |
| Backend HEAD `6f80cb4` | unchanged | same |
| Backend working tree | **pre-existing external edits** to `backend/app/routes/wallet.py` and `backend/tests/test_wallet_security.py` (2026-10-26 19:49–19:53 IST, not made by this project). Unchanged during the freeze and not touched | same |

**Not run:** the backend test suite. No backend file was modified by this work, and the backend contains someone
else's uncommitted changes, which this task must not disturb.

**Update (final requirements verification, 2026-10-27):** 26 lifecycle and day/night tests were added in `tests/test_passenger_lifecycle.py`; the V6 suite is now **60 passed, 0 failed**. See `FINAL_REQUIREMENTS_VERIFICATION.md`.
