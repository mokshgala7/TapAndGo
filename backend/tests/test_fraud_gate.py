"""
test_fraud_gate.py
──────────────────
The shared fraud gate (app/services/fraud_gate.py) and the email-OTP step-up (app/services/payment_otp.py) on
QR confirm, POST /api/nfc/pay and POST /api/wallet/pay.

Fail-closed contract under TAPGO_FRAUD_MODE=enforce: a flagged payment (ML flag, 10-minute rule, or no ML score)
moves no money and creates no completed transaction until the emailed OTP is verified; wrong x3 / expiry / cancel
record a failed payment and never move money. The default mode (shadow) changes nothing for users.
"""
import json
import logging
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tests.helpers import Env
from app.models import FraudAssessment, NFCCard, PaymentOtpChallenge, PaymentRequest, Transaction, User
from app.services import fraud_gate, payment_otp

UID = "04A2B3C4D5E681"
BACKEND = Path(__file__).resolve().parents[1]


# ── fixtures ─────────────────────────────────────────────────────────────────

class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def logs():
    h = _Capture()
    targets = [logging.getLogger(), logging.getLogger("tapgo.fraud_gate"), logging.getLogger("tapgo.fraud_risk"),
               logging.getLogger("app.services.payment_otp")]
    for lg in targets:
        lg.addHandler(h)
    yield h.lines
    for lg in targets:
        lg.removeHandler(h)


@pytest.fixture
def mail(monkeypatch):
    """Captured OTP emails (to, otp, amount, driver) and failure notices; nothing leaves the process."""
    box = {"otp": [], "failure": [], "fail_send": False}

    def fake_otp(to_email, otp, amount, driver_name, expires_minutes=5, channel="nfc", demo_for=None):
        if box.get("delay"):
            import time as _t
            _t.sleep(box["delay"])
        if box["fail_send"]:
            return False
        box["otp"].append({"to": to_email, "otp": otp, "amount": amount, "driver": driver_name, "channel": channel,
                           "demo_for": demo_for})
        return True

    def fake_failure(**kw):
        box["failure"].append(kw)
        return True

    monkeypatch.setattr(payment_otp, "send_payment_otp", fake_otp)
    import app.routes.nfc_pay as nfc_mod
    import app.routes.qr as qr_mod
    import app.utils.nfc_failure_email as nfe
    monkeypatch.setattr(nfc_mod, "send_nfc_failure_email", fake_failure)
    monkeypatch.setattr(qr_mod, "send_nfc_failure_email", fake_failure)
    monkeypatch.setattr(nfe, "send_nfc_failure_email", fake_failure)
    for mod in (nfc_mod, qr_mod):
        monkeypatch.setattr(mod, "send_ride_passenger_email", lambda **k: True)
        monkeypatch.setattr(mod, "send_ride_driver_email", lambda **k: True)
    import app.routes.wallet as wallet_mod
    monkeypatch.setattr(wallet_mod, "send_ride_passenger_email", lambda **k: True)
    monkeypatch.setattr(wallet_mod, "send_ride_driver_email", lambda **k: True)
    return box


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    monkeypatch.delenv("TAPGO_RISK_DISABLED", raising=False)


@pytest.fixture
def scene(mail):
    env = Env()
    driver_id = env.add_user("drv@gate.local", account_type="driver", balance=0, name="Ravi Driver",
                             vehicle_type="auto_rickshaw")
    other_driver = env.add_user("drv2@gate.local", account_type="driver", balance=0, name="Other Driver")
    pax_id = env.add_user("maya.pax@example.com", account_type="passenger", balance=10000, name="Asha Verma")
    db = env.db()
    try:
        db.add(NFCCard(user_id=pax_id, card_reference="NFC-GATE0001", card_uid=UID, status="active"))
        db.commit()
    finally:
        db.close()
    return {"env": env, "driver_id": driver_id, "other_driver": other_driver, "pax_id": pax_id,
            "driver_headers": env.user_headers(driver_id), "other_headers": env.user_headers(other_driver),
            "pax_headers": env.user_headers(pax_id), "mail": mail}


def add_history(scene, n=25, low=120, high=180, days=True, status="completed", created_at=None, amount=None):
    """n earlier ride payments of the passenger (one per day by default, ending yesterday)."""
    db = scene["env"].db()
    try:
        start = datetime.utcnow() - timedelta(days=n + 1)
        for i in range(n):
            db.add(Transaction(
                reference=f"H{uuid.uuid4().hex[:12]}", passenger_id=scene["pax_id"], driver_id=scene["driver_id"],
                amount=Decimal(str(amount if amount is not None else low + (i * 37) % (high - low + 1))),
                payment_method="QR", status=status, otp_verified=False, fraud_status="clear",
                transaction_type="ride_payment", idempotency_key=f"hist:{uuid.uuid4().hex}",
                created_at=created_at if created_at is not None else start + timedelta(days=i)))
        db.commit()
    finally:
        db.close()


def tap(scene, amount=150, key=None, headers=None):
    key = key or f"tap-{uuid.uuid4().hex}"
    r = scene["env"].client.post("/api/nfc/pay", json={"card_uid": UID, "amount": amount, "idempotency_key": key},
                                 headers=headers or scene["driver_headers"])
    return r, key


def nfc_verify(scene, challenge_id, otp, key, headers=None):
    return scene["env"].client.post("/api/nfc/pay/verify-otp",
                                    json={"challenge_id": challenge_id, "otp": otp, "idempotency_key": key},
                                    headers=headers or scene["driver_headers"])


def qr_create(scene, amount):
    r = scene["env"].client.post("/api/qr/create-request", json={"amount": amount}, headers=scene["driver_headers"])
    assert r.status_code == 200, r.text
    return r.json()["token"]


def qr_confirm(scene, token, key=None):
    return scene["env"].client.post(f"/api/qr/{token}/confirm", json={"idempotency_key": key or f"qr-{uuid.uuid4().hex}"},
                                    headers=scene["pax_headers"])


def qr_status(scene, token):
    return scene["env"].client.get(f"/api/qr/{token}/status", headers=scene["driver_headers"]).json()["status"]


def balances(scene):
    env = scene["env"]
    return env.balance(scene["pax_id"]), env.balance(scene["driver_id"])


def rows(scene, model, **filters):
    db = scene["env"].db()
    try:
        q = db.query(model)
        for k, v in filters.items():
            q = q.filter(getattr(model, k) == v)
        return q.all()
    finally:
        db.close()


def completed(scene):
    return [t for t in rows(scene, Transaction, passenger_id=scene["pax_id"], status="completed")
            if not (t.idempotency_key or "").startswith("hist:")]


def last_otp(scene):
    return scene["mail"]["otp"][-1]["otp"]


def wrong(otp):
    return f"{(int(otp) + 1) % 1000000:06d}"


def expire(scene, challenge_id):
    db = scene["env"].db()
    try:
        db.query(PaymentOtpChallenge).filter(PaymentOtpChallenge.public_id == challenge_id).update(
            {"expires_at": datetime.utcnow() - timedelta(seconds=1)})
        db.commit()
    finally:
        db.close()


# ── the plain 10-minute rule (no ML) ─────────────────────────────────────────

@pytest.mark.parametrize("gap,fires,elapsed", [(599, True, 599), (600, True, 600), (601, False, 601),
                                               (600.4, True, 600)])
def test_ten_minute_rule_boundaries(scene, gap, fires, elapsed):
    now = datetime(2026, 10, 14, 7, 30)
    add_history(scene, 1, created_at=now - timedelta(seconds=gap))
    db = scene["env"].db()
    try:
        assert fraud_gate.ten_minute_rule(db, scene["pax_id"], now) == (fires, elapsed)
    finally:
        db.close()


def test_ten_minute_rule_ignores_failed_rides(scene):
    now = datetime(2026, 10, 14, 7, 30)
    add_history(scene, 1, created_at=now - timedelta(hours=2))
    add_history(scene, 1, created_at=now - timedelta(minutes=5), status="failed")
    db = scene["env"].db()
    try:
        assert fraud_gate.ten_minute_rule(db, scene["pax_id"], now) == (False, 7200)
        add_history(scene, 1, created_at=now - timedelta(minutes=9))
        assert fraud_gate.ten_minute_rule(db, scene["pax_id"], now) == (True, 540)
    finally:
        db.close()


