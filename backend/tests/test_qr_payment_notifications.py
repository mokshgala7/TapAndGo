"""
test_qr_payment_notifications.py
────────────────────────────────
Confirmation emails and PDF receipt for QR payments, and the ride payment-mode
labels. Email delivery is mocked at `send_email`; no real email or payment.
"""
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from tests.helpers import Env
from app.models import PaymentRequest, Wallet
from app.services import receipt_service
from app.utils import email_service
from app.utils.email_service import _normalize_ride_payment_mode


@pytest.fixture
def scene():
    env = Env()
    driver_id = env.add_user("driver@qrmail.local", account_type="driver", balance=0, name="Ravi Driver")
    passenger_id = env.add_user("pax@qrmail.local", account_type="passenger", balance=500, name="Asha Passenger")
    return {
        "env": env,
        "driver_id": driver_id,
        "passenger_id": passenger_id,
        "driver_headers": env.user_headers(driver_id),
        "pax_headers": env.user_headers(passenger_id),
    }


def create_token(scene, amount=58.0, headers=None):
    r = scene["env"].client.post(
        "/api/qr/create-request", json={"amount": amount}, headers=headers or scene["driver_headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def confirm(scene, token, key=None, headers=None):
    return scene["env"].client.post(
        f"/api/qr/{token}/confirm",
        json={"idempotency_key": key or f"test-{uuid.uuid4().hex}"},
        headers=headers or scene["pax_headers"],
    )


@contextmanager
def capture():
    """Mock delivery and record every email plus the PDF receipt detail rows."""
    sent, pdf_rows = [], []
    real_table = receipt_service._create_details_table

    def spy_table(styles, rows):
        pdf_rows.append(dict(rows))
        return real_table(styles, rows)

    def fake_send(**kwargs):
        sent.append(kwargs)
        return True

    with patch.object(email_service, "send_email", side_effect=fake_send), \
         patch.object(receipt_service, "_create_details_table", side_effect=spy_table):
        yield sent, pdf_rows


def by_type(sent, email_type):
    return [m for m in sent if m["email_type"] == email_type]


# ── Successful QR payment ────────────────────────────────────────────────────

def test_successful_qr_payment_sends_passenger_and_driver_email(scene):
    token = create_token(scene)
    with capture() as (sent, _):
        r = confirm(scene, token)
    assert r.status_code == 200, r.text
    ref = r.json()["transaction"]["reference"]

    passenger = by_type(sent, "ride_passenger_payment")
    driver = by_type(sent, "ride_driver_payment")
    assert len(passenger) == 1 and len(driver) == 1
    assert passenger[0]["to_email"] == "pax@qrmail.local"
    assert driver[0]["to_email"] == "driver@qrmail.local"
    assert passenger[0]["reference"] == ref and driver[0]["reference"] == ref


def test_passenger_email_shows_payment_mode_qr(scene):
    token = create_token(scene)
    with capture() as (sent, _):
        assert confirm(scene, token).status_code == 200
    mail = by_type(sent, "ride_passenger_payment")[0]
    html, text = mail["html_content"], mail["text_content"]
    assert ">Payment Mode<" in html and ">QR<" in html
    assert ">Card<" not in html
    assert "Payment Mode: QR\n" in text
    assert "Card" not in text
    assert f"Transaction ID: {mail['reference']}" in text
    assert f"PDF receipt attached: Receipt-{mail['reference']}.pdf" in text
    # Subject, recipient and the PDF attachment are unchanged.
    assert mail["subject"] == "Tap & Go - Ride Payment Successful"
    assert mail["to_email"] == "pax@qrmail.local"
    assert len(mail["attachments"]) == 1


def test_driver_email_shows_payment_mode_qr(scene):
    token = create_token(scene)
    with capture() as (sent, _):
        assert confirm(scene, token).status_code == 200
    html = by_type(sent, "ride_driver_payment")[0]["html_content"]
    assert ">Payment Mode<" in html and ">QR<" in html
    # Existing driver fields are preserved.
    for field in ("Amount Credited", "Passenger", "Transaction ID", "Date &amp; Time"):
        assert field in html


def test_pdf_receipt_shows_payment_mode_qr_and_is_attached(scene):
    token = create_token(scene)
    with capture() as (sent, pdf_rows):
        r = confirm(scene, token)
    ref = r.json()["transaction"]["reference"]

    assert len(pdf_rows) == 1
    assert pdf_rows[0]["Payment Mode"] == "QR"
    assert pdf_rows[0]["Transaction Reference"] == ref

    attachments = by_type(sent, "ride_passenger_payment")[0]["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == f"Receipt-{ref}.pdf"
    assert attachments[0]["mime_type"] == "application/pdf"
    assert attachments[0]["content"].startswith(b"%PDF")
    # The driver email keeps having no attachment.
    assert not by_type(sent, "ride_driver_payment")[0].get("attachments")


# ── Payment-mode mapping ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, label", [
    ("QR", "QR"), ("qr", "QR"), (" QR ", "QR"), ("Tap & Go Wallet (QR)", "QR"),
    ("CARD", "Card"), ("card", "Card"), ("NFC", "Card"), ("nfc", "Card"), ("RFID", "Card"),
    ("Tap & Go Wallet (NFC)", "Card"),
    (None, "Tap & Go Wallet"), ("", "Tap & Go Wallet"), ("wallet", "Tap & Go Wallet"),
])
def test_ride_payment_mode_mapping(raw, label):
    assert _normalize_ride_payment_mode(raw) == label


@pytest.mark.parametrize("raw", ["xyz", "UPI", "QR_CODE_X", "cardless"])
def test_unknown_methods_are_not_classified_as_qr_or_card(raw):
    assert _normalize_ride_payment_mode(raw) not in ("QR", "Card")


def test_card_value_renders_card_in_driver_email():
    with capture() as (sent, _):
        email_service.send_ride_driver_email("d@x.local", "Driver", 40.0, "Pax", "TXN-CARD-1", payment_method="NFC")
    html = sent[0]["html_content"]
    assert ">Card<" in html and ">QR<" not in html


def test_card_value_renders_card_in_passenger_email_both_versions():
    with capture() as (sent, _):
        email_service.send_ride_passenger_email("p@x.local", "Pax", 40.0, "Driver", "TXN-CARD-2", payment_method="NFC")
    assert ">Card<" in sent[0]["html_content"] and ">QR<" not in sent[0]["html_content"]
    assert "Payment Mode: Card\n" in sent[0]["text_content"]


def test_driver_email_without_method_has_no_payment_mode_row():
    with capture() as (sent, _):
        email_service.send_ride_driver_email("d@x.local", "Driver", 40.0, "Pax", "TXN-OLD-1")
    assert "Payment Mode" not in sent[0]["html_content"]


# ── No email for unsuccessful payments ───────────────────────────────────────

def _set_request(scene, token, **values):
    db = scene["env"].db()
    try:
        db.query(PaymentRequest).filter(PaymentRequest.utr == token).update(values, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_no_email_for_insufficient_balance(scene):
    token = create_token(scene, amount=900.0)
    with capture() as (sent, _):
        assert confirm(scene, token).status_code == 400
    assert sent == []


def test_no_email_for_frozen_wallet(scene):
    token = create_token(scene)
    db = scene["env"].db()
    try:
        db.query(Wallet).filter(Wallet.user_id == scene["passenger_id"]).update({"is_frozen": True})
        db.commit()
    finally:
        db.close()
    with capture() as (sent, _):
        assert confirm(scene, token).status_code == 400
    assert sent == []


def test_no_email_for_expired_request(scene):
    token = create_token(scene)
    _set_request(scene, token, expires_at=datetime.utcnow() - timedelta(seconds=1))
    with capture() as (sent, _):
        assert confirm(scene, token).status_code == 410
    assert sent == []


def test_no_email_for_cancelled_request(scene):
    token = create_token(scene)
    assert scene["env"].client.post(f"/api/qr/{token}/cancel", headers=scene["driver_headers"]).status_code == 200
    with capture() as (sent, _):
        assert confirm(scene, token).status_code in (409, 410)
    assert sent == []


def test_no_email_for_processing_request(scene):
    token = create_token(scene)
    _set_request(scene, token, status="processing")
    with capture() as (sent, _):
        assert confirm(scene, token).status_code == 410
    assert sent == []


# ── No duplicate notifications ───────────────────────────────────────────────

def test_idempotent_replay_sends_no_second_email(scene):
    token = create_token(scene)
    key = f"replay-{uuid.uuid4().hex}"
    with capture() as (sent, _):
        assert confirm(scene, token, key).status_code == 200
        replay = confirm(scene, token, key)
    assert replay.status_code == 200 and replay.json()["idempotent"] is True
    assert len(by_type(sent, "ride_passenger_payment")) == 1
    assert len(by_type(sent, "ride_driver_payment")) == 1


def test_completed_request_reconfirm_with_new_key_sends_no_email(scene):
    token = create_token(scene)
    with capture() as (sent, _):
        assert confirm(scene, token).status_code == 200
        assert confirm(scene, token).status_code == 410
    assert len(sent) == 2  # one passenger + one driver, from the first payment only


def test_concurrent_confirmations_notify_once(tmp_path):
    env = Env(path=str(tmp_path / "notify_race.db"))
    driver_id = env.add_user("drv_race@qrmail.local", account_type="driver", balance=0, name="Race Driver")
    pax_id = env.add_user("pax_race@qrmail.local", account_type="passenger", balance=500)
    scene = {"env": env, "driver_headers": env.user_headers(driver_id), "pax_headers": env.user_headers(pax_id)}
    token = create_token(scene, amount=50.0)
    key = f"race-{uuid.uuid4().hex}"

    with capture() as (sent, _):
        threads = [threading.Thread(target=confirm, args=(scene, token, key)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(by_type(sent, "ride_passenger_payment")) == 1
    assert len(by_type(sent, "ride_driver_payment")) == 1


# ── Email failure never undoes the payment ───────────────────────────────────

def test_email_failure_keeps_completed_payment(scene):
    token = create_token(scene)
    with patch("app.routes.qr.send_ride_passenger_email", side_effect=RuntimeError("SES down")), \
         patch("app.routes.qr.send_ride_driver_email", side_effect=RuntimeError("SES down")):
        r = confirm(scene, token)
    assert r.status_code == 200, r.text
    assert scene["env"].balance(scene["passenger_id"]) == 442.0
    assert scene["env"].balance(scene["driver_id"]) == 58.0


# ── /api/wallet/pay uses the saved transaction method ────────────────────────

def test_wallet_pay_emails_use_saved_payment_method(scene):
    with capture() as (sent, pdf_rows):
        r = scene["env"].client.post(
            "/api/wallet/pay",
            json={"driver_id": scene["driver_id"], "fare": 20.0, "idempotency_key": f"pay-{uuid.uuid4().hex}"},
            headers=scene["pax_headers"],
        )
    assert r.status_code == 200, r.text
    passenger = by_type(sent, "ride_passenger_payment")[0]
    assert ">QR<" in passenger["html_content"]
    assert "Payment Mode: QR\n" in passenger["text_content"]
    assert ">QR<" in by_type(sent, "ride_driver_payment")[0]["html_content"]
    assert pdf_rows[0]["Payment Mode"] == "QR"
