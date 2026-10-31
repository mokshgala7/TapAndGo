"""
The 10-minute rule is mandatory: a passenger who completed a ride payment less than ten minutes ago needs the
emailed OTP for the next one, on every channel (card/phone tap, QR, wallet pay), for every passenger, whatever
TAPGO_FRAUD_MODE says and without any allowlist. Nothing moves before the right code.
"""
import uuid
from datetime import datetime

import pytest

from tests.test_fraud_gate import (  # noqa: F401  (fixtures and helpers shared with the fraud gate tests)
    balances, completed, expire, last_otp, mail, nfc_verify, qr_confirm, qr_create, qr_pos_verify, rows, scene, tap,
    wallet_pos_verify, wrong,
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
    v = qr_pos_verify(scene, t2, last_otp(scene))               # the code is typed on the POS, not on the website
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


# ── every ordered pair of the four payment modes is ONE stream ───────────────────────────────────────────

import itertools
from datetime import timedelta

PHONE_UID = "08A1B2C3"
APP = {"X-Tapgo-Client": "mobile-app"}
MODES = ["nfc", "qr", "phone", "wallet"]


def start_payment(scene, mode, amount=50):
    """Begin one payment in `mode`. Returns (body, finish) where finish(otp) enters the code the way that mode does
    (always on the POS) and returns the response body."""
    env, client = scene["env"], scene["env"].client
    if mode in ("nfc", "phone"):
        key = f"{mode}-{uuid.uuid4().hex}"
        uid = PHONE_UID if mode == "phone" else "04A2B3C4D5E681"
        if mode == "phone":
            assert client.post("/api/nfc/phone/arm", headers={**scene["pax_headers"], **APP}).status_code == 200
        body = client.post("/api/nfc/pay", json={"card_uid": uid, "amount": amount, "idempotency_key": key},
                           headers=scene["driver_headers"]).json()
        return body, lambda otp: nfc_verify(scene, body.get("challenge_id"), otp, key).json()
    if mode == "qr":
        token = qr_create(scene, amount)
        body = qr_confirm(scene, token).json()
        return body, lambda otp: qr_pos_verify(scene, token, otp).json()
    key = f"wallet-{uuid.uuid4().hex}"
    body = client.post("/api/wallet/pay", headers=scene["pax_headers"], json={
        "driver_id": scene["driver_id"], "fare": amount, "payment_method": "QR", "idempotency_key": key}).json()
    return body, lambda otp: wallet_pos_verify(scene, body.get("challenge_id"), otp).json()


@pytest.fixture(params=["outside_list", "inside_list"])
def party(request, scene, monkeypatch):
    """A passenger who is not in TAPGO_FRAUD_ENFORCE_USER_IDS, and the same passenger once listed (ids are never
    hard-coded: the list is built from the test passenger's id)."""
    if request.param == "inside_list":
        monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(scene["pax_id"]))
    return request.param


@pytest.mark.parametrize("a,b", list(itertools.product(MODES, MODES)))
@pytest.mark.parametrize("gap", [599, 600, 601])
def test_any_mode_then_any_mode_within_600_seconds_needs_the_otp(scene, party, monkeypatch, a, b, gap):
    # A: the first payment completes (nothing earlier, small amount).
    body_a, _ = start_payment(scene, a)
    assert body_a["success"] is True, body_a
    db = scene["env"].db()
    first_at = db.query(Transaction.created_at).filter(
        Transaction.passenger_id == scene["pax_id"], Transaction.status == "completed").one()[0]
    db.close()

    # B is judged exactly `gap` seconds after A completed (the gate's clock is pinned for the rule only).
    real = fraud_gate.ten_minute_rule
    monkeypatch.setattr(fraud_gate, "ten_minute_rule",
                        lambda db, pid, now, exclude_key=None: real(db, pid, first_at + timedelta(seconds=gap), exclude_key))
    before = balances(scene)
    body_b, finish = start_payment(scene, b)
    if gap <= 600:
        assert body_b.get("status") == "otp_required", (a, b, gap, party, body_b)
        assert balances(scene) == before                                      # no wallet change before a verified code
        assert len(scene["mail"]["otp"]) == 1
        done = finish(last_otp(scene))
        assert done["success"] is True, done
        assert balances(scene) == (before[0] - 50, before[1] + 50)
    else:
        assert body_b["success"] is True, (a, b, gap, party, body_b)
        assert scene["mail"]["otp"] == []
        assert balances(scene) == (before[0] - 50, before[1] + 50)


