"""
Isolation Forest model wrapper for TapGo fraud detection.

Isolation Forest is an UNSUPERVISED anomaly detector.  It does NOT take
y_train — it learns what "normal" looks like and flags outliers.

Because it produces a raw anomaly score (not a probability), it is evaluated
with ROC-AUC and compared to the supervised models, but threshold tuning
uses the same Precision-Recall approach, applied to the negated score.
"""

import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import IsolationForest

from src.config import MODEL_DIR, IF_PARAMS

MODEL_PATH = MODEL_DIR / "isolation_forest.pkl"


def build() -> IsolationForest:
    return IsolationForest(**IF_PARAMS)


def save(model: IsolationForest) -> None:
    joblib.dump(model, MODEL_PATH)
    print(f"[IF] Model saved → {MODEL_PATH}")


def load() -> IsolationForest:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"No saved model at {MODEL_PATH}")
    return joblib.load(MODEL_PATH)


def anomaly_scores(model: IsolationForest, X: pd.DataFrame) -> np.ndarray:
    """
    Return fraud-probability-like scores in [0, 1].
    IsolationForest.score_samples() returns negative anomaly scores
    (more negative = more anomalous). We negate and min-max scale
    so higher value → more likely fraud, matching the other models.
    """
    raw = model.score_samples(X)          # negative → anomalous
    neg = -raw                             # positive → anomalous
    mn, mx = neg.min(), neg.max()
    if mx == mn:
        return np.zeros_like(neg)
    return (neg - mn) / (mx - mn)
