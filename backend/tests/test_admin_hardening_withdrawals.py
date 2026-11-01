"""Phase 4 of the admin hardening: payout reference (UTR) and full payout details for the administrator."""
import uuid
from unittest.mock import patch

import pytest

from app.models import EmailOTP, User, WithdrawalRequest
from helpers import Env

BANK = dict(bank_account_holder="Rider R", bank_account_number="123456789012",
            bank_ifsc="HDFC0001234", bank_upi_id="rider@hdfc")


@pytest.fixture(autouse=True)
def _no_email():
    with patch("app.routes.wallet.send_withdrawal_otp", return_value=True), \
         patch("app.routes.wallet.send_withdrawal_email", return_value=True), \
         patch("app.routes.admin.send_withdrawal_approved_email", return_value=True), \
         patch("app.routes.admin.send_withdrawal_paid_email", return_value=True), \
         patch("app.routes.admin.send_withdrawal_rejected_email", return_value=True):
        yield


@pytest.fixture
def env():
    e = Env()
    e.p = e.add_user("rider@test.local", balance=500, **BANK)
    e.ph = e.user_headers(e.p)
    e.ah = e.admin_headers(e.add_admin())
    return e


def make_withdrawal(env, amount=100):
    assert env.client.post("/api/wallet/withdraw/request-otp", json={"amount": amount}, headers=env.ph).status_code == 200
    db = env.db()
    try:
        otp = db.query(EmailOTP).filter(EmailOTP.reason == "withdraw_balance").order_by(EmailOTP.id.desc()).first().otp
    finally:
        db.close()
    res = env.client.post("/api/wallet/withdraw", json={"amount": amount, "otp": otp, "idempotency_key": uuid.uuid4().hex}, headers=env.ph)
    assert res.status_code == 200, res.text
    db = env.db()
    try:
        return db.query(WithdrawalRequest).order_by(WithdrawalRequest.id.desc()).first().id
    finally:
        db.close()


def approve(env, wid):
    assert env.client.patch(f"/api/admin/withdrawal-requests/{wid}/approve", headers=env.ah).status_code == 200


def test_pay_without_body_still_works(env):
    wid = make_withdrawal(env); approve(env, wid)
    res = env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah)
    assert res.status_code == 200 and res.json()["withdrawal_request"]["status"] == "paid"
    assert res.json()["withdrawal_request"]["payout_reference"] is None


def test_pay_with_reference_stores_it_trimmed(env):
    wid = make_withdrawal(env); approve(env, wid)
    res = env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah, json={"payout_reference": "  UTR-123456789012  "})
    assert res.status_code == 200 and res.json()["withdrawal_request"]["payout_reference"] == "UTR-123456789012"
    listed = env.client.get("/api/admin/withdrawal-requests", headers=env.ah).json()["items"][0]
    assert listed["payout_reference"] == "UTR-123456789012"
    # a second call does not overwrite it
    again = env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah, json={"payout_reference": "OTHER"})
    assert again.status_code == 200 and again.json()["withdrawal_request"]["payout_reference"] == "UTR-123456789012"


@pytest.mark.parametrize("bad", ["has space", "semi;colon", "x" * 65, "ünï"])
def test_invalid_reference_is_rejected_and_nothing_changes(env, bad):
    wid = make_withdrawal(env); approve(env, wid)
    assert env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah, json={"payout_reference": bad}).status_code == 422
    assert env.client.get(f"/api/admin/withdrawal-requests/{wid}", headers=env.ah).json()["status"] == "approved"


def test_blank_reference_is_treated_as_none(env):
    wid = make_withdrawal(env); approve(env, wid)
    res = env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah, json={"payout_reference": "   "})
    assert res.status_code == 200 and res.json()["withdrawal_request"]["payout_reference"] is None


def test_admin_sees_full_bank_details_and_no_warning_when_unchanged(env):
    wid = make_withdrawal(env)
    item = env.client.get("/api/admin/withdrawal-requests", headers=env.ah).json()["items"][0]
    payout = item["payout"]
    assert payout["account_number"] == "123456789012" and payout["ifsc"] == "HDFC0001234"
    assert payout["upi_id"] == "rider@hdfc" and payout["account_holder"] == "Rider R"
    assert payout["details_changed"] is False and payout["warning"] is None
    assert item["user_name"] == "Rider"
    assert env.client.get(f"/api/admin/withdrawal-requests/{wid}", headers=env.ah).json()["payout"]["account_number"] == "123456789012"


def test_warning_when_bank_account_changed_after_request(env):
    wid = make_withdrawal(env)
    db = env.db()
    try:
        db.get(User, env.p).bank_account_number = "999999990000"
        db.commit()
    finally:
        db.close()
    payout = env.client.get(f"/api/admin/withdrawal-requests/{wid}", headers=env.ah).json()["payout"]
    assert payout["details_changed"] is True and "changed" in payout["warning"].lower()
    assert payout["account_number"] == "999999990000"


def test_warning_for_upi_destination_changed(env):
    db = env.db()
    try:
        u = db.get(User, env.p); u.bank_account_number = None; db.commit()
    finally:
        db.close()
    wid = make_withdrawal(env)
    assert env.client.get(f"/api/admin/withdrawal-requests/{wid}", headers=env.ah).json()["payout"]["details_changed"] is False
    db = env.db()
    try:
        db.get(User, env.p).bank_upi_id = "new@upi"; db.commit()
    finally:
        db.close()
    assert env.client.get(f"/api/admin/withdrawal-requests/{wid}", headers=env.ah).json()["payout"]["details_changed"] is True


def test_admin_only(env):
    wid = make_withdrawal(env)
    assert env.client.get("/api/admin/withdrawal-requests").status_code == 401
    assert env.client.get(f"/api/admin/withdrawal-requests/{wid}", headers=env.ph).status_code == 401
    # the user's own history never exposes bank details
    hist = env.client.get("/api/wallet/withdraw/history", headers=env.ph).text
    assert "123456789012" not in hist


def test_user_history_shows_status_progression(env):
    wid = make_withdrawal(env)
    statuses = lambda: [t["status"] for t in env.client.get(f"/api/wallet/{env.p}/transactions", headers=env.ph).json()["transactions"]
                        if t.get("transaction_type") in ("withdrawal_hold", "withdrawal")]
    assert statuses() == ["Pending"]
    approve(env, wid)
    assert statuses() == ["Approved"]
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah, json={"payout_reference": "UTR1"})
    assert statuses() == ["Completed"]
    assert env.client.get("/api/wallet/withdraw/history", headers=env.ph).json()["withdrawal_requests"][0]["status"] == "paid"


@pytest.mark.parametrize("amount", [1, 500])
def test_no_withdrawal_limits_added(amount):
    # amount > 0 and <= balance stay the only rules: 1 rupee and the entire balance both go through
    e = Env()
    e.p = e.add_user("rider@test.local", balance=500, **BANK)
    e.ph = e.user_headers(e.p)
    e.ah = e.admin_headers(e.add_admin())
    make_withdrawal(e, amount=amount)
