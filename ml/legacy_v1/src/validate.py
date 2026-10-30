"""
validate.py  –  Run models on the validation split to select thresholds.

What this does
--------------
1. Load validation data + apply the same feature engineering
2. For each model, compute predicted fraud-probability scores
3. Run threshold_selection to find the best operating point
4. Print a summary table
5. Save thresholds to reports/thresholds.csv

Usage
-----
    python -m src.validate
"""

import json
import numpy  as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score

from src.data_loader          import load_split
from src.feature_engineering  import add_engineered_features
from src.preprocessing        import apply_scaler
from src.threshold_selection  import select_threshold, print_threshold_report
from src.config               import VAL_FILE, REPORT_DIR

import src.models.logistic_regression_model as lr_mod
import src.models.random_forest_model       as rf_mod
import src.models.xgboost_model             as xgb_mod
import src.models.isolation_forest_model    as if_mod


def validate_all() -> dict:
    print("=" * 60)
    print("  TapGo-ML  ·  VALIDATION PIPELINE")
    print("=" * 60)

    # ── Load & engineer validation data ──────────────────────────
    X_val, y_val, _ = load_split(VAL_FILE, name="VALIDATION")
    X_val = add_engineered_features(X_val)
    X_val_scaled = apply_scaler(X_val)

    results = {}

    def _evaluate_model(name, y_score):
        roc  = roc_auc_score(y_val, y_score)
        prauc = average_precision_score(y_val, y_score)
        thr  = select_threshold(y_val, y_score)
        print_threshold_report(name, thr)
        print(f"  ROC-AUC   : {roc:.4f}")
        print(f"  PR-AUC    : {prauc:.4f}")
        return {**thr, "roc_auc": roc, "pr_auc": prauc}

    # ── Logistic Regression ───────────────────────────────────────
    print("\n── Logistic Regression ──────────────────────────────────")
    lr = lr_mod.load()
    lr_scores = lr.predict_proba(X_val_scaled)[:, 1]
    results["logistic_regression"] = _evaluate_model("Logistic Regression", lr_scores)

    # ── Random Forest ─────────────────────────────────────────────
    print("\n── Random Forest ────────────────────────────────────────")
    rf = rf_mod.load()
    rf_scores = rf.predict_proba(X_val)[:, 1]
    results["random_forest"] = _evaluate_model("Random Forest", rf_scores)

    # ── XGBoost ───────────────────────────────────────────────────
    print("\n── XGBoost ──────────────────────────────────────────────")
    xgb = xgb_mod.load()
    xgb_scores = xgb.predict_proba(X_val)[:, 1]
    results["xgboost"] = _evaluate_model("XGBoost", xgb_scores)

    # ── Isolation Forest ──────────────────────────────────────────
    print("\n── Isolation Forest ─────────────────────────────────────")
    iso = if_mod.load()
    iso_scores = if_mod.anomaly_scores(iso, X_val)
    results["isolation_forest"] = _evaluate_model("Isolation Forest", iso_scores)

    # ── Summary table ─────────────────────────────────────────────
    print("\n\n" + "=" * 60)
    print("  VALIDATION SUMMARY")
    print("=" * 60)
    df_res = pd.DataFrame(results).T[
        ["roc_auc", "pr_auc", "threshold", "precision", "recall", "f1", "fallback"]
    ].round(4)
    print(df_res.to_string())

    # ── Save thresholds ───────────────────────────────────────────
    out_path = REPORT_DIR / "thresholds.csv"
    df_res.to_csv(out_path)
    print(f"\nThresholds saved → {out_path}")

    return results


if __name__ == "__main__":
    validate_all()
