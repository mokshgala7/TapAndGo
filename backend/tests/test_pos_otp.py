"""
test_pos_otp.py
───────────────
The emailed payment code is entered ONLY on the driver's POS, for QR and wallet payments (NFC already worked that way).

  * the website / passenger-authenticated verify and resend endpoints refuse with OTP_ENTRY_POS_ONLY and change nothing;
    the passenger can still cancel and can poll my-status (a waiting screen, no code input);
  * new driver-authenticated, driver-scoped POS endpoints verify / resend / cancel / look up the status;
  * every existing rule still holds (single use, attempt limit in the DB, expiry, resend cooldown, binding, money only
    after a verified code, failure emails as before) and nothing private reaches the POS.
Mail is mocked; no real email is sent.
"""
import json
import uuid
from datetime import datetime, timedelta

import pytest

from app.models import PaymentOtpChallenge
from tests.test_fraud_gate import (  # noqa: F401 - fixtures are imported by name so pytest finds them here
    add_history, balances, completed, enforce, expire, last_otp, mail, qr_confirm, qr_create, qr_pos_verify, qr_status,
    rows, scene, wallet_pos_verify, wrong,
)

POS_ONLY = "OTP_ENTRY_POS_ONLY"


def client(scene):
    return scene["env"].client


def wallet_pay(scene, fare=5000, key=None):
    key = key or f"pay-{uuid.uuid4().hex}"
    r = client(scene).post("/api/wallet/pay", json={"driver_id": scene["driver_id"], "fare": fare, "idempotency_key": key},
                           headers=scene["pax_headers"])
    return r, key


def start_qr(scene, amount=5000):
    add_history(scene)
    token = qr_create(scene, amount)
    body = qr_confirm(scene, token).json()
    assert body["status"] == "otp_required", body
    return token, body["challenge_id"]


def start_wallet(scene, amount=5000):
    add_history(scene)
    r, key = wallet_pay(scene, amount)
    assert r.json()["status"] == "otp_required", r.text
    return r.json()["challenge_id"], key


def pos(scene, method, path, headers=None, **kw):
    return getattr(client(scene), method)(path, headers=headers or scene["driver_headers"], **kw)


def attempts(scene):
    (c,) = rows(scene, PaymentOtpChallenge)
    return c.attempts, c.status


# ── the website no longer accepts or resends a payment OTP ────────────────────────────────────────────

def test_website_qr_verify_and_resend_are_refused_and_change_nothing(scene, enforce):
    before = balances(scene)
    token, cid = start_qr(scene)
    otp = last_otp(scene)
    for path in ("verify-otp", "resend-otp"):
        r = client(scene).post(f"/api/qr/{token}/{path}", json={"challenge_id": cid, "otp": otp},
                               headers=scene["pax_headers"])
        assert r.status_code == 403 and r.json()["code"] == POS_ONLY and r.json()["success"] is False, r.text
    assert balances(scene) == before and completed(scene) == [] and attempts(scene) == (0, "pending")
    assert len(scene["mail"]["otp"]) == 1                                    # no resend either
    assert qr_status(scene, token) == "AwaitingOtp"


def test_website_wallet_verify_and_resend_are_refused_and_change_nothing(scene, enforce):
    before = balances(scene)
    cid, _ = start_wallet(scene)
    otp = last_otp(scene)
    for path in ("verify-otp", "resend-otp"):
        r = client(scene).post(f"/api/wallet/pay/{path}", json={"challenge_id": cid, "otp": otp}, headers=scene["pax_headers"])
        assert r.status_code == 403 and r.json()["code"] == POS_ONLY, r.text
    assert balances(scene) == before and completed(scene) == [] and attempts(scene) == (0, "pending")
    assert len(scene["mail"]["otp"]) == 1


def test_refusal_needs_a_login_and_never_leaks(scene, enforce):
    r = client(scene).post("/api/qr/sometoken/verify-otp", json={"otp": "123456"})
    assert r.status_code == 401
    token, cid = start_qr(scene)
    body = client(scene).post(f"/api/qr/{token}/verify-otp", json={"challenge_id": cid, "otp": "000000"},
                              headers=scene["pax_headers"]).text
    assert "maya.pax" not in body and "attempts_left" not in body


def test_there_is_no_way_to_complete_an_otp_payment_from_the_website_alone(scene, enforce):
    before = balances(scene)
    token, cid = start_qr(scene)
    otp = last_otp(scene)
    c = client(scene)
    hdr = scene["pax_headers"]
    attempts_made = [
        c.post(f"/api/qr/{token}/verify-otp", json={"challenge_id": cid, "otp": otp}, headers=hdr),
        c.post(f"/api/qr/{token}/confirm", json={"idempotency_key": "another-key-12345"}, headers=hdr),
        c.post(f"/api/qr/{token}/pos/verify-otp", json={"otp": otp}, headers=hdr),                 # passenger on a POS path
        c.post("/api/wallet/pay/verify-otp", json={"challenge_id": cid, "otp": otp}, headers=hdr),
        c.post("/api/wallet/pos/verify-otp", json={"challenge_id": cid, "otp": otp}, headers=hdr),
    ]
    assert not any(r.json().get("success") is True for r in attempts_made), [r.text for r in attempts_made]
    assert balances(scene) == before and completed(scene) == []


