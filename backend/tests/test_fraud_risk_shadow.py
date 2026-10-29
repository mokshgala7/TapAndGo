"""
test_fraud_risk_shadow.py
─────────────────────────
Shadow-mode fraud risk scoring on QR confirm: it logs an audit record and never changes the payment
(response, balances, Transaction row, PaymentRequest status), including when it is disabled, the ML
package is missing, scoring raises, or its database read fails. (A payment that needed no OTP is stored
with otp_verified=False, fraud_status="clear"; see app/services/fraud_gate.py.)
"""
import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.helpers import Env
from app.models import PaymentRequest, Transaction
from app.services import fraud_risk_shadow

PKG = Path(fraud_risk_shadow.__file__).resolve().parent / "tapgo_fraud_risk"


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.items = []

    def emit(self, record):
        self.items.append(record)


@pytest.fixture
def records(monkeypatch):
    monkeypatch.delenv("TAPGO_RISK_DISABLED", raising=False)
    h = _Records()
    fraud_risk_shadow.logger.addHandler(h)
    yield h.items
    fraud_risk_shadow.logger.removeHandler(h)


@pytest.fixture
def scene():
    env = Env()
    driver_id = env.add_user("driver@shadow.local", account_type="driver", balance=0, name="Shadow Driver")
    passenger_id = env.add_user("pax@shadow.local", account_type="passenger", balance=2000, name="Shadow Pax")
    return {"env": env, "driver_id": driver_id, "passenger_id": passenger_id,
            "driver_headers": env.user_headers(driver_id), "pax_headers": env.user_headers(passenger_id)}


def pay(scene, amount):
    env = scene["env"]
    token = env.client.post("/api/qr/create-request", json={"amount": amount}, headers=scene["driver_headers"]).json()["token"]
    r = env.client.post(f"/api/qr/{token}/confirm", json={"idempotency_key": f"shadow-{uuid.uuid4().hex}"},
                        headers=scene["pax_headers"])
    return r


def add_history(scene, n, amount="100.00", days_back=None):
    """Earlier completed ride payments for the passenger (one per day, ending yesterday)."""
    db = scene["env"].db()
    try:
        start = datetime.utcnow() - timedelta(days=days_back or n + 1)
        for i in range(n):
            db.add(Transaction(reference=f"H{uuid.uuid4().hex[:12]}", passenger_id=scene["passenger_id"],
                               driver_id=scene["driver_id"], amount=Decimal(amount), payment_method="QR",
                               status="completed", otp_verified=True, fraud_status="clear",
                               transaction_type="ride_payment", idempotency_key=f"qr:{scene['passenger_id']}:h{i}",
                               created_at=start + timedelta(days=i)))
        db.commit()
    finally:
        db.close()


def audits(records):
    return [json.loads(r.getMessage()) for r in records]


def outcome(scene, r):
    """Everything the payment changes, minus values that legitimately differ per request."""
    body = r.json()
    db = scene["env"].db()
    try:
        txn = db.query(Transaction).filter(Transaction.id == body["transaction"]["id"]).one()
        pr = db.query(PaymentRequest).filter(PaymentRequest.id == txn.payment_request_id).one()
        return {"http": r.status_code, "success": body["success"], "amount": body["transaction"]["amount"],
                "txn": (txn.status, txn.otp_verified, txn.fraud_status, txn.transaction_type, float(txn.amount)),
                "request_status": pr.status}
    finally:
        db.close()


# ── vendored package integrity ──────────────────────────────────────────────

def test_vendored_package_matches_manifest():
    manifest = json.loads((PKG / "MANIFEST.json").read_text())
    assert "models/tapgo_fraud_v6.xgb.json" in manifest and not list(PKG.rglob("*.joblib"))
    for rel, digest in manifest.items():
        assert hashlib.sha256((PKG / rel).read_bytes()).hexdigest() == digest, rel


# ── shadow scoring logs and changes nothing ─────────────────────────────────