def test_ten_minute_rule_clock_skew_counts_as_recent(scene):
    now = datetime(2026, 10, 14, 7, 30)
    add_history(scene, 1, created_at=now + timedelta(seconds=4))
    db = scene["env"].db()
    try:
        assert fraud_gate.ten_minute_rule(db, scene["pax_id"], now) == (True, 0)
    finally:
        db.close()


# ── default mode changes nothing ─────────────────────────────────────────────

def test_default_mode_is_shadow_and_payments_unchanged(scene, monkeypatch):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    add_history(scene)
    r, _ = tap(scene, amount=5000)                       # would be flagged
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    r, _ = tap(scene, amount=150)                         # 10-minute repeat
    assert r.json()["success"] is True
    token = qr_create(scene, 140)
    r = qr_confirm(scene, token)
    assert r.json()["success"] is True
    assert balances(scene) == (10000 - 5000 - 150 - 140, 5290)
    assert scene["mail"]["otp"] == []
    a = rows(scene, FraudAssessment)
    assert len(a) == 3 and {x.mode for x in a} == {"shadow"} and {x.decision for x in a} == {"proceed"}
    assert a[0].model_flag is True and a[1].rule_10min is True
    for t in completed(scene):
        assert (t.otp_verified, t.fraud_status) == (False, "clear")


def test_off_mode_skips_scoring(scene, monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "off")
    add_history(scene)
    r, _ = tap(scene, amount=5000)
    assert r.json()["success"] is True
    (a,) = rows(scene, FraudAssessment)
    assert (a.mode, a.ml_status, a.decision, a.risk_score) == ("off", "off", "proceed", None)


def test_unknown_mode_is_a_loud_error_not_enforce(scene, monkeypatch):
    for bad in ("enforced", "on", "true", "ENFORCE ME"):
        monkeypatch.setenv("TAPGO_FRAUD_MODE", bad)
        with pytest.raises(fraud_gate.FraudConfigError) as e:
            fraud_gate.validate_fraud_config()
        assert "off | shadow | enforce" in str(e.value)
        with pytest.raises(fraud_gate.FraudConfigError):
            fraud_gate.fraud_mode()
    monkeypatch.delenv("TAPGO_FRAUD_MODE")
    assert fraud_gate.validate_fraud_config() == "shadow"
    monkeypatch.setenv("TAPGO_FRAUD_MODE", " Enforce ")
    monkeypatch.setenv("PAYMENT_OTP_SECRET", "a-long-private-random-value")
    assert fraud_gate.validate_fraud_config() == "enforce"


@pytest.mark.parametrize("secret", [None, "", "   ", "tapgo_super_secret_jwt_key_2026"])
def test_enforce_refuses_missing_or_dev_otp_secret(monkeypatch, secret):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    if secret is None:
        monkeypatch.delenv("PAYMENT_OTP_SECRET", raising=False)
    else:
        monkeypatch.setenv("PAYMENT_OTP_SECRET", secret)
    with pytest.raises(fraud_gate.FraudConfigError, match="PAYMENT_OTP_SECRET"):
        fraud_gate.validate_fraud_config()


@pytest.mark.parametrize("mode", ["shadow", "off"])
def test_shadow_and_off_only_warn_about_the_secret(monkeypatch, logs, mode):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", mode)
    monkeypatch.delenv("PAYMENT_OTP_SECRET", raising=False)
    assert fraud_gate.validate_fraud_config() == mode
    assert any("payment_otp_secret_not_set" in line for line in logs)


def _boot(env_extra):
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("TAPGO_FRAUD_MODE", "PAYMENT_OTP_SECRET")}
    env.update({"TAPGO_TESTING": "1", "DATABASE_URL": "sqlite:///:memory:", **env_extra})
    return subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND, env=env, capture_output=True,
                          text=True, timeout=180)


def test_app_refuses_to_start_on_bad_mode_or_unsafe_enforce():
    bad = _boot({"TAPGO_FRAUD_MODE": "enfroce"})
    assert bad.returncode != 0 and "off | shadow | enforce" in bad.stderr
    unsafe = _boot({"TAPGO_FRAUD_MODE": "enforce"})
    assert unsafe.returncode != 0 and "PAYMENT_OTP_SECRET" in unsafe.stderr
    dev = _boot({"TAPGO_FRAUD_MODE": "enforce", "PAYMENT_OTP_SECRET": "tapgo_super_secret_jwt_key_2026"})
    assert dev.returncode != 0 and "PAYMENT_OTP_SECRET" in dev.stderr
    ok = _boot({"TAPGO_FRAUD_MODE": "enforce", "PAYMENT_OTP_SECRET": "a-long-private-random-value"})
    assert ok.returncode == 0, ok.stderr[-1500:]
    assert _boot({}).returncode == 0                       # unset -> shadow, starts


# ── enforce: OTP is required and nothing moves before it ─────────────────────

def test_600s_repeat_requires_otp_with_ml_disabled(scene, enforce, monkeypatch):
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    add_history(scene, 1, created_at=datetime.utcnow() - timedelta(seconds=597))
    before = balances(scene)
    r, _ = tap(scene)
    body = r.json()
    assert body["status"] == "otp_required" and body["success"] is False, body
    assert balances(scene) == before and completed(scene) == []
    (a,) = rows(scene, FraudAssessment)
    assert a.rule_10min is True and a.ml_status == "disabled" and a.decision == "otp_required"
    assert a.elapsed_seconds in range(597, 601) and a.reasons == "rule_10min"


def test_ml_disabled_no_rule_proceeds(scene, enforce, monkeypatch):
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    add_history(scene, 1, created_at=datetime.utcnow() - timedelta(seconds=700))
    r, _ = tap(scene)
    assert r.json()["success"] is True


