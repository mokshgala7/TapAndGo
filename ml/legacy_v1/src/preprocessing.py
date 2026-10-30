"""
preprocessing.py  –  Fit and apply feature scalers.

Why two scalers?
  - Tree-based models (Random Forest, XGBoost, Isolation Forest) are
    invariant to monotonic feature scaling — raw values are fine.
  - Logistic Regression is distance-based and needs scaled features.
    We use RobustScaler (median / IQR) because transaction amounts and
    velocity counts have heavy-tailed distributions.

Usage
-----
    from src.preprocessing import fit_scaler, apply_scaler
"""

import joblib
import numpy  as np
import pandas as pd
from pathlib import Path
from sklearn.preprocessing import RobustScaler

from src.config import MODEL_DIR


SCALER_PATH = MODEL_DIR / "robust_scaler.pkl"


# ─────────────────────────────────────────────────────────────────────────────
def fit_scaler(X_train: pd.DataFrame) -> RobustScaler:
    """
    Fit a RobustScaler on the training feature matrix and save it to disk.

    Parameters
    ----------
    X_train : pd.DataFrame  – training feature matrix (numeric columns only)

    Returns
    -------
    scaler : fitted RobustScaler
    """
    scaler = RobustScaler()
    scaler.fit(X_train)
    joblib.dump(scaler, SCALER_PATH)
    print(f"[preprocessing] RobustScaler fitted on {X_train.shape[1]} features")
    print(f"  Saved → {SCALER_PATH}")
    return scaler


# ─────────────────────────────────────────────────────────────────────────────
def apply_scaler(
    X: pd.DataFrame,
    scaler: RobustScaler | None = None,
) -> pd.DataFrame:
    """
    Apply the fitted scaler to a feature matrix, returning a DataFrame.

    Parameters
    ----------
    X      : pd.DataFrame   – feature matrix to scale
    scaler : RobustScaler   – if None, loads from MODEL_DIR/robust_scaler.pkl

    Returns
    -------
    X_scaled : pd.DataFrame  – scaled features (same columns / index as X)
    """
    if scaler is None:
        if not SCALER_PATH.exists():
            raise FileNotFoundError(
                f"No scaler found at {SCALER_PATH}. "
                "Run fit_scaler(X_train) first."
            )
        scaler = joblib.load(SCALER_PATH)
        print(f"[preprocessing] Loaded scaler from {SCALER_PATH}")

    X_scaled = pd.DataFrame(
        scaler.transform(X),
        columns=X.columns,
        index=X.index,
    )
    return X_scaled


# ─────────────────────────────────────────────────────────────────────────────
def load_scaler() -> RobustScaler:
    """Load a previously saved scaler from disk."""
    if not SCALER_PATH.exists():
        raise FileNotFoundError(
            f"No scaler found at {SCALER_PATH}. Run fit_scaler(X_train) first."
        )
    return joblib.load(SCALER_PATH)
