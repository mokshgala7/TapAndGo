# Test report (V6)

All suites ran locally on 2026-10-26 with `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests`.
No network, database or credentials were used, and no cache files were written.

| Suite | Directory | Result |
|---|---|---|
| **V6** | `experiments/passenger_fraud_v6` | **34 passed, 0 failed, 0 skipped** |
| V5 (protected, read-only) | `experiments/passenger_fraud_v5` | 63 passed |
| V4 (protected, read-only) | `experiments/passenger_fraud_v4` | 69 passed |
| Legacy ML | `TapGo-ML` | 57 passed |

The backend suite was not re-run: V6 touched no backend file. Backend: backend HEAD unchanged; **the backend working tree changed during this session** (`backend/app/routes/wallet.py` modified 19:49 IST, `backend/tests/test_wallet_security.py` 19:53 IST, +571/−2 lines). V6 issued no backend command (its only backend access was read-only inspection during the earlier audit), so this was another session or person; V6 did not touch or revert it.

## V6 tests (34)

`tests/test_requirement_gates.py` (11). Mandatory gates on the **frozen bundle**:
- G1 fare anomaly and monotonicity
- G2 variable passenger
- G3 day/night, including boundaries and naive timestamps
- G4 cold start
- G5 10-minute rule 599/600/601, failed-ride reference, duplicate requests, multi-leg, missing timestamp
- G6 error handling
- G7 no location
- G8 available inputs only
- an explicit familiar-driver suppression test
- G9 no future leakage
- G10 interface/batch parity

`tests/test_data_features.py` (12):
- protected files (404) unchanged
- pre-registration hash
- V3 code copy byte-identical
- no forbidden or location columns in feature sets
- no location column in any generated CSV
- label-free ledger, manifests match
- generator shortcut gate
- disjoint and chronological splits
- training/selection never read test data
- freeze precedes post-freeze data
- DR worlds lack the unseen mechanism
- only an eligible candidate selected, and eligibility matches the gate results

`tests/test_inference.py` (11):
- output schema
- contract document ↔ code
- no side-effect methods
- never approves or rejects
- determinism
- duplicate requests
- missing, corrupt and mismatched bundles
- schema mismatch, bad threshold, version mismatch
- error hierarchy
- bundle reload equals the candidate model (2,000 rows)
- unknown categoricals

## Additional verification (scripts)

| Check | Result |
|---|---|
| Interface vs batch scores, 300 T3 rides with full histories | 0 mismatches; p50 5.5 ms, p95 7.4 ms (`evaluation/inference_benchmark.json`) |
| Reproducibility | D6_dr1 and D6_fresh regenerate identically; matrix max diff 0.0; refit of C9 bit-identical (`evaluation/reproducibility.json`) |

## Failures during development (all fixed; no assertion weakened to fit a model)

1. `evaluate_final.py` had a syntax error and stopped **before** generating any data. Fixed and re-run. The
   post-freeze guarantee held: no universe existed before the successful run.
2. Gate G8's implementation compared feature names against a literal round-1 list instead of the spec's
   "computable from passenger history" rule. The implementation was corrected to the spec (amendment A5). This
   did not relax the requirement.
3. `test_contract_document_matches_code` failed until the contract was written. Expected.
4. Candidates C0–C8 **failed** mandatory gates and were recorded as ineligible. The gates were not changed;
   the fixes were model-structure changes (amendments A3/A4).