def test_shadow_scoring_logs_audit_and_payment_is_unchanged(scene, records):
    add_history(scene, 30)
    r = pay(scene, 100.0)
    assert r.status_code == 200, r.text
    assert outcome(scene, r)["txn"] == ("completed", False, "clear", "ride_payment", 100.0)
    (a,) = audits(records)
    assert a["status"] == "scored" and a["mode"] == "shadow" and a["backend_action"] == "proceed_unchanged"
    assert a["model_version"] == "passenger_fraud_v6.1.0.0" and a["history_rows"] == 30
    assert a["payment_request_id"] is not None and isinstance(a["risk_score"], float)
    # pseudonymous: the raw passenger id, names and emails are not in the record
    raw = json.dumps(a)
    assert a["passenger_key"] != str(scene["passenger_id"]) and "pax@shadow.local" not in raw and "Shadow" not in raw


def test_unusual_fare_is_recorded_but_payment_still_proceeds(scene, records):
    """₹100 passenger charged ₹500 by a familiar driver: the anomaly is logged; shadow mode never blocks."""
    add_history(scene, 30)
    r = pay(scene, 500.0)
    assert r.status_code == 200, r.text
    assert outcome(scene, r)["txn"] == ("completed", False, "clear", "ride_payment", 500.0)
    (a,) = audits(records)
    assert a["status"] == "scored" and a["fare_anomaly_level"] == "high" and a["rules"]["amount_anomalous"] is True
    assert a["backend_action"] == "proceed_unchanged"


def test_rapid_repeat_rule_logged(scene, records):
    pay(scene, 100.0)
    pay(scene, 100.0)
    a = audits(records)
    assert len(a) == 2 and a[1]["rules"]["rapid_repeat_10min"] is True and a[1]["backend_action"] == "proceed_unchanged"


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_kill_switch_skips_scoring_and_payment_identical(scene, records, monkeypatch, value):
    baseline = outcome(scene, pay(scene, 75.0))
    records.clear()
    monkeypatch.setenv("TAPGO_RISK_DISABLED", value)
    r = pay(scene, 75.0)
    assert outcome(scene, r) == baseline and records == []


def test_missing_ml_package_does_not_break_payment(scene, records, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.services.tapgo_fraud_risk", None)     # import raises ImportError
    r = pay(scene, 80.0)
    assert outcome(scene, r)["txn"] == ("completed", False, "clear", "ride_payment", 80.0)
    (a,) = audits(records)
    assert a["status"] == "shadow_error" and "ModuleNotFoundError" in a["error"]


def test_scoring_exception_does_not_break_payment(scene, records, monkeypatch):
    import app.services.tapgo_fraud_risk as pkg

    def boom(*a, **k):
        raise RuntimeError("scorer exploded")
    monkeypatch.setattr(pkg, "assess_ride_payment", boom)
    r = pay(scene, 90.0)
    assert outcome(scene, r)["txn"] == ("completed", False, "clear", "ride_payment", 90.0)
    assert audits(records)[0]["status"] == "shadow_error"
    assert scene["env"].balance(scene["passenger_id"]) == pytest.approx(2000 - 90.0)


def test_database_error_inside_shadow_read_keeps_outer_transaction(scene, records):
    """A failing query runs inside a SAVEPOINT: work already flushed in the payment transaction survives."""
    from app.models import User, Wallet
    db = scene["env"].db()
    try:
        wallet = db.query(Wallet).filter(Wallet.user_id == scene["driver_id"]).one()
        pr = PaymentRequest(user_id=scene["driver_id"], wallet_id=wallet.id, amount=Decimal("50"), status="processing",
                            provider="QR_WALLET", upi_uri="https://example.invalid/qr", utr=f"shadow-{uuid.uuid4().hex}")
        db.add(pr)
        db.flush()

        def failing_query(*a, **k):
            db.execute(text("SELECT * FROM table_that_does_not_exist"))
        db.query = failing_query
        driver = db.get(User, scene["driver_id"])
        assert fraud_risk_shadow.log_shadow_assessment(db, scene["passenger_id"], driver, Decimal("50"),
                                                       datetime.utcnow(), "qr:x:y", pr.id) is None
        del db.query
        db.commit()
        assert db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).one().status == "processing"
    finally:
        db.close()
    assert audits(records)[0]["status"] == "shadow_error"


def test_helper_never_raises_on_bad_input(records):
    assert fraud_risk_shadow.log_shadow_assessment(None, None, None, None, None, None) is None
    assert audits(records)[0]["status"] == "shadow_error"
