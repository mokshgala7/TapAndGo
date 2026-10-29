"""
service.py  –  The single entry point the backend calls: `assess_ride_payment(...)`.

Safety design:
  * mode "shadow" (DEFAULT): score and return an audit record; `backend_action` is always "proceed_unchanged", so the
    payment flow behaves exactly as today. This is how real outcomes are collected before any enforcement.
  * mode "enforce": `backend_action` = "step_up_otp" when the model flags or a configured rule fires, else "proceed".
    Enforcement requires an explicit product decision (OTP policy D2 / D3) and is never the default.
  * kill switch: ML disabled -> "proceed_unchanged" with status "disabled" (identical to today's behaviour).
  * any scoring or adapter failure -> no score. In shadow mode the payment proceeds unchanged; in enforce mode the
    configured `failure_action` applies (default "step_up_otp"). A failure is NEVER reported as low risk or approval.
  * the model never approves, rejects, charges, sends OTPs, or touches the database or network.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .adapter import AdapterError, history_from_transactions, transaction_for_scoring
from .scorer import FraudScorerFinal, InferenceError

PACKAGE_VERSION = "tapgo_fraud_risk/1.1.0"
_MODELS_DIR = Path(__file__).resolve().parent / "models"
# Portable native-XGBoost exports of the frozen bundles (bit-identical scores; no scikit-learn or pickle needed).
MODELS = {"v6": _MODELS_DIR / "tapgo_fraud_v6.xgb.json", "k3": _MODELS_DIR / "tapgo_fraud_k3.xgb.json"}


@dataclass(frozen=True)
class RiskConfig:
    db_timezone: str                                   # REQUIRED; evidence says "UTC" for this backend (see adapter)
    mode: str = "shadow"                               # "shadow" | "enforce"
    kill_switch: bool = False
    model: str = "v6"                                  # "v6" (default; robust on fare anomalies) | "k3" (NOT recommended: see validation/)
    step_up_rules: tuple = ("rapid_repeat_10min",)     # enforce mode only; the bundle's documented policy
    new_passenger_amount_rule: bool = False            # enforce only; OFF by default (validation: ~38 legit per extra fraud)
    failure_action: str = "step_up_otp"                # enforce only: what to do when scoring fails

    def __post_init__(self):
        if self.mode not in ("shadow", "enforce"):
            raise ValueError("mode must be 'shadow' or 'enforce'")
        if self.model not in MODELS:
            raise ValueError(f"model must be one of {sorted(MODELS)}")
        if self.failure_action not in ("step_up_otp", "proceed"):
            raise ValueError("failure_action must be 'step_up_otp' or 'proceed'")
        from zoneinfo import ZoneInfo
        ZoneInfo(self.db_timezone)                     # raises if the timezone name is invalid


_SCORERS: dict = {}


def load_scorer(model: str = "v6") -> FraudScorerFinal:
    """Load once per process (model and metadata hash-verified against their .sha256 sidecars)."""
    if model not in _SCORERS:
        _SCORERS[model] = FraudScorerFinal.load_portable(MODELS[model])
    return _SCORERS[model]


@dataclass
class Assessment:
    status: str                       # scored | disabled | invalid_input | duplicate_request | model_unavailable | prediction_error | ...
    backend_action: str               # proceed_unchanged | proceed | step_up_otp
    mode: str
    model_version: str | None
    risk: dict | None                 # full scorer output (risk_score, model_flag, passenger_fare_anomaly, rules, warnings ...)
    reasons: list = field(default_factory=list)
    audit: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


def _audit(passenger_id, amount, cfg: RiskConfig, status, action, risk) -> dict:
    """Audit record for shadow-mode analysis. Pseudonymous passenger key; no names, contact data or location."""
    return {"logged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "package": PACKAGE_VERSION,
            "passenger_key": hashlib.sha256(f"tapgo:{passenger_id}".encode()).hexdigest()[:16], "amount": float(amount) if amount is not None else None,
            "mode": cfg.mode, "status": status, "backend_action": action,
            "risk_score": (risk or {}).get("risk_score"), "model_flag": (risk or {}).get("model_flag"),
            "fare_anomaly_level": ((risk or {}).get("passenger_fare_anomaly") or {}).get("level"),
            "rules": {k: (v["triggered"] if isinstance(v, dict) else v) for k, v in ((risk or {}).get("rules") or {}).items()},
            "model_version": (risk or {}).get("model_version")}


def assess_ride_payment(passenger_id: Any, driver_id: Any, amount: Any, history_rows: Iterable[Any], config: RiskConfig,
                        at: Any = None, driver_vehicle_type: str | None = None, idempotency_key: str | None = None,
                        history_vehicle_types: Mapping[Any, str | None] | None = None) -> Assessment:
    """Assess one ride payment BEFORE the wallet transfer. `history_rows` = this passenger's earlier `transactions` rows
    (ORM objects or dicts). Never raises for scoring problems; returns a fail-safe Assessment instead."""
    if config.kill_switch:
        return Assessment("disabled", "proceed_unchanged", config.mode, None, None, ["kill_switch"],
                          _audit(passenger_id, amount, config, "disabled", "proceed_unchanged", None))
    try:
        scorer = load_scorer(config.model)
    except InferenceError as e:
        return _failed(passenger_id, amount, config, e.status, str(e))
    try:
        tx = transaction_for_scoring(passenger_id, driver_id, amount, at, config.db_timezone, vehicle_type=driver_vehicle_type,
                                     idempotency_key=idempotency_key)
        hist = history_from_transactions(history_rows, passenger_id, config.db_timezone, history_vehicle_types)
    except AdapterError as e:
        return _failed(passenger_id, amount, config, "invalid_input", str(e))
    risk = scorer.score_safe(tx, hist)
    if risk["scoring_status"] != "scored":
        return _failed(passenger_id, amount, config, risk["scoring_status"], risk.get("error", ""), risk)
    fired = [r for r in config.step_up_rules if (risk["rules"].get(r, {}).get("triggered") if isinstance(risk["rules"].get(r), dict)
                                                 else risk["rules"].get(r))]
    if config.new_passenger_amount_rule and risk["rules"]["amount_anomalous"] and risk["history"]["prior_completed_rides"] < 20:
        fired.append("new_passenger_amount_anomaly")
    step_up = bool(risk["model_flag"]) or bool(fired)
    reasons = (["model_flag"] if risk["model_flag"] else []) + fired
    action = "proceed_unchanged" if config.mode == "shadow" else ("step_up_otp" if step_up else "proceed")
    return Assessment("scored", action, config.mode, risk["model_version"], risk, reasons,
                      _audit(passenger_id, amount, config, "scored", action, risk) | {"would_step_up": step_up, "reasons": reasons})


def _failed(passenger_id, amount, config, status, msg, risk=None) -> Assessment:
    action = "proceed_unchanged" if config.mode == "shadow" else config.failure_action
    return Assessment(status, action, config.mode, None, risk, [f"failure:{status}"],
                      _audit(passenger_id, amount, config, status, action, risk) | {"error": msg[:300]})
