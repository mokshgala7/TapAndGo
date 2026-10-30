# `ml/`: training, evaluation and data for the fraud model

This folder holds the machine-learning work behind the fraud check. **It is documentation and research code. The backend
does not import anything from here**; the model the backend actually runs is the frozen, hash-checked copy under
`backend/app/services/tapgo_fraud_risk/`. Nothing in `ml/` changes how the app runs. Everything measured here is
**synthetic/demo-derived, not real-world performance**.

| Path | What |
|---|---|
| `v6/` | the V6 experiment (the deployed model): generator, features, training, selection, evaluation, tests, audit, reports |
| `v6/data/generator_v6.py`, `build_datasets.py` | the synthetic-data generator (seeds in `v6/config/experiment_config.json`) |
| `v6/training/` | `train_candidates.py`, `select_model.py`, `evaluate_final.py`, `gates.py` (the requirement tests), `reproduce_check.py` |
| `v6/evaluation/`, `v6/reports/` | the recorded evaluation outputs and the written reports (start with `v6/reports/FINAL_REPORT.md`) |
| `reports/` | the evaluation summary for an examiner (`evaluation_summary.md`), `evaluation_metrics.json`, three small charts, and the script that builds them |
| `data/` | `README.md` (column dictionary, splits, seeds, checksums) and a 1,000-row **sample**. The full dataset is not in git |
| `legacy_v1/` | the earlier baseline pipeline (logistic regression, random forest, isolation forest, XGBoost) with its charts; kept for the history |
| `patches/optional_median_rule.patch` | an optional own-median OTP rule that was evaluated and **not** adopted; it is a patch file only and is not applied |
| `requirements-train.txt` | libraries for training only (the backend deploy uses the root `requirements.txt` and is not affected) |

## Reproduce (from the repository root)

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r ml/requirements-train.txt
python ml/v6/data/build_datasets.py --stage dev        # regenerates the development universe into ml/v6/data/synthetic/ (git-ignored)
python ml/reports/make_report_assets.py                # rebuilds evaluation_metrics.json and the charts from the recorded outputs
```

Honest limits of "reproduce": the generator, features, selection and evaluation scripts are included and the seeds are recorded,
but some comparison scripts (`score_references.py`, `evaluate_final.py`) also score the earlier V4/V5 models, whose packages are not
copied here; and the frozen model file is the one in the backend (`tapgo_fraud_v6.xgb.json`, checked against `MANIFEST.json`).
Training and evaluation were run on a laptop with the library versions listed in `v6/artifacts/model_metadata.json`.

The full training dataset, the candidate models and the cached score matrices (about 1 GB) are deliberately not in git; `ml/.gitignore`
keeps them out. How to verify you have the same data: `data/README.md`.
