"""
One fraud gate for every ride payment (QR confirm, NFC tap, wallet pay).

    decision = evaluate_payment(db, passenger, driver, amount, now, idempotency_key, channel)
    decision["action"]  # "proceed" | "otp_required"

It combines two independent checks:

  1. The mandatory 10-minute rule, plain SQL/Python with NO dependency on the ML package: the payment needs OTP
     when it is initiated within 600 s of the passenger's previous COMPLETED ride payment. Elapsed time is whole
     seconds, floored, inclusive: 599 s and 600 s fire, 601 s does not (600.9 s floors to 600 and fires). Failed
     rides never reset the reference. Clock skew (a completed ride stamped after "now") counts as 0 s: that ride
     really is recent. This is the model's own definition, so QR and NFC agree with the scorer.
  2. The V6 ML risk score (app.services.fraud_risk_shadow.run_assessment). The model only scores; this gate decides.

Mode (env TAPGO_FRAUD_MODE):
  off      no check at all; every payment proceeds exactly as before the gate existed (decision still recorded).
  shadow   DEFAULT. Both checks run and are recorded/logged; every payment proceeds unchanged.
  The 10-minute rule is separate: it asks for the OTP for everyone in EVERY mode (even shadow and off) unless
  TAPGO_TEN_MINUTE_RULE=off. The modes below govern the ML score.
  enforce  otp_required when the model flags, the 10-minute rule fires, or the model produced no score
           (unavailable, invalid input, error). A failure is never treated as low risk. ML switched off on purpose
           with TAPGO_RISK_DISABLED=1 is "disabled", not a failure: the 10-minute rule still applies.
  Unset means shadow. Any other value is a configuration error: validate_fraud_config() (run at app startup)
  refuses to start and names the allowed values. enforce also needs PAYMENT_OTP_SECRET (see below).

Per-user enforcement (env TAPGO_FRAUD_ENFORCE_USER_IDS, comma-separated passenger user ids, default empty):
  mode off      nothing runs; the list is ignored (the kill switch wins).
  mode enforce  enforce for everyone; the list is ignored.
  mode shadow   shadow for everyone EXCEPT passengers in the list, who get full enforcement (flagged, 10-minute rule
                or ML failure -> email OTP, no money moves without a verified OTP).
  The list is validated at startup (positive integers; one trailing comma allowed; anything else stops the app).
  Verify/resend/cancel and the status lookup act on existing challenges, so they follow automatically.
  Every fraud_assessments row records the mode that applied to that payment and whether the allowlist caused it.

Demo OTP redirect (env TAPGO_OTP_DEMO_REDIRECT_EMAIL, default unset): payment-OTP emails of passengers in the
allowlist go to that one address instead of the passenger's own (never withdrawals, receipts or other mail). Ignored
(with a warning) in mode off and in mode enforce; it must be one valid address or the app refuses to start. The address
is never logged, stored or returned (see send_email's recipient redaction).

Fail-safe: evaluate_payment never raises for fraud-code problems. An unexpected error returns otp_required for a
passenger that is enforced and proceed for everyone else (payment unchanged).

Every decision is stored in fraud_assessments (ids, amount, scores, decision; no names, contact data or location)
and printed as one `tapgo.fraud_gate` JSON line.
"""
import json
import logging
import os
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.config import DEV_SECRET_KEY
from app.models import FraudAssessment, Transaction
from app.services.fraud_risk_shadow import ml_disabled, run_assessment

logger = logging.getLogger("tapgo.fraud_gate")

TEN_MINUTES_S = 600
MODES = ("off", "shadow", "enforce")
CHANNELS = ("qr", "nfc", "wallet")


class FraudConfigError(RuntimeError):
    """The fraud/OTP environment is unsafe or invalid; the app must not start (or serve a payment) with it."""


def fraud_mode() -> str:
    raw = os.getenv("TAPGO_FRAUD_MODE", "").strip().lower() or "shadow"
    if raw not in MODES:
        raise FraudConfigError(
            f"TAPGO_FRAUD_MODE={raw[:30]!r} is not valid. Allowed values: off | shadow | enforce "
            "(unset means shadow).")
    return raw


def enforce_user_ids() -> frozenset:
    """TAPGO_FRAUD_ENFORCE_USER_IDS as a set of passenger ids. Raises FraudConfigError for anything malformed:
    non-integers, zero/negative ids, or empty items (a single trailing comma is allowed)."""
    raw = os.getenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    items = raw.split(",")
    if items and items[-1].strip() == "":
        items = items[:-1]                              # one trailing comma is fine
    ids = set()
    for item in items:
        item = item.strip()
        if not item.isascii() or not item.isdigit() or int(item) < 1:
            raise FraudConfigError(
                f"TAPGO_FRAUD_ENFORCE_USER_IDS is malformed (bad item {item[:20]!r}). Expected positive integer "
                "passenger ids separated by commas, e.g. 12,34 (unset or empty = nobody).")
        ids.add(int(item))
    return frozenset(ids)


