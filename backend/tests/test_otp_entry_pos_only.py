"""
The emailed PAYMENT code is entered only on the driver's POS. Every passenger-facing endpoint that could take or
request a code refuses (403) and changes nothing: no attempt is counted, no new email is sent, no money moves.
(The account login / registration / top-up / withdrawal codes are different features and are not covered here.)
"""
import uuid

import pytest

from app.models import PaymentOtpChallenge, Transaction
from tests.test_fraud_gate import (  # noqa: F401
    balances, enforce, last_otp, mail, nfc_verify, qr_confirm, qr_create, rows, scene, tap, add_history,
)


def start_each(scene):
    """One pending challenge per channel (NFC, QR, wallet) for the same passenger, created under enforce."""
    add_history(scene)
    r, nfc_key = tap(scene, amount=5000)
    assert r.json()["status"] == "otp_required"
    token = qr_create(scene, 5000)
    q = qr_confirm(scene, token).json()
    assert q["status"] == "otp_required"
    w = scene["env"].client.post("/api/wallet/pay", headers=scene["pax_headers"], json={
        "driver_id": scene["driver_id"], "fare": 5000, "idempotency_key": f"w-{uuid.uuid4().hex}"}).json()
    assert w["status"] == "otp_required"
    return {"nfc": (r.json()["challenge_id"], nfc_key), "qr": (token, q["challenge_id"]), "wallet": w["challenge_id"]}


def snapshot(scene):
    chs = rows(scene, PaymentOtpChallenge)
    return (balances(scene), sorted((c.public_id, c.attempts, c.status, c.resend_count if hasattr(c, "resend_count") else None)
                                    for c in chs), len(scene["mail"]["otp"]),
            len(rows(scene, Transaction, status="completed")))


def test_every_passenger_facing_code_entry_or_resend_is_refused_and_changes_nothing(scene, enforce):
    ids = start_each(scene)
    code = last_otp(scene)
    before = snapshot(scene)
    c = scene["env"].client
    pax = scene["pax_headers"]
    token, qcid = ids["qr"]
    nfc_cid, nfc_key = ids["nfc"]
    calls = [
        ("post", f"/api/qr/{token}/verify-otp", {"challenge_id": qcid, "otp": code}),
        ("post", f"/api/qr/{token}/resend-otp", {"challenge_id": qcid}),
        ("post", "/api/wallet/pay/verify-otp", {"challenge_id": ids["wallet"], "otp": code}),
        ("post", "/api/wallet/pay/resend-otp", {"challenge_id": ids["wallet"]}),
        # the NFC endpoints belong to the driver's terminal: a passenger session is refused
        ("post", "/api/nfc/pay/verify-otp", {"challenge_id": nfc_cid, "otp": code, "idempotency_key": nfc_key}),
        ("post", "/api/nfc/pay/resend-otp", {"challenge_id": nfc_cid}),
        ("post", "/api/nfc/pay/cancel-otp", {"challenge_id": nfc_cid}),
        # the POS endpoints are driver-only too
        ("post", f"/api/qr/{token}/pos/verify-otp", {"otp": code}),
        ("post", "/api/wallet/pos/verify-otp", {"challenge_id": ids["wallet"], "otp": code}),
    ]
    for method, path, body in calls:
        r = getattr(c, method)(path, json=body, headers=pax)
        assert r.status_code in (403, 404), (path, r.status_code, r.text)
        assert r.json().get("success") is not True, path
        assert snapshot(scene) == before, path
    assert any(getattr(c, m)(p, json=b, headers=pax).json().get("code") == "OTP_ENTRY_POS_ONLY" for m, p, b in calls[:4])


def test_phone_tap_endpoints_have_no_code_entry_at_all(scene):
    paths = set(scene["env"].client.get("/openapi.json").json()["paths"])
    arm_paths = sorted(p for p in paths if p.startswith("/api/nfc/phone"))
    assert arm_paths and not any("otp" in p for p in arm_paths), arm_paths
