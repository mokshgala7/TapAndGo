"""Razorpay TEST-mode gateway for the mobile app.

Mirrors `razorpay_service` but only ever uses test credentials, read from their own
environment variables so the live RAZORPAY_* keys (used by the website) are never touched:

    RAZORPAY_TEST_KEY_ID          must start with rzp_test_
    RAZORPAY_TEST_KEY_SECRET
    RAZORPAY_TEST_WEBHOOK_SECRET  optional, falls back to the test key secret
    RAZORPAY_TEST_ALLOWED_EMAILS  comma separated emails, or * for everyone
"""
import hashlib
import hmac
import logging
import os
import uuid
from typing import Any, Dict, Optional

from app.services.payment.razorpay_service import PaymentsNotConfigured

logger = logging.getLogger(__name__)

try:
    import razorpay
except ImportError:
    razorpay = None


def test_key_id() -> str:
    return os.getenv("RAZORPAY_TEST_KEY_ID", "").strip()


def test_key_secret() -> str:
    return os.getenv("RAZORPAY_TEST_KEY_SECRET", "").strip()


def test_webhook_secret() -> str:
    return os.getenv("RAZORPAY_TEST_WEBHOOK_SECRET", "").strip() or test_key_secret()


def allowed_emails() -> set:
    raw = os.getenv("RAZORPAY_TEST_ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def email_is_allowed(email: Optional[str]) -> bool:
    """Closed by default: nothing is allowed until RAZORPAY_TEST_ALLOWED_EMAILS is set."""
    allowed = allowed_emails()
    if "*" in allowed:
        return True
    return bool(email) and email.strip().lower() in allowed


class RazorpayTestService:
    def is_configured(self) -> bool:
        return test_key_id().startswith("rzp_test_") and bool(test_key_secret())

    def _require_configured(self) -> None:
        if not self.is_configured():
            # Fail closed: a live key (or none) is never accepted on the test routes.
            raise PaymentsNotConfigured("Test payments are not available right now.")
        if razorpay is None:
            raise RuntimeError("razorpay package is not installed. Please run `pip install razorpay`.")

    def get_client(self):
        self._require_configured()
        return razorpay.Client(auth=(test_key_id(), test_key_secret()))

    def create_order(self, amount_in_rupees: float, notes: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        if amount_in_rupees < 1.0:
            raise ValueError("Minimum order amount is ₹1.00 (100 paise).")
        self._require_configured()
        order = self.get_client().order.create(data={
            "amount": int(round(amount_in_rupees * 100)),
            "currency": "INR",
            "receipt": f"rcpt_{uuid.uuid4().hex[:12]}",
            "notes": notes or {"purpose": "Tap&Go Wallet Add Money (TEST)"},
        })
        return {
            "id": order["id"],
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "receipt": order["receipt"],
            "key_id": test_key_id(),
            "is_mock": False,
        }

    def verify_payment_signature(self, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
        secret = test_key_secret()
        if not self.is_configured():
            return False
        body = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, razorpay_signature or "")

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        secret = test_webhook_secret()
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def get_payment_details(self, payment_id: str) -> Optional[Dict[str, Any]]:
        if not payment_id:
            return None
        try:
            return self.get_client().payment.fetch(payment_id)
        except Exception as e:
            logger.warning(f"[RazorpayTest] Could not fetch payment details for {payment_id}: {e}")
            return None


razorpay_test_service = RazorpayTestService()