def test_model_unavailable_requires_otp(scene, enforce, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.services.tapgo_fraud_risk", None)
    r, _ = tap(scene)
    assert r.json()["status"] == "otp_required"
    (a,) = rows(scene, FraudAssessment)
    assert a.ml_status == "error" and a.reasons == "ml_failure:error" and a.risk_score is None


def test_scorer_exception_requires_otp(scene, enforce, monkeypatch):
    import app.services.tapgo_fraud_risk as pkg

    def boom(*a, **k):
        raise ValueError("could not convert string to float")
    monkeypatch.setattr(pkg, "assess_ride_payment", boom)
    r, _ = tap(scene)
    assert r.json()["status"] == "otp_required"


def test_flagged_5000_waits_for_otp_then_completes_exactly_once(scene, enforce):
    add_history(scene)
    before = balances(scene)
    r, key = tap(scene, amount=5000)
    body = r.json()
    assert body["status"] == "otp_required", body
    assert set(body) == {"success", "status", "challenge_id", "email_hint", "expires_in_seconds", "attempts_left",
                         "resends_left"}
    assert body["email_hint"] == "m***@e***.com" and body["expires_in_seconds"] == 300 and body["attempts_left"] == 3
    assert balances(scene) == before and completed(scene) == []
    (a,) = rows(scene, FraudAssessment)
    assert a.model_flag is True and a.decision == "otp_required" and a.challenge_id is not None
    sent = scene["mail"]["otp"]
    assert len(sent) == 1 and sent[0]["to"] == "maya.pax@example.com" and sent[0]["amount"] == 5000.0
    assert sent[0]["driver"] == "Ravi Driver"

    r = nfc_verify(scene, body["challenge_id"], last_otp(scene), key)
    assert r.json()["success"] is True and r.json()["status"] == "Completed", r.text
    assert balances(scene) == (before[0] - 5000, before[1] + 5000)
    (t,) = completed(scene)
    assert (t.otp_verified, t.fraud_status, t.payment_method, t.amount) == (True, "otp_verified", "NFC", 5000)

    # replays: same verify, same tap key -> the same completed payment, no second debit
    r2 = nfc_verify(scene, body["challenge_id"], last_otp(scene), key)
    assert r2.json()["success"] is True and r2.json().get("idempotent") is True
    r3, _ = tap(scene, amount=5000, key=key)
    assert r3.json()["success"] is True and r3.json().get("idempotent") is True
    assert balances(scene) == (before[0] - 5000, before[1] + 5000) and len(completed(scene)) == 1
    assert len(scene["mail"]["otp"]) == 1


def test_wrong_otp_three_times_cancels_without_moving_money(scene, enforce):
    add_history(scene)
    before = balances(scene)
    r, key = tap(scene, amount=5000)
    cid, otp = r.json()["challenge_id"], last_otp(scene)
    assert nfc_verify(scene, cid, wrong(otp), key).json() == {
        "success": False, "status": "otp_invalid", "attempts_left": 2, "message": "Wrong OTP, 2 attempts left."}
    assert nfc_verify(scene, cid, "abc", key).json()["attempts_left"] == 1
    r = nfc_verify(scene, cid, wrong(otp), key)
    assert r.json()["status"] == "Failed" and r.json()["code"] == "OTP_FAILED"
    # even the right code is useless now
    assert nfc_verify(scene, cid, otp, key).json()["code"] == "OTP_FAILED"
    assert balances(scene) == before and completed(scene) == []
    (f,) = rows(scene, Transaction, failure_code="OTP_FAILED")
    assert (f.status, f.amount, f.otp_verified) == ("failed", 5000, False)
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_FAILED"]


def test_expired_otp_cancels(scene, enforce):
    add_history(scene)
    before = balances(scene)
    r, key = tap(scene, amount=5000)
    cid = r.json()["challenge_id"]
    expire(scene, cid)
    r = nfc_verify(scene, cid, last_otp(scene), key)
    assert r.json()["code"] == "OTP_EXPIRED"
    assert balances(scene) == before and completed(scene) == []
    assert rows(scene, PaymentOtpChallenge)[0].status == "expired"


def test_cancel_otp(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    cid = r.json()["challenge_id"]
    r = scene["env"].client.post("/api/nfc/pay/cancel-otp", json={"challenge_id": cid}, headers=scene["driver_headers"])
    assert r.json()["code"] == "OTP_CANCELLED"
    assert nfc_verify(scene, cid, last_otp(scene), key).json()["code"] == "OTP_CANCELLED"
    assert completed(scene) == []


def test_replayed_tap_returns_same_challenge_without_new_email(scene, enforce):
    add_history(scene)
    r1, key = tap(scene, amount=5000)
    r2, _ = tap(scene, amount=5000, key=key)
    assert r2.json()["challenge_id"] == r1.json()["challenge_id"]
    assert len(scene["mail"]["otp"]) == 1 and len(rows(scene, PaymentOtpChallenge)) == 1
    r3, _ = tap(scene, amount=4000, key=key)
    assert r3.status_code == 409


def test_new_tap_supersedes_pending_challenge(scene, enforce):
    add_history(scene)
    r1, key1 = tap(scene, amount=5000)
    r2, key2 = tap(scene, amount=4500)
    assert r2.json()["status"] == "otp_required" and r2.json()["challenge_id"] != r1.json()["challenge_id"]
    old = nfc_verify(scene, r1.json()["challenge_id"], scene["mail"]["otp"][0]["otp"], key1)
    assert old.json()["code"] == "OTP_CANCELLED"
    assert [c.status for c in rows(scene, PaymentOtpChallenge)] == ["cancelled", "pending"]
    assert nfc_verify(scene, r2.json()["challenge_id"], last_otp(scene), key2).json()["success"] is True
    assert len(completed(scene)) == 1


def test_no_email_on_file_declines(scene, enforce):
    add_history(scene)
    db = scene["env"].db()
    try:
        db.query(User).filter(User.id == scene["pax_id"]).update({"email": "  "})
        db.commit()
    finally:
        db.close()
    before = balances(scene)
    r, _ = tap(scene, amount=5000)
    assert r.json()["status"] == "Failed" and r.json()["code"] == "OTP_UNAVAILABLE"
    assert balances(scene) == before and completed(scene) == [] and rows(scene, PaymentOtpChallenge) == []


def test_email_send_failure_declines(scene, enforce):
    add_history(scene)
    scene["mail"]["fail_send"] = True
    before = balances(scene)
    r, key = tap(scene, amount=5000)
    assert r.json()["code"] == "OTP_UNAVAILABLE"
    assert balances(scene) == before and completed(scene) == []
    r, _ = tap(scene, amount=5000, key=key)          # replay: same declined result
    assert r.json()["code"] == "OTP_UNAVAILABLE" and r.json().get("idempotent") is True


def test_resend_limits_and_old_code_invalid(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    cid = r.json()["challenge_id"]
    first = last_otp(scene)
    post = lambda: scene["env"].client.post("/api/nfc/pay/resend-otp", json={"challenge_id": cid},
                                            headers=scene["driver_headers"])
    assert post().status_code == 429                       # 30 s cooldown

    def age():
        db = scene["env"].db()
        try:
            db.query(PaymentOtpChallenge).filter(PaymentOtpChallenge.public_id == cid).update(
                {"last_sent_at": datetime.utcnow() - timedelta(seconds=31)})
            db.commit()
        finally:
            db.close()
    age()
    assert post().json()["resends_left"] == 1
    age()
    assert post().json()["resends_left"] == 0
    age()
    assert post().status_code == 400                       # max 2 resends
    assert len(scene["mail"]["otp"]) == 3
    assert nfc_verify(scene, cid, first, key).json()["status"] == "otp_invalid"
    assert nfc_verify(scene, cid, last_otp(scene), key).json()["success"] is True


def test_verify_bound_to_terminal_and_key(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    cid, otp = r.json()["challenge_id"], last_otp(scene)
    assert nfc_verify(scene, cid, otp, "a-different-key").status_code == 409
    assert nfc_verify(scene, cid, otp, key, headers=scene["other_headers"]).status_code == 404
    assert nfc_verify(scene, "not-a-challenge", otp, key).status_code == 404
    assert scene["env"].client.post("/api/wallet/pay/verify-otp", json={"challenge_id": cid, "otp": otp},
                                    headers=scene["pax_headers"]).status_code == 404
    assert completed(scene) == []
    assert rows(scene, PaymentOtpChallenge)[0].attempts == 0


def test_card_blocked_while_waiting_fails(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    db = scene["env"].db()
    try:
        db.query(NFCCard).filter(NFCCard.card_uid == UID).update({"status": "blocked"})
        db.commit()
    finally:
        db.close()
    before = balances(scene)
    assert nfc_verify(scene, r.json()["challenge_id"], last_otp(scene), key).json()["code"] == "CARD_BLOCKED"
    assert balances(scene) == before and completed(scene) == []


def test_otp_never_in_logs_responses_or_db(scene, enforce, logs):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    otp = last_otp(scene)
    texts = [r.text]
    texts.append(nfc_verify(scene, r.json()["challenge_id"], wrong(otp), key).text)
    texts.append(nfc_verify(scene, r.json()["challenge_id"], otp, key).text)
    token = qr_create(scene, 4800)
    rq = qr_confirm(scene, token)
    otp2 = last_otp(scene)
    texts.append(rq.text)
    texts.append(scene["env"].client.get(f"/api/qr/{token}", headers=scene["pax_headers"]).text)
    for code in (otp, otp2):
        assert not any(code in t for t in texts)
        assert not any(code in line for line in logs)
    for ch in rows(scene, PaymentOtpChallenge):
        assert ch.otp_hash not in (otp, otp2) and len(ch.otp_hash) == 64
    assert not any("maya.pax@example.com" in t for t in texts)


def test_clock_skew_and_zero_amount_failed_rows_never_break_scoring(scene, enforce):
    add_history(scene)
    add_history(scene, 1, status="failed", amount=0, created_at=datetime.utcnow() - timedelta(hours=1))
    add_history(scene, 1, created_at=datetime.utcnow() + timedelta(seconds=5))     # stamped by a fast DB clock
    tap(scene, amount=150)
    (a,) = rows(scene, FraudAssessment)
    assert a.ml_status == "scored" and a.risk_score is not None
    assert a.rule_10min is True and a.elapsed_seconds == 0   # the skewed ride really is recent


# ── QR: AwaitingOtp ──────────────────────────────────────────────────────────

def test_qr_awaiting_otp_survives_refresh_and_expiry_then_completes(scene, enforce):
    add_history(scene)
    before = balances(scene)
    token = qr_create(scene, 5000)
    r = qr_confirm(scene, token)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "otp_required", body
    assert qr_status(scene, token) == "AwaitingOtp"
    assert balances(scene) == before and completed(scene) == []
    # POS 2-minute refresh: the QR clock runs out, but the request is not expired or replaced
    db = scene["env"].db()
    try:
        db.query(PaymentRequest).filter(PaymentRequest.utr == token).update(
            {"expires_at": datetime.utcnow() - timedelta(seconds=10)})
        db.commit()
    finally:
        db.close()
    assert qr_status(scene, token) == "AwaitingOtp"
    # passenger reopens the page mid-verification
    g = scene["env"].client.get(f"/api/qr/{token}", headers=scene["pax_headers"]).json()
    assert g["payment"]["status"] == "AwaitingOtp" and g["otp"]["challenge_id"] == body["challenge_id"]
    # confirm pressed again: same challenge, no new email
    assert qr_confirm(scene, token).json()["challenge_id"] == body["challenge_id"]
    assert len(scene["mail"]["otp"]) == 1
    v = scene["env"].client.post(f"/api/qr/{token}/verify-otp",
                                 json={"challenge_id": body["challenge_id"], "otp": last_otp(scene)},
                                 headers=scene["pax_headers"])
    assert v.status_code == 200 and v.json()["success"] is True, v.text
    assert qr_status(scene, token) == "Completed"
    assert balances(scene) == (before[0] - 5000, before[1] + 5000)
    (t,) = completed(scene)
    assert (t.payment_method, t.otp_verified, t.fraud_status) == ("QR", True, "otp_verified")


def test_qr_wrong_otp_fails_request(scene, enforce):
    add_history(scene)
    before = balances(scene)
    token = qr_create(scene, 5000)
    cid = qr_confirm(scene, token).json()["challenge_id"]
    otp = last_otp(scene)
    for left in (2, 1):
        r = scene["env"].client.post(f"/api/qr/{token}/verify-otp", json={"challenge_id": cid, "otp": wrong(otp)},
                                     headers=scene["pax_headers"])
        assert r.json() == {"success": False, "status": "otp_invalid", "attempts_left": left,
                            "detail": f"Wrong code. {left} attempt{'s' if left != 1 else ''} left."}
    r = scene["env"].client.post(f"/api/qr/{token}/verify-otp", json={"challenge_id": cid, "otp": wrong(otp)},
                                 headers=scene["pax_headers"])
    assert r.status_code == 400 and r.json()["code"] == "OTP_FAILED"
    assert qr_status(scene, token) == "Failed"
    assert balances(scene) == before and completed(scene) == []


def test_qr_otp_expiry_seen_by_pos(scene, enforce):
    add_history(scene)
    token = qr_create(scene, 5000)
    cid = qr_confirm(scene, token).json()["challenge_id"]
    expire(scene, cid)
    assert qr_status(scene, token) == "Failed"
    assert rows(scene, Transaction, failure_code="OTP_EXPIRED")[0].payment_method == "QR"


def test_qr_and_nfc_decide_identically(scene, enforce, monkeypatch):
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    add_history(scene, 1, created_at=datetime.utcnow() - timedelta(seconds=120))
    r, _ = tap(scene)
    token = qr_create(scene, 150)
    q = qr_confirm(scene, token)
    assert r.json()["status"] == q.json()["status"] == "otp_required"
    a_nfc, a_qr = rows(scene, FraudAssessment)
    assert (a_nfc.channel, a_qr.channel) == ("nfc", "qr")
    assert (a_nfc.decision, a_nfc.reasons, a_nfc.rule_10min) == (a_qr.decision, a_qr.reasons, a_qr.rule_10min)
    # the NFC challenge was superseded by the QR one (one active challenge per passenger)
    assert [c.status for c in rows(scene, PaymentOtpChallenge)] == ["cancelled", "pending"]


def test_wallet_pay_otp_flow(scene, enforce):
    add_history(scene)
    before = balances(scene)
    key = f"pay-{uuid.uuid4().hex}"
    body = {"driver_id": scene["driver_id"], "fare": 5000, "idempotency_key": key}
    r = scene["env"].client.post("/api/wallet/pay", json=body, headers=scene["pax_headers"])
    assert r.json()["status"] == "otp_required", r.text
    assert balances(scene) == before
    cid = r.json()["challenge_id"]
    v = scene["env"].client.post("/api/wallet/pay/verify-otp", json={"challenge_id": cid, "otp": last_otp(scene)},
                                 headers=scene["pax_headers"])
    assert v.json()["success"] is True, v.text
    r2 = scene["env"].client.post("/api/wallet/pay", json=body, headers=scene["pax_headers"])
    assert r2.json()["idempotent"] is True
    assert balances(scene) == (before[0] - 5000, before[1] + 5000) and len(completed(scene)) == 1


def test_insufficient_balance_is_refused_before_any_otp(scene, enforce):
    add_history(scene)
    r, _ = tap(scene, amount=20000)
    assert r.json()["code"] == "INSUFFICIENT_BALANCE" and scene["mail"]["otp"] == []


# ── startup safety ───────────────────────────────────────────────────────────

def test_app_starts_without_xgboost():
    code = ("import sys, os; sys.modules['xgboost'] = None; os.environ['TAPGO_TESTING'] = '1'; "
            "os.environ['DATABASE_URL'] = 'sqlite:///:memory:'; import app.main; "
            "from app.services.tapgo_fraud_risk import load_scorer\n"
            "try:\n    load_scorer('v6')\nexcept Exception as e:\n    print(type(e).__name__)")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "ModelUnavailableError" in out.stdout


def test_requirements_pin_working_ml_versions():
    import numpy
    import pandas
    import xgboost
    reqs = (BACKEND / "requirements.txt").read_text()
    for line in ("numpy>=1.26,<3", "pandas>=2.1,<4", "xgboost>=3.1,<4"):
        assert line in reqs
    major_minor = tuple(int(x) for x in xgboost.__version__.split(".")[:2])
    assert (3, 1) <= major_minor < (4, 0), xgboost.__version__
    assert json.loads(json.dumps({"np": numpy.__version__, "pd": pandas.__version__}))


def test_pos_cancel_after_expiry_is_recorded_as_expired(scene, enforce):
    add_history(scene)
    r, _ = tap(scene, amount=5000)
    cid = r.json()["challenge_id"]
    expire(scene, cid)
    out = scene["env"].client.post("/api/nfc/pay/cancel-otp", json={"challenge_id": cid}, headers=scene["driver_headers"])
    assert out.json()["code"] == "OTP_EXPIRED"
    assert [t.failure_code for t in rows(scene, Transaction, status="failed")] == ["OTP_EXPIRED"]


# ── status lookup for the POS (timeout safety) ───────────────────────────────

def status_of(scene, key, headers=None):
    return scene["env"].client.get("/api/nfc/pay/status", params={"idempotency_key": key},
                                   headers=headers or scene["driver_headers"])


def test_status_lookup_not_found_then_otp_pending_then_completed(scene, enforce):
    add_history(scene)
    key = f"tap-{uuid.uuid4().hex}"
    assert status_of(scene, key).json() == {"status": "not_found", "transaction_ref": None, "amount": None,
                                            "failure_code": None}
    r, _ = tap(scene, amount=5000, key=key)
    assert status_of(scene, key).json()["status"] == "otp_pending"
    # the verify succeeds in the DB but the client never sees the response
    nfc_verify(scene, r.json()["challenge_id"], last_otp(scene), key)
    body = status_of(scene, key).json()
    assert body["status"] == "completed" and body["amount"] == 5000.0 and body["transaction_ref"].startswith("TXN")
    assert set(body) == {"status", "transaction_ref", "amount", "failure_code"}


def test_status_lookup_hides_other_drivers_payments(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    nfc_verify(scene, r.json()["challenge_id"], last_otp(scene), key)
    assert status_of(scene, key).json()["status"] == "completed"
    other = status_of(scene, key, headers=scene["other_headers"])
    assert other.status_code == 200 and other.json()["status"] == "not_found"
    assert status_of(scene, key, headers=scene["pax_headers"]).status_code == 403
    assert status_of(scene, "short").status_code == 400
    assert scene["env"].client.get("/api/nfc/pay/status", params={"idempotency_key": key}).status_code == 401


def test_status_lookup_reports_failures_and_expiry_without_writing(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    expire(scene, r.json()["challenge_id"])
    body = status_of(scene, key).json()
    assert (body["status"], body["failure_code"]) == ("failed", "OTP_EXPIRED")
    assert rows(scene, PaymentOtpChallenge)[0].status == "pending"      # read-only: nothing closed
    assert nfc_verify(scene, r.json()["challenge_id"], last_otp(scene), key).json()["code"] == "OTP_EXPIRED"
    assert status_of(scene, key).json()["failure_code"] == "OTP_EXPIRED"
    r2, key2 = tap(scene, amount=20000)                                 # insufficient balance: recorded failure
    assert status_of(scene, key2).json()["failure_code"] == "INSUFFICIENT_BALANCE"


# ── driver cancel of an AwaitingOtp QR request ───────────────────────────────

def test_driver_cancels_awaiting_otp_qr_request(scene, enforce):
    add_history(scene)
    before = balances(scene)
    token = qr_create(scene, 5000)
    cid = qr_confirm(scene, token).json()["challenge_id"]
    assert qr_status(scene, token) == "AwaitingOtp"
    r = scene["env"].client.post(f"/api/qr/{token}/cancel", headers=scene["driver_headers"])
    assert r.status_code == 200 and r.json()["status"] == "Failed" and r.json()["code"] == "OTP_CANCELLED", r.text
    assert qr_status(scene, token) == "Failed"
    assert balances(scene) == before and completed(scene) == []
    (f,) = rows(scene, Transaction, failure_code="OTP_CANCELLED")
    assert (f.status, f.payment_method, f.amount) == ("failed", "QR", 5000)
    assert rows(scene, PaymentOtpChallenge)[0].status == "cancelled"
    # the passenger's code is dead
    v = scene["env"].client.post(f"/api/qr/{token}/verify-otp", json={"challenge_id": cid, "otp": last_otp(scene)},
                                 headers=scene["pax_headers"])
    assert v.status_code == 400 and v.json()["code"] == "OTP_CANCELLED"
    assert balances(scene) == before
    again = scene["env"].client.post(f"/api/qr/{token}/cancel", headers=scene["driver_headers"])
    assert again.status_code == 200 and again.json()["status"] == "Failed"            # idempotent
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_CANCELLED"]


def test_driver_cannot_cancel_another_drivers_awaiting_request(scene, enforce):
    add_history(scene)
    token = qr_create(scene, 5000)
    cid = qr_confirm(scene, token).json()["challenge_id"]
    r = scene["env"].client.post(f"/api/qr/{token}/cancel", headers=scene["other_headers"])
    assert r.status_code == 404
    assert qr_status(scene, token) == "AwaitingOtp" and rows(scene, PaymentOtpChallenge)[0].status == "pending"
    v = scene["env"].client.post(f"/api/qr/{token}/verify-otp", json={"challenge_id": cid, "otp": last_otp(scene)},
                                 headers=scene["pax_headers"])
    assert v.json()["success"] is True


def test_completed_payment_cannot_be_cancelled(scene, enforce):
    add_history(scene)
    before = balances(scene)
    token = qr_create(scene, 5000)
    cid = qr_confirm(scene, token).json()["challenge_id"]
    scene["env"].client.post(f"/api/qr/{token}/verify-otp", json={"challenge_id": cid, "otp": last_otp(scene)},
                             headers=scene["pax_headers"])
    r = scene["env"].client.post(f"/api/qr/{token}/cancel", headers=scene["driver_headers"])
    assert r.status_code == 200 and r.json()["status"] == "Completed"
    assert balances(scene) == (before[0] - 5000, before[1] + 5000) and len(completed(scene)) == 1
    assert rows(scene, Transaction, failure_code="OTP_CANCELLED") == []


def test_cancel_awaiting_after_expiry_records_expired(scene, enforce):
    add_history(scene)
    token = qr_create(scene, 5000)
    cid = qr_confirm(scene, token).json()["challenge_id"]
    expire(scene, cid)
    r = scene["env"].client.post(f"/api/qr/{token}/cancel", headers=scene["driver_headers"])
    assert r.json()["status"] == "Failed"
    assert rows(scene, Transaction, failure_code="OTP_EXPIRED") and not rows(scene, Transaction, failure_code="OTP_CANCELLED")


# ── per-user enforcement allowlist (TAPGO_FRAUD_ENFORCE_USER_IDS) ────────────

UID2 = "04A2B3C4D5E699"


@pytest.fixture
def duo(scene):
    """Two otherwise identical passengers (a '69-like' and a '70-like' one) plus a bystander, each with a card,
    history and a funded wallet. scene['pax_id'] is the first; the dict gains 'pax2_id' / 'pax3_id'."""
    env = scene["env"]
    for n, uid in ((2, UID2), (3, "04A2B3C4D5E6AA")):
        pid = env.add_user(f"pax{n}@gate.local", account_type="passenger", balance=10000, name=f"Pax {n}")
        db = env.db()
        try:
            db.add(NFCCard(user_id=pid, card_reference=f"NFC-GATE000{n}", card_uid=uid, status="active"))
            db.commit()
        finally:
            db.close()
        scene[f"pax{n}_id"] = pid
    return scene


def add_history_for(scene, pid, n=25, created_at=None, status="completed"):
    db = scene["env"].db()
    try:
        start = datetime.utcnow() - timedelta(days=n + 1)
        for i in range(n):
            db.add(Transaction(
                reference=f"H{uuid.uuid4().hex[:12]}", passenger_id=pid, driver_id=scene["driver_id"],
                amount=Decimal(str(120 + (i * 37) % 61)), payment_method="QR", status=status, otp_verified=False,
                fraud_status="clear", transaction_type="ride_payment", idempotency_key=f"hist:{uuid.uuid4().hex}",
                created_at=created_at if created_at is not None else start + timedelta(days=i)))
        db.commit()
    finally:
        db.close()


def tap_uid(scene, uid, amount=150, key=None):
    key = key or f"tap-{uuid.uuid4().hex}"
    r = scene["env"].client.post("/api/nfc/pay", json={"card_uid": uid, "amount": amount, "idempotency_key": key},
                                 headers=scene["driver_headers"])
    return r, key


def completed_for(scene, pid):
    return [t for t in rows(scene, Transaction, passenger_id=pid, status="completed")
            if not (t.idempotency_key or "").startswith("hist:")]


@pytest.mark.parametrize("raw,expected", [
    ("", frozenset()), ("   ", frozenset()), ("69", {69}), ("69,70", {69, 70}), (" 69 , 70 ", {69, 70}),
    ("69,70,", {69, 70}), ("70,70", {70}),
])
def test_allowlist_parsing_valid(monkeypatch, raw, expected):
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", raw)
    assert fraud_gate.enforce_user_ids() == frozenset(expected)
    monkeypatch.delenv("TAPGO_FRAUD_ENFORCE_USER_IDS")
    assert fraud_gate.enforce_user_ids() == frozenset()


@pytest.mark.parametrize("raw", ["abc", "69,abc", "69,,70", ",69", "69;70", "69 70", "0", "-5", "6.9", "69,0", "٦٩",
                                 "69,70,,", ",", "69, ,70"])
def test_allowlist_parsing_malformed(monkeypatch, raw):
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", raw)
    with pytest.raises(fraud_gate.FraudConfigError, match="TAPGO_FRAUD_ENFORCE_USER_IDS"):
        fraud_gate.enforce_user_ids()
    monkeypatch.setenv("PAYMENT_OTP_SECRET", "a-long-private-random-value")
    with pytest.raises(fraud_gate.FraudConfigError):
        fraud_gate.validate_fraud_config()


def test_effective_mode_matrix(monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "69,70")
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    assert fraud_gate.effective_mode(69) == ("enforce", True)
    assert fraud_gate.effective_mode(70) == ("enforce", True)
    assert fraud_gate.effective_mode(71) == ("shadow", False)
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "shadow")
    assert fraud_gate.effective_mode(69) == ("enforce", True)
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "off")
    assert fraud_gate.effective_mode(69) == ("off", False) and fraud_gate.effective_mode(71) == ("off", False)
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    assert fraud_gate.effective_mode(69) == ("enforce", False)       # enforce already covers everyone
    assert fraud_gate.effective_mode(71) == ("enforce", False)


def test_allowlist_needs_a_real_otp_secret_to_validate(monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "69,70")
    for bad in (None, "", "tapgo_super_secret_jwt_key_2026"):
        if bad is None:
            monkeypatch.delenv("PAYMENT_OTP_SECRET", raising=False)
        else:
            monkeypatch.setenv("PAYMENT_OTP_SECRET", bad)
        monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
        with pytest.raises(fraud_gate.FraudConfigError, match="PAYMENT_OTP_SECRET"):
            fraud_gate.validate_fraud_config()
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "off")                      # nothing runs in off: the secret is not needed
    monkeypatch.delenv("PAYMENT_OTP_SECRET", raising=False)
    assert fraud_gate.validate_fraud_config() == "off"
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "shadow")
    monkeypatch.setenv("PAYMENT_OTP_SECRET", "a-long-private-random-value")
    assert fraud_gate.validate_fraud_config() == "shadow"


def test_app_refuses_to_start_on_bad_allowlist_or_missing_secret():
    secret = {"PAYMENT_OTP_SECRET": "a-long-private-random-value"}
    for bad in ("69,abc", "69,,70", "0", "6.9"):
        r = _boot({"TAPGO_FRAUD_ENFORCE_USER_IDS": bad, **secret})
        assert r.returncode != 0 and "TAPGO_FRAUD_ENFORCE_USER_IDS" in r.stderr, bad
    r = _boot({"TAPGO_FRAUD_ENFORCE_USER_IDS": "69,70"})                       # no secret
    assert r.returncode != 0 and "PAYMENT_OTP_SECRET" in r.stderr
    r = _boot({"TAPGO_FRAUD_ENFORCE_USER_IDS": "69,70", "PAYMENT_OTP_SECRET": "tapgo_super_secret_jwt_key_2026"})
    assert r.returncode != 0 and "PAYMENT_OTP_SECRET" in r.stderr
    assert _boot({"TAPGO_FRAUD_ENFORCE_USER_IDS": "69,70,", **secret}).returncode == 0
    assert _boot({"TAPGO_FRAUD_ENFORCE_USER_IDS": "69,70", "TAPGO_FRAUD_MODE": "off"}).returncode == 0
    assert _boot({"TAPGO_FRAUD_ENFORCE_USER_IDS": "69,x", "TAPGO_FRAUD_MODE": "off"}).returncode != 0   # still validated


def test_listed_passenger_enforced_others_stay_in_shadow_in_the_same_run(duo, monkeypatch):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")                     # only the 10-minute rule
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", f"{duo['pax_id']},")
    recent = datetime.utcnow() - timedelta(seconds=300)
    for pid in (duo["pax_id"], duo["pax2_id"]):
        add_history_for(duo, pid, n=1, created_at=recent)
    before2 = duo["env"].balance(duo["pax2_id"])
    r1, k1 = tap_uid(duo, UID)                                         # listed
    r2, _ = tap_uid(duo, UID2)                                         # not listed, identical situation
    assert r1.json()["status"] == "otp_required"
    assert r2.json()["success"] is True and r2.json()["status"] == "Completed"
    assert duo["env"].balance(duo["pax2_id"]) == before2 - 150
    a1, a2 = (rows(duo, FraudAssessment, passenger_id=duo[k])[0] for k in ("pax_id", "pax2_id"))
    assert (a1.mode, a1.enforced_by_allowlist, a1.decision) == ("enforce", True, "otp_required")
    assert (a2.mode, a2.enforced_by_allowlist, a2.decision) == ("shadow", False, "proceed")
    assert a2.rule_10min is True                                       # recorded, but shadow never blocks
    assert nfc_verify(duo, r1.json()["challenge_id"], last_otp(duo), k1).json()["success"] is True


def test_allowlist_is_ignored_in_off_and_enforce_modes(duo, monkeypatch):
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    monkeypatch.setenv("PAYMENT_OTP_SECRET", "a-long-private-random-value")
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(duo["pax_id"]))
    recent = datetime.utcnow() - timedelta(seconds=300)
    add_history_for(duo, duo["pax_id"], n=1, created_at=recent)
    add_history_for(duo, duo["pax2_id"], n=1, created_at=recent)
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "off")
    assert tap_uid(duo, UID)[0].json()["success"] is True              # listed + off -> nothing runs
    assert tap_uid(duo, UID2)[0].json()["success"] is True
    a = rows(duo, FraudAssessment, passenger_id=duo["pax_id"])[0]
    assert (a.mode, a.enforced_by_allowlist, a.ml_status, a.decision) == ("off", False, "off", "proceed")
    # a fresh recent ride for the next check
    add_history_for(duo, duo["pax_id"], n=1, created_at=datetime.utcnow() - timedelta(seconds=100))
    add_history_for(duo, duo["pax2_id"], n=1, created_at=datetime.utcnow() - timedelta(seconds=100))
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    assert tap_uid(duo, UID)[0].json()["status"] == "otp_required"
    assert tap_uid(duo, UID2)[0].json()["status"] == "otp_required"    # enforce covers everyone
    last = rows(duo, FraudAssessment, passenger_id=duo["pax_id"])[-1]
    assert (last.mode, last.enforced_by_allowlist) == ("enforce", False)


@pytest.mark.parametrize("scenario", ["repeat_600s_ml_disabled", "fare_10x", "model_unavailable"])
@pytest.mark.parametrize("which", ["pax_id", "pax2_id"])           # '69-like' and '70-like'
def test_listed_demo_passengers_need_otp_and_bystander_proceeds(duo, monkeypatch, scenario, which):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.delenv("TAPGO_RISK_DISABLED", raising=False)
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", f"{duo['pax_id']},{duo['pax2_id']}")
    uids = {"pax_id": UID, "pax2_id": UID2}
    amount = 150
    for pid in (duo["pax_id"], duo["pax2_id"], duo["pax3_id"]):
        if scenario == "repeat_600s_ml_disabled":
            add_history_for(duo, pid, n=1, created_at=datetime.utcnow() - timedelta(seconds=597))
        else:
            add_history_for(duo, pid, n=25)
    if scenario == "repeat_600s_ml_disabled":
        monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    elif scenario == "fare_10x":
        amount = 1500
    else:
        monkeypatch.setitem(sys.modules, "app.services.tapgo_fraud_risk", None)

    pid = duo[which]
    before = duo["env"].balance(pid), duo["env"].balance(duo["driver_id"])
    r, key = tap_uid(duo, uids[which], amount=amount)
    assert r.json()["status"] == "otp_required", r.text
    assert (duo["env"].balance(pid), duo["env"].balance(duo["driver_id"])) == before      # nothing moved
    assert completed_for(duo, pid) == []                                                  # nothing completed
    assert len(duo["mail"]["otp"]) == 1
    v = nfc_verify(duo, r.json()["challenge_id"], last_otp(duo), key)
    assert v.json()["success"] is True
    assert nfc_verify(duo, r.json()["challenge_id"], last_otp(duo), key).json().get("idempotent") is True
    assert duo["env"].balance(pid) == before[0] - amount and len(completed_for(duo, pid)) == 1   # exactly once
    (t,) = completed_for(duo, pid)
    assert (t.otp_verified, t.fraud_status) == (True, "otp_verified")

    # the bystander (not listed) in the same scenario proceeds unchanged, with no OTP
    r3, _ = tap_uid(duo, "04A2B3C4D5E6AA", amount=amount)
    assert r3.json()["success"] is True and r3.json()["status"] == "Completed"
    a3 = rows(duo, FraudAssessment, passenger_id=duo["pax3_id"])[0]
    assert (a3.mode, a3.enforced_by_allowlist, a3.decision) == ("shadow", False, "proceed")
    assert len(duo["mail"]["otp"]) == 1


def test_allowlist_covers_qr_wallet_and_the_status_lookup(duo, monkeypatch):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(duo["pax_id"]))
    add_history_for(duo, duo["pax_id"], n=1, created_at=datetime.utcnow() - timedelta(seconds=120))
    token = qr_create(duo, 140)
    assert qr_confirm(duo, token).json()["status"] == "otp_required"
    assert qr_status(duo, token) == "AwaitingOtp"
    rw = duo["env"].client.post("/api/wallet/pay", json={"driver_id": duo["driver_id"], "fare": 130,
                                                          "idempotency_key": f"pay-{uuid.uuid4().hex}"},
                                headers=duo["pax_headers"])
    assert rw.json()["status"] == "otp_required"                       # supersedes the QR challenge, still enforced
    r, key = tap_uid(duo, UID)
    assert r.json()["status"] == "otp_required"
    assert status_of(duo, key).json()["status"] == "otp_pending"
    nfc_verify(duo, r.json()["challenge_id"], last_otp(duo), key)
    assert status_of(duo, key).json()["status"] == "completed"


