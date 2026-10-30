"""Logistic Regression model wrapper for TapGo fraud detection."""

import joblib
from pathlib import Path
from sklearn.linear_model import LogisticRegression

from src.config import MODEL_DIR, LR_PARAMS

MODEL_PATH = MODEL_DIR / "logistic_regression.pkl"


def build() -> LogisticRegression:
    return LogisticRegression(**LR_PARAMS)


def save(model: LogisticRegression) -> None:
    joblib.dump(model, MODEL_PATH)
    print(f"[LR] Model saved → {MODEL_PATH}")


def load() -> LogisticRegression:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"No saved model at {MODEL_PATH}")
    return joblib.load(MODEL_PATH)
