"""Razorpay TEST-mode wallet top-up for the mobile app.

Same flow and guarantees as app/routes/payment.py (mandatory amount-tied OTP, server-side
order, signature + provider check, exactly-once credit) but it uses the RAZORPAY_TEST_*
credentials and is open only to the emails listed in RAZORPAY_TEST_ALLOWED_EMAILS.
Credits are recorded with provider RAZORPAY_TEST so they are easy to tell apart.
The live routes in payment.py are not changed and cannot settle these orders (and vice versa):
the signing secrets differ.
"""
import json
import logging
import math
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EmailOTP, PaymentOrder, Transaction, User, Wallet
from app.routes import payment as live_payment
from app.routes.auth import (
    OTP_MAX_ATTEMPTS,
    _consume_otp,
    _verify_otp_code,
    get_current_user,
)
from app.services.payment.razorpay_service import PaymentsNotConfigured
from app.services.payment.razorpay_test_service import (
    allowed_emails,
    email_is_allowed,
    razorpay_test_service,
    test_webhook_secret,
)
from app.utils.email_service import _normalize_razorpay_method, send_wallet_topup_email
from app.utils.security import is_otp_expired

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment-test", tags=["Payment (test mode)"])

TEST_PROVIDER = "RAZORPAY_TEST"


def _require_test_access(user: User) -> None:
    if not allowed_emails():
        raise HTTPException(status_code=503, detail="Test top-up is not enabled.")
    if not email_is_allowed(user.email):
        raise HTTPException(status_code=403, detail="Test top-up is not enabled for this account.")


@router.get("/eligibility")
def test_topup_eligibility(current_user: User = Depends(get_current_user)):
    """Tells the app whether this account may use test top-up (otherwise it sends the user to the website)."""
    enabled = bool(allowed_emails()) and email_is_allowed(current_user.email) and razorpay_test_service.is_configured()
    return {"success": True, "test_topup_enabled": enabled}