# ── the gate itself never raises on a bad amount, and a bad amount is never "proceed" in enforce ─────────

@pytest.mark.parametrize("bad", [0, -5, None, "abc", float("nan"), float("inf"), "", Decimal("0.00")])
def test_gate_treats_invalid_amounts_as_failures_not_low_risk(scene, monkeypatch, bad):
    add_history(scene)
    db = scene["env"].db()
    try:
        pax, drv = db.get(User, scene["pax_id"]), db.get(User, scene["driver_id"])
        monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
        d = fraud_gate.evaluate_payment(db, pax, drv, bad, datetime.utcnow(), "k-bad", "nfc")
        assert d["action"] == "otp_required" and d["ml_status"] == "invalid_input" and d["risk_score"] is None
        assert "ml_failure:invalid_input" in d["reasons"]
        monkeypatch.setenv("TAPGO_FRAUD_MODE", "shadow")
        d = fraud_gate.evaluate_payment(db, pax, drv, bad, datetime.utcnow(), "k-bad2", "nfc")
        assert d["action"] == "proceed" and d["would_require_otp"] is True
        a = db.query(FraudAssessment).filter(FraudAssessment.idempotency_key == "k-bad").one()
        assert float(a.amount) == 0.0 and a.ml_status == "invalid_input"
    finally:
        db.close()


