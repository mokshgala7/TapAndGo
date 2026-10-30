"""
report.py  --  Generate visual evaluation reports.

Produces the following plots saved to reports/:
  1. roc_curves.png          -- ROC curves for all 4 models
  2. pr_curves.png           -- Precision-Recall curves for all 4 models
  3. confusion_matrices.png  -- Confusion matrices for all 4 models (at chosen threshold)
  4. feature_importance.png  -- Top-20 features for RF and XGBoost

Usage
-----
    python -m src.report
"""

import warnings
warnings.filterwarnings("ignore")

import numpy  as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # non-interactive backend (no display needed)
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from sklearn.metrics import (
    roc_curve, auc,
    precision_recall_curve, average_precision_score,
    confusion_matrix,
)

from src.data_loader          import load_split
from src.feature_engineering  import add_engineered_features
from src.preprocessing        import apply_scaler
from src.config               import TEST_FILE, REPORT_DIR

import src.models.logistic_regression_model as lr_mod
import src.models.random_forest_model       as rf_mod
import src.models.xgboost_model             as xgb_mod
import src.models.isolation_forest_model    as if_mod

COLORS = {
    "logistic_regression": "#4C72B0",
    "random_forest":       "#55A868",
    "xgboost":             "#DD8452",
    "isolation_forest":    "#C44E52",
}

LABELS = {
    "logistic_regression": "Logistic Regression",
    "random_forest":       "Random Forest",
    "xgboost":             "XGBoost",
    "isolation_forest":    "Isolation Forest",
}


# ---------------------------------------------------------------------------
def _load_everything():
    thr_path = REPORT_DIR / "thresholds.csv"
    thresholds = pd.read_csv(thr_path, index_col=0)["threshold"].to_dict()

    X_test, y_test, _ = load_split(TEST_FILE, name="TEST", validate=False)
    X_test = add_engineered_features(X_test)
    X_test_scaled = apply_scaler(X_test)

    scores = {
        "logistic_regression": lr_mod.load().predict_proba(X_test_scaled)[:, 1],
        "random_forest":       rf_mod.load().predict_proba(X_test)[:, 1],
        "xgboost":             xgb_mod.load().predict_proba(X_test)[:, 1],
        "isolation_forest":    if_mod.anomaly_scores(if_mod.load(), X_test),
    }

    return y_test, scores, thresholds, X_test


# ---------------------------------------------------------------------------
def plot_roc_curves(y_test, scores):
    fig, ax = plt.subplots(figsize=(8, 6))
    for key, sc in scores.items():
        fpr, tpr, _ = roc_curve(y_test, sc)
        roc_auc = auc(fpr, tpr)
        ax.plot(fpr, tpr, color=COLORS[key], lw=2,
                label=f"{LABELS[key]}  (AUC = {roc_auc:.3f})")
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC Curves -- TapGo Fraud Detection")
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3)
    path = REPORT_DIR / "roc_curves.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


# ---------------------------------------------------------------------------
def plot_pr_curves(y_test, scores, thresholds):
    fig, ax = plt.subplots(figsize=(8, 6))
    baseline = y_test.mean()
    ax.axhline(y=baseline, color="grey", lw=1, linestyle="--",
               label=f"Random baseline (P={baseline:.3f})")

    for key, sc in scores.items():
        prec, rec, thresh = precision_recall_curve(y_test, sc)
        prauc = average_precision_score(y_test, sc)
        ax.plot(rec, prec, color=COLORS[key], lw=2,
                label=f"{LABELS[key]}  (PR-AUC = {prauc:.3f})")

        # Mark the chosen operating point
        thr = thresholds.get(key, 0.5)
        preds = (sc >= thr).astype(int)
        op_p = (preds * (y_test == 1).values).sum() / (preds.sum() + 1e-9)
        op_r = (preds * (y_test == 1).values).sum() / (y_test == 1).sum()
        ax.scatter(op_r, op_p, color=COLORS[key], s=80, zorder=5, marker="*")

    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-Recall Curves -- TapGo Fraud Detection\n(* = chosen OTP threshold)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1.05])
    path = REPORT_DIR / "pr_curves.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


# ---------------------------------------------------------------------------
def plot_confusion_matrices(y_test, scores, thresholds):
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    axes = axes.flatten()

    for ax, (key, sc) in zip(axes, scores.items()):
        thr = thresholds.get(key, 0.5)
        y_pred = (sc >= thr).astype(int)
        cm = confusion_matrix(y_test, y_pred)

        im = ax.imshow(cm, interpolation="nearest", cmap="Blues")
        ax.set_title(f"{LABELS[key]}\n(threshold={thr:.3f})", fontsize=10)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_xticks([0, 1]); ax.set_xticklabels(["Legit", "Fraud"])
        ax.set_yticks([0, 1]); ax.set_yticklabels(["Legit", "Fraud"])

        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{cm[i, j]:,}",
                        ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "black",
                        fontsize=14, fontweight="bold")

    fig.suptitle("Confusion Matrices -- Test Set", fontsize=13, fontweight="bold")
    path = REPORT_DIR / "confusion_matrices.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


# ---------------------------------------------------------------------------
def plot_feature_importance(X_test):
    fig, axes = plt.subplots(1, 2, figsize=(14, 8))

    for ax, (mod_name, mod) in zip(axes, [
        ("Random Forest", rf_mod.load()),
        ("XGBoost",       xgb_mod.load()),
    ]):
        importances = mod.feature_importances_
        feat_names  = X_test.columns
        idx = np.argsort(importances)[-20:][::-1]
        top_names  = feat_names[idx]
        top_values = importances[idx]

        colors = ["#DD8452" if mod_name == "XGBoost" else "#55A868"] * len(top_names)
        ax.barh(range(len(top_names)), top_values[::-1], color=colors[::-1])
        ax.set_yticks(range(len(top_names)))
        ax.set_yticklabels(top_names[::-1], fontsize=8)
        ax.set_xlabel("Feature Importance")
        ax.set_title(f"Top 20 Features -- {mod_name}", fontsize=11)
        ax.grid(axis="x", alpha=0.3)

    path = REPORT_DIR / "feature_importance.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {path}")


# ---------------------------------------------------------------------------
def generate_all_reports():
    print("=" * 60)
    print("  TapGo-ML  --  GENERATING VISUAL REPORTS")
    print("=" * 60)

    y_test, scores, thresholds, X_test = _load_everything()

    print("\n[1/4] ROC Curves ...")
    plot_roc_curves(y_test, scores)

    print("[2/4] Precision-Recall Curves ...")
    plot_pr_curves(y_test, scores, thresholds)

    print("[3/4] Confusion Matrices ...")
    plot_confusion_matrices(y_test, scores, thresholds)

    print("[4/4] Feature Importance ...")
    plot_feature_importance(X_test)

    print("\n>> All reports saved to reports/")


if __name__ == "__main__":
    generate_all_reports()
