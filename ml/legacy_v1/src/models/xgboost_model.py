"""XGBoost model wrapper for TapGo fraud detection."""

import joblib
from pathlib import Path
from xgboost import XGBClassifier

from src.config import MODEL_DIR, XGB_PARAMS

MODEL_PATH = MODEL_DIR / "xgboost.pkl"


def build() -> XGBClassifier:
    # Remove use_label_encoder – deprecated in newer XGBoost
    params = {k: v for k, v in XGB_PARAMS.items() if k != "use_label_encoder"}
    return XGBClassifier(**params)


def save(model: XGBClassifier) -> None:
    joblib.dump(model, MODEL_PATH)
    print(f"[XGB] Model saved → {MODEL_PATH}")


def load() -> XGBClassifier:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"No saved model at {MODEL_PATH}")
    return joblib.load(MODEL_PATH)