# ── history rows without a driver (seeded / demo ledger rows) are still used ─────────────────────────────

def test_history_rows_without_a_driver_are_used_not_dropped(scene, enforce):
    db = scene["env"].db()
    try:
        start = datetime.utcnow() - timedelta(days=40)
        for i in range(30):
            db.add(Transaction(reference=f"DEM{uuid.uuid4().hex[:10]}", passenger_id=scene["pax_id"], driver_id=None,
                               amount=Decimal(str(120 + (i * 37) % 61)), payment_method="NFC", status="completed",
                               otp_verified=False, fraud_status="clear", transaction_type="ride_payment",
                               idempotency_key=None, created_at=start + timedelta(days=i)))
        db.commit()
        from app.services.fraud_risk_shadow import run_assessment
        pax, drv = db.get(User, scene["pax_id"]), db.get(User, scene["driver_id"])
        a, _ = run_assessment(db, pax.id, drv, Decimal("150"), datetime.utcnow(), "k1", mode="enforce")
        assert a.status == "scored" and a.risk["history"]["prior_completed_rides"] == 30      # not 0
        assert a.risk["passenger_fare_anomaly"]["history_stage"] == "developing"
        assert "new_passenger_no_completed_history" not in a.risk["warnings"]
    finally:
        db.close()
    # a normal fare is fine; a 10x fare is flagged against that driver-less history
    r, _ = tap(scene, amount=150)
    assert r.json()["success"] is True
    add = rows(scene, FraudAssessment)[-1]
    assert add.ml_status == "scored" and add.model_flag is False
    r2, _ = tap(scene, amount=1700)
    assert r2.json()["status"] == "otp_required"
    assert rows(scene, FraudAssessment)[-1].model_flag is True



