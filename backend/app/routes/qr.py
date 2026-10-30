"""
QR Payment flow for Tap&Go POS Terminal prototype.

Endpoints
─────────
POST /api/qr/create-request      Driver creates a payment request (120-second expiry)
GET  /api/qr/{token}             Passenger fetches payment details after scanning
POST /api/qr/{token}/confirm     Passenger confirms and executes the wallet transfer
GET  /api/qr/{token}/status      Driver terminal polls for payment completion
POST /api/qr/{token}/cancel      Driver cancels a pending request (idempotent)
POST /api/qr/{token}/verify-otp  Passenger submits the emailed code when confirm answered otp_required
POST /api/qr/{token}/resend-otp  Passenger asks for a new code (max 2, 30 s apart)
POST /api/qr/{token}/cancel-otp  Passenger abandons the verification (request becomes Failed)

The three driver/terminal endpoints (create-request, status, cancel) use only the
Authorization bearer header and JSON bodies - no cookies, no CORS dependence - so a
microcontroller POS can call them with plain HTTPS.

Design decisions
────────────────
- PaymentRequest rows are re-used with a new `qr_token` column (added by startup
  migration).  The `upi_uri` column stores the full scannable URL; `provider`
  is set to "QR_WALLET" to distinguish from Razorpay rows.
- Status values follow the existing convention (capital first letter):
    Pending → Processing → Completed | Failed      (Processing is internal, exists
    only while confirm runs); Pending → Expired | Cancelled;
    Pending → AwaitingOtp → Completed | Failed     (fraud gate asked for an email OTP).
  AwaitingOtp never expires on the 120 s QR clock and cannot be cancelled by the driver: the POS keeps
  polling until the OTP challenge (5 min) completes or fails.
  Expiry is derived from `expires_at` on every read, so a request is reported
  Expired the moment 120 s pass, whether or not anything polls it.
- The confirm endpoint claims the row with a conditional UPDATE before touching
  any wallet, preventing double-spend under concurrent requests.
- The actual debit/credit uses the exact same helpers (_debit, _credit,
  _lock_order) and produces a Transaction row identical to /api/wallet/pay,
  so all existing reporting, idempotency and history code works unchanged.
- Fraud gate (app/services/fraud_gate.py) runs before the claim. With TAPGO_FRAUD_MODE=enforce a flagged
  payment is not executed: confirm answers {"success": false, "status": "otp_required", "challenge_id", ...}
  and the money moves only in verify-otp (app/services/payment_otp.py).
"""
import secrets
import uuid
import math
import logging
from types import SimpleNamespace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import PaymentRequest, Transaction, User, Wallet
from app.routes.auth import get_current_user
from app.services import payment_otp
from app.services.fraud_gate import evaluate_payment
from app.utils.nfc_failure_email import queue_decline_notice, send_nfc_failure_email
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
# 128-bit → 22 URL-safe chars. Unguessable for a 120 s, authenticated-only window, and short
# enough that the payment URL draws as a small (version 3) QR on the POS display.
QR_TOKEN_BYTES = 16
QR_PATH_PREFIX = "/p"        # website route that opens the payment page: <web>/p/<token>


# ──────────────────────────── helpers ─────────────────────────────────────────

