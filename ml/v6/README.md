# passenger_fraud_v6: requirements-first fraud risk model (research; synthetic data)

V6 corrects V5's requirement failures. **Requirements gate model selection; AP only ranks eligible models.** Start
with `reports/FINAL_REPORT.md`.

**Status: reference candidate** (decision D1 in `reports/DECISIONS.md`: extra OTP challenges on legitimately
expensive trips are accepted). Not production-ready.

| Folder | Contents |
|---|---|
| `audit/` | V4/V5 re-verification, requirement test spec (gates G1–G10), **pre-registration** (hashed) + amendments, feature-scope audit, protected-files manifest |
| `config/experiment_config.json` | seeds, splits, candidates, selection, threshold, commands |
| `data/` | `generator_v6.py` (de-biased; no location columns), `universes.py`, `build_datasets.py`, `synthetic/` |
| `features/` | `feature_builder.py`, `v3_features.py` (byte-identical V3 copy), `FEATURE_DICTIONARY.md` |
| `training/` | `data_diagnostics.py`, `gates.py`, `train_candidates.py`, `select_model.py`, `score_references.py`, `evaluate_final.py`, `benchmark_inference.py`, `reproduce_check.py`, `write_manifest.py`, `metrics.py` |
| `artifacts/` | frozen bundle + sidecar + metadata; `candidate_models/` (10); `cache/` (regenerable matrices and scores) |
| `evaluation/` | candidates and gate results (`round1/`, `round2/` kept), selection, final metrics, comparisons, threshold analysis, failure and shift reports |
| `integration/` | `inference.py` (`FraudScorerV6`), contract, error handling |
| `tests/` | 34 tests (gates on the frozen bundle, data/feature integrity, inference) |
| `reports/` | final report, compliance, V4/V5/V6 comparison, tests, next steps, reproducibility manifest |
| `scratch_exploration/` | the recorded round-3 probe |

## Reproduce

Run from this directory:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests
```

```bash
PYTHONDONTWRITEBYTECODE=1 python3 training/reproduce_check.py
```

`training/evaluate_final.py --reuse-post-freeze` re-runs the evaluation. The pipeline refuses to re-freeze or to
regenerate post-freeze data.

## Use

```python
from integration.inference import FraudScorerV6
out = FraudScorerV6.load().score_safe(transaction, passenger_history)
# out["recommended_action"]: step_up_verification | no_additional_verification | apply_fallback_policy (never approval)
```