# ── demo OTP redirect (TAPGO_OTP_DEMO_REDIRECT_EMAIL) ────────────────────────────────────────────────────

REDIRECT = "demo.inbox@example.org"


def _dump_tables(scene):
    """Every column of the fraud tables as text, to prove an address is never stored there."""
    out = []
    for model in (FraudAssessment, PaymentOtpChallenge):
        for row in rows(scene, model):
            out.append(" ".join(str(getattr(row, c.name)) for c in model.__table__.columns))
    return "\n".join(out)


def test_redirect_applies_only_to_listed_users_and_is_hidden(duo, monkeypatch, logs):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(duo["pax_id"]))
    monkeypatch.setenv("TAPGO_OTP_DEMO_REDIRECT_EMAIL", REDIRECT)
    add_history_for(duo, duo["pax_id"], n=1, created_at=datetime.utcnow() - timedelta(seconds=200))
    r, key = tap_uid(duo, UID)
    assert r.json()["status"] == "otp_required"
    sent = duo["mail"]["otp"][-1]
    assert sent["to"] == REDIRECT and sent["demo_for"] == duo["pax_id"]
    assert r.json()["email_hint"] == "d***@e***.org"                       # hint of the address actually used
    v = nfc_verify(duo, r.json()["challenge_id"], wrong(sent["otp"]), key)
    done = nfc_verify(duo, r.json()["challenge_id"], sent["otp"], key)
    assert done.json()["success"] is True
    everything = r.text + v.text + done.text + _dump_tables(duo) + "\n".join(logs)
    assert REDIRECT not in everything and "demo.inbox" not in everything
    assert "pax@" not in everything and "maya.pax" not in everything       # nor the passenger's own address

    # the redirect never reaches a user who is not in the list: with everyone enforced it is ignored
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    add_history_for(duo, duo["pax2_id"], n=1, created_at=datetime.utcnow() - timedelta(seconds=100))
    r2, _ = tap_uid(duo, UID2)
    assert r2.json()["status"] == "otp_required"
    assert duo["mail"]["otp"][-1]["to"] == "pax2@gate.local" and duo["mail"]["otp"][-1]["demo_for"] is None
    assert r2.json()["email_hint"] == "p***@g***.local"