def _generate_token() -> str:
    return secrets.token_urlsafe(QR_TOKEN_BYTES)


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Naive-UTC datetimes are stored; emit them with an explicit Z so clients parse them as UTC."""
    return dt.isoformat() + "Z" if dt else None


def _payment_url(token: str) -> str:
    return f"{settings.PUBLIC_WEB_URL}{QR_PATH_PREFIX}/{token}"


def _seconds_remaining(pr: PaymentRequest, now: datetime) -> int:
    return max(0, int((pr.expires_at - now).total_seconds())) if pr.expires_at else 0


def _expire_if_due(db: Session, pr: PaymentRequest, now: datetime) -> None:
    """Persist Pending → Expired once the deadline has passed (conditional, race-safe)."""
    if pr.status == "Pending" and pr.expires_at and pr.expires_at < now:
        db.query(PaymentRequest).filter(
            PaymentRequest.id == pr.id,
            PaymentRequest.status == "Pending",
        ).update({"status": "Expired"}, synchronize_session=False)
        db.commit()
        db.refresh(pr)


def _public_status(pr: PaymentRequest, now: datetime) -> str:
    """Status shown to clients: exactly Pending|Processing|Completed|Failed|Expired|Cancelled."""
    if pr.status == "Pending" and pr.expires_at and pr.expires_at < now:
        return "Expired"
    if (pr.status or "").lower() == "processing":
        return "Processing"
    return pr.status


def _unavailable(pr: PaymentRequest, now: datetime) -> JSONResponse:
    """410 for a request that can no longer be paid. `detail` stays a plain string (existing
    clients show it); `status` lets the payment page pick the right end-state screen."""
    status = _public_status(pr, now)
    if status == "Expired":
        msg = "This QR code has expired. Please ask the driver to show a new code."
    elif status == "Completed":
        msg = "This payment has already been made."
    elif status == "Cancelled":
        msg = "The driver cancelled this payment request."
    else:
        msg = f"This payment request is no longer available (status: {status})."
    return JSONResponse(status_code=410, content={"success": False, "detail": msg, "status": status})


def _pr_to_public_dict(pr: PaymentRequest, driver: User, now: datetime, passenger_balance: Optional[float] = None) -> dict:
    """Safe subset of a PaymentRequest row suitable for the passenger-facing GET."""
    remaining = _seconds_remaining(pr, now)
    out = {
        "token": pr.utr,                     # we store the token in utr (see note below)
        "driver_name": driver.name,
        "vehicle_registration": driver.vehicle_registration or None,
        "vehicle_type": driver.vehicle_type or None,
        "amount": float(pr.amount),
        "status": _public_status(pr, now),
        "expires_at": _iso_utc(pr.expires_at),
        "remaining_seconds": remaining,
        "seconds_remaining": remaining,
        "payment_method": "QR_WALLET",
    }
    if passenger_balance is not None:
        out["wallet_balance"] = passenger_balance
    return out


def _get_driver_for_request(pr: PaymentRequest, db: Session) -> User:
    """Return the driver attached to this payment request, never exposed raw."""
    driver = db.get(User, pr.user_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Payment request is invalid.")
    return driver


def _challenge_for_request(db: Session, pr: PaymentRequest):
    return db.query(payment_otp.PaymentOtpChallenge).filter(
        payment_otp.PaymentOtpChallenge.payment_request_id == pr.id,
    ).order_by(payment_otp.PaymentOtpChallenge.id.desc()).first()


def _settle_awaiting_otp(db: Session, pr: PaymentRequest, now: datetime, background_tasks=None):
    """An AwaitingOtp request whose code expired becomes Failed (OTP_EXPIRED) the moment anyone looks."""
    if pr.status != "AwaitingOtp":
        return None
    ch = _challenge_for_request(db, pr)
    out = payment_otp.expire_if_due(db, ch, now)
    if out is not None:
        _queue_notices(out, background_tasks)
    db.refresh(pr)
    return ch


def _send_failure_notice(**kwargs):
    try:
        if not send_nfc_failure_email(**kwargs):
            logger.warning(f"[QREmail] Failure notice for {kwargs.get('reference')} was not delivered")
    except Exception as e:
        logger.warning(f"[QREmail] Failure notice failed: {e}")


def _queue_notices(out, background_tasks) -> None:
    for notice in out.notices:
        if background_tasks is not None:
            background_tasks.add_task(_send_failure_notice, **notice)
        else:
            _send_failure_notice(**notice)


def _send_receipts(txn: Transaction, passenger: User, driver: User, balance_after) -> None:
    """Post-commit notifications (never affect the financial record)."""
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
                balance_after=float(balance_after),
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


def _queue_receipts(background_tasks: BackgroundTasks, txn: Transaction, passenger: User, driver: User,
                    balance_after) -> None:
    """Send the receipts AFTER the response (SES + PDF take seconds and must not delay the payment answer).
    The request's DB session is closed by then, so everything the e-mails need is copied into plain values."""
    snap_txn = SimpleNamespace(amount=txn.amount, reference=txn.reference, payment_method=txn.payment_method,
                               created_at=txn.created_at)
    snap_passenger = SimpleNamespace(email=passenger.email, name=passenger.name)
    snap_driver = SimpleNamespace(email=driver.email, name=driver.name, vehicle_type=driver.vehicle_type,
                                  vehicle_registration=driver.vehicle_registration)
    background_tasks.add_task(_send_receipts, snap_txn, snap_passenger, snap_driver, float(balance_after))