def test_a_payment_waiting_for_its_code_does_not_start_the_window(scene, monkeypatch):
    first, finish = start_payment(scene, "nfc", 50)
    assert first["success"] is True
    # second one waits for its code (rule fires); a third attempt made while it waits is judged against the FIRST
    second, _ = start_payment(scene, "nfc", 60)
    assert second["status"] == "otp_required"
    db = scene["env"].db()
    pending_txns = db.query(Transaction).filter(Transaction.status == "completed").count()
    db.close()
    assert pending_txns == 1                                                    # the waiting payment is not a completed one


def test_failed_and_expired_attempts_do_not_start_the_window(scene):
    now = datetime(2026, 10, 14, 7, 30)
    add_history_rows = __import__("tests.test_fraud_gate", fromlist=["add_history"]).add_history
    add_history_rows(scene, 1, created_at=now - timedelta(minutes=2), status="failed")
    add_history_rows(scene, 1, created_at=now - timedelta(minutes=3), status="cancelled")
    db = scene["env"].db()
    try:
        assert fraud_gate.ten_minute_rule(db, scene["pax_id"], now) == (False, None)
    finally:
        db.close()


# ── the rule for passengers outside the list: mail failure, balance order, new-account policy ───────────

def pin_gap(monkeypatch, scene, gap):
    db = scene["env"].db()
    first_at = db.query(Transaction.created_at).filter(
        Transaction.passenger_id == scene["pax_id"], Transaction.status == "completed").order_by(
        Transaction.created_at.desc()).first()[0]
    db.close()
    real = fraud_gate.ten_minute_rule
    monkeypatch.setattr(fraud_gate, "ten_minute_rule",
                        lambda db, pid, now, exclude_key=None: real(db, pid, first_at + timedelta(seconds=gap), exclude_key))


@pytest.mark.parametrize("mode", MODES)
def test_an_otp_that_cannot_be_sent_declines_the_payment(scene, monkeypatch, mode):
    assert start_payment(scene, mode)[0]["success"] is True
    pin_gap(monkeypatch, scene, 120)
    scene["mail"]["fail_send"] = True
    before = balances(scene)
    body, _ = start_payment(scene, mode)
    assert body.get("success") is False and body.get("status") != "otp_required", body
    assert balances(scene) == before and scene["mail"]["otp"] == []


@pytest.mark.parametrize("mode", MODES)
def test_insufficient_balance_is_answered_before_any_otp_email(scene, monkeypatch, mode):
    assert start_payment(scene, mode)[0]["success"] is True
    pin_gap(monkeypatch, scene, 120)
    before = balances(scene)
    body, _ = start_payment(scene, mode, amount=20000)
    assert body.get("success") is not True and body.get("status") != "otp_required", body
    assert scene["mail"]["otp"] == [] and balances(scene) == before


@pytest.mark.parametrize("mode", ["nfc", "qr", "wallet"])
def test_new_account_amount_policy_still_applies_and_the_rule_adds_to_it(scene, monkeypatch, mode):
    monkeypatch.setenv("TAPGO_NEWUSER_POLICY", "enforce")
    # above Rs 300 -> code needed even for the first payment
    big, _ = start_payment(scene, mode, amount=301)
    assert big.get("status") == "otp_required", big
    # up to and including Rs 300 -> allowed (no earlier payment)
    ok, _ = start_payment(scene, mode, amount=300)
    assert ok["success"] is True, ok
    # a small payment right after: the 10-minute rule asks for the code although the amount is small
    pin_gap(monkeypatch, scene, 300)
    small, _ = start_payment(scene, mode, amount=10)
    assert small.get("status") == "otp_required", small
