"""
data_loader.py  –  Load and validate the TapGo CSV splits.

Usage
-----
    from src.data_loader import load_split, load_all_splits

Returns
-------
    X  : pd.DataFrame  – features (no target, no raw IDs)
    y  : pd.Series     – 0/1 labels  (is_fraud)
    df : pd.DataFrame  – full raw frame with all columns (for diagnostics)
"""

import pandas as pd
import numpy  as np
from pathlib import Path
from src.config import (
    TRAIN_FILE, VAL_FILE, TEST_FILE, FULL_FILE,
    TARGET_COL, ID_COLS, CAT_COLS, NUMERIC_COLS
)


# ─────────────────────────────────────────────────────────────────────────────
def _validate(df: pd.DataFrame, name: str) -> None:
    """Quick sanity-checks on a loaded dataframe."""
    print(f"[data_loader] {name}: {df.shape[0]:,} rows × {df.shape[1]} cols")

    # Missing values
    n_missing = df.isnull().sum().sum()
    if n_missing:
        print(f"  ⚠  {n_missing} missing values found – check your CSV!")
    else:
        print(f"  ✓  No missing values")

    # Target distribution
    if TARGET_COL in df.columns:
        fraud_n  = df[TARGET_COL].sum()
        fraud_pct = 100 * fraud_n / len(df)
        print(f"  ✓  Fraud rows: {fraud_n:,} ({fraud_pct:.2f}%)")

    # Negative amounts
    if "transaction_amount" in df.columns:
        neg = (df["transaction_amount"] < 0).sum()
        if neg:
            print(f"  ⚠  {neg} negative transaction amounts")


# ─────────────────────────────────────────────────────────────────────────────
def _parse_and_build(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parse the timestamp column and add cyclic hour/day features.
    These are added here (not feature_engineering) because they derive
    directly from raw columns with zero leakage risk.
    """
    df = df.copy()

    # Parse timestamp → datetime
    df["transaction_timestamp"] = pd.to_datetime(
        df["transaction_timestamp"], errors="coerce"
    )

    # Cyclic encoding of hour (0-23) – avoids discontinuity between 23 and 0
    hour = df["transaction_hour"]
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    # Cyclic encoding of day-of-week (0-6)
    dow = df["transaction_day_of_week"]
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)

    # One-hot encode payment_method (NFC / QR)
    df = pd.get_dummies(df, columns=["payment_method"], drop_first=False, dtype=int)

    return df


# ─────────────────────────────────────────────────────────────────────────────
def load_split(
    csv_path: Path,
    name: str = "dataset",
    validate: bool = True,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """
    Load one CSV split.

    Parameters
    ----------
    csv_path : Path or str  – path to the CSV file
    name     : str          – label for log messages
    validate : bool         – whether to run sanity checks

    Returns
    -------
    X  : pd.DataFrame  – model-ready features
    y  : pd.Series     – binary labels
    df : pd.DataFrame  – full raw frame (for diagnostics / time-based analysis)
    """
    df_raw = pd.read_csv(csv_path)

    if validate:
        _validate(df_raw, name)

    # Keep the full raw frame for diagnostics
    df_full = df_raw.copy()

    # Parse & build cyclic / encoded features
    df = _parse_and_build(df_raw)

    # Separate target
    y = df[TARGET_COL].astype(int)

    # Drop IDs, raw timestamp, raw cyclic source columns, and target
    drop_cols = ID_COLS + [TARGET_COL]
    # Also drop the original linear hour / dow columns (replaced by sin/cos)
    drop_cols += ["transaction_hour", "transaction_day_of_week"]
    drop_cols = [c for c in drop_cols if c in df.columns]

    X = df.drop(columns=drop_cols)

    print(f"  → Feature matrix shape: {X.shape}\n")
    return X, y, df_full


# ─────────────────────────────────────────────────────────────────────────────
def load_all_splits(
    validate: bool = True,
) -> dict[str, tuple[pd.DataFrame, pd.Series, pd.DataFrame]]:
    """
    Convenience function: load train, validation, and test splits.

    Returns
    -------
    dict with keys "train", "val", "test", each mapping to (X, y, df_raw).
    """
    splits = {
        "train" : (TRAIN_FILE, "TRAIN"),
        "val"   : (VAL_FILE,   "VALIDATION"),
        "test"  : (TEST_FILE,  "TEST"),
    }

    loaded = {}
    for key, (path, label) in splits.items():
        print(f"── Loading {label} ──────────────────────────────")
        X, y, df_raw = load_split(path, name=label, validate=validate)
        loaded[key] = (X, y, df_raw)

    return loaded