def _success_body(txn: Transaction, p_wallet: Wallet, driver: Optional[User], idempotent: bool = False) -> dict:
    body = {
        "success": True,
        "message": f"Payment of ₹{float(txn.amount):.2f} {'already ' if idempotent else ''}completed.",
        "wallet": wallet_to_dict(p_wallet),
        "transaction": {
            "id": txn.id,
            "reference": txn.reference,
            "status": txn.status,
            "amount": float(txn.amount),
            "driver_name": driver.name if driver else "Driver",
        },
    }
    if idempotent:
        body["idempotent"] = True
    return body


QR_FAILURE_MESSAGES = {
    "OTP_FAILED": "Wrong code entered too many times. The payment was cancelled and nothing was charged.",
    "OTP_EXPIRED": "The verification code expired. The payment was cancelled and nothing was charged.",
    "OTP_CANCELLED": "The payment was cancelled. Nothing was charged.",
    "OTP_UNAVAILABLE": "This payment needs email verification, but no code could be sent to your registered "
                       "email. The payment was declined and nothing was charged.",
    "INSUFFICIENT_BALANCE": "Insufficient wallet balance. Nothing was charged.",
    "WALLET_FROZEN": "Your wallet is frozen. Payment failed.",
    "PASSENGER_INACTIVE": "Your account is not active. Payment failed.",
    "DRIVER_UNAVAILABLE": "The driver cannot receive payments right now.",
}


def _failed_body(txn: Optional[Transaction], code: Optional[str], idempotent: bool = False) -> JSONResponse:
    content = {"success": False, "status": "Failed", "code": code or "FAILED",
               "detail": QR_FAILURE_MESSAGES.get(code, "The payment could not be completed. Nothing was charged.")}
    if txn is not None:
        content["reference"] = txn.reference
    if idempotent:
        content["idempotent"] = True
    return JSONResponse(status_code=400, content=content)