def effective_mode(passenger_id):
    """(mode that applies to this passenger, whether the allowlist caused it)."""
    base = fraud_mode()
    if base == "shadow" and passenger_id in enforce_user_ids():
        return "enforce", True
    return base, False


_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


def otp_demo_redirect():
    """The configured demo redirect address or None. Raises FraudConfigError (WITHOUT echoing the value) when it is
    set but is not exactly one syntactically valid address."""
    raw = os.getenv("TAPGO_OTP_DEMO_REDIRECT_EMAIL", "").strip()
    if not raw:
        return None
    if len(raw) > 254 or not _EMAIL_RE.match(raw):
        raise FraudConfigError("TAPGO_OTP_DEMO_REDIRECT_EMAIL is set but is not exactly one valid email address "
                               "(the value is not shown). Fix it or unset it.")
    return raw


def otp_recipient(passenger):
    """(address the payment OTP goes to, whether it is the demo redirect). The redirect applies ONLY to allowlisted
    passengers while the base mode is shadow."""
    try:
        redirect = otp_demo_redirect()
        if redirect and fraud_mode() == "shadow" and passenger.id in enforce_user_ids():
            return redirect, True
    except FraudConfigError:
        pass                                                    # invalid config is stopped at startup; never redirect on doubt
    return (passenger.email or ""), False


def otp_secret_is_safe() -> bool:
    secret = os.getenv("PAYMENT_OTP_SECRET", "").strip()
    return bool(secret) and secret != DEV_SECRET_KEY


def validate_fraud_config() -> str:
    """Startup check (app/main.py). Returns the mode. Raises FraudConfigError for an unknown mode, a malformed
    TAPGO_FRAUD_ENFORCE_USER_IDS, or enforcement (mode enforce, or a non-empty list outside mode off) without a real
    PAYMENT_OTP_SECRET (unset, or equal to the committed dev SECRET_KEY default). Otherwise an unsafe secret only logs
    a warning: no OTP is issued."""
    mode = fraud_mode()
    listed = enforce_user_ids()                         # validates the list even when mode is off
    redirect = otp_demo_redirect()                      # validates the address (never echoed)
    if redirect:
        note = ("TAPGO_OTP_DEMO_REDIRECT_EMAIL is IGNORED: " + ("mode is off" if mode == "off" else
                "TAPGO_FRAUD_MODE=enforce covers everyone (the redirect is only for the listed demo users)" if mode == "enforce" else
                "TAPGO_FRAUD_ENFORCE_USER_IDS is empty")) if (mode != "shadow" or not listed) else \
               "DEMO OTP REDIRECT ACTIVE: payment OTPs of the listed demo users go to one demo inbox. Remove it after the demo"
        logger.warning(json.dumps({"status": "demo_otp_redirect", "note": note}))
    if not otp_secret_is_safe():
        if mode == "enforce" or (listed and mode != "off"):
            why = "TAPGO_FRAUD_MODE=enforce" if mode == "enforce" else "a non-empty TAPGO_FRAUD_ENFORCE_USER_IDS"
            raise FraudConfigError(
                f"{why} requires PAYMENT_OTP_SECRET to be set to a private random value "
                "(unset, or equal to the development SECRET_KEY default, is refused). Set PAYMENT_OTP_SECRET first, "
                "then enable enforcement.")
        logger.warning(json.dumps({"status": "payment_otp_secret_not_set", "mode": mode,
                                   "note": "set PAYMENT_OTP_SECRET before enabling enforcement"}))
    return mode


def _ensure_handler() -> None:
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False


def ten_minute_rule_enforced() -> bool:
    """The 10-minute rule asks for an email OTP for EVERY passenger on every channel, whatever TAPGO_FRAUD_MODE says
    (the ML score still follows the mode). Only TAPGO_TEN_MINUTE_RULE=off|0|false|no switches it off."""
    return os.getenv("TAPGO_TEN_MINUTE_RULE", "on").strip().lower() not in ("off", "0", "false", "no")


