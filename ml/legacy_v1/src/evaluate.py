"""
evaluate.py  –  Final unbiased evaluation on the held-out test split.

What this does
--------------
1. Load test data + apply same feature engineering
2. For each model, load saved thresholds from validate.py output
3. Compute full classification metrics at the chosen threshold:
      Precision, Recall, F1, ROC-AUC, PR-AUC, Confusion Matrix
4. Print report + save to reports/test_evaluation.csv

Usage
-----
    python -m src.evaluate
"""

import numpy  as np
import pandas as pd
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    precision_score, recall_score, f1_score,
    confusion_matrix, classification_report,
)

from src.data_loader          import load_split
from src.feature_engineering  import add_engineered_features
from src.preprocessing        import apply_scaler
from src.config               import TEST_FILE, REPORT_DIR

import src.models.logistic_regression_model as lr_mod
import src.models.random_forest_model       as rf_mod
import src.models.xgboost_model             as xgb_mod
import src.models.isolation_forest_model    as if_mod


def _apply_threshold(y_score: np.ndarray, threshold: float) -> np.ndarray:
    return (y_score >= threshold).astype(int)


def _metrics(y_true, y_pred, y_score) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    return {
        "roc_auc"   : roc_auc_score(y_true, y_score),
        "pr_auc"    : average_precision_score(y_true, y_score),
        "precision" : precision_score(y_true, y_pred, zero_division=0),
        "recall"    : recall_score(y_true, y_pred, zero_division=0),
        "f1"        : f1_score(y_true, y_pred, zero_division=0),
        "tp"        : int(tp),
        "fp"        : int(fp),
        "fn"        : int(fn),
        "tn"        : int(tn),
    }


def evaluate_all(thresholds: dict | None = None) -> pd.DataFrame:
    """
    Parameters
    ----------
    thresholds : dict  – {model_name: threshold_float}
                         If None, loads from reports/thresholds.csv

    Returns
    -------
    df_results : pd.DataFrame  – per-model test metrics
    """
    print("=" * 60)
    print("  TapGo-ML  ·  TEST EVALUATION PIPELINE")
    print("=" * 60)

    # Load thresholds from validate step
    if thresholds is None:
        thr_path = REPORT_DIR / "thresholds.csv"
        if not thr_path.exists():
            raise FileNotFoundError(
                f"No thresholds file at {thr_path}. Run validate.py first."
            )
        thr_df = pd.read_csv(thr_path, index_col=0)
        thresholds = thr_df["threshold"].to_dict()
        print(f"Loaded thresholds from {thr_path}")

    # Load test data
    X_test, y_test, _ = load_split(TEST_FILE, name="TEST")
    X_test = add_engineered_features(X_test)
    X_test_scaled = apply_scaler(X_test)

    all_results = {}

    def _run(name, scores, thr_key):
        thr = thresholds.get(thr_key, 0.5)
        y_pred = _apply_threshold(scores, thr)
        m = _metrics(y_test.values, y_pred, scores)
        print(f"\n── {name} (threshold={thr:.4f}) ──────────────────────")
        print(f"  ROC-AUC   : {m['roc_auc']:.4f}")
        print(f"  PR-AUC    : {m['pr_auc']:.4f}")
        print(f"  Precision : {m['precision']:.4f}")
        print(f"  Recall    : {m['recall']:.4f}")
        print(f"  F1        : {m['f1']:.4f}")
        print(f"  Confusion : TP={m['tp']} FP={m['fp']} FN={m['fn']} TN={m['tn']}")
        all_results[thr_key] = {**m, "threshold": thr}

    # Logistic Regression
    lr = lr_mod.load()
    _run("Logistic Regression", lr.predict_proba(X_test_scaled)[:, 1], "logistic_regression")

    # Random Forest
    rf = rf_mod.load()
    _run("Random Forest", rf.predict_proba(X_test)[:, 1], "random_forest")

    # XGBoost
    xgb = xgb_mod.load()
    _run("XGBoost", xgb.predict_proba(X_test)[:, 1], "xgboost")

    # Isolation Forest
    iso = if_mod.load()
    iso_scores = if_mod.anomaly_scores(iso, X_test)
    _run("Isolation Forest", iso_scores, "isolation_forest")

    # Summary
    df_results = pd.DataFrame(all_results).T[
        ["threshold", "roc_auc", "pr_auc", "precision", "recall", "f1",
         "tp", "fp", "fn", "tn"]
    ].round(4)

    print("\n\n" + "=" * 60)
    print("  FINAL TEST RESULTS")
    print("=" * 60)
    print(df_results.to_string())

    out_path = REPORT_DIR / "test_evaluation.csv"
    df_results.to_csv(out_path)
    print(f"\nResults saved → {out_path}")

    return df_results


if __name__ == "__main__":
    evaluate_all()