def _qr_outcome(db: Session, out, background_tasks) -> object:
    """Passenger-facing response for an OTP outcome."""
    now = datetime.utcnow()
    _queue_notices(out, background_tasks)
    ch = out.challenge
    if out.kind == "otp_required":
        return JSONResponse(status_code=200, content={
            "success": False, "status": "otp_required",
            "detail": "For your security, enter the code we emailed you to complete this payment.",
            **payment_otp.public_view(ch, db.get(User, ch.passenger_id), now),
        })
    if out.kind == "otp_invalid":
        n = out.attempts_left
        return JSONResponse(status_code=200, content={
            "success": False, "status": "otp_invalid", "attempts_left": n,
            "detail": f"Wrong code. {n} attempt{'s' if n != 1 else ''} left.",
        })
    if out.kind == "completed":
        passenger, driver = db.get(User, out.txn.passenger_id), db.get(User, out.txn.driver_id)
        p_wallet = get_or_create_wallet(passenger.id, db)
        if not out.idempotent:
            _queue_receipts(background_tasks, out.txn, passenger, driver, out.txn.balance_after)
        return _success_body(out.txn, p_wallet, driver, idempotent=out.idempotent)
    return _failed_body(out.txn, out.code, idempotent=out.idempotent)


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
    - Returns the token and the short website URL (<web>/p/<token>) the terminal draws as a QR.
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
        upi_uri=_payment_url(token),
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
        "expires_at": _iso_utc(expires_at),
        "expires_in_seconds": QR_EXPIRY_SECONDS,
        "payment_url": _payment_url(token),
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
    - Rejects expired or non-Pending requests (410 with a `status` field naming why).
    - Does NOT process a payment — it only returns display information (driver name,
      vehicle, fare, time left, and the passenger's own wallet balance).
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
    _expire_if_due(db, pr, now)
    ch = _settle_awaiting_otp(db, pr, now)

    if pr.status == "AwaitingOtp" and ch is not None and ch.passenger_id == current_user.id:
        # The paying passenger reopened the page mid-verification: let them finish it.
        driver = _get_driver_for_request(pr, db)
        p_wallet = get_or_create_wallet(current_user.id, db)
        return {
            "success": True,
            "payment": _pr_to_public_dict(pr, driver, now, passenger_balance=float(p_wallet.balance)),
            "otp": payment_otp.public_view(ch, current_user, now),
        }

    if pr.status != "Pending":
        return _unavailable(pr, now)

    driver = _get_driver_for_request(pr, db)
    p_wallet = get_or_create_wallet(current_user.id, db)
    return {
        "success": True,
        "payment": _pr_to_public_dict(pr, driver, now, passenger_balance=float(p_wallet.balance)),
    }


# ──────────────────────────── confirm (passenger) ─────────────────────────────

class ConfirmQRRequest(BaseModel):
    # No passenger-supplied amount or driver_id — everything comes from the stored request.
    idempotency_key: str


@router.post("/{token}/confirm")
def confirm_qr_payment(
    token: str,
    data: ConfirmQRRequest,
    background_tasks: BackgroundTasks,
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
        if existing_txn.status != "completed":
            return _failed_body(existing_txn, existing_txn.failure_code, idempotent=True)
        driver = db.get(User, existing_txn.driver_id)
        p_wallet = get_or_create_wallet(passenger.id, db)
        return _success_body(existing_txn, p_wallet, driver, idempotent=True)

    # ── 2. Load and validate the payment request ─────────────────────────────
    pr = db.query(PaymentRequest).filter(
        PaymentRequest.utr == token,
        PaymentRequest.provider == "QR_WALLET",
    ).first()

    if not pr:
        raise HTTPException(status_code=404, detail="Payment request not found.")

    now = datetime.utcnow()
    _expire_if_due(db, pr, now)
    ch = _settle_awaiting_otp(db, pr, now, background_tasks)
    if pr.status == "AwaitingOtp" and ch is not None and ch.passenger_id == passenger.id:
        # Confirm pressed again while the code is pending: the same challenge, no new email.
        return _qr_outcome(db, payment_otp.final_outcome(db, ch, now), background_tasks)
    if pr.status != "Pending":
        return _unavailable(pr, now)

    # ── 3. Validate driver from stored request ───────────────────────────────
    driver = db.get(User, pr.user_id)
    if not driver or driver.account_type != "driver" or driver.status != "active":
        db.query(PaymentRequest).filter(PaymentRequest.id == pr.id, PaymentRequest.status == "Pending").update(
            {"status": "Failed"}, synchronize_session=False
        )
        db.commit()
        raise HTTPException(status_code=400, detail="The driver account is no longer eligible to receive payments.")

    if driver.id == passenger.id:
        db.query(PaymentRequest).filter(PaymentRequest.id == pr.id, PaymentRequest.status == "Pending").update(
            {"status": "Failed"}, synchronize_session=False
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Self-payment is not allowed.")

    fare_dec = Decimal(str(pr.amount))

    # ── 4. Fraud gate (10-minute rule + ML score), before anything is claimed ──
    p_wallet = get_or_create_wallet(passenger.id, db)
    if not p_wallet.is_frozen and p_wallet.balance < fare_dec:
        # Never ask for an OTP on a payment that cannot succeed; the request stays Pending.
        queue_decline_notice(db, background_tasks, passenger=passenger, driver=driver, amount=fare_dec,
                             code="INSUFFICIENT_BALANCE", channel="qr", scoped_key=scoped_key)
        return JSONResponse(status_code=400, content={
            "success": False,
            "code": "insufficient_balance",
            "detail": f"Insufficient wallet balance (₹{float(p_wallet.balance):.2f}). Please add funds first.",
            "balance": float(p_wallet.balance),
            "required": float(fare_dec),
        })
    decision = evaluate_payment(db, passenger, driver, fare_dec, now, scoped_key, "qr", payment_request_id=pr.id)
    if decision["action"] == "otp_required":
        awaiting = db.query(PaymentRequest).filter(
            PaymentRequest.id == pr.id, PaymentRequest.status == "Pending",
        ).update({"status": "AwaitingOtp"}, synchronize_session=False)
        if awaiting != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Payment already being processed. Please wait or try a new QR code.")
        try:
            out = payment_otp.open_challenge(db, passenger=passenger, driver=driver, channel="qr",
                                             scoped_key=scoped_key, amount=fare_dec, now=now,
                                             payment_request_id=pr.id, assessment_id=decision.get("assessment_id"))
        except payment_otp.ChallengeConflict:
            db.rollback()
            raise HTTPException(status_code=409, detail="This idempotency key was used for a different payment.")
        return _qr_outcome(db, out, background_tasks)

    # ── 4b. Claim the request (Pending → processing) atomically ──────────────
    claimed = db.query(PaymentRequest).filter(
        PaymentRequest.id == pr.id,
        PaymentRequest.status == "Pending",
    ).update({"status": "processing"}, synchronize_session=False)
    db.flush()      # flush within the same transaction; commit happens with the wallet transfer

    if claimed != 1:
        # Another request won the race.
        raise HTTPException(status_code=409, detail="Payment already being processed. Please wait or try a new QR code.")

    # ── 5. Wallet operations (same atomic helpers as /api/wallet/pay) ─────────
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
            # Rolls back the Pending → processing claim and any partial debit.
            db.rollback()
            if uid == passenger.id:
                db.refresh(p_wallet)
                if not p_wallet.is_frozen:
                    # Short of funds: the request is Pending again, so the passenger can top up and
                    # retry before it expires. Nothing was charged.
                    queue_decline_notice(db, background_tasks, passenger=passenger, driver=driver, amount=fare_dec,
                                         code="INSUFFICIENT_BALANCE", channel="qr", scoped_key=scoped_key)
                    return JSONResponse(status_code=400, content={
                        "success": False,
                        "code": "insufficient_balance",
                        "detail": f"Insufficient wallet balance (₹{float(p_wallet.balance):.2f}). Please add funds first.",
                        "balance": float(p_wallet.balance),
                        "required": float(fare_dec),
                    })
            # Frozen wallet or driver unable to receive: this request can never succeed.
            try:
                with db.begin_nested():
                    db.query(PaymentRequest).filter(PaymentRequest.id == pr.id).update(
                        {"status": "Failed"}, synchronize_session=False
                    )
            except Exception:
                pass
            db.commit()
            if uid == passenger.id:
                raise HTTPException(status_code=400, detail="Your wallet is frozen. Payment failed.")
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
        otp_verified=False,
        fraud_status="clear",
        transaction_type="ride_payment",
        description=f"₹{fare_dec:.2f} paid to {driver.name} via QR",
        balance_after=p_wallet.balance,
        idempotency_key=scoped_key,
        payment_request_id=pr.id,
        created_at=now,
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
            if existing.status != "completed":
                return _failed_body(existing, existing.failure_code, idempotent=True)
            return _success_body(existing, get_or_create_wallet(passenger.id, db), db.get(User, existing.driver_id),
                                 idempotent=True)
        raise HTTPException(status_code=409, detail="Could not record the payment. Please try again.")

    db.refresh(p_wallet)
    db.refresh(txn)

    # Post-commit notifications (never affect the financial record). Replays and
    # lost races return earlier, so each completed payment is notified once.
    _queue_receipts(background_tasks, txn, passenger, driver, p_wallet.balance)
    return _success_body(txn, p_wallet, driver)


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
    - Reports Expired as soon as the expiry time has passed, even if nothing polled it before.
    - `status` is exactly one of Pending, Processing, AwaitingOtp, Completed, Failed, Expired, Cancelled.
      AwaitingOtp: the passenger is entering an emailed code; keep this QR and keep polling.
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

    # Persist the expiry, but report from the clock either way (see _public_status).
    _expire_if_due(db, pr, now)
    _settle_awaiting_otp(db, pr, now)

    remaining = _seconds_remaining(pr, now)

    resp = {
        "success": True,
        "status": _public_status(pr, now),
        "amount": float(pr.amount),
        "expires_at": _iso_utc(pr.expires_at),
        "remaining_seconds": remaining,
        "seconds_remaining": remaining,
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
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Driver cancels a pending QR payment request safely.
    Only the creating driver can cancel their own request.
    Cancelled requests cannot be paid. Idempotent: always 200 for the owner's request, with
    the resulting `status` (Cancelled, or Expired/Completed/... if it was already settled).

    A request that is AwaitingOtp (the passenger is entering an emailed code) can be cancelled by its own
    driver too: the OTP challenge is cancelled (failure OTP_CANCELLED, a failed transaction is recorded,
    the passenger is notified) and the request becomes Failed. No money moves. A request that has already
    been paid stays Completed: it cannot be cancelled.
    """
    driver = current_user
    if driver.account_type != "driver":
        raise HTTPException(status_code=403, detail="Only driver accounts can cancel QR payment requests.")

    pr = db.query(PaymentRequest).filter(
        PaymentRequest.utr == token,
        PaymentRequest.provider == "QR_WALLET",
        PaymentRequest.user_id == driver.id,
    ).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Payment request not found.")

    now = datetime.utcnow()
    # A request already past its deadline is Expired, not Cancelled, and cancelling it still succeeds.
    _expire_if_due(db, pr, now)

    ch = _settle_awaiting_otp(db, pr, now, background_tasks)
    if pr.status == "AwaitingOtp" and ch is not None:
        out = payment_otp.cancel(db, ch, now)
        _queue_notices(out, background_tasks)
        db.refresh(pr)
        if out.kind == "failed":
            return {"success": True, "status": pr.status, "code": out.code,
                    "message": "Payment cancelled during verification. Nothing was charged."}
        return {"success": True, "status": _public_status(pr, now), "message": f"Request is already {pr.status}."}

    cancelled = db.query(PaymentRequest).filter(
        PaymentRequest.id == pr.id,
        PaymentRequest.status == "Pending",
    ).update({"status": "Cancelled"}, synchronize_session=False)
    db.commit()
    db.refresh(pr)

    status = _public_status(pr, now)
    if cancelled:
        return {"success": True, "status": "Cancelled", "message": "Payment request cancelled."}
    # Idempotent: repeating a cancel (or cancelling an expired/finished request) is not an error.
    # `status` tells the terminal what actually happened - e.g. Completed if the passenger paid first.
    return {"success": True, "status": status, "message": f"Request is already {status}."}


# ──────────────────────────── OTP step-up (passenger) ─────────────────────────

class QROtpRequest(BaseModel):
    challenge_id: Optional[str] = None
    otp: Optional[str] = None


def _passenger_challenge(token: str, data: QROtpRequest, passenger: User, db: Session):
    """The passenger's own challenge for this QR request, or an HTTPException."""
    if passenger.account_type != "passenger":
        raise HTTPException(status_code=403, detail="Only passenger accounts can verify QR payments.")
    pr = db.query(PaymentRequest).filter(PaymentRequest.utr == token, PaymentRequest.provider == "QR_WALLET").first()
    ch = payment_otp.get_challenge(db, data.challenge_id)
    if (pr is None or ch is None or ch.channel != "qr" or ch.passenger_id != passenger.id
            or ch.payment_request_id != pr.id):
        raise HTTPException(status_code=404, detail="Verification not found for this payment.")
    return ch


@router.post("/{token}/verify-otp")
def verify_qr_otp(token: str, data: QROtpRequest, background_tasks: BackgroundTasks,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ch = _passenger_challenge(token, data, current_user, db)
    return _qr_outcome(db, payment_otp.verify(db, ch, data.otp, datetime.utcnow()), background_tasks)


@router.post("/{token}/resend-otp")
def resend_qr_otp(token: str, data: QROtpRequest, background_tasks: BackgroundTasks,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ch = _passenger_challenge(token, data, current_user, db)
    now = datetime.utcnow()
    out, refused = payment_otp.resend(db, ch, now)
    if refused:
        return JSONResponse(status_code=429 if refused[0] == "resend_cooldown" else 400,
                            content={"success": False, "status": "otp_required", "code": refused[0],
                                     "detail": refused[1], **payment_otp.public_view(ch, current_user, now)})
    return _qr_outcome(db, out, background_tasks)


@router.post("/{token}/cancel-otp")
def cancel_qr_otp(token: str, data: QROtpRequest, background_tasks: BackgroundTasks,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ch = _passenger_challenge(token, data, current_user, db)
    return _qr_outcome(db, payment_otp.cancel(db, ch, datetime.utcnow()), background_tasks)
