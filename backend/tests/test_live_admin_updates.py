"""What the user sees after the administrator acts on a withdrawal: the history text and status follow the decision."""
import uuid
from unittest.mock import patch

import pytest

from app.models import EmailOTP, Transaction, WithdrawalRequest
from helpers import Env

BANK = dict(bank_account_holder="Rider R", bank_account_number="123456789012", bank_ifsc="HDFC0001234", bank_upi_id="rider@hdfc")


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
    e.d = e.add_user("driver@test.local", account_type="driver", balance=500, **BANK)
    e.ah = e.admin_headers(e.add_admin())
    return e


def request_withdrawal(env, uid, email, amount=100):
    headers = env.user_headers(uid)
    assert env.client.post("/api/wallet/withdraw/request-otp", json={"amount": amount}, headers=headers).status_code == 200
    db = env.db()
    try:
        otp = db.query(EmailOTP).filter(EmailOTP.email == email, EmailOTP.reason == "withdraw_balance").order_by(EmailOTP.id.desc()).first().otp
    finally:
        db.close()
    assert env.client.post("/api/wallet/withdraw", json={"amount": amount, "otp": otp, "idempotency_key": uuid.uuid4().hex}, headers=headers).status_code == 200
    db = env.db()
    try:
        return headers, db.query(WithdrawalRequest).filter_by(user_id=uid).order_by(WithdrawalRequest.id.desc()).first().id
    finally:
        db.close()


def withdrawal_row(env, uid, headers):
    rows = env.client.get(f"/api/wallet/{uid}/transactions", headers=headers).json()["transactions"]
    return next(r for r in rows if r["type"] == "Withdrawal")


def test_text_and_status_follow_each_admin_step(env):
    headers, wid = request_withdrawal(env, env.p, "rider@test.local")
    row = withdrawal_row(env, env.p, headers)
    assert row["status"] == "Pending" and "awaiting admin approval" in row["description"] and "hold" not in row["description"].lower()

    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/approve", headers=env.ah)
    row = withdrawal_row(env, env.p, headers)
    assert row["status"] == "Approved" and "approved" in row["description"] and "in progress" in row["description"]

    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah, json={"payout_reference": "UTR-998877"})
    row = withdrawal_row(env, env.p, headers)
    assert row["status"] == "Completed" and row["payout_reference"] == "UTR-998877"
    assert "paid out" in row["description"] and "UTR-998877" in row["description"]
    assert "hold" not in row["description"].lower() and "pending" not in row["description"].lower()


def test_paid_without_a_reference_still_reads_as_paid(env):
    headers, wid = request_withdrawal(env, env.p, "rider@test.local")
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/approve", headers=env.ah)
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah)
    row = withdrawal_row(env, env.p, headers)
    assert row["status"] == "Completed" and "paid out" in row["description"] and row["payout_reference"] is None


def test_a_stale_hold_transaction_cannot_hide_the_paid_status(env):
    """Rows already paid before this fix (and any row whose hold transaction lags) must read as paid."""
    headers, wid = request_withdrawal(env, env.p, "rider@test.local")
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/approve", headers=env.ah)
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah)
    db = env.db()
    try:
        hold = db.query(Transaction).filter(Transaction.transaction_type.in_(("withdrawal", "withdrawal_hold"))).one()
        hold.status, hold.transaction_type = "pending", "withdrawal_hold"
        hold.description = "₹100.00 withdrawal hold — pending admin approval to Bank Account (XXXX XXXX 9012)"
        db.commit()
    finally:
        db.close()
    row = withdrawal_row(env, env.p, headers)
    assert row["status"] == "Completed" and "paid out" in row["description"]


def test_rejection_is_shown_and_the_refund_is_listed(env):
    headers, wid = request_withdrawal(env, env.p, "rider@test.local")
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/reject", headers=env.ah, json={"admin_note": "wrong details"})
    row = withdrawal_row(env, env.p, headers)
    assert row["status"] == "Cancelled" and "rejected" in row["description"] and "returned to your wallet" in row["description"]
    rows = env.client.get(f"/api/wallet/{env.p}/transactions", headers=headers).json()["transactions"]
    assert any(r["type"] == "Withdrawal Reversal" for r in rows)
    assert env.balance(env.p) == 500.0


def test_driver_history_follows_the_decision_too(env):
    headers, wid = request_withdrawal(env, env.d, "driver@test.local", amount=50)
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/approve", headers=env.ah)
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah, json={"payout_reference": "DRV-1"})
    row = withdrawal_row(env, env.d, headers)
    assert row["status"] == "Completed" and "paid out" in row["description"]


def test_other_rows_and_balances_are_unchanged(env):
    headers, wid = request_withdrawal(env, env.p, "rider@test.local", amount=100)
    before = env.client.get(f"/api/wallet/{env.p}", headers=headers).json()["wallet"]["balance"]
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/approve", headers=env.ah)
    env.client.patch(f"/api/admin/withdrawal-requests/{wid}/pay", headers=env.ah)
    assert env.client.get(f"/api/wallet/{env.p}", headers=headers).json()["wallet"]["balance"] == before == 400.0
    row = withdrawal_row(env, env.p, headers)
    assert row["amount"] == 100.0 and row["is_credit"] is False and row["balance_after"] == 400.0
