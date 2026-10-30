"""
predict.py  --  Run fraud risk scoring on new transactions.

This is the inference entry-point for the Tap&Go backend.
Given a dict (or list of dicts) representing one or more transactions,
it returns a risk score [0-1] and a boolean flag indicating whether
an OTP step-up challenge should be triggered.

Usage (as a module from your backend)
--------------------------------------
    from src.predict import predict_transaction, load_inference_pipeline

    pipeline = load_inference_pipeline()
    result = predict_transaction(pipeline, {
        "transaction_amount": 450.0,
        "payment_method": "NFC",
        "transaction_hour": 23,
        "transaction_day_of_week": 5,
        ...
    })
    # result = {"risk_score": 0.73, "trigger_otp": True, "model": "xgboost"}

Usage (standalone CLI)
-----------------------
    python -m src.predict --json "{...}"
"""

import json
import argparse
import warnings
warnings.filterwarnings("ignore")

import numpy  as np
import pandas as pd

from src.feature_engineering import add_engineered_features
from src.preprocessing       import apply_scaler
from src.config              import REPORT_DIR

import src.models.xgboost_model as xgb_mod   # primary model


# ---------------------------------------------------------------------------
class InferencePipeline:
    """
    Holds the loaded model + threshold so you only pay the
    disk-load cost once at app startup.
    """
    def __init__(self, model, threshold: float, model_name: str = "xgboost"):
        self.model      = model
        self.threshold  = threshold
        self.model_name = model_name

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X)[:, 1]

    def predict(self, X: pd.DataFrame) -> dict:
        scores   = self.score(X)
        triggers = (scores >= self.threshold).tolist()
        return {
            "risk_scores": scores.tolist(),
            "trigger_otp": triggers,
            "model":       self.model_name,
            "threshold":   self.threshold,
        }


# ---------------------------------------------------------------------------
def load_inference_pipeline(model_name: str = "xgboost") -> InferencePipeline:
    """
    Load the saved model and its validated threshold.

    Parameters
    ----------
    model_name : str  -- "xgboost" (default) | "random_forest" | "logistic_regression"

    Returns
    -------
    InferencePipeline ready for .predict(X)
    """
    # Load threshold from reports/thresholds.csv
    thr_path = REPORT_DIR / "thresholds.csv"
    if not thr_path.exists():
        raise FileNotFoundError(
            f"Threshold file not found at {thr_path}. "
            "Run validate.py first."
        )
    thr_df    = pd.read_csv(thr_path, index_col=0)
    threshold = float(thr_df.loc[model_name, "threshold"])

    # Load model
    if model_name == "xgboost":
        import src.models.xgboost_model as mod
    elif model_name == "random_forest":
        import src.models.random_forest_model as mod
    elif model_name == "logistic_regression":
        import src.models.logistic_regression_model as mod
    else:
        raise ValueError(f"Unknown model: {model_name}")

    model = mod.load()
    print(f"[predict] Loaded '{model_name}' (threshold={threshold:.4f})")
    return InferencePipeline(model, threshold, model_name)


# ---------------------------------------------------------------------------
def _preprocess_input(raw: dict | list[dict]) -> pd.DataFrame:
    """
    Convert raw transaction dict(s) into a model-ready feature matrix.
    Handles the same transforms as data_loader + feature_engineering.
    """
    if isinstance(raw, dict):
        raw = [raw]

    df = pd.DataFrame(raw)

    # Cyclic hour/dow encoding
    if "transaction_hour" in df.columns:
        h = df["transaction_hour"]
        df["hour_sin"] = np.sin(2 * np.pi * h / 24)
        df["hour_cos"] = np.cos(2 * np.pi * h / 24)
        df = df.drop(columns=["transaction_hour"])

    if "transaction_day_of_week" in df.columns:
        d = df["transaction_day_of_week"]
        df["dow_sin"] = np.sin(2 * np.pi * d / 7)
        df["dow_cos"] = np.cos(2 * np.pi * d / 7)
        df = df.drop(columns=["transaction_day_of_week"])

    # One-hot encode payment_method (safe for single dicts where only 1 method is present)
    if "payment_method" in df.columns:
        pm = df["payment_method"].astype(str).str.upper()
        df["payment_method_NFC"] = (pm == "NFC").astype(int)
        df["payment_method_QR"] = (pm == "QR").astype(int)
        df = df.drop(columns=["payment_method"])
    else:
        if "payment_method_NFC" not in df.columns:
            df["payment_method_NFC"] = 0
        if "payment_method_QR" not in df.columns:
            df["payment_method_QR"] = 0

    # Drop ID / metadata columns if present
    drop_cols = ["transaction_id", "user_id", "transaction_timestamp", "is_fraud"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    # Add engineered features
    df = add_engineered_features(df)

    # Reorder columns to match model training order if feature_names_in_ is present
    return df


# ---------------------------------------------------------------------------
def predict_transaction(
    pipeline:    InferencePipeline,
    transaction: dict | list[dict],
    use_scaler:  bool = False,
) -> dict:
    """
    Score one or more transactions.

    Parameters
    ----------
    pipeline    : InferencePipeline  -- from load_inference_pipeline()
    transaction : dict or list[dict] -- raw transaction feature values
    use_scaler  : bool               -- set True if model is logistic_regression

    Returns
    -------
    result dict with keys:
        risk_scores  : list[float]  -- fraud probability for each transaction
        trigger_otp  : list[bool]   -- True = send OTP challenge
        model        : str
        threshold    : float
    """
    X = _preprocess_input(transaction)

    if hasattr(pipeline.model, "feature_names_in_"):
        for col in pipeline.model.feature_names_in_:
            if col not in X.columns:
                X[col] = 0
        X = X[list(pipeline.model.feature_names_in_)]

    if use_scaler:
        X = apply_scaler(X)

    return pipeline.predict(X)


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="TapGo fraud risk scorer")
    parser.add_argument(
        "--json", type=str, required=True,
        help='JSON string of a transaction dict, e.g. \'{"transaction_amount": 450, ...}\''
    )
    parser.add_argument("--model", default="xgboost",
                        choices=["xgboost", "random_forest", "logistic_regression"])
    args = parser.parse_args()

    transaction = json.loads(args.json)
    pipeline    = load_inference_pipeline(args.model)
    result      = predict_transaction(pipeline, transaction)

    print("\n--- Prediction Result ---")
    for i, (score, otp) in enumerate(zip(result["risk_scores"], result["trigger_otp"])):
        status = ">> OTP CHALLENGE TRIGGERED" if otp else "   OK (low risk)"
        print(f"  Transaction {i+1}: risk_score={score:.4f}  {status}")
    print(f"  Model: {result['model']}  |  Threshold: {result['threshold']:.4f}")


if __name__ == "__main__":
    main()
