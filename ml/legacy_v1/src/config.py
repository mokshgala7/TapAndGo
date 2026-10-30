"""
config.py  –  Central configuration for the TapGo-ML pipeline.

All paths, feature lists, and default hyperparameters live here
so every other module imports from one place.
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─────────────────────────────────────────────────
#  Root Paths
# ─────────────────────────────────────────────────
ROOT_DIR   = Path(__file__).resolve().parent.parent   # TapGo-ML/
DATA_DIR   = ROOT_DIR / "data"
MODEL_DIR  = ROOT_DIR / "models"
REPORT_DIR = ROOT_DIR / "reports"

# Create output dirs if they do not exist yet
MODEL_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────
#  Dataset Files
# ─────────────────────────────────────────────────
TRAIN_FILE      = DATA_DIR / "tapgo_train.csv"
VAL_FILE        = DATA_DIR / "tapgo_validation.csv"
TEST_FILE       = DATA_DIR / "tapgo_test.csv"
FULL_FILE       = DATA_DIR / "tapgo_transactions_full.csv"

# ─────────────────────────────────────────────────
#  Column Definitions
# ─────────────────────────────────────────────────
TARGET_COL  = "is_fraud"
ID_COLS     = ["transaction_id", "user_id", "transaction_timestamp"]

# Categorical columns that need encoding
CAT_COLS    = ["payment_method"]

# Numeric feature columns fed to models
NUMERIC_COLS = [
    "transaction_amount",
    "transaction_hour",
    "transaction_day_of_week",
    "account_age_days",
    "previous_transaction_count",
    "previous_fraud_count",
    "transactions_last_5min",
    "transactions_last_1hour",
    "transactions_last_24hours",
    "amount_last_1hour",
    "amount_last_24hours",
    "new_device",
    "previous_device_used",
    "device_transaction_count",
    "failed_otp_attempts",
    "failed_login_attempts",
    "distance_from_previous_transaction_km",
    "location_change_rate",
    "average_transaction_amount",
    "max_transaction_amount_last_30days",
    "transactions_last_7days",
]

# ─────────────────────────────────────────────────
#  Class-Imbalance Settings
# ─────────────────────────────────────────────────
# Fraud rate is ~3.16 %, so the positive class weight for
# scikit-learn / XGBoost is roughly 96.84 / 3.16 ≈ 30.6
FRAUD_RATE      = 0.0316
POS_CLASS_WEIGHT = round((1 - FRAUD_RATE) / FRAUD_RATE, 1)  # ≈ 30.6

RANDOM_STATE    = 42

# ─────────────────────────────────────────────────
#  Default Hyperparameters
# ─────────────────────────────────────────────────
LR_PARAMS = {
    "C": 0.1,
    # penalty='l2' deprecated in sklearn 1.8 - l2 is the default, so just omit it
    # liblinear solver: coordinate descent, converges reliably on imbalanced data
    # without needing huge max_iter like lbfgs
    "solver": "liblinear",
    "max_iter": 1000,
    "class_weight": "balanced",
    "random_state": RANDOM_STATE,
}

RF_PARAMS = {
    "n_estimators": 300,
    "max_depth": 12,
    "min_samples_leaf": 4,
    "class_weight": "balanced",
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}

XGB_PARAMS = {
    "n_estimators": 400,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "scale_pos_weight": POS_CLASS_WEIGHT,
    "use_label_encoder": False,
    "eval_metric": "aucpr",
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}

IF_PARAMS = {
    "n_estimators": 200,
    "contamination": FRAUD_RATE,
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}

# ─────────────────────────────────────────────────
#  Threshold-Tuning Target
# ─────────────────────────────────────────────────
# We prefer high recall (catch fraud) while keeping precision
# above this minimum to avoid too many OTP challenges.
MIN_PRECISION_TARGET = 0.30