def test_passenger_can_still_cancel_qr_and_wallet_and_the_failure_email_goes_out_once(scene, enforce):
    token, cid = start_qr(scene)
    r = client(scene).post(f"/api/qr/{token}/cancel-otp", json={"challenge_id": cid}, headers=scene["pax_headers"])
    assert r.status_code == 400 and r.json()["code"] == "OTP_CANCELLED"
    client(scene).post(f"/api/qr/{token}/cancel-otp", json={"challenge_id": cid}, headers=scene["pax_headers"])
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_CANCELLED"]
    wid, _ = start_wallet(scene)
    r = client(scene).post("/api/wallet/pay/cancel-otp", json={"challenge_id": wid}, headers=scene["pax_headers"])
    assert r.json()["code"] == "OTP_CANCELLED"
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_CANCELLED", "OTP_CANCELLED"]


# ── QR: the POS flow ─────────────────────────────────────────────────────────────────────────────────

def test_qr_pos_sees_the_waiting_code_with_only_a_masked_hint(scene, enforce):
    token, cid = start_qr(scene)
    r = pos(scene, "get", f"/api/qr/{token}/status")
    body = r.json()
    assert body["status"] == "AwaitingOtp" and body["otp"]["challenge_id"] == cid
    assert body["otp"]["email_hint"] == "m***@e***.com" and body["otp"]["attempts_left"] == 3 and body["otp"]["resends_left"] == 2
    s = pos(scene, "get", f"/api/qr/{token}/pos/otp-status").json()
    assert s["status"] == "otp_pending" and s["amount"] == 5000.0 and s["failure_code"] is None
    for text in (json.dumps(body), json.dumps(s)):
        assert "maya.pax@example.com" not in text and "Asha" not in text and "10000" not in text


def test_qr_pos_verify_moves_money_exactly_once_and_the_passenger_page_sees_it(scene, enforce):
    before = balances(scene)
    token, cid = start_qr(scene)
    wrong_r = qr_pos_verify(scene, token, wrong(last_otp(scene)))
    assert wrong_r.status_code == 200 and wrong_r.json() == {
        "success": False, "status": "otp_invalid", "attempts_left": 2, "message": "Wrong OTP, 2 attempts left."}
    assert balances(scene) == before
    mid = client(scene).get(f"/api/qr/{token}/my-status", headers=scene["pax_headers"]).json()
    assert mid["status"] == "AwaitingOtp" and mid["otp"]["attempts_left"] == 2 and "wallet_balance" not in mid
    ok = qr_pos_verify(scene, token, last_otp(scene))
    assert ok.status_code == 200 and ok.json()["success"] is True and ok.json()["status"] == "Completed"
    ref = ok.json()["reference"]
    assert balances(scene) == (before[0] - 5000, before[1] + 5000) and len(completed(scene)) == 1
    again = qr_pos_verify(scene, token, last_otp(scene))
    assert again.json()["success"] is True and again.json()["idempotent"] is True       # a double submit
    assert balances(scene) == (before[0] - 5000, before[1] + 5000) and len(completed(scene)) == 1
    done = client(scene).get(f"/api/qr/{token}/my-status", headers=scene["pax_headers"]).json()
    assert done["status"] == "Completed" and done["reference"] == ref and done["wallet_balance"] == before[0] - 5000
    assert qr_status(scene, token) == "Completed"
    s = pos(scene, "get", f"/api/qr/{token}/pos/otp-status").json()
    assert s["status"] == "completed" and s["transaction_ref"] == ref


def test_qr_pos_wrong_code_three_times_fails_with_the_same_email(scene, enforce):
    before = balances(scene)
    token, _ = start_qr(scene)
    otp = last_otp(scene)
    for _ in range(2):
        assert qr_pos_verify(scene, token, wrong(otp)).json()["status"] == "otp_invalid"
    last = qr_pos_verify(scene, token, wrong(otp)).json()
    assert last["status"] == "Failed" and last["code"] == "OTP_FAILED"
    assert qr_pos_verify(scene, token, otp).json()["code"] == "OTP_FAILED"                  # the right code is useless now
    assert balances(scene) == before and completed(scene) == []
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_FAILED"]
    mine = client(scene).get(f"/api/qr/{token}/my-status", headers=scene["pax_headers"]).json()
    assert mine["status"] == "Failed" and mine["code"] == "OTP_FAILED"