def test_redirect_ignored_when_mode_off_and_when_nobody_is_listed(duo, monkeypatch):
    from app.services import fraud_gate as fg
    monkeypatch.setenv("TAPGO_OTP_DEMO_REDIRECT_EMAIL", REDIRECT)
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(duo["pax_id"]))
    pax = type("P", (), {"id": duo["pax_id"], "email": "own@x.org"})()
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "off")
    assert fg.otp_recipient(pax) == ("own@x.org", False)
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    assert fg.otp_recipient(pax) == ("own@x.org", False)
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "shadow")
    assert fg.otp_recipient(pax) == (REDIRECT, True)
    other = type("P", (), {"id": duo["pax_id"] + 99, "email": "other@x.org"})()
    assert fg.otp_recipient(other) == ("other@x.org", False)
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "")
    assert fg.otp_recipient(pax) == ("own@x.org", False)


@pytest.mark.parametrize("bad", ["not-an-email", "a@b", "a@b.com,c@d.com", "a b@c.com", "@x.com", "x@.com", "a@b.c"])
def test_invalid_redirect_value_stops_startup_without_echoing_it(bad):
    r = _boot({"TAPGO_OTP_DEMO_REDIRECT_EMAIL": bad})
    assert r.returncode != 0 and "TAPGO_OTP_DEMO_REDIRECT_EMAIL" in r.stderr
    assert bad not in r.stderr.replace("TAPGO_OTP_DEMO_REDIRECT_EMAIL", "")


def test_valid_redirect_starts_with_a_warning_that_hides_the_address():
    secret = {"PAYMENT_OTP_SECRET": "a-long-private-random-value"}
    r = _boot({"TAPGO_OTP_DEMO_REDIRECT_EMAIL": REDIRECT, "TAPGO_FRAUD_ENFORCE_USER_IDS": "4,69,70", **secret})
    assert r.returncode == 0, r.stderr[-800:]
    assert REDIRECT not in r.stdout + r.stderr
    assert _boot({"TAPGO_OTP_DEMO_REDIRECT_EMAIL": REDIRECT, "TAPGO_FRAUD_MODE": "off"}).returncode == 0
    assert _boot({"TAPGO_OTP_DEMO_REDIRECT_EMAIL": REDIRECT}).returncode == 0       # nobody listed: ignored


def test_withdrawal_and_other_mail_is_never_redirected(monkeypatch):
    from app.utils import email_service as es
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "shadow")
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "1")
    monkeypatch.setenv("TAPGO_OTP_DEMO_REDIRECT_EMAIL", REDIRECT)
    seen = []
    monkeypatch.setattr(es, "send_email", lambda **kw: seen.append(kw) or True)
    es.send_withdrawal_otp("user@x.org", "123456", 10.0)
    assert seen[0]["to_email"] == "user@x.org" and not seen[0].get("redact_recipient")


def test_redirect_address_is_redacted_from_logs_and_the_email_log(monkeypatch, logs):
    from app.utils import email_service as es
    rec = []

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def add(self, o): rec.append(o)
        def commit(self): pass
    monkeypatch.setattr(es, "SessionLocal", lambda: FakeSession())
    es.send_email(REDIRECT, "s", "<p>x</p>", email_type="payment_otp", redact_recipient=True)
    assert REDIRECT not in "\n".join(logs) and all(o.recipient == "<demo-redirect>" for o in rec)
    es.send_email(REDIRECT, "s", "<p>x</p>", email_type="payment_otp")                  # control: normal mail still logs it
    assert any(REDIRECT in line for line in logs) and rec[-1].recipient == REDIRECT


# ── hardening: slow mail, gate errors, balance guard ─────────────────────────────────────────────────────

def test_slow_email_provider_declines_an_enforced_payment_quickly(scene, enforce, monkeypatch):
    import time
    monkeypatch.setattr(payment_otp, "OTP_EMAIL_TIMEOUT_S", 0.3)
    scene["mail"]["delay"] = 2.0
    add_history(scene)
    before = balances(scene)
    t0 = time.time()
    r, _ = tap(scene, amount=5000)
    assert time.time() - t0 < 1.6, "the request waited for the slow provider"
    assert r.json()["status"] == "Failed" and r.json()["code"] == "OTP_UNAVAILABLE"
    assert balances(scene) == before and completed(scene) == []


