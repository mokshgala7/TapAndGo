"""
test_nfc_phone_tap.py
─────────────────────
Tap & Pay with a phone: the passenger "arms" in the app, the POS posts the phone's random UID to
POST /api/nfc/pay, and the unchanged card handler takes the payment from the armed passenger.
"""
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from tests.helpers import Env
from app.models import NFCCard, Transaction
from app.routes.nfc_phone import NfcPhoneArm

PHONE_UID = "08A1B2C3"     # Android card emulation: random 4-byte UID, first byte 0x08
CARD_UID = "04A2B3C4D5E680"


@pytest.fixture
def scene():
    env = Env()
    driver = env.add_user("drv@phonetest.local", account_type="driver", balance=0, name="Rakesh Sharma")
    pax = env.add_user("pax@phonetest.local", account_type="passenger", balance=500, name="Asha Verma")
    other = env.add_user("pax2@phonetest.local", account_type="passenger", balance=500, name="Ben Other")
    db = env.db()
    db.add(NFCCard(user_id=other, card_reference="NFC-REAL0001", card_uid=CARD_UID, status="active"))
    db.commit()
    db.close()
    return dict(env=env, driver=driver, pax=pax, other=other, dh=env.user_headers(driver),
                ph=env.user_headers(pax), oh=env.user_headers(other))


def arm(s, headers=None):
    return s["env"].client.post("/api/nfc/phone/arm", headers=headers or s["ph"])


def tap(s, uid=PHONE_UID, amount=20.0, key=None):
    return s["env"].client.post("/api/nfc/pay", headers=s["dh"],
                                json={"card_uid": uid, "amount": amount, "idempotency_key": key or f"tap-{uuid.uuid4().hex}"})


def arm_row(s, arm_id):
    db = s["env"].db()
    try:
        return db.get(NfcPhoneArm, arm_id)
    finally:
        db.close()


def card_count(s):
    db = s["env"].db()
    try:
        return db.query(NFCCard).count()
    finally:
        db.close()


def test_armed_phone_tap_pays_the_armed_passenger_and_writes_no_card(scene):
    a = arm(scene).json()
    assert a["success"] and a["status"] == "armed" and a["seconds_left"] > 0
    cards_before = card_count(scene)
    with patch("app.routes.nfc_pay._send_passenger_receipt"), patch("app.routes.nfc_pay._send_driver_receipt"):
        r = tap(scene, amount=20.0)
    body = r.json()
    assert r.status_code == 200 and body["success"] is True and body["amount"] == 20.0
    assert body["passenger_name"] == "Asha"
    env = scene["env"]
    assert env.balance(scene["pax"]) == 480 and env.balance(scene["driver"]) == 20
    assert env.balance(scene["other"]) == 500
    assert card_count(scene) == cards_before          # nothing added to nfc_cards
    st = env.client.get(f"/api/nfc/phone/arm/{a['arm_id']}", headers=scene["ph"]).json()
    assert st["status"] == "paid" and st["reference"] == body["reference"] and st["amount"] == 20.0
    assert st["driver_name"] == "Rakesh Sharma"
    db = env.db()
    t = db.query(Transaction).filter(Transaction.reference == body["reference"]).one()
    assert (t.passenger_id, t.driver_id, t.payment_method, t.status) == (scene["pax"], scene["driver"], "NFC", "completed")


def test_a_second_phone_tap_cannot_reuse_the_arm(scene):
    arm(scene)
    with patch("app.routes.nfc_pay._send_passenger_receipt"), patch("app.routes.nfc_pay._send_driver_receipt"):
        assert tap(scene).json()["success"] is True
        again = tap(scene).json()
    assert again["success"] is False and again["code"] == "CARD_UNKNOWN"
    assert scene["env"].balance(scene["pax"]) == 480


def test_a_pos_retry_with_the_same_key_is_a_replay_not_a_conflict_or_second_charge(scene):
    arm(scene)
    with patch("app.routes.nfc_pay._send_passenger_receipt"), patch("app.routes.nfc_pay._send_driver_receipt"):
        first = tap(scene, key="key-aaaa-1111").json()
        retry = tap(scene, key="key-aaaa-1111").json()
    assert first["success"] and retry["success"] and retry.get("idempotent") is True
    assert retry["reference"] == first["reference"]
    assert scene["env"].balance(scene["pax"]) == 480


def test_phone_tap_without_anyone_armed_is_card_not_recognised(scene):
    r = tap(scene).json()
    assert r["success"] is False and r["code"] == "CARD_UNKNOWN"
    assert scene["env"].balance(scene["pax"]) == 500


def test_two_armed_passengers_fail_closed(scene):
    arm(scene)
    arm(scene, scene["oh"])
    r = tap(scene).json()
    assert r["success"] is False and r["code"] == "CARD_UNKNOWN"
    assert (scene["env"].balance(scene["pax"]), scene["env"].balance(scene["other"])) == (500, 500)


