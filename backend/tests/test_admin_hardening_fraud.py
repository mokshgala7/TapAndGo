"""Phase 2 of the admin hardening: the Fraud Centre shows model-flagged payments (admin-side sync, no payment code)."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.models import FraudAlert, FraudAssessment, Wallet, User
from app.services.fraud_alert_sync import sync_flagged_assessments
from helpers import Env


@pytest.fixture
def env():
    return Env()


def assess(env, passenger_id, driver_id, flagged, amount="250.00", score="0.91", key=None, channel="nfc"):
    db = env.db()
    try:
        row = FraudAssessment(
            passenger_id=passenger_id, driver_id=driver_id, channel=channel, idempotency_key=key,
            amount=Decimal(amount), assessed_at=datetime.utcnow(), mode="shadow", enforced_by_allowlist=False,
            risk_score=Decimal(score), model_flag=flagged, rule_10min=False, ml_status="scored",
            decision="proceed", reasons="model_flag" if flagged else None, threshold=Decimal("0.80"))
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def setup(env):
    admin = env.add_admin()
    passenger = env.add_user("rider@example.com", balance=500)
    driver = env.add_user("drv@example.com", account_type="driver")
    return env.admin_headers(admin), passenger, driver


def test_flagged_assessment_appears_and_unflagged_does_not(env):
    h, p, d = setup(env)
    assess(env, p, d, True, amount="250.00", score="0.91")
    assess(env, p, d, False, score="0.10")
    res = env.client.get("/api/admin/fraud-alerts", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["user_name"] == "Rider" and item["amount"] == 250.0
    assert item["risk_score"] == 91 and item["status"] == "open"
    assert "ML model flagged" in item["reason"]


def test_sync_is_idempotent(env):
    h, p, d = setup(env)
    assess(env, p, d, True)
    for _ in range(3):
        env.client.get("/api/admin/fraud-alerts", headers=h)
    db = env.db()
    try:
        assert db.query(FraudAlert).count() == 1
        assert sync_flagged_assessments(db) == 0
    finally:
        db.close()


def test_default_hides_reviewed_and_status_filter_works(env):
    h, p, d = setup(env)
    a1, a2, a3 = (assess(env, p, d, True) for _ in range(3))
    items = env.client.get("/api/admin/fraud-alerts", headers=h).json()["items"]
    ids = {i["id"] for i in items}
    assert len(ids) == 3
    first, second, third = sorted(ids)
    assert env.client.post(f"/api/admin/fraud-alerts/{first}/review", headers=h, json={"action": "safe"}).status_code == 200
    assert env.client.post(f"/api/admin/fraud-alerts/{second}/review", headers=h, json={"action": "block"}).status_code == 200

    get = lambda q="": env.client.get(f"/api/admin/fraud-alerts{q}", headers=h).json()
    assert [i["id"] for i in get()["items"]] == [third]                       # default: flagged only
    assert [i["id"] for i in get("?status=safe")["items"]] == [first]
    assert [i["id"] for i in get("?status=blocked")["items"]] == [second]
    assert get("?status=all")["total"] == 3
    assert get("?status=open")["total"] == 1
    assert env.client.get("/api/admin/fraud-alerts?status=bogus", headers=h).status_code == 422


def test_review_block_suspends_and_freeze_freezes_wallet(env):
    h, p, d = setup(env)
    assess(env, p, d, True)
    alert = env.client.get("/api/admin/fraud-alerts", headers=h).json()["items"][0]["id"]
    assert env.client.post(f"/api/admin/fraud-alerts/{alert}/review", headers=h, json={"action": "freeze"}).status_code == 200
    db = env.db()
    try:
        assert db.query(Wallet).filter(Wallet.user_id == p).first().is_frozen is True
    finally:
        db.close()
    assess(env, p, d, True)
    alert2 = env.client.get("/api/admin/fraud-alerts", headers=h).json()["items"][0]["id"]
    assert env.client.post(f"/api/admin/fraud-alerts/{alert2}/review", headers=h, json={"action": "block"}).status_code == 200
    db = env.db()
    try:
        assert db.get(User, p).status == "suspended"
    finally:
        db.close()


def test_dashboard_counts_synced_open_alerts_and_requires_admin(env):
    h, p, d = setup(env)
    assess(env, p, d, True)
    assert env.client.get("/api/admin/dashboard", headers=h).json()["fraud_alerts"] == 1
    assert env.client.get("/api/admin/fraud-alerts").status_code == 401


def test_sync_failure_never_breaks_the_page(env, monkeypatch):
    h, p, d = setup(env)
    import app.services.fraud_alert_sync as mod

    def boom(_assessment):
        raise RuntimeError("sync broke")
    assess(env, p, d, True)
    monkeypatch.setattr(mod, "_reason", boom)
    res = env.client.get("/api/admin/fraud-alerts", headers=h)
    assert res.status_code == 200 and res.json()["total"] == 0
    assert env.client.get("/api/admin/dashboard", headers=h).status_code == 200
