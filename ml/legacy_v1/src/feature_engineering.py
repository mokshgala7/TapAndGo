"""
feature_engineering.py  –  Derived and interaction features.

The base rolling/velocity features already exist in the CSV.
This module adds higher-order signals that the models can exploit:

  1. Ratio features  – normalise velocity/amount against user history
  2. Auth pressure   – combined OTP + login failure signal
  3. Device novelty  – interaction between new_device and high velocity
  4. Location stress – interaction between location_change_rate and velocity
  5. Amount stress   – ratio of current amount to user's running average
"""

import numpy  as np
import pandas as pd


def add_engineered_features(X: pd.DataFrame) -> pd.DataFrame:
    """
    Add derived interaction features to X.

    Parameters
    ----------
    X : pd.DataFrame  – feature matrix produced by data_loader.load_split()

    Returns
    -------
    X_eng : pd.DataFrame  – feature matrix with extra columns appended
    """
    X = X.copy()

    # 1. Amount ratio vs user's running average
    #    (NaN-safe: first transactions have average_transaction_amount == typical fare)
    avg = X["average_transaction_amount"].replace(0, np.nan)
    X["amount_vs_avg_ratio"] = (X["transaction_amount"] / avg).fillna(1.0)

    # 2. Velocity per-hour ratio: transactions_last_1hour relative to daily rate
    daily = X["transactions_last_24hours"].replace(0, np.nan)
    X["velocity_hourly_vs_daily"] = (
        X["transactions_last_1hour"] * 24 / daily
    ).fillna(0.0)

    # 3. Combined authentication pressure score
    X["auth_pressure"] = (
        X["failed_otp_attempts"] + X["failed_login_attempts"]
    )

    # 4. New device under high velocity (conjunction signal)
    X["new_device_high_velocity"] = (
        X["new_device"] * (X["transactions_last_1hour"] >= 3).astype(int)
    )

    # 5. Location stress – location change rate × 5-min velocity
    X["location_stress"] = (
        X["location_change_rate"] * X["transactions_last_5min"]
    )

    # 6. Amount vs max in 30 days  (unusual spike)
    max30 = X["max_transaction_amount_last_30days"].replace(0, np.nan)
    X["amount_vs_max30_ratio"] = (X["transaction_amount"] / max30).fillna(1.0)

    # 7. Fraud history rate (previous_fraud_count / previous_transaction_count)
    prev = X["previous_transaction_count"].replace(0, np.nan)
    X["fraud_history_rate"] = (
        X["previous_fraud_count"] / prev
    ).fillna(0.0)

    print(
        f"[feature_engineering] Added 7 derived features. "
        f"Total columns: {X.shape[1]}"
    )
    return X