def test_an_expired_arm_is_not_used(scene):
    a = arm(scene).json()
    db = scene["env"].db()
    db.query(NfcPhoneArm).update({"expires_at": datetime.utcnow() - timedelta(seconds=1)})
    db.commit()
    db.close()
    assert tap(scene).json()["code"] == "CARD_UNKNOWN"
    st = scene["env"].client.get(f"/api/nfc/phone/arm/{a['arm_id']}", headers=scene["ph"]).json()
    assert st["status"] == "expired" and scene["env"].balance(scene["pax"]) == 500


def test_only_random_style_uids_are_treated_as_phones(scene):
    a = arm(scene).json()
    r = tap(scene, uid="04A1B2C3").json()      # first byte 0x04: not a random UID
    assert r["success"] is False and r["code"] == "CARD_UNKNOWN"
    assert arm_row(scene, a["arm_id"]).status == "armed"


def test_a_registered_card_is_never_taken_over_by_an_armed_phone(scene):
    arm(scene)
    with patch("app.routes.nfc_pay._send_passenger_receipt"), patch("app.routes.nfc_pay._send_driver_receipt"):
        r = tap(scene, uid=CARD_UNKNOWN_FREE_CARD(scene)).json()
    assert r["success"] is True
    env = scene["env"]
    assert env.balance(scene["other"]) == 480 and env.balance(scene["pax"]) == 500   # the card owner paid


def CARD_UNKNOWN_FREE_CARD(scene):
    return CARD_UID


def test_a_registered_card_with_a_random_style_uid_still_uses_the_card_handler(scene):
    db = scene["env"].db()
    db.add(NFCCard(user_id=scene["other"], card_reference="NFC-RANDOM01", card_uid="08DEADBE", status="active"))
    db.commit()
    db.close()
    arm(scene)
    with patch("app.routes.nfc_pay._send_passenger_receipt"), patch("app.routes.nfc_pay._send_driver_receipt"):
        r = tap(scene, uid="08DEADBE").json()
    assert r["success"] is True and scene["env"].balance(scene["other"]) == 480
    assert scene["env"].balance(scene["pax"]) == 500


def test_insufficient_balance_is_recorded_like_a_card_and_reported_to_the_app(scene):
    a = arm(scene).json()
    with patch("app.routes.nfc_pay._send_failure_notice"):
        r = tap(scene, amount=900.0).json()
    assert r["success"] is False and r["code"] == "INSUFFICIENT_BALANCE"
    st = scene["env"].client.get(f"/api/nfc/phone/arm/{a['arm_id']}", headers=scene["ph"]).json()
    assert st["status"] == "failed" and st["failure_code"] == "INSUFFICIENT_BALANCE"
    db = scene["env"].db()
    t = db.query(Transaction).filter(Transaction.status == "failed").one()
    assert t.passenger_id == scene["pax"] and t.failure_code == "INSUFFICIENT_BALANCE"
    assert scene["env"].balance(scene["pax"]) == 500


def test_cancel_and_ownership_and_roles(scene):
    a = arm(scene).json()
    assert scene["env"].client.get(f"/api/nfc/phone/arm/{a['arm_id']}", headers=scene["oh"]).status_code == 404
    c = scene["env"].client.post(f"/api/nfc/phone/arm/{a['arm_id']}/cancel", headers=scene["ph"]).json()
    assert c["status"] == "cancelled"
    assert tap(scene).json()["code"] == "CARD_UNKNOWN"
    assert arm(scene, scene["dh"]).status_code == 403          # drivers cannot arm
    assert scene["env"].client.post("/api/nfc/phone/arm").status_code == 401


def test_arming_again_replaces_the_earlier_arm(scene):
    first = arm(scene).json()
    second = arm(scene).json()
    assert arm_row(scene, first["arm_id"]).status == "cancelled" and arm_row(scene, second["arm_id"]).status == "armed"
    with patch("app.routes.nfc_pay._send_passenger_receipt"), patch("app.routes.nfc_pay._send_driver_receipt"):
        assert tap(scene).json()["success"] is True


def test_email_restriction(scene, monkeypatch):
    monkeypatch.setenv("NFC_PHONE_ALLOWED_EMAILS", "pax2@phonetest.local")
    assert arm(scene).status_code == 403
    assert arm(scene, scene["oh"]).status_code == 200
    monkeypatch.setenv("NFC_PHONE_ALLOWED_EMAILS", "*")
    assert arm(scene).status_code == 200


def test_a_frozen_wallet_cannot_arm(scene):
    db = scene["env"].db()
    from app.models import Wallet
    db.query(Wallet).filter(Wallet.user_id == scene["pax"]).update({"is_frozen": True})
    db.commit()
    db.close()
    assert arm(scene).status_code == 400
