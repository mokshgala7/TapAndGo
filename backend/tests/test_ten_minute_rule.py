"""
The 10-minute rule is mandatory: a passenger who completed a ride payment less than ten minutes ago needs the
emailed OTP for the next one, on every channel (card/phone tap, QR, wallet pay), for every passenger, whatever
TAPGO_FRAUD_MODE says and without any allowlist. Nothing moves before the right code.
"""
import uuid

import pytest

from tests.test_fraud_gate import (  # noqa: F401  (fixtures and helpers shared with the fraud gate tests)
    balances, completed, expire, last_otp, mail, nfc_verify, qr_confirm, qr_create, rows, scene, tap, wrong,
)
from app.models import Transaction
from app.services import fraud_gate


@pytest.fixture(autouse=True)
def rule_on(monkeypatch):
    monkeypatch.setenv("TAPGO_TEN_MINUTE_RULE", "on")
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")          # only the rule decides in these tests
    monkeypatch.delenv("TAPGO_FRAUD_ENFORCE_USER_IDS", raising=False)


@pytest.fixture(params=["shadow", "off", ""])
def any_mode(request, monkeypatch):
    if request.param:
        monkeypatch.setenv("TAPGO_FRAUD_MODE", request.param)
    else:
        monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)    # unset = shadow
    return request.param


def test_card_tap_second_payment_within_ten_minutes_needs_otp(scene, any_mode):
    r1, _ = tap(scene, amount=100)
    assert r1.json()["success"] is True                          # first payment: nothing to wait for
    before = balances(scene)
    r2, key = tap(scene, amount=100)
    body = r2.json()
    assert body["status"] == "otp_required" and body["challenge_id"]
    assert balances(scene) == before                              # no money moved
    ok = nfc_verify(scene, body["challenge_id"], last_otp(scene), key).json()
    assert ok["success"] is True
    assert balances(scene) == (before[0] - 100, before[1] + 100)


def test_wrong_code_never_pays(scene, any_mode):
    tap(scene, amount=100)
    before = balances(scene)
    r2, key = tap(scene, amount=100)
    cid = r2.json()["challenge_id"]
    bad = nfc_verify(scene, cid, wrong(last_otp(scene)), key).json()
    assert bad["status"] == "otp_invalid"
    assert balances(scene) == before


def test_qr_second_payment_within_ten_minutes_needs_otp(scene, any_mode):
    t1 = qr_create(scene, 50)
    assert qr_confirm(scene, t1).json()["success"] is True
    before = balances(scene)
    t2 = qr_create(scene, 50)
    r = qr_confirm(scene, t2)
    assert r.json()["status"] == "otp_required"
    assert balances(scene) == before
    cid = r.json()["challenge_id"]
    v = scene["env"].client.post(f"/api/qr/{t2}/verify-otp", json={"challenge_id": cid, "otp": last_otp(scene)},
                                 headers=scene["pax_headers"])
    assert v.json()["success"] is True
    assert balances(scene) == (before[0] - 50, before[1] + 50)


def test_wallet_pay_second_payment_within_ten_minutes_needs_otp(scene, any_mode):
    def pay(key):
        return scene["env"].client.post("/api/wallet/pay", headers=scene["pax_headers"], json={
            "driver_id": scene["driver_id"], "fare": 40, "payment_method": "QR", "idempotency_key": key})
    assert pay(f"w-{uuid.uuid4().hex}").json()["success"] is True
    before = balances(scene)
    r = pay(f"w-{uuid.uuid4().hex}")
    assert r.json()["status"] == "otp_required"
    assert balances(scene) == before


def test_after_ten_minutes_no_code_is_needed(scene, any_mode):
    from datetime import datetime, timedelta
    tap(scene, amount=100)
    db = scene["env"].db()
    db.query(Transaction).filter(Transaction.transaction_type == "ride_payment").update(
        {"created_at": datetime.utcnow() - timedelta(seconds=700)})
    db.commit()
    db.close()
    r, _ = tap(scene, amount=100)
    assert r.json()["success"] is True


def test_applies_to_every_passenger_not_just_a_list(scene, any_mode):
    # a second passenger with their own card, never on any allowlist
    from app.models import NFCCard
    env = scene["env"]
    other = env.add_user("second.pax@example.com", account_type="passenger", balance=1000, name="Second Pax")
    db = env.db()
    db.add(NFCCard(user_id=other, card_reference="NFC-SECOND", card_uid="04AABBCCDDEE01", status="active"))
    db.commit()
    db.close()

    def tap2():
        key = f"t-{uuid.uuid4().hex}"
        return env.client.post("/api/nfc/pay", json={"card_uid": "04AABBCCDDEE01", "amount": 30, "idempotency_key": key},
                               headers=scene["driver_headers"]).json()
    assert tap2()["success"] is True
    assert tap2()["status"] == "otp_required"


def test_the_switch_turns_it_off(scene, monkeypatch):
    monkeypatch.setenv("TAPGO_TEN_MINUTE_RULE", "off")
    tap(scene, amount=100)
    r, _ = tap(scene, amount=100)
    assert r.json()["success"] is True


def test_gate_error_fails_closed_for_the_rule(scene, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(fraud_gate, "_evaluate_payment", boom)
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "shadow")
    r, _ = tap(scene, amount=100)
    assert r.json()["status"] == "otp_required"
