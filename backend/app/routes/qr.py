"""
QR Payment flow for Tap&Go POS Terminal prototype.

Endpoints
─────────
POST /api/qr/create-request      Driver creates a payment request (120-second expiry)
GET  /api/qr/{token}             Passenger fetches payment details after scanning
POST /api/qr/{token}/confirm     Passenger confirms and executes the wallet transfer
GET  /api/qr/{token}/status      Driver terminal polls for payment completion

Design decisions
────────────────
- PaymentRequest rows are re-used with a new `qr_token` column (added by startup
  migration).  The `upi_uri` column stores the full scannable URL; `provider`
  is set to "QR_WALLET" to distinguish from Razorpay rows.
- Status values follow the existing convention (capital first letter):
    Pending → Completed | Expired | Cancelled | Failed
- The confirm endpoint claims the row with a conditional UPDATE before touching
  any wallet, preventing double-spend under concurrent requests.
- The actual debit/credit uses the exact same helpers (_debit, _credit,
  _lock_order) and produces a Transaction row identical to /api/wallet/pay,
  so all existing reporting, idempotency and history code works unchanged.
"""
import secrets
import uuid
import math
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PaymentRequest, Transaction, User, Wallet
from app.routes.auth import get_current_user
from app.utils.email_service import send_ride_passenger_email, send_ride_driver_email
from app.routes.wallet import (
    _credit,
    _debit,
    _lock_order,
    get_or_create_wallet,
    to_money,
    wallet_to_dict,
    MAX_PAYMENT_AMOUNT,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/qr", tags=["QR Payment"])

QR_EXPIRY_SECONDS = 120
QR_TOKEN_BYTES = 32          # 256-bit → URL-safe base64 ≈ 43 chars, unpredictable


# ──────────────────────────── helpers ─────────────────────────────────────────

def _generate_token() -> str:
    return secrets.token_urlsafe(QR_TOKEN_BYTES)


def _pr_to_public_dict(pr: PaymentRequest, driver: User) -> dict:
    """Safe subset of a PaymentRequest row suitable for the passenger-facing GET."""
    now = datetime.utcnow()
    expires_at = pr.expires_at
    remaining_seconds = max(0, int((expires_at - now).total_seconds())) if expires_at else 0
    return {
        "token": pr.utr,                     # we store the token in utr (see note below)
        "driver_name": driver.name,
        "amount": float(pr.amount),
        "status": pr.status,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remaining_seconds": remaining_seconds,
        "payment_method": "QR_WALLET",
    }


def _get_driver_for_request(pr: PaymentRequest, db: Session) -> User:
    """Return the driver attached to this payment request, never exposed raw."""
    driver = db.get(User, pr.user_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Payment request is invalid.")
    return driver


# ──────────────────────────── create-request ──────────────────────────────────

class CreateQRRequest(BaseModel):
    amount: float


@router.post("/create-request")
def create_qr_request(
    data: CreateQRRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Authenticated driver creates a QR payment request.

    - Validates driver role and active status.
    - Validates amount server-side (≥0.01, ≤MAX, ≤2dp).
    - Generates a cryptographically secure, unpredictable 256-bit token.
    - Stores the request in payment_requests; expires in 120 seconds.
    - Returns the token and full payment URL for QR generation on the terminal.
    """
    driver = current_user
    if driver.account_type != "driver":
        raise HTTPException(status_code=403, detail="Only driver accounts can create QR payment requests.")
    if driver.status != "active":
        raise HTTPException(status_code=403, detail="Driver account is not active.")

    amount_dec = to_money(data.amount)
    if amount_dec > MAX_PAYMENT_AMOUNT:
        raise HTTPException(status_code=400, detail=f"Amount exceeds the ₹{MAX_PAYMENT_AMOUNT:.2f} limit.")

    # Ensure driver has a wallet (creates one if absent, harmless if already exists).
    d_wallet = get_or_create_wallet(driver.id, db)
    if d_wallet.is_frozen:
        raise HTTPException(status_code=400, detail="Your wallet is frozen. You cannot receive payments right now.")

    token = _generate_token()
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=QR_EXPIRY_SECONDS)

    pr = PaymentRequest(
        user_id=driver.id,
        wallet_id=d_wallet.id,
        amount=amount_dec,
        # upi_uri carries the scannable payment URL; token stored in utr for indexing.
        upi_uri=f"tapgo://pay?token={token}",
        utr=token,                      # indexed column → fast token lookups
        status="Pending",
        provider="QR_WALLET",
        created_at=now,
        expires_at=expires_at,
    )
    db.add(pr)
    try:
        db.commit()
        db.refresh(pr)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not create payment request. Please try again.")

    return {
        "success": True,
        "token": token,
        "amount": float(amount_dec),
        "driver_name": driver.name,
        "driver_id": driver.id,
        "status": pr.status,
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": QR_EXPIRY_SECONDS,
        "payment_url": f"tapgo://pay?token={token}",
        "request_id": pr.id,
    }


# ──────────────────────────── get details (passenger) ─────────────────────────

@router.get("/{token}")
def get_qr_details(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Authenticated passenger fetches payment details after scanning a QR.

    - Rejects invalid / unknown tokens (same error either way to avoid oracle attacks).
    - Rejects expired or non-Pending requests.
    - Does NOT process a payment — it only returns display information.
    - Does not expose sensitive driver information.
    """
    if current_user.account_type != "passenger":
        raise HTTPException(status_code=403, detail="Only passenger accounts can retrieve QR payment details.")
    if current_user.status != "active":
        raise HTTPException(status_code=403, detail="Your account is not active.")

    pr = db.query(PaymentRequest).filter(
        PaymentRequest.utr == token,
        PaymentRequest.provider == "QR_WALLET",
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Payment request not found or already used.")

    now = datetime.utcnow()

    # Auto-mark expired Pending rows so status is always accurate.
    if pr.status == "Pending" and pr.expires_at and pr.expires_at < now:
        db.query(PaymentRequest).filter(
            PaymentRequest.id == pr.id,
            PaymentRequest.status == "Pending",
        ).update({"status": "Expired"}, synchronize_session=False)
        db.commit()
        raise HTTPException(status_code=410, detail="This QR code has expired. Please ask the driver to show a new code.")

    if pr.status != "Pending":
        raise HTTPException(status_code=410, detail=f"This payment request is no longer available (status: {pr.status}).")

    driver = _get_driver_for_request(pr, db)
    return {
        "success": True,
        "payment": _pr_to_public_dict(pr, driver),
    }


# ──────────────────────────── confirm (passenger) ─────────────────────────────

class ConfirmQRRequest(BaseModel):
    # No passenger-supplied amount or driver_id — everything comes from the stored request.
    idempotency_key: str


@router.post("/{token}/confirm")
def confirm_qr_payment(
    token: str,
    data: ConfirmQRRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Authenticated passenger confirms and executes a QR wallet payment.

    Security guarantees:
    - Driver ID and amount are read from the stored PaymentRequest, never from
      the passenger's request body.
    - The PaymentRequest is claimed with a conditional UPDATE (Pending → processing)
      before any wallet mutation, preventing double-spend under concurrency.
    - Wallet debit/credit uses the same atomic helpers as /api/wallet/pay.
    - Idempotency key scoped to the passenger prevents duplicate charges on retry.
    - Expired, Cancelled, Completed or Failed requests are refused.
    """
    passenger = current_user
    if passenger.account_type != "passenger":
        raise HTTPException(status_code=403, detail="Only passenger accounts can confirm QR payments.")
    if passenger.status != "active":
        raise HTTPException(status_code=403, detail="Your account is not active.")

    key = (data.idempotency_key or "").strip()
    if len(key) < 8 or len(key) > 100:
        raise HTTPException(status_code=400, detail="A valid idempotency key (8–100 chars) is required.")
    scoped_key = f"qr:{passenger.id}:{key}"

    # ── 1. Idempotency replay check ──────────────────────────────────────────
    existing_txn = db.query(Transaction).filter(
        Transaction.idempotency_key == scoped_key
    ).first()
    if existing_txn:
        driver = db.get(User, existing_txn.driver_id)
        p_wallet = get_or_create_wallet(passenger.id, db)
        return {
            "success": True,
            "idempotent": True,
            "message": f"Payment of ₹{float(existing_txn.amount):.2f} already completed.",
            "wallet": wallet_to_dict(p_wallet),
            "transaction": {
                "id": existing_txn.id,
                "reference": existing_txn.reference,
                "status": existing_txn.status,
                "amount": float(existing_txn.amount),
                "driver_name": driver.name if driver else "Driver",
            },
        }

    # ── 2. Load and validate the payment request ─────────────────────────────
    pr = db.query(PaymentRequest).filter(
        PaymentRequest.utr == token,
        PaymentRequest.provider == "QR_WALLET",
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Payment request not found.")

    now = datetime.utcnow()
    if pr.expires_at and pr.expires_at < now:
        # Mark expired atomically if still Pending.
        db.query(PaymentRequest).filter(
            PaymentRequest.id == pr.id,
            PaymentRequest.status == "Pending",
        ).update({"status": "Expired"}, synchronize_session=False)
        db.commit()
        raise HTTPException(status_code=410, detail="This QR code has expired. Please ask the driver to show a new code.")

    if pr.status != "Pending":
        raise HTTPException(status_code=410, detail=f"This payment request is no longer available (status: {pr.status}).")

    # ── 3. Claim the request (Pending → processing) atomically ───────────────
    claimed = db.query(PaymentRequest).filter(
        PaymentRequest.id == pr.id,
        PaymentRequest.status == "Pending",
    ).update({"status": "processing"}, synchronize_session=False)
    db.flush()      # flush within the same transaction; commit happens with the wallet transfer

    if claimed != 1:
        # Another request won the race.
        raise HTTPException(status_code=409, detail="Payment already being processed. Please wait or try a new QR code.")

    # ── 4. Validate driver from stored request ───────────────────────────────
    driver = db.get(User, pr.user_id)
    if not driver or driver.account_type != "driver" or driver.status != "active":
        db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).update(
            {"status": "Failed"}, synchronize_session=False
        )
        db.commit()
        raise HTTPException(status_code=400, detail="The driver account is no longer eligible to receive payments.")

    if driver.id == passenger.id:
        db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).update(
            {"status": "Failed"}, synchronize_session=False
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Self-payment is not allowed.")

    fare_dec = Decimal(str(pr.amount))

    # ── 5. Wallet operations (same atomic helpers as /api/wallet/pay) ─────────
    p_wallet = get_or_create_wallet(passenger.id, db)
    d_wallet = get_or_create_wallet(driver.id, db)

    if p_wallet.is_frozen:
        db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).update(
            {"status": "Failed"}, synchronize_session=False
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Your wallet is frozen. Payment cannot proceed.")

    if d_wallet.is_frozen:
        db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).update(
            {"status": "Failed"}, synchronize_session=False
        )
        db.commit()
        raise HTTPException(status_code=400, detail="The driver cannot receive payments right now.")

    steps = {
        passenger.id: lambda: _debit(db, passenger.id, fare_dec),
        driver.id: lambda: _credit(db, driver.id, fare_dec),
    }
    for uid in _lock_order(passenger.id, driver.id):
        if not steps[uid]():
            db.rollback()
            # Re-open the request so the terminal can show a useful message.
            try:
                with db.begin_nested():
                    db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).update(
                        {"status": "Failed"}, synchronize_session=False
                    )
            except Exception:
                pass
            db.commit()
            if uid == passenger.id:
                db.refresh(p_wallet)
                if p_wallet.is_frozen:
                    raise HTTPException(status_code=400, detail="Your wallet is frozen. Payment failed.")
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient wallet balance (₹{float(p_wallet.balance):.2f}). Please add funds first.",
                )
            raise HTTPException(status_code=400, detail="The driver cannot receive payments right now.")

    db.refresh(p_wallet)
    ref_code = f"QR{uuid.uuid4().hex[:10].upper()}"
    txn = Transaction(
        reference=ref_code,
        passenger_id=passenger.id,
        driver_id=driver.id,
        wallet_id=p_wallet.id,
        amount=fare_dec,
        payment_method="QR",
        status="completed",
        otp_verified=True,
        fraud_status="clear",
        transaction_type="ride_payment",
        description=f"₹{fare_dec:.2f} paid to {driver.name} via QR",
        balance_after=p_wallet.balance,
        idempotency_key=scoped_key,
        payment_request_id=pr.id,
    )
    db.add(txn)

    # Mark the payment request Completed and record the verified_at timestamp.
    db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).update(
        {
            "status": "Completed",
            "verified_at": now,
            "payer_name": passenger.name,
        },
        synchronize_session=False,
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Check for idempotency replay (same key committed concurrently).
        existing = db.query(Transaction).filter(Transaction.idempotency_key == scoped_key).first()
        if existing:
            drv = db.get(User, existing.driver_id)
            pw = get_or_create_wallet(passenger.id, db)
            return {
                "success": True,
                "idempotent": True,
                "message": f"Payment of ₹{float(existing.amount):.2f} already completed.",
                "wallet": wallet_to_dict(pw),
                "transaction": {
                    "id": existing.id,
                    "reference": existing.reference,
                    "status": existing.status,
                    "amount": float(existing.amount),
                    "driver_name": drv.name if drv else "Driver",
                },
            }
        raise HTTPException(status_code=409, detail="Could not record the payment. Please try again.")

    db.refresh(p_wallet)
    db.refresh(txn)

    # Post-commit notifications (never affect the financial record). Replays and
    # lost races return earlier, so each completed payment is notified once.
    try:
        if passenger.email:
            send_ride_passenger_email(
                to_email=passenger.email,
                passenger_name=passenger.name,
                fare=float(txn.amount),
                driver_name=driver.name,
                reference=txn.reference,
                status="Successful",
                vehicle_type=driver.vehicle_type,
                vehicle_registration=driver.vehicle_registration,
                payment_method=txn.payment_method,
                balance_after=float(p_wallet.balance),
                created_at=txn.created_at,
            )
    except Exception as e:
        logger.warning(f"[QREmail] Passenger receipt failed: {e}")

    try:
        if driver.email:
            send_ride_driver_email(
                to_email=driver.email,
                driver_name=driver.name,
                fare=float(txn.amount),
                passenger_name=passenger.name,
                reference=txn.reference,
                payment_method=txn.payment_method,
            )
    except Exception as e:
        logger.warning(f"[QREmail] Driver credit receipt failed: {e}")

    return {
        "success": True,
        "message": f"Payment of ₹{fare_dec:.2f} completed.",
        "wallet": wallet_to_dict(p_wallet),
        "transaction": {
            "id": txn.id,
            "reference": txn.reference,
            "status": txn.status,
            "amount": float(txn.amount),
            "driver_name": driver.name,
        },
    }


# ──────────────────────────── status (driver terminal) ────────────────────────

@router.get("/{token}/status")
def get_qr_status(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Authenticated driver terminal polls for the payment status of its own request.

    - Only the driver who CREATED the request can poll its status.
    - Does not expose passenger account information.
    - Auto-marks Pending rows as Expired if past their expiry time.
    """
    driver = current_user
    if driver.account_type != "driver":
        raise HTTPException(status_code=403, detail="Only driver accounts can poll terminal payment status.")

    pr = db.query(PaymentRequest).filter(
        PaymentRequest.utr == token,
        PaymentRequest.provider == "QR_WALLET",
        PaymentRequest.user_id == driver.id,    # ← owner check
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Payment request not found.")

    now = datetime.utcnow()

    # Auto-expire stale Pending rows.
    if pr.status == "Pending" and pr.expires_at and pr.expires_at < now:
        db.query(PaymentRequest).filter(
            PaymentRequest.id == pr.id,
            PaymentRequest.status == "Pending",
        ).update({"status": "Expired"}, synchronize_session=False)
        db.commit()
        db.refresh(pr)

    expires_at = pr.expires_at
    remaining = max(0, int((expires_at - now).total_seconds())) if expires_at else 0

    resp = {
        "success": True,
        "status": pr.status,
        "amount": float(pr.amount),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "remaining_seconds": remaining,
    }

    # Include the transaction reference on success (but NOT passenger identity).
    if pr.status == "Completed":
        txn = db.query(Transaction).filter(
            Transaction.payment_request_id == pr.id
        ).first()
        if txn:
            resp["transaction_reference"] = txn.reference
            resp["verified_at"] = pr.verified_at.isoformat() if pr.verified_at else None

    return resp


# ──────────────────────────── cancel (driver terminal) ────────────────────────

@router.post("/{token}/cancel")
def cancel_qr_request(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Driver cancels a pending QR payment request safely.
    Only the creating driver can cancel their own request.
    Cancelled requests cannot be paid.
    """
    driver = current_user
    if driver.account_type != "driver":
        raise HTTPException(status_code=403, detail="Only driver accounts can cancel QR payment requests.")

    cancelled = db.query(PaymentRequest).filter(
        PaymentRequest.utr == token,
        PaymentRequest.provider == "QR_WALLET",
        PaymentRequest.user_id == driver.id,
        PaymentRequest.status == "Pending",
    ).update({"status": "Cancelled"}, synchronize_session=False)
    db.commit()

    if cancelled == 0:
        # Might already be Completed / Expired / Cancelled — check what it is.
        pr = db.query(PaymentRequest).filter(
            PaymentRequest.utr == token,
            PaymentRequest.provider == "QR_WALLET",
            PaymentRequest.user_id == driver.id,
        ).first()
        if not pr:
            raise HTTPException(status_code=404, detail="Payment request not found.")
        return {"success": True, "status": pr.status, "message": f"Request is already {pr.status}."}

    return {"success": True, "status": "Cancelled", "message": "Payment request cancelled."}