def test_qr_pos_expiry_and_cancel_record_the_failure_once(scene, enforce):
    token, cid = start_qr(scene)
    expire(scene, cid)
    r = qr_pos_verify(scene, token, last_otp(scene)).json()
    assert r["status"] == "Failed" and r["code"] == "OTP_EXPIRED"
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_EXPIRED"]
    token2, _ = start_qr(scene)
    c = pos(scene, "post", f"/api/qr/{token2}/pos/cancel-otp").json()
    assert c["status"] == "Failed" and c["code"] == "OTP_CANCELLED"
    pos(scene, "post", f"/api/qr/{token2}/pos/cancel-otp")
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_EXPIRED", "OTP_CANCELLED"]


def test_qr_pos_resend_has_a_cooldown_a_limit_and_kills_the_old_code(scene, enforce):
    token, cid = start_qr(scene)
    old = last_otp(scene)
    r = pos(scene, "post", f"/api/qr/{token}/pos/resend-otp")
    assert r.status_code == 429 and r.json()["code"] == "resend_cooldown" and len(scene["mail"]["otp"]) == 1
    for n in range(2):
        db = scene["env"].db()
        try:
            db.query(PaymentOtpChallenge).filter(PaymentOtpChallenge.public_id == cid).update(
                {"last_sent_at": datetime.utcnow() - timedelta(seconds=31)})
            db.commit()
        finally:
            db.close()
        r = pos(scene, "post", f"/api/qr/{token}/pos/resend-otp")
        assert r.status_code == 200 and r.json()["status"] == "otp_required" and r.json()["resends_left"] == 1 - n
    assert len(scene["mail"]["otp"]) == 3
    db = scene["env"].db()
    try:
        db.query(PaymentOtpChallenge).filter(PaymentOtpChallenge.public_id == cid).update(
            {"last_sent_at": datetime.utcnow() - timedelta(seconds=31)})
        db.commit()
    finally:
        db.close()
    assert pos(scene, "post", f"/api/qr/{token}/pos/resend-otp").json()["code"] == "resend_limit"
    assert qr_pos_verify(scene, token, old).json()["status"] in ("otp_invalid", "Failed")  # the first code no longer works
    assert qr_pos_verify(scene, token, last_otp(scene)).json()["success"] is True


def test_qr_pos_endpoints_are_driver_scoped(scene, enforce):
    before = balances(scene)
    token, cid = start_qr(scene)
    otp = last_otp(scene)
    c = client(scene)
    for headers in (scene["other_headers"],):
        for method, path, body in (("post", f"/api/qr/{token}/pos/verify-otp", {"otp": otp}),
                                   ("post", f"/api/qr/{token}/pos/resend-otp", None),
                                   ("post", f"/api/qr/{token}/pos/cancel-otp", None),
                                   ("get", f"/api/qr/{token}/pos/otp-status", None)):
            r = getattr(c, method)(path, headers=headers, **({"json": body} if body is not None else {}))
            assert r.status_code == 404 and r.json()["code"] == "CHALLENGE_INVALID", (path, r.text)
            assert "challenge_id" not in r.text and "email_hint" not in r.text
    for method, path, body in (("post", f"/api/qr/{token}/pos/verify-otp", {"otp": otp}),
                               ("get", f"/api/qr/{token}/pos/otp-status", None)):
        r = getattr(c, method)(path, headers=scene["pax_headers"], **({"json": body} if body is not None else {}))
        assert r.status_code == 403 and r.json()["code"] == "DRIVER_NOT_ALLOWED"
        assert getattr(c, method)(path, **({"json": body} if body is not None else {})).status_code == 401
    assert qr_pos_verify(scene, token, "not-a-code").json()["status"] == "otp_invalid"
    assert balances(scene) == before and completed(scene) == [] and attempts(scene) == (1, "pending")


def test_qr_pos_verify_is_bound_to_the_requests_own_challenge(scene, enforce):
    token, _ = start_qr(scene)
    other_token = qr_create(scene, 4000)
    assert pos(scene, "post", f"/api/qr/{other_token}/pos/verify-otp", json={"otp": last_otp(scene)}).status_code == 404
    assert completed(scene) == []


# ── wallet pay: the POS flow ──────────────────────────────────────────────────────────────────────────

def test_wallet_pos_lists_only_its_own_pending_codes_with_a_masked_hint(scene, enforce):
    cid, _ = start_wallet(scene)
    mine = pos(scene, "get", "/api/wallet/pos/pending-otp").json()
    assert mine["success"] is True and [p["challenge_id"] for p in mine["pending"]] == [cid]
    assert mine["pending"][0]["amount"] == 5000.0 and mine["pending"][0]["email_hint"] == "m***@e***.com"
    assert pos(scene, "get", "/api/wallet/pos/pending-otp", headers=scene["other_headers"]).json()["pending"] == []
    assert pos(scene, "get", "/api/wallet/pos/pending-otp", headers=scene["pax_headers"]).status_code == 403
    assert "maya.pax@example.com" not in json.dumps(mine)


