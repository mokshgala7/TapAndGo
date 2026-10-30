"""
train.py  –  Train all four TapGo fraud-detection models.

What this does
--------------
1. Load training data  (tapgo_train.csv)
2. Add engineered features
3. Fit a RobustScaler (for Logistic Regression only)
4. Train:
     - Logistic Regression  (on scaled features)
     - Random Forest        (on raw features)
     - XGBoost              (on raw features)
     - Isolation Forest     (on raw features, unsupervised)
5. Save every trained model to models/

Usage
-----
    python -m src.train
"""

import time
import pandas as pd
import numpy  as np

from src.data_loader        import load_split
from src.feature_engineering import add_engineered_features
from src.preprocessing       import fit_scaler, apply_scaler
from src.config              import TRAIN_FILE, RANDOM_STATE

import src.models.logistic_regression_model as lr_mod
import src.models.random_forest_model       as rf_mod
import src.models.xgboost_model             as xgb_mod
import src.models.isolation_forest_model    as if_mod


# ─────────────────────────────────────────────────────────────────────────────
def train_all() -> dict:
    """
    Full training loop.  Returns a dict of trained model objects.
    """
    print("=" * 60)
    print("  TapGo-ML  ·  TRAINING PIPELINE")
    print("=" * 60)

    # ── 1. Load data ──────────────────────────────────────────────
    X_train, y_train, _ = load_split(TRAIN_FILE, name="TRAIN")

    # ── 2. Add engineered features ────────────────────────────────
    X_train = add_engineered_features(X_train)

    # ── 3. Fit scaler (Logistic Regression needs it) ──────────────
    scaler = fit_scaler(X_train)
    X_train_scaled = apply_scaler(X_train, scaler)

    models = {}

    # ── 4a. Logistic Regression ───────────────────────────────────
    print("\n── Training Logistic Regression ─────────────────────────")
    t0 = time.time()
    lr = lr_mod.build()
    lr.fit(X_train_scaled, y_train)
    lr_mod.save(lr)
    print(f"  Done in {time.time() - t0:.1f}s")
    models["logistic_regression"] = lr

    # ── 4b. Random Forest ─────────────────────────────────────────
    print("\n── Training Random Forest ───────────────────────────────")
    t0 = time.time()
    rf = rf_mod.build()
    rf.fit(X_train, y_train)
    rf_mod.save(rf)
    print(f"  Done in {time.time() - t0:.1f}s")
    models["random_forest"] = rf

    # ── 4c. XGBoost ───────────────────────────────────────────────
    print("\n── Training XGBoost ─────────────────────────────────────")
    t0 = time.time()
    xgb = xgb_mod.build()
    xgb.fit(X_train, y_train)
    xgb_mod.save(xgb)
    print(f"  Done in {time.time() - t0:.1f}s")
    models["xgboost"] = xgb

    # ── 4d. Isolation Forest (unsupervised — no y_train) ─────────
    print("\n── Training Isolation Forest ────────────────────────────")
    t0 = time.time()
    iso = if_mod.build()
    iso.fit(X_train)          # <<< no labels!
    if_mod.save(iso)
    print(f"  Done in {time.time() - t0:.1f}s")
    models["isolation_forest"] = iso

    print("\n" + "=" * 60)
    print("  All models trained and saved to models/")
    print("=" * 60)

    return models


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    train_all()