@router.post("/topup/request-otp")
def request_test_topup_otp(
    data: live_payment.TopupOTPRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_test_access(current_user)
    return live_payment.request_topup_otp(data, current_user, db)


@router.post("/create-order")
def create_test_order(
    data: live_payment.CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_test_access(current_user)
    if not math.isfinite(data.amount) or data.amount < 1.0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Minimum top-up amount is ₹1.00.")

    wallet = live_payment.get_or_create_wallet(current_user.id, db)
    if wallet.is_frozen:
        raise HTTPException(status_code=400, detail="Your wallet is frozen. Adding funds is disabled.")

    # ── Mandatory server-side OTP gate (same rules as the website) ──────────────
    if not data.otp or not data.otp.strip():
        raise HTTPException(status_code=400, detail="Wallet top-up OTP is required. Please request an OTP first.")

    clean_email = current_user.email.strip().lower()
    db_otp = db.query(EmailOTP).filter(
        func.lower(EmailOTP.email) == clean_email,
        or_(EmailOTP.reason == "wallet_topup", EmailOTP.purpose == "wallet_topup"),
        EmailOTP.used == False,
    ).order_by(EmailOTP.created_at.desc()).first()
    if not db_otp:
        raise HTTPException(status_code=400, detail="No wallet top-up OTP found for this account. Please request an OTP first.")

    if db_otp.attempts >= OTP_MAX_ATTEMPTS:
        db_otp.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Too many incorrect OTP attempts. Please request a new OTP.")
    if is_otp_expired(db_otp.expires_at):
        db_otp.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Top-up OTP has expired. Please request a new OTP.")

    outcome, attempts = _verify_otp_code(db, db_otp, data.otp)
    if outcome == "locked" or (outcome == "wrong" and attempts >= OTP_MAX_ATTEMPTS):
        raise HTTPException(status_code=400, detail="Too many incorrect OTP attempts. Please request a new OTP.")
    if outcome == "gone":
        raise HTTPException(status_code=400, detail="This OTP is no longer valid. Please request a new OTP.")
    if outcome == "wrong":
        remaining = max(0, OTP_MAX_ATTEMPTS - attempts)
        raise HTTPException(status_code=400, detail=f"Invalid top-up OTP. ({remaining} attempts remaining)")

    try:
        meta = json.loads(db_otp.otp_metadata) if db_otp.otp_metadata else {}
    except Exception:
        meta = {}
    stored_amount = meta.get("amount")
    stored_user_id = meta.get("user_id")
    if stored_amount is not None and round(stored_amount, 2) != round(data.amount, 2):
        db.query(EmailOTP).filter(EmailOTP.id == db_otp.id).update(
            {EmailOTP.attempts: EmailOTP.attempts + 1}, synchronize_session=False
        )
        db.query(EmailOTP).filter(EmailOTP.id == db_otp.id, EmailOTP.attempts >= OTP_MAX_ATTEMPTS).update(
            {EmailOTP.used: True}, synchronize_session=False
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"OTP was issued for a different amount (₹{stored_amount:.2f}). Please request a new OTP for ₹{data.amount:.2f}.",
        )
    if stored_user_id is not None and stored_user_id != current_user.id:
        db_otp.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="OTP does not match authenticated user.")

    if not _consume_otp(db, db_otp):
        db.rollback()
        raise HTTPException(status_code=400, detail="This OTP is no longer valid. Please request a new OTP.")
    # ── End OTP gate ────────────────────────────────────────────────────────────

    try:
        order = razorpay_test_service.create_order(
            amount_in_rupees=data.amount,
            notes={"user_id": str(current_user.id), "user_email": current_user.email, "mode": "test"},
        )
    except PaymentsNotConfigured as nc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(nc))
    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error(f"[PaymentTest] Error creating Razorpay test order: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate Razorpay order. Please try again.")

    db.add(PaymentOrder(
        order_id=order["order_id"],
        user_id=current_user.id,
        amount_paise=int(order["amount"]),
        currency=order["currency"],
        status="created",
        is_mock=False,
    ))
    db.commit()

    return {
        "success": True,
        "order_id": order["order_id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "key_id": order["key_id"],
        "is_mock": False,
    }


def _credit_test_order(db: Session, order: PaymentOrder, payment_id: str, raw_method: Optional[str], source: str):
    """Credit the wallet for a test `order` exactly once (see payment._credit_order)."""
    user = db.get(User, order.user_id)
    wallet = live_payment.get_or_create_wallet(order.user_id, db)

    claimed = db.query(PaymentOrder).filter(
        PaymentOrder.id == order.id, PaymentOrder.status == "created"
    ).update(
        {"status": "paid", "provider_payment_id": payment_id, "paid_at": datetime.utcnow()},
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        existing = db.query(Transaction).filter(Transaction.provider_transaction_id == payment_id).first()
        return existing, False

    credit_amount = (Decimal(order.amount_paise) / Decimal(100)).quantize(Decimal("0.01"))
    db.query(Wallet).filter(Wallet.id == wallet.id).update(
        {Wallet.balance: Wallet.balance + credit_amount}, synchronize_session=False
    )
    db.flush()
    db.refresh(wallet)

    normalized_method = _normalize_razorpay_method(raw_method)
    txn = Transaction(
        reference=f"RZT{uuid.uuid4().hex[:10].upper()}",
        passenger_id=user.id if user.account_type == "passenger" else None,
        driver_id=user.id if user.account_type == "driver" else None,
        wallet_id=wallet.id,
        amount=credit_amount,
        payment_method=normalized_method or "Razorpay",
        status="completed",
        otp_verified=True,
        fraud_status="clear",
        transaction_type="deposit",
        description=f"₹{float(credit_amount):.2f} added to wallet via Razorpay (TEST mode){' (webhook)' if source == 'webhook' else ''}",
        balance_after=wallet.balance,
        provider=TEST_PROVIDER,
        provider_transaction_id=payment_id,
        utr=order.order_id,
    )
    db.add(txn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.query(Transaction).filter(Transaction.provider_transaction_id == payment_id).first(), False
    db.refresh(txn)
    db.refresh(wallet)

    if user.email:
        try:
            send_wallet_topup_email(
                to_email=user.email,
                user_name=user.name,
                amount=float(credit_amount),
                reference=txn.reference,
                status="Successful",
                provider="Razorpay (Test mode)",
                payment_method=normalized_method,
                razorpay_payment_id=payment_id,
                razorpay_order_id=order.order_id,
                balance_after=float(wallet.balance),
                created_at=txn.created_at,
                account_type=user.account_type,
            )
        except Exception as e:
            logger.warning(f"[PaymentTestEmail] Topup email delivery failed: {e}")
    return txn, True


def _provider_payment_matches(order: PaymentOrder, payment_id: str):
    info = razorpay_test_service.get_payment_details(payment_id)
    if not isinstance(info, dict):
        return False, None
    ok = (
        info.get("status") == "captured"
        and info.get("order_id") == order.order_id
        and str(info.get("currency", "")).upper() == order.currency.upper()
        and int(info.get("amount", -1)) == int(order.amount_paise)
    )
    return ok, info.get("method")


@router.post("/verify-payment")
def verify_test_payment(
    data: live_payment.VerifyPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_test_access(current_user)
    if not data.razorpay_order_id or not data.razorpay_payment_id or not data.razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing required Razorpay verification parameters.")
    if data.user_id is not None and data.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to verify this payment.")

    order = db.query(PaymentOrder).filter(PaymentOrder.order_id == data.razorpay_order_id).first()
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Payment order not found.")

    if order.status == "paid":
        existing = db.query(Transaction).filter(
            Transaction.provider_transaction_id == order.provider_payment_id
        ).first()
        if order.provider_payment_id != data.razorpay_payment_id:
            raise HTTPException(status_code=409, detail="This order was already paid with a different payment.")
        wallet = live_payment.get_or_create_wallet(current_user.id, db)
        return {
            "success": True,
            "message": "Payment already verified and credited.",
            "balance": float(wallet.balance),
            "reference": existing.reference if existing else None,
            "idempotent": True,
        }

    if not razorpay_test_service.verify_payment_signature(
        razorpay_order_id=data.razorpay_order_id,
        razorpay_payment_id=data.razorpay_payment_id,
        razorpay_signature=data.razorpay_signature,
    ):
        logger.warning("[PaymentTest] Invalid signature for order %s", data.razorpay_order_id)
        raise HTTPException(status_code=400, detail="Payment verification failed due to invalid signature.")

    ok, provider_method = _provider_payment_matches(order, data.razorpay_payment_id)
    if not ok:
        raise HTTPException(status_code=400, detail="The payment could not be confirmed with the payment provider.")

    txn, credited = _credit_test_order(db, order, data.razorpay_payment_id, provider_method or data.payment_method, "verify")
    wallet = live_payment.get_or_create_wallet(current_user.id, db)
    if txn is None:
        raise HTTPException(status_code=409, detail="This order was already paid with a different payment.")
    return {
        "success": True,
        "message": (
            f"Successfully added ₹{float(txn.amount):.2f} to your wallet (test payment)."
            if credited else "Payment already verified and credited."
        ),
        "balance": float(wallet.balance),
        "reference": txn.reference,
        **({} if credited else {"idempotent": True}),
    }


@router.post("/webhook")
async def test_razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
    db: Session = Depends(get_db),
):
    """Asynchronous reconciliation for test-mode payments (signed with the test webhook secret)."""
    if not test_webhook_secret():
        raise HTTPException(status_code=503, detail="Webhook is not configured.")
    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing webhook signature.")

    body_bytes = await request.body()
    if not razorpay_test_service.verify_webhook_signature(body_bytes, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body_bytes)
        if payload.get("event") not in ("payment.captured", "order.paid"):
            return {"status": "ignored"}

        entity = (payload.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}
        payment_id = entity.get("id")
        order_id = entity.get("order_id")
        if not payment_id or not order_id:
            return {"status": "ignored"}

        order = db.query(PaymentOrder).filter(PaymentOrder.order_id == order_id).first()
        if not order:
            return {"status": "ignored"}
        if order.status == "paid":
            return {"status": "ok", "duplicate": True}
        if (
            entity.get("status") not in (None, "captured")
            or str(entity.get("currency", order.currency)).upper() != order.currency.upper()
            or int(entity.get("amount", -1)) != int(order.amount_paise)
        ):
            logger.error("[PaymentTest Webhook] Amount/currency/status mismatch for order %s.", order_id)
            return {"status": "ignored"}

        _credit_test_order(db, order, payment_id, entity.get("method"), "webhook")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[PaymentTest Webhook] Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed.")