def test_wallet_pos_verify_moves_money_once_and_the_passenger_page_sees_it(scene, enforce):
    before = balances(scene)
    cid, key = start_wallet(scene)
    assert wallet_pos_verify(scene, cid, wrong(last_otp(scene))).json()["attempts_left"] == 2
    ok = wallet_pos_verify(scene, cid, last_otp(scene))
    assert ok.status_code == 200 and ok.json()["success"] is True
    assert wallet_pos_verify(scene, cid, last_otp(scene)).json()["idempotent"] is True
    assert balances(scene) == (before[0] - 5000, before[1] + 5000) and len(completed(scene)) == 1
    st = client(scene).get(f"/api/wallet/pay/otp-status?challenge_id={cid}", headers=scene["pax_headers"]).json()
    assert st["status"] == "Completed" and st["wallet_balance"] == before[0] - 5000
    assert pos(scene, "get", f"/api/wallet/pos/otp-status?challenge_id={cid}").json()["status"] == "completed"
    r2, _ = wallet_pay(scene, 5000, key=key)
    assert r2.json()["idempotent"] is True and len(completed(scene)) == 1


def test_wallet_pos_wrong_code_expiry_and_cancel_send_the_same_failure_emails(scene, enforce):
    cid, _ = start_wallet(scene)
    otp = last_otp(scene)
    for _ in range(2):
        wallet_pos_verify(scene, cid, wrong(otp))
    assert wallet_pos_verify(scene, cid, wrong(otp)).json()["code"] == "OTP_FAILED"
    cid2, _ = start_wallet(scene)
    expire(scene, cid2)
    assert wallet_pos_verify(scene, cid2, last_otp(scene)).json()["code"] == "OTP_EXPIRED"
    cid3, _ = start_wallet(scene)
    assert pos(scene, "post", "/api/wallet/pos/cancel-otp", json={"challenge_id": cid3}).json()["code"] == "OTP_CANCELLED"
    assert [n["code"] for n in scene["mail"]["failure"]] == ["OTP_FAILED", "OTP_EXPIRED", "OTP_CANCELLED"]


def test_wallet_pos_endpoints_are_driver_scoped(scene, enforce):
    before = balances(scene)
    cid, _ = start_wallet(scene)
    otp = last_otp(scene)
    h = scene["other_headers"]
    for path, body in (("verify-otp", {"challenge_id": cid, "otp": otp}), ("resend-otp", {"challenge_id": cid}),
                       ("cancel-otp", {"challenge_id": cid})):
        r = client(scene).post(f"/api/wallet/pos/{path}", json=body, headers=h)
        assert r.status_code == 404 and r.json()["code"] == "CHALLENGE_INVALID", (path, r.text)
    assert pos(scene, "get", f"/api/wallet/pos/otp-status?challenge_id={cid}", headers=h).status_code == 404
    assert pos(scene, "post", "/api/wallet/pos/verify-otp", json={"challenge_id": "nope", "otp": otp}).status_code == 404
    assert balances(scene) == before and attempts(scene) == (0, "pending")


def test_a_qr_challenge_is_not_usable_on_the_wallet_pos_path_and_the_reverse(scene, enforce):
    token, qcid = start_qr(scene)
    assert wallet_pos_verify(scene, qcid, last_otp(scene)).status_code == 404
    wcid, _ = start_wallet(scene, amount=4000)             # a new payment supersedes the passenger's pending QR code
    r = pos(scene, "post", f"/api/qr/{token}/pos/verify-otp", json={"otp": last_otp(scene)}).json()
    assert r["status"] == "Failed" and r["code"] == "OTP_CANCELLED"
    assert pos(scene, "get", "/api/wallet/pos/pending-otp").json()["pending"][0]["challenge_id"] == wcid
    assert completed(scene) == []


def test_receipts_are_sent_once_after_a_pos_verified_payment(scene, enforce, monkeypatch):
    sent = []
    import app.routes.qr as qr_mod
    monkeypatch.setattr(qr_mod, "send_ride_passenger_email", lambda **k: sent.append(("pax", k["reference"])) or True)
    monkeypatch.setattr(qr_mod, "send_ride_driver_email", lambda **k: sent.append(("drv", k["reference"])) or True)
    token, _ = start_qr(scene)
    qr_pos_verify(scene, token, last_otp(scene))
    qr_pos_verify(scene, token, last_otp(scene))
    assert sorted(k for k, _ in sent) == ["drv", "pax"]
