"""
test_failure_email_notifications.py
───────────────────────────────────
Failure emails to the passenger when a ride payment fails (QR confirm, POST /api/nfc/pay, POST /api/wallet/pay).

Already present before this change (verified here, not re-implemented): the OTP failures - wrong code used up,
cancelled, expired - email the passenger once per channel through payment_otp -> send_nfc_failure_email.
Added by this change: the insufficient-balance decline of QR confirm and wallet pay, which returned an error and sent
nothing. Those declines write no transaction, so they are deduplicated on a reference derived from the idempotency key.
Mail delivery is always mocked; no real email is sent.
"""
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

import app.utils.nfc_failure_email as nfe
from app.models import EmailLog, User, Wallet
from tests.test_fraud_gate import (  # noqa: F401 - fixtures are imported by name so pytest finds them here
    add_history, balances, enforce, expire, last_otp, mail, nfc_verify, qr_confirm, qr_create, qr_status,
    scene, tap, wrong,
)

_REAL_SEND = nfe.send_nfc_failure_email          # the `mail` fixture replaces the module attribute during a test


class InlinePool:
    """Runs the worker-pool job in the calling thread so a test can assert on it right away."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def fresh_claims(monkeypatch):
    nfe._claims.clear()
    monkeypatch.setattr(nfe, "_POOL", InlinePool())
    yield
    nfe._claims.clear()


def set_balance(scene, amount):
    db = scene["env"].db()
    try:
        db.query(Wallet).filter(Wallet.user_id == scene["pax_id"]).update({"balance": Decimal(str(amount))})
        db.commit()
    finally:
        db.close()


def set_email(scene, email):
    db = scene["env"].db()
    try:
        db.query(User).filter(User.id == scene["pax_id"]).update({"email": email})
        db.commit()
    finally:
        db.close()


def wallet_pay(scene, fare=5000, key=None):
    key = key or f"pay-{uuid.uuid4().hex}"
    r = scene["env"].client.post("/api/wallet/pay", json={"driver_id": scene["driver_id"], "fare": fare,
                                                           "idempotency_key": key}, headers=scene["pax_headers"])
    return r, key


def wallet_verify(scene, cid, otp):
    return scene["env"].client.post("/api/wallet/pos/verify-otp", json={"challenge_id": cid, "otp": otp},
                                    headers=scene["driver_headers"])


def wallet_cancel(scene, cid):
    return scene["env"].client.post("/api/wallet/pay/cancel-otp", json={"challenge_id": cid}, headers=scene["pax_headers"])


def qr_verify(scene, token, cid, otp):
    return scene["env"].client.post(f"/api/qr/{token}/pos/verify-otp", json={"otp": otp}, headers=scene["driver_headers"])


def qr_cancel_otp(scene, token, cid):
    return scene["env"].client.post(f"/api/qr/{token}/cancel-otp", json={"challenge_id": cid}, headers=scene["pax_headers"])


def nfc_cancel(scene, cid):
    return scene["env"].client.post("/api/nfc/pay/cancel-otp", json={"challenge_id": cid}, headers=scene["driver_headers"])


def codes(scene):
    return [n["code"] for n in scene["mail"]["failure"]]


# ── OTP failures: already emailed once per channel; nothing while attempts remain ───────────────────────

def start(scene, channel):
    """Open an OTP challenge for a flagged 5000 payment. Returns (challenge_id, key, token)."""
    add_history(scene)
    if channel == "nfc":
        r, key = tap(scene, amount=5000)
        return r.json()["challenge_id"], key, None
    if channel == "qr":
        token = qr_create(scene, 5000)
        return qr_confirm(scene, token).json()["challenge_id"], None, token
    r, key = wallet_pay(scene)
    return r.json()["challenge_id"], key, None


def verify(scene, channel, cid, otp, key, token):
    if channel == "nfc":
        return nfc_verify(scene, cid, otp, key)
    if channel == "qr":
        return qr_verify(scene, token, cid, otp)
    return wallet_verify(scene, cid, otp)


def cancel(scene, channel, cid, token):
    return {"nfc": lambda: nfc_cancel(scene, cid), "qr": lambda: qr_cancel_otp(scene, token, cid),
            "wallet": lambda: wallet_cancel(scene, cid)}[channel]()


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_no_failure_email_when_the_otp_is_requested_or_while_attempts_remain(scene, enforce, channel):
    cid, key, token = start(scene, channel)
    assert len(scene["mail"]["otp"]) == 1 and codes(scene) == []            # the OTP email covers the request
    otp = last_otp(scene)
    verify(scene, channel, cid, wrong(otp), key, token)
    verify(scene, channel, cid, wrong(otp), key, token)
    assert codes(scene) == []                                                # two wrong codes, one attempt left
    assert verify(scene, channel, cid, otp, key, token).json().get("success") is True   # the right code still works
    assert codes(scene) == []


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_wrong_code_used_up_sends_exactly_one_email_even_when_repeated(scene, enforce, channel):
    cid, key, token = start(scene, channel)
    otp = last_otp(scene)
    for _ in range(3):
        verify(scene, channel, cid, wrong(otp), key, token)
    assert codes(scene) == ["OTP_FAILED"]
    for _ in range(3):                                                       # repeated verify / cancel / resend
        verify(scene, channel, cid, wrong(otp), key, token)
        verify(scene, channel, cid, otp, key, token)
        cancel(scene, channel, cid, token)
    assert codes(scene) == ["OTP_FAILED"]


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_cancel_after_a_wrong_code_sends_one_email_and_repeats_send_none(scene, enforce, channel):
    cid, key, token = start(scene, channel)
    verify(scene, channel, cid, wrong(last_otp(scene)), key, token)         # what the POS sketch does: one wrong code ...
    assert codes(scene) == []
    cancel(scene, channel, cid, token)                                       # ... then /cancel-otp
    cancel(scene, channel, cid, token)
    assert codes(scene) == ["OTP_CANCELLED"]


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_expired_code_sends_one_email(scene, enforce, channel):
    cid, key, token = start(scene, channel)
    expire(scene, cid)
    verify(scene, channel, cid, last_otp(scene), key, token)
    verify(scene, channel, cid, last_otp(scene), key, token)
    cancel(scene, channel, cid, token)
    assert codes(scene) == ["OTP_EXPIRED"]


def test_no_failure_email_when_the_passenger_has_no_email_and_the_payment_is_declined(scene, enforce):
    add_history(scene)
    set_email(scene, "")
    r, _ = tap(scene, amount=5000)
    assert r.json()["code"] == "OTP_UNAVAILABLE" and codes(scene) == [] and scene["mail"]["otp"] == []


# ── insufficient balance on QR confirm and wallet pay (the emails added by this change) ──────────────────

@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_qr_insufficient_balance_sends_one_email_and_no_otp(scene, monkeypatch, mode):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", mode)
    token = qr_create(scene, 5000)
    set_balance(scene, 100)
    r = qr_confirm(scene, token, key="qr-short-0001")
    assert r.status_code == 400 and r.json()["code"] == "insufficient_balance"     # response unchanged
    assert scene["mail"]["otp"] == []
    (n,) = scene["mail"]["failure"]
    assert n["code"] == "INSUFFICIENT_BALANCE" and n["payment_mode"] == "QR" and n["fare"] == 5000.0
    assert n["time_zone"] == "IST" and n["reference_label"] == "Reference" and n["driver_name"] == "Ravi Driver"
    assert "wallet_balance" not in n and n["to_email"] == "maya.pax@example.com"
    assert balances(scene)[0] == 100 and qr_status(scene, token) == "Pending"        # nothing charged, request still usable


def test_qr_insufficient_balance_retries_and_double_submits_send_no_duplicate(scene):
    token = qr_create(scene, 5000)
    set_balance(scene, 100)
    for _ in range(4):
        assert qr_confirm(scene, token, key="qr-short-0002").json()["code"] == "insufficient_balance"
    assert codes(scene) == ["INSUFFICIENT_BALANCE"]
    qr_confirm(scene, token, key="qr-short-0003")                                    # a genuinely new attempt: its own email
    assert codes(scene) == ["INSUFFICIENT_BALANCE", "INSUFFICIENT_BALANCE"]
    refs = {n["reference"] for n in scene["mail"]["failure"]}
    assert len(refs) == 2 and all(r.startswith("QRDECL") and len(r) == 16 for r in refs)


def test_qr_top_up_then_retry_with_the_same_key_still_pays(scene):
    token = qr_create(scene, 150)
    set_balance(scene, 100)
    assert qr_confirm(scene, token, key="qr-short-0004").json()["code"] == "insufficient_balance"
    set_balance(scene, 1000)
    r = qr_confirm(scene, token, key="qr-short-0004")
    assert r.status_code == 200 and r.json()["success"] is True and codes(scene) == ["INSUFFICIENT_BALANCE"]


def test_wallet_pay_insufficient_balance_sends_one_email_and_keeps_the_response(scene):
    set_balance(scene, 100)
    r, key = wallet_pay(scene, fare=5000, key="pay-short-0001")
    assert r.status_code == 400 and r.json()["detail"].startswith("Insufficient wallet balance")
    assert scene["mail"]["otp"] == []
    (n,) = scene["mail"]["failure"]
    assert n["code"] == "INSUFFICIENT_BALANCE" and n["payment_mode"] == "Wallet" and n["reference"].startswith("WPDECL")
    for _ in range(3):
        assert wallet_pay(scene, fare=5000, key="pay-short-0001")[0].status_code == 400
    assert codes(scene) == ["INSUFFICIENT_BALANCE"]
    assert balances(scene)[0] == 100


def test_nfc_insufficient_balance_is_unchanged_one_row_and_one_email(scene, monkeypatch):
    import app.routes.nfc_pay as nfc_pay
    monkeypatch.setenv("NFC_FAILURE_EMAIL_COOLDOWN_SECONDS", "0")
    nfc_pay._failure_email_last_sent.clear()
    set_balance(scene, 100)
    r, key = tap(scene, amount=5000)
    assert r.json()["code"] == "INSUFFICIENT_BALANCE"
    tap(scene, amount=5000, key=key)                                                 # replay: same failure, no new email
    assert codes(scene) == ["INSUFFICIENT_BALANCE"]


# ── never blocks or breaks the payment; no email on file ─────────────────────────────────────────────

def test_a_send_that_raises_or_times_out_leaves_the_normal_decline(scene, monkeypatch):
    def boom(**kw):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(nfe, "send_nfc_failure_email", boom)
    token = qr_create(scene, 5000)
    set_balance(scene, 100)
    q = qr_confirm(scene, token, key="qr-boom-0001")
    assert q.status_code == 400 and q.json()["code"] == "insufficient_balance"
    w, _ = wallet_pay(scene, fare=5000, key="pay-boom-0001")
    assert w.status_code == 400 and w.json()["detail"].startswith("Insufficient wallet balance")
    assert balances(scene)[0] == 100


def test_a_failed_delivery_is_retried_on_the_next_attempt_with_the_same_key(scene, monkeypatch):
    results = iter([False, True])
    seen = []

    def flaky(**kw):
        seen.append(kw["reference"])
        return next(results)

    monkeypatch.setattr(nfe, "send_nfc_failure_email", flaky)
    token = qr_create(scene, 5000)
    set_balance(scene, 100)
    qr_confirm(scene, token, key="qr-flaky-0001")
    qr_confirm(scene, token, key="qr-flaky-0001")
    qr_confirm(scene, token, key="qr-flaky-0001")
    assert len(seen) == 2 and seen[0] == seen[1]                       # one retry after the failed delivery, then no more


def test_wallet_response_does_not_wait_for_a_slow_mail_provider(scene, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(nfe, "_POOL", nfe.ThreadPoolExecutor(max_workers=1))      # the real, asynchronous pool
    monkeypatch.setattr(nfe, "send_nfc_failure_email", lambda **kw: release.wait(5) or True)
    set_balance(scene, 100)
    started = time.monotonic()
    r, _ = wallet_pay(scene, fare=5000, key="pay-slow-0001")
    assert time.monotonic() - started < 3 and r.status_code == 400
    release.set()


@pytest.mark.parametrize("empty", ["", "   "])
def test_no_email_on_file_skips_silently(scene, empty):
    set_email(scene, empty)
    token = qr_create(scene, 5000)
    set_balance(scene, 100)
    assert qr_confirm(scene, token, key="qr-none-0001").status_code == 400
    assert wallet_pay(scene, fare=5000, key="pay-none-0001")[0].status_code == 400
    assert codes(scene) == []


# ── durable dedupe (survives a restart) and email content ─────────────────────────────────────────────

def test_a_sent_row_in_email_logs_blocks_a_duplicate_after_a_restart(scene):
    ref = nfe.decline_reference("qr", f"qr:{scene['pax_id']}:qr-logged-0001")
    db = scene["env"].db()
    try:
        db.add(EmailLog(email_type=nfe.DECLINE_EMAIL_TYPE, recipient="x", reference=ref, status="SENT"))
        db.commit()
    finally:
        db.close()
    token = qr_create(scene, 5000)
    set_balance(scene, 100)
    qr_confirm(scene, token, key="qr-logged-0001")
    assert codes(scene) == []                                                   # already sent for this attempt
    qr_confirm(scene, token, key="qr-logged-0002")
    assert codes(scene) == ["INSUFFICIENT_BALANCE"]                            # a different attempt is still emailed


def test_a_failed_log_row_does_not_block_the_email(scene):
    ref = nfe.decline_reference("qr", f"qr:{scene['pax_id']}:qr-logged-0003")
    db = scene["env"].db()
    try:
        db.add(EmailLog(email_type=nfe.DECLINE_EMAIL_TYPE, recipient="x", reference=ref, status="FAILED"))
        db.commit()
    finally:
        db.close()
    token = qr_create(scene, 5000)
    set_balance(scene, 100)
    qr_confirm(scene, token, key="qr-logged-0003")
    assert codes(scene) == ["INSUFFICIENT_BALANCE"]


def test_email_body_has_the_required_facts_and_no_private_data(scene, monkeypatch):
    captured = []

    def fake_send_email(**kw):
        captured.append(kw)
        return True

    monkeypatch.setattr(nfe, "send_email", fake_send_email)
    monkeypatch.setattr(nfe, "send_nfc_failure_email", _REAL_SEND)
    db = scene["env"].db()
    try:
        pax, drv = db.get(User, scene["pax_id"]), db.get(User, scene["driver_id"])
        drv.vehicle_registration = "MH12AB1234"
        notice = nfe.build_decline_notice(db, passenger=pax, driver=drv, amount=Decimal("5000"),
                                          code="INSUFFICIENT_BALANCE", channel="qr", scoped_key="qr:1:body-check-1")
        notice["created_at"] = datetime(2026, 10, 30, 6, 30)                    # 12:00 PM IST
    finally:
        db.close()
    assert nfe.send_decline_notice(**notice) is True
    (mail,) = captured
    blob = f"{mail['subject']} {mail['html_content']} {mail['text_content']}"
    for needle in ("5000.00", "Ravi Driver", "MH12AB1234", "Insufficient wallet balance", "nothing was charged",
                   "30 October 2026, 12:00 PM IST", "FAILED"):
        assert needle in blob, needle
    for secret in ("04A2B3C4D5E681", "Wallet Balance", "\u20b910000", "OTP", "otp_hash"):
        assert secret not in blob, secret
    assert mail["email_type"] == nfe.DECLINE_EMAIL_TYPE and mail["reference"].startswith("QRDECL")
    assert "card payment" not in blob.lower()                                  # a QR decline never says "card"


def test_nfc_email_output_is_unchanged_for_the_card_flow():
    sent = []
    import app.utils.nfc_failure_email as mod

    orig = mod.send_email
    mod.send_email = lambda **kw: sent.append(kw) or True
    try:
        mod.send_nfc_failure_email(to_email="a@b.test", passenger_name="Asha V", fare=40.0, driver_name="Ravi",
                                   reference="TXN123", code="INSUFFICIENT_BALANCE", wallet_balance=12.5,
                                   created_at=datetime(2026, 10, 30, 6, 30))
    finally:
        mod.send_email = orig
    (m,) = sent
    assert "30 October 2026, 06:30 AM UTC" in m["html_content"] and "Transaction ID" in m["html_content"]
    assert "Current Wallet Balance" in m["html_content"] and "Your card payment could not be completed." in m["text_content"]
