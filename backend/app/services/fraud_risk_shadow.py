"""
ML fraud risk scoring for ride payments (QR, NFC, wallet pay).

`run_assessment` scores one payment with the vendored `tapgo_fraud_risk` package BEFORE the wallet transfer and
writes one JSON audit line to the `tapgo.fraud_risk` logger. It is called by `app.services.fraud_gate`, which owns
the decision (proceed / OTP); this module only scores. `log_shadow_assessment` is the original shadow-only helper.

  - it never raises: a missing ML dependency, a scoring error or a failed query returns no assessment;
  - its database reads run inside a SAVEPOINT, so a failed query cannot abort the payment transaction;
  - it never writes to the database, sends an OTP or alters `otp_verified` / `fraud_status`.

History is cleaned before scoring so that backend data quirks can never cause a scoring failure (which in enforce
mode would mean a spurious OTP): failed rows without a usable amount (AMOUNT_INVALID taps store 0.00) are dropped,
rows with identical timestamps are separated by 1 microsecond, and the scoring time is moved just after the
passenger's latest row when clock skew puts that row at/after "now".

Settings (environment):
  TAPGO_RISK_DISABLED      "1"/"true"/"yes" turns ML scoring off completely (kill switch). Default: on.
  TAPGO_RISK_DB_TIMEZONE   timezone of the naive `transactions.created_at` values. Default: "UTC".
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

from app.models import Transaction, User

logger = logging.getLogger("tapgo.fraud_risk")
HISTORY_LIMIT = 1000
_TICK = timedelta(microseconds=1)


def ml_disabled() -> bool:
    return os.getenv("TAPGO_RISK_DISABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _ensure_handler() -> None:
    # The app configures no logging; without this, INFO records would be dropped (root level is WARNING).
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False


def _clean_history(history, at: datetime):
    """Scorer-safe history rows (plain dicts, oldest first) and a scoring time strictly after all of them."""
    rows = []
    for t in history:
        if t.created_at is None:
            continue
        if t.amount is None or Decimal(str(t.amount)) <= 0:
            continue                                   # e.g. AMOUNT_INVALID taps: no fare information
        # A ride without a driver (seeded/demo ledger rows) still carries a real fare and time. The scorer needs a
        # driver id per row, so each such ride gets its OWN placeholder: its amounts and timing are used, and no
        # driver familiarity is claimed (a placeholder never matches another ride's driver).
        driver_id = t.driver_id if t.driver_id is not None else f"nodriver-{t.id}"
        rows.append({"passenger_id": t.passenger_id, "driver_id": driver_id, "amount": t.amount,
                     "payment_method": t.payment_method, "status": t.status, "transaction_type": t.transaction_type,
                     "idempotency_key": t.idempotency_key, "created_at": t.created_at})
    rows.sort(key=lambda r: r["created_at"])
    for prev, cur in zip(rows, rows[1:]):
        if cur["created_at"] <= prev["created_at"]:
            cur["created_at"] = prev["created_at"] + _TICK
    if rows and rows[-1]["created_at"] >= at:
        at = rows[-1]["created_at"] + _TICK              # clock skew: never let it become an "invalid input"
    return rows, at


def run_assessment(db, passenger_id, driver, amount, at: datetime, idempotency_key: str, mode: str = "shadow",
                   payment_request_id=None, channel=None):
    """Score one ride payment and log the audit record. Never raises.
    Returns (Assessment or None, audit dict or None). None/None only when ML is disabled by the kill switch."""
    if ml_disabled():
        return None, None
    try:
        _ensure_handler()
        from app.services.tapgo_fraud_risk import RiskConfig, assess_ride_payment

        config = RiskConfig(db_timezone=os.getenv("TAPGO_RISK_DB_TIMEZONE", "UTC"), mode=mode, model="v6")
        with db.begin_nested():
            history = (
                db.query(Transaction)
                .filter(Transaction.passenger_id == passenger_id, Transaction.transaction_type == "ride_payment")
                .order_by(Transaction.created_at.desc())
                .limit(HISTORY_LIMIT)
                .all()
            )
            driver_ids = {t.driver_id for t in history if t.driver_id is not None}
            vehicle_types = (
                dict(db.query(User.id, User.vehicle_type).filter(User.id.in_(driver_ids)).all()) if driver_ids else {}
            )
        rows, score_at = _clean_history(history, at)
        assessment = assess_ride_payment(
            passenger_id, driver.id, amount, rows, config, at=score_at,
            driver_vehicle_type=driver.vehicle_type, idempotency_key=idempotency_key,
            history_vehicle_types=vehicle_types,
        )
        audit = dict(assessment.audit, payment_request_id=payment_request_id, history_rows=len(history))
        if channel:
            audit["channel"] = channel
        logger.info(json.dumps(audit, default=str))
        return assessment, audit
    except Exception as exc:  # noqa: BLE001 - scoring must never break the payment route
        audit = {"status": "shadow_error" if mode == "shadow" else "ml_error",
                 "error": f"{type(exc).__name__}: {exc}"[:300], "payment_request_id": payment_request_id}
        try:
            logger.warning(json.dumps(audit))
        except Exception:  # noqa: BLE001
            pass
        return None, audit


def log_shadow_assessment(db, passenger_id, driver, amount, at: datetime, idempotency_key: str,
                          payment_request_id=None):
    """Score one ride payment in shadow mode and log the audit record. Never raises; returns the audit dict or None."""
    assessment, audit = run_assessment(db, passenger_id, driver, amount, at, idempotency_key, "shadow",
                                       payment_request_id)
    return audit if assessment is not None else None
