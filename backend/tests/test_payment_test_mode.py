"""Razorpay TEST-mode top-up for the mobile app (/api/payment-test).

Everything is mocked: no Razorpay account or network is used. The secrets below are throw-away values.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import EmailOTP, PaymentOrder, Transaction
from app.services.payment.razorpay_service import razorpay_service
from app.services.payment.razorpay_test_service import razorpay_test_service
from helpers import Env

LIVE_SECRET = "live_only_secret_not_real"
TEST_SECRET = "test_mode_secret_not_real"
TEST_KEY_ID = "rzp_test_fakefakefake"
HOOK_SECRET = "test_mode_webhook_secret"
EMAIL = "tester@test.local"


def sign(order_id, payment_id, secret=TEST_SECRET):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def cfg():
    with patch.dict(os.environ, {
        "RAZORPAY_KEY_ID": "rzp_live_fakefake", "RAZORPAY_KEY_SECRET": LIVE_SECRET,
        "RAZORPAY_TEST_KEY_ID": TEST_KEY_ID, "RAZORPAY_TEST_KEY_SECRET": TEST_SECRET,
        "RAZORPAY_TEST_WEBHOOK_SECRET": HOOK_SECRET, "RAZORPAY_TEST_ALLOWED_EMAILS": EMAIL,
    }):
        yield


@pytest.fixture
def env(cfg):
    e = Env()
    e.uid = e.add_user(EMAIL, balance=10)
    e.other = e.add_user("other@test.local", balance=10)
    e.h = e.user_headers(e.uid)
    return e


def add_order(env, user_id=None, amount_paise=10000, order_id="order_T1", status="created"):
    db = env.db()
    db.add(PaymentOrder(order_id=order_id, user_id=user_id or env.uid, amount_paise=amount_paise,
                        currency="INR", status=status, is_mock=False))
    db.commit()
    db.close()
    return order_id


def provider(order_id="order_T1", amount=10000, status="captured", method="upi"):
    return {"id": "pay_1", "order_id": order_id, "amount": amount, "currency": "INR",
            "status": status, "method": method}


def verify(env, order_id="order_T1", payment_id="pay_1", headers=None, sig=None, path="/api/payment-test/verify-payment",
           secret=TEST_SECRET, prov=None):
    body = {"razorpay_order_id": order_id, "razorpay_payment_id": payment_id,
            "razorpay_signature": sig if sig is not None else sign(order_id, payment_id, secret)}
    with patch.object(razorpay_test_service, "get_payment_details", return_value=prov or provider(order_id)), \
            patch.object(razorpay_service, "get_payment_details", return_value=prov or provider(order_id)):
        return env.client.post(path, json=body, headers=headers if headers is not None else env.h)


def deposits(env):
    db = env.db()
    try:
        return db.query(Transaction).filter(Transaction.transaction_type == "deposit").all()
    finally:
        db.close()


def otp(env, amount, email=EMAIL, user_id=None):
    db = env.db()
    db.add(EmailOTP(email=email, otp="123456", reason="wallet_topup", purpose="wallet_topup",
                    expires_at=datetime.utcnow() + timedelta(minutes=5),
                    otp_metadata=json.dumps({"amount": amount, "user_id": user_id or env.uid})))
    db.commit()
    db.close()


def hook(env, payload, secret=HOOK_SECRET):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return env.client.post("/api/payment-test/webhook", content=body,
                           headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig})


class TestAccess:
    def test_eligibility_only_for_the_allowed_email(self, env):
        assert env.client.get("/api/payment-test/eligibility", headers=env.h).json()["test_topup_enabled"] is True
        other = env.client.get("/api/payment-test/eligibility", headers=env.user_headers(env.other))
        assert other.json()["test_topup_enabled"] is False

    def test_eligibility_requires_login(self, env):
        assert env.client.get("/api/payment-test/eligibility").status_code == 401

    def test_other_users_cannot_use_any_test_route(self, env):
        h = env.user_headers(env.other)
        assert env.client.post("/api/payment-test/topup/request-otp", json={"amount": 100}, headers=h).status_code == 403
        assert env.client.post("/api/payment-test/create-order", json={"amount": 100, "otp": "1"}, headers=h).status_code == 403
        add_order(env, user_id=env.other)
        assert verify(env, headers=h).status_code == 403
        assert env.balance(env.other) == 10

    def test_closed_when_no_allowlist_is_set(self, env):
        with patch.dict(os.environ, {"RAZORPAY_TEST_ALLOWED_EMAILS": ""}):
            assert env.client.get("/api/payment-test/eligibility", headers=env.h).json()["test_topup_enabled"] is False
            assert env.client.post("/api/payment-test/create-order", json={"amount": 100, "otp": "1"},
                                   headers=env.h).status_code == 503

    def test_star_allows_everyone_and_lists_are_case_insensitive(self, env):
        h = env.user_headers(env.other)
        with patch.dict(os.environ, {"RAZORPAY_TEST_ALLOWED_EMAILS": "*"}):
            assert env.client.get("/api/payment-test/eligibility", headers=h).json()["test_topup_enabled"] is True
        with patch.dict(os.environ, {"RAZORPAY_TEST_ALLOWED_EMAILS": "A@x.com, OTHER@Test.local"}):
            assert env.client.get("/api/payment-test/eligibility", headers=h).json()["test_topup_enabled"] is True
            assert env.client.get("/api/payment-test/eligibility", headers=env.h).json()["test_topup_enabled"] is False

    def test_a_live_key_is_never_accepted_on_the_test_routes(self, env):
        with patch.dict(os.environ, {"RAZORPAY_TEST_KEY_ID": "rzp_live_oops"}):
            assert razorpay_test_service.is_configured() is False
            assert env.client.get("/api/payment-test/eligibility", headers=env.h).json()["test_topup_enabled"] is False
            otp(env, 100.0)
            r = env.client.post("/api/payment-test/create-order", json={"amount": 100.0, "otp": "123456"}, headers=env.h)
            assert r.status_code == 503
        db = env.db()
        assert db.query(PaymentOrder).count() == 0


class TestCreateOrder:
    def create(self, env, amount=100.0, code="123456", headers=None):
        return env.client.post("/api/payment-test/create-order", json={"amount": amount, "otp": code},
                               headers=headers if headers is not None else env.h)

    def fake_order(self):
        return {"id": "order_N1", "order_id": "order_N1", "amount": 10000, "currency": "INR",
                "key_id": TEST_KEY_ID, "is_mock": False}

    def test_otp_is_required_before_an_order_exists(self, env):
        with patch.object(razorpay_test_service, "create_order", return_value=self.fake_order()) as m:
            assert self.create(env, code="").status_code == 400
            assert self.create(env).status_code == 400          # no OTP requested yet
            otp(env, 100.0)
            assert self.create(env, code="000000").status_code == 400
            assert not m.called
        db = env.db()
        assert db.query(PaymentOrder).count() == 0

    def test_otp_must_match_the_amount(self, env):
        otp(env, 100.0)
        with patch.object(razorpay_test_service, "create_order", return_value=self.fake_order()):
            assert self.create(env, amount=500.0).status_code == 400

    def test_order_is_stored_for_the_user_with_the_test_key(self, env):
        otp(env, 100.0)
        with patch.object(razorpay_test_service, "create_order", return_value=self.fake_order()):
            r = self.create(env)
        assert r.status_code == 200
        assert r.json()["key_id"] == TEST_KEY_ID and r.json()["is_mock"] is False
        db = env.db()
        o = db.query(PaymentOrder).filter_by(order_id="order_N1").first()
        assert (o.user_id, o.amount_paise, o.status) == (env.uid, 10000, "created")

    def test_the_otp_is_single_use(self, env):
        otp(env, 100.0)
        with patch.object(razorpay_test_service, "create_order", return_value=self.fake_order()):
            assert self.create(env).status_code == 200
            assert self.create(env).status_code == 400

    def test_request_otp_sends_a_topup_code(self, env):
        with patch("app.routes.payment.send_topup_otp", return_value=True) as send:
            r = env.client.post("/api/payment-test/topup/request-otp", json={"amount": 100.0}, headers=env.h)
        assert r.status_code == 200 and send.called
        db = env.db()
        row = db.query(EmailOTP).filter_by(email=EMAIL, purpose="wallet_topup").first()
        assert row is not None and json.loads(row.otp_metadata)["amount"] == 100.0


class TestVerifyPayment:
    def test_credits_once_and_records_a_test_deposit(self, env):
        add_order(env)
        r = verify(env)
        assert r.status_code == 200 and r.json()["balance"] == 110.0
        assert env.balance(env.uid) == 110.0
        rows = deposits(env)
        assert len(rows) == 1
        t = rows[0]
        assert (t.provider, t.status, t.transaction_type, float(t.amount), float(t.balance_after)) == \
            ("RAZORPAY_TEST", "completed", "deposit", 100.0, 110.0)
        assert t.reference.startswith("RZT") and "TEST" in t.description and t.provider_transaction_id == "pay_1"

    def test_replay_is_idempotent(self, env):
        add_order(env)
        assert verify(env).status_code == 200
        again = verify(env)
        assert again.status_code == 200 and again.json().get("idempotent") is True
        assert env.balance(env.uid) == 110.0 and len(deposits(env)) == 1

    def test_deposit_shows_in_the_wallet_activity(self, env):
        add_order(env)
        verify(env)
        r = env.client.get(f"/api/wallet/{env.uid}/transactions", headers=env.h)
        assert r.status_code == 200
        body = json.dumps(r.json())
        assert "TEST mode" in body

    def test_bad_signature_credits_nothing(self, env):
        add_order(env)
        for sig in ("", "deadbeef", sign("order_T1", "pay_1", LIVE_SECRET)):
            assert verify(env, sig=sig or "x").status_code == 400
        assert env.balance(env.uid) == 10 and not deposits(env)

    def test_provider_mismatch_credits_nothing(self, env):
        add_order(env)
        assert verify(env, prov=provider(amount=1)).status_code == 400
        assert verify(env, prov=provider(status="authorized")).status_code == 400
        assert env.balance(env.uid) == 10

    def test_only_the_owner_can_verify(self, env):
        add_order(env)
        assert verify(env, headers=env.user_headers(env.other)).status_code == 403  # not allowlisted
        assert env.balance(env.uid) == 10

    def test_live_route_cannot_settle_a_test_order(self, env):
        add_order(env)
        r = verify(env, path="/api/payment/verify-payment")     # signed with the TEST secret
        assert r.status_code == 400
        assert env.balance(env.uid) == 10 and not deposits(env)

    def test_test_route_cannot_settle_a_live_order(self, env):
        add_order(env, order_id="order_LIVE1")
        r = verify(env, order_id="order_LIVE1", secret=LIVE_SECRET)   # signed with the LIVE secret
        assert r.status_code == 400
        assert env.balance(env.uid) == 10 and not deposits(env)


class TestWebhook:
    def payload(self, order_id="order_T1", amount=10000, payment_id="pay_1"):
        return {"event": "payment.captured", "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": amount, "currency": "INR",
            "status": "captured", "method": "upi"}}}}

    def test_signed_webhook_credits_once_and_races_with_verify(self, env):
        add_order(env)
        assert hook(env, self.payload()).status_code == 200
        assert env.balance(env.uid) == 110.0
        assert hook(env, self.payload()).json().get("duplicate") is True
        assert verify(env).json().get("idempotent") is True
        assert env.balance(env.uid) == 110.0 and len(deposits(env)) == 1
        assert "webhook" in deposits(env)[0].description

    def test_bad_signature_and_wrong_amount_credit_nothing(self, env):
        add_order(env)
        assert hook(env, self.payload(), secret="nope").status_code == 400
        assert hook(env, self.payload(amount=1)).json()["status"] == "ignored"
        assert env.balance(env.uid) == 10

    def test_live_webhook_secret_does_not_work_here(self, env):
        add_order(env)
        assert hook(env, self.payload(), secret=LIVE_SECRET).status_code == 400
