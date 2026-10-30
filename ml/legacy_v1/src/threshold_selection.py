"""
threshold_selection.py  –  Find the optimal decision threshold per model.

Context
-------
The Tap&Go platform does NOT hard-block suspicious transactions.
Instead, it triggers an OTP step-up challenge.  Therefore:

  • FALSE NEGATIVES (missed fraud)  → fraud slips through undetected.
  • FALSE POSITIVES (legitimate flagged) → real passenger annoyed by OTP.

We want:
  - High RECALL  → catch as many fraud transactions as possible
  - Precision ≥ MIN_PRECISION_TARGET  → keep OTP friction acceptable

Strategy:   Walk the Precision-Recall curve.  Among all thresholds where
            precision ≥ MIN_PRECISION_TARGET, pick the one with the
            highest recall.  Tie-break: higher F1.

Usage
-----
    from src.threshold_selection import select_threshold, print_threshold_report
"""

import numpy  as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, f1_score

from src.config import MIN_PRECISION_TARGET


# ─────────────────────────────────────────────────────────────────────────────
def select_threshold(
    y_true:  np.ndarray | pd.Series,
    y_score: np.ndarray,
    min_precision: float = MIN_PRECISION_TARGET,
) -> dict:
    """
    Select the decision threshold that maximises recall while keeping
    precision >= min_precision.

    Parameters
    ----------
    y_true        : true binary labels (0/1)
    y_score       : fraud-probability scores from the model
    min_precision : minimum acceptable precision (default from config)

    Returns
    -------
    result : dict with keys
        threshold    – chosen threshold float
        precision    – precision at that threshold
        recall       – recall at that threshold
        f1           – F1 at that threshold
        fallback     – True if no threshold met the precision constraint
                       (in that case, best-F1 threshold is returned)
    """
    y_true  = np.asarray(y_true)
    y_score = np.asarray(y_score)

    precisions, recalls, thresholds = precision_recall_curve(y_true, y_score)
    # Note: len(thresholds) == len(precisions) - 1
    # The last entry in precisions/recalls has no corresponding threshold.
    precisions = precisions[:-1]
    recalls    = recalls[:-1]

    # ── Try to satisfy the precision constraint ────────────────────
    mask = precisions >= min_precision
    if mask.any():
        # Among valid thresholds, maximise recall; tie-break on F1
        valid_idx = np.where(mask)[0]
        best_idx  = valid_idx[np.argmax(recalls[valid_idx])]
        fallback  = False
    else:
        # Fall back: take the threshold with the best F1
        f1s     = 2 * precisions * recalls / (precisions + recalls + 1e-9)
        best_idx = np.argmax(f1s)
        fallback = True

    return {
        "threshold" : float(thresholds[best_idx]),
        "precision" : float(precisions[best_idx]),
        "recall"    : float(recalls[best_idx]),
        "f1"        : float(
            2 * precisions[best_idx] * recalls[best_idx]
            / (precisions[best_idx] + recalls[best_idx] + 1e-9)
        ),
        "fallback"  : fallback,
    }


# ─────────────────────────────────────────────────────────────────────────────
def print_threshold_report(model_name: str, result: dict) -> None:
    flag = " ⚠ FALLBACK (precision constraint not met)" if result["fallback"] else ""
    print(f"\n[threshold] {model_name}{flag}")
    print(f"  Threshold : {result['threshold']:.4f}")
    print(f"  Precision : {result['precision']:.4f}")
    print(f"  Recall    : {result['recall']:.4f}")
    print(f"  F1        : {result['f1']:.4f}")