def ten_minute_rule(db, passenger_id: int, now: datetime):
    """(fired, elapsed_seconds or None) against the previous COMPLETED ride payment. No ML involved."""
    last = (
        db.query(Transaction.created_at)
        .filter(Transaction.passenger_id == passenger_id, Transaction.transaction_type == "ride_payment",
                Transaction.status == "completed", Transaction.created_at.isnot(None))
        .order_by(Transaction.created_at.desc())
        .first()
    )
    if not last:
        return False, None
    elapsed = max(0, int((now - last[0]).total_seconds() // 1))
    return elapsed <= TEN_MINUTES_S, elapsed


def evaluate_payment(db, passenger, driver, amount, now: datetime, idempotency_key: str, channel: str,
                     payment_request_id=None) -> dict:
    """Decide whether this payment may proceed or needs an email OTP first. Commits one fraud_assessments row
    (call it while nothing else is pending in the session). Returns the decision dict with `assessment_id`.
    Never raises for fraud-code problems: an unexpected error is otp_required for an enforced passenger (fail
    closed) and proceed for everyone else (payment unchanged)."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}")
    try:
        return _evaluate_payment(db, passenger, driver, amount, now, idempotency_key, channel, payment_request_id)
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        try:
            mode, by_allowlist = effective_mode(passenger.id)
        except FraudConfigError:
            mode, by_allowlist = "enforce", False               # unreadable configuration: fail closed
        logger.error(json.dumps({"status": "gate_error", "error": type(exc).__name__, "mode": mode}))
        enforced = mode == "enforce" or ten_minute_rule_enforced()      # the mandatory rule fails closed too
        return {"action": "otp_required" if enforced else "proceed", "would_require_otp": mode != "off" or enforced, "mode": mode,
                "enforced_by_allowlist": by_allowlist, "reasons": ["ml_failure:gate_error"], "risk_score": None,
                "model_flag": None, "rule_10min": False, "elapsed_seconds": None, "ml_status": "gate_error",
                "model_version": None, "threshold": None, "assessment_id": None}


def _evaluate_payment(db, passenger, driver, amount, now: datetime, idempotency_key: str, channel: str,
                      payment_request_id=None) -> dict:
    mode, by_allowlist = effective_mode(passenger.id)
    # The routes validate amounts before calling the gate; the gate still never raises on a bad one. An amount that
    # is not a finite number > 0 counts as invalid input: never scored, never "low risk" (OTP in enforce), stored as 0.
    try:
        amount = Decimal(str(amount))
        amount_ok = amount.is_finite() and amount > 0
    except (InvalidOperation, ValueError, TypeError):
        amount_ok = False
    if not amount_ok:
        amount = Decimal("0.00")

    rule_fired, elapsed = ten_minute_rule(db, passenger.id, now)

    risk = None
    if mode == "off":
        ml_status = "off"
    elif not amount_ok:
        ml_status = "invalid_input"
    elif ml_disabled():
        ml_status = "disabled"
    else:
        assessment, audit = run_assessment(db, passenger.id, driver, amount, now, idempotency_key,
                                           mode="enforce" if mode == "enforce" else "shadow",
                                           payment_request_id=payment_request_id, channel=channel)
        if assessment is None:
            ml_status = "error"
        else:
            ml_status = assessment.status if assessment.status != "disabled" else "disabled"
            risk = assessment.risk if assessment.status == "scored" else None

    model_flag = bool(risk["model_flag"]) if risk else None
    reasons = []
    if rule_fired:
        reasons.append("rule_10min")
    if model_flag:
        reasons.append("model_flag")
    if ml_status not in ("scored", "disabled", "off"):
        reasons.append(f"ml_failure:{ml_status}")

    rule_forces_otp = rule_fired and ten_minute_rule_enforced()
    action = "otp_required" if ((mode == "enforce" and reasons) or rule_forces_otp) else "proceed"
    decision = {
        "action": action,
        "would_require_otp": bool(reasons) and (mode != "off" or rule_forces_otp),
        "mode": mode,
        "enforced_by_allowlist": by_allowlist,
        "reasons": reasons,
        "risk_score": risk["risk_score"] if risk else None,
        "model_flag": model_flag,
        "rule_10min": rule_fired,
        "elapsed_seconds": elapsed,
        "ml_status": ml_status,
        "model_version": risk["model_version"] if risk else None,
        "threshold": risk["threshold"]["value"] if risk else None,
    }

    row = FraudAssessment(
        passenger_id=passenger.id, driver_id=driver.id, channel=channel, idempotency_key=idempotency_key,
        amount=amount, assessed_at=now, mode=mode, enforced_by_allowlist=by_allowlist, risk_score=decision["risk_score"], model_flag=model_flag,
        rule_10min=rule_fired, elapsed_seconds=elapsed, ml_status=ml_status[:30], decision=action,
        reasons=",".join(reasons) or None, model_version=decision["model_version"], threshold=decision["threshold"],
    )
    try:
        db.add(row)
        db.commit()
        decision["assessment_id"] = row.id
    except Exception as exc:  # noqa: BLE001 - an audit write must not decide the payment
        db.rollback()
        decision["assessment_id"] = None
        logger.warning(json.dumps({"status": "assessment_write_failed", "error": f"{type(exc).__name__}"}))

    try:
        _ensure_handler()
        logger.info(json.dumps({k: v for k, v in decision.items()} | {
            "channel": channel, "passenger_id": passenger.id, "driver_id": driver.id,
            "amount": float(amount), "at": now.isoformat(timespec="seconds"),
        }, default=str))
    except Exception:  # noqa: BLE001
        pass
    return decision


def link_challenge(db, assessment_id, challenge_id) -> None:
    """Point the stored decision at the OTP challenge it created (best effort)."""
    if not assessment_id:
        return
    db.query(FraudAssessment).filter(FraudAssessment.id == assessment_id).update(
        {"challenge_id": challenge_id}, synchronize_session=False)
