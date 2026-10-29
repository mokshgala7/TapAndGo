"""tapgo_fraud_risk  –  Integration-ready fraud risk scoring for Tap & Go ride payments (offline; no DB/network).

    from tapgo_fraud_risk import RiskConfig, assess_ride_payment
    result = assess_ride_payment(passenger_id, driver_id, amount, history_rows, RiskConfig(db_timezone="UTC"))
    result.backend_action   # "proceed_unchanged" in shadow mode (default)

Research prototype evaluated on synthetic data only: run in SHADOW mode until real outcomes validate it.
"""

from .adapter import AdapterError, history_from_transactions, transaction_for_scoring
from .scorer import FraudScorerFinal, InferenceError
from .service import PACKAGE_VERSION, Assessment, RiskConfig, assess_ride_payment, load_scorer

__all__ = ["RiskConfig", "Assessment", "assess_ride_payment", "load_scorer", "FraudScorerFinal", "InferenceError",
           "AdapterError", "history_from_transactions", "transaction_for_scoring", "PACKAGE_VERSION"]
