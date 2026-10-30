"""Random Forest model wrapper for TapGo fraud detection."""

import joblib
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier

from src.config import MODEL_DIR, RF_PARAMS

MODEL_PATH = MODEL_DIR / "random_forest.pkl"


def build() -> RandomForestClassifier:
    return RandomForestClassifier(**RF_PARAMS)


def save(model: RandomForestClassifier) -> None:
    joblib.dump(model, MODEL_PATH)
    print(f"[RF] Model saved → {MODEL_PATH}")


def load() -> RandomForestClassifier:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"No saved model at {MODEL_PATH}")
    return joblib.load(MODEL_PATH)
