"""
tune.py  --  Hyperparameter tuning via RandomizedSearchCV.

Tunes Random Forest and XGBoost on the training set, scoring by PR-AUC
(average_precision), which is the right metric for highly imbalanced data.

Usage
-----
    python -m src.tune
    python -m src.tune --model rf       # only Random Forest
    python -m src.tune --model xgb      # only XGBoost
"""

import argparse
import joblib
import numpy as np
import pandas as pd
from scipy.stats import randint, uniform
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold
from sklearn.metrics import average_precision_score

from src.data_loader          import load_split
from src.feature_engineering  import add_engineered_features
from src.config               import TRAIN_FILE, MODEL_DIR, RANDOM_STATE

import src.models.random_forest_model as rf_mod
import src.models.xgboost_model       as xgb_mod


CV      = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
N_ITER  = 30   # number of random param combinations to try


# ---------------------------------------------------------------------------
#  Random Forest search space
# ---------------------------------------------------------------------------
RF_SEARCH = {
    "n_estimators"   : randint(200, 600),
    "max_depth"      : randint(6, 20),
    "min_samples_leaf": randint(2, 10),
    "max_features"   : ["sqrt", "log2", 0.3, 0.5],
}


# ---------------------------------------------------------------------------
#  XGBoost search space
# ---------------------------------------------------------------------------
XGB_SEARCH = {
    "n_estimators"    : randint(200, 600),
    "max_depth"       : randint(3, 10),
    "learning_rate"   : uniform(0.01, 0.2),
    "subsample"       : uniform(0.6, 0.4),
    "colsample_bytree": uniform(0.5, 0.5),
    "gamma"           : uniform(0, 0.5),
    "reg_alpha"       : uniform(0, 1.0),
    "reg_lambda"      : uniform(0.5, 2.0),
}


def tune_model(name: str, model, param_dist: dict, X, y) -> dict:
    print(f"\n-- Tuning {name} ({N_ITER} random combinations x 5-fold CV) --")
    search = RandomizedSearchCV(
        model,
        param_distributions=param_dist,
        n_iter=N_ITER,
        scoring="average_precision",
        cv=CV,
        refit=True,
        n_jobs=-1,
        verbose=1,
        random_state=RANDOM_STATE,
    )
    search.fit(X, y)

    best = search.best_estimator_
    best_score = search.best_score_

    print(f"   Best CV PR-AUC : {best_score:.4f}")
    print(f"   Best params    : {search.best_params_}")

    return {"estimator": best, "score": best_score, "params": search.best_params_}


def run_tuning(model_choice: str = "all"):
    print("=" * 60)
    print("  TapGo-ML  --  HYPERPARAMETER TUNING")
    print("=" * 60)

    X_train, y_train, _ = load_split(TRAIN_FILE, name="TRAIN")
    X_train = add_engineered_features(X_train)

    results = {}

    if model_choice in ("all", "rf"):
        rf_result = tune_model(
            "Random Forest", rf_mod.build(), RF_SEARCH, X_train, y_train
        )
        rf_mod.save(rf_result["estimator"])
        results["random_forest"] = rf_result

    if model_choice in ("all", "xgb"):
        xgb_result = tune_model(
            "XGBoost", xgb_mod.build(), XGB_SEARCH, X_train, y_train
        )
        xgb_mod.save(xgb_result["estimator"])
        results["xgboost"] = xgb_result

    print("\n" + "=" * 60)
    print("  TUNING COMPLETE  -- Re-saved best models to models/")
    print("  Run validate.py then evaluate.py to get updated metrics.")
    print("=" * 60)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["all", "rf", "xgb"], default="all")
    args = parser.parse_args()
    run_tuning(args.model)