def test_gate_error_fails_closed_for_enforced_and_open_for_shadow(duo, monkeypatch):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(duo["pax_id"]))

    def boom(*a, **k):
        raise RuntimeError("database hiccup")
    monkeypatch.setattr(fraud_gate, "ten_minute_rule", boom)
    before2 = duo["env"].balance(duo["pax2_id"])
    r1, _ = tap_uid(duo, UID)                                # listed -> OTP, never an approval, never a 500
    r2, _ = tap_uid(duo, UID2)                               # not listed -> unchanged payment
    assert r1.status_code == 200 and r1.json()["status"] == "otp_required"
    assert r2.status_code == 200 and r2.json()["success"] is True
    assert duo["env"].balance(duo["pax2_id"]) == before2 - 150 and completed_for(duo, duo["pax_id"]) == []


def test_listed_user_below_the_fare_is_declined_before_any_otp_on_qr_and_wallet(scene, enforce):
    add_history(scene)
    db = scene["env"].db()
    try:
        from app.models import Wallet
        db.query(Wallet).filter(Wallet.user_id == scene["pax_id"]).update({"balance": Decimal("10")}); db.commit()
    finally:
        db.close()
    token = qr_create(scene, 5000)
    q = qr_confirm(scene, token)
    assert q.status_code == 400 and q.json()["code"] == "insufficient_balance"
    assert qr_status(scene, token) == "Pending"
    w = scene["env"].client.post("/api/wallet/pay", json={"driver_id": scene["driver_id"], "fare": 5000,
                                                          "idempotency_key": f"pay-{uuid.uuid4().hex}"},
                                 headers=scene["pax_headers"])
    assert w.status_code == 400 and "Insufficient" in w.json()["detail"]
    n, _ = tap(scene, amount=5000)
    assert n.json()["code"] == "INSUFFICIENT_BALANCE"
    assert scene["mail"]["otp"] == []                         # no email spam


# ── attempt limit is enforced atomically and survives (stored in the database) ───────────────────────────

def test_attempt_slots_are_reserved_before_the_comparison(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    cid, real = r.json()["challenge_id"], last_otp(scene)
    for left in (2, 1):
        assert nfc_verify(scene, cid, wrong(real), key).json()["attempts_left"] == left
    # the third (last) slot is still usable by the CORRECT code
    assert nfc_verify(scene, cid, real, key).json()["success"] is True
    assert rows(scene, PaymentOtpChallenge)[0].attempts == 3 and len(completed(scene)) == 1


def test_attempts_never_exceed_the_limit_and_the_right_code_is_then_refused(scene, enforce):
    add_history(scene)
    r, key = tap(scene, amount=5000)
    cid, real = r.json()["challenge_id"], last_otp(scene)
    for _ in range(3):
        nfc_verify(scene, cid, wrong(real), key)
    for _ in range(3):                                    # extra guesses after the lock-out must not even be counted
        assert nfc_verify(scene, cid, real, key).json()["code"] == "OTP_FAILED"
    ch = rows(scene, PaymentOtpChallenge)[0]
    assert (ch.status, ch.attempts) == ("failed", 3) and completed(scene) == []


def test_root_and_backend_requirements_stay_identical():
    """The root Procfile/nixpacks.toml build from the ROOT requirements.txt (--app-dir backend): it must carry the same
    pins (numpy/pandas/xgboost) as backend/requirements.txt or the model silently cannot load there."""
    root = BACKEND.parent / "requirements.txt"
    if root.exists():
        assert root.read_text() == (BACKEND / "requirements.txt").read_text()


# ── a low-spend commuter (about 100 small driver-less demo rides, usual fare ~Rs35) ─────────────────────────
# demo/synthetic-derived fixtures, not real-world performance. The clock is frozen so the scores are deterministic.

COMMUTER_FARES = [35, 36, 34, 35, 37, 33, 35, 38, 36, 34, 35, 32, 35, 36, 39, 35, 34, 37, 35, 40]


def freeze_clock(monkeypatch, at):
    import app.routes.nfc_pay as nfc_mod
    import app.routes.qr as qr_mod
    import app.routes.wallet as wal_mod

    class Frozen(datetime):
        @classmethod
        def utcnow(cls):
            return at
    for m in (nfc_mod, qr_mod, wal_mod):
        monkeypatch.setattr(m, "datetime", Frozen)


def add_commuter_history(scene, pid, today):
    """100 completed Rs32-40 rides without a driver (morning and evening, ~2 a day) ending the day before `today`,
    plus 3 rides earlier today (35 at -30 min, 30 at -27 min, 35 at -15 min) like the demo sequence."""
    db = scene["env"].db()
    try:
        n = 0
        day = today.replace(hour=0, minute=0) - timedelta(days=1)
        while n < 100:
            for hour in (12, 3):                                   # 17:30 and 09:00 IST
                if n < 100:
                    db.add(Transaction(reference=f"DEM{pid}x{n}", passenger_id=pid, driver_id=None,
                                       amount=Decimal(COMMUTER_FARES[n % len(COMMUTER_FARES)]), payment_method="NFC" if n % 3 else "QR",
                                       status="completed", otp_verified=False, fraud_status="clear", transaction_type="ride_payment",
                                       idempotency_key=None, created_at=day.replace(hour=hour, minute=7 * (n % 7))))
                    n += 1
            day -= timedelta(days=1)
        for tag, t, amt in (("a", -30 * 60, 35), ("b", -27 * 60, 30), ("c", -15 * 60, 35)):
            db.add(Transaction(reference=f"DEM{pid}s{tag}", passenger_id=pid, driver_id=None, amount=Decimal(amt), payment_method="NFC",
                               status="completed", otp_verified=False, fraud_status="clear", transaction_type="ride_payment",
                               idempotency_key=None, created_at=today + timedelta(seconds=t)))
        db.commit()
    finally:
        db.close()


def test_commuter_flagged_fare_needs_otp_normal_fare_does_not_and_bystander_proceeds(duo, monkeypatch):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.delenv("TAPGO_RISK_DISABLED", raising=False)
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(duo["pax_id"]))
    today = datetime(2026, 10, 30, 8, 30)                          # 14:00 IST
    freeze_clock(monkeypatch, today)
    for pid in (duo["pax_id"], duo["pax2_id"]):
        add_commuter_history(duo, pid, today)
    before = duo["env"].balance(duo["pax_id"]), duo["env"].balance(duo["driver_id"])
    done_before = len(completed_for(duo, duo["pax_id"]))

    # a normal Rs35 ride: scored, not flagged, no OTP, paid
    r0, _ = tap_uid(duo, UID, amount=35)
    assert r0.json()["success"] is True
    a0 = rows(duo, FraudAssessment, passenger_id=duo["pax_id"])[-1]
    assert a0.ml_status == "scored" and a0.model_flag is False and a0.rule_10min is False and a0.decision == "proceed"
    # move on: the next ride is Rs80, more than double the usual fare, after four rides inside the last hour
    r, key = tap_uid(duo, UID, amount=80)
    assert r.json()["status"] == "otp_required", r.text
    a = rows(duo, FraudAssessment, passenger_id=duo["pax_id"])[-1]
    assert a.model_flag is True and a.ml_status == "scored" and float(a.risk_score) >= 0.0633
    assert duo["env"].balance(duo["pax_id"]) == before[0] - 35                      # only the first (normal) ride moved money
    assert len(completed_for(duo, duo["pax_id"])) == done_before + 1                  # the flagged one is NOT completed
    cid = r.json()["challenge_id"]
    assert nfc_verify(duo, cid, wrong(last_otp(duo)), key).json()["attempts_left"] == 2
    assert duo["env"].balance(duo["pax_id"]) == before[0] - 35
    assert nfc_verify(duo, cid, last_otp(duo), key).json()["success"] is True
    assert duo["env"].balance(duo["pax_id"]) == before[0] - 35 - 80 and len(completed_for(duo, duo["pax_id"])) == done_before + 2

    # the identical passenger who is NOT listed pays the same Rs80 untouched (shadow records it only)
    r2, _ = tap_uid(duo, UID2, amount=80)
    assert r2.json()["success"] is True and r2.json()["status"] == "Completed"
    a2 = rows(duo, FraudAssessment, passenger_id=duo["pax2_id"])[-1]
    assert (a2.mode, a2.decision, a2.model_flag) == ("shadow", "proceed", True)
