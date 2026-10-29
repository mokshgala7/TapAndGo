from decimal import Decimal, InvalidOperation
import json
import math
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Transaction, User, Wallet, EmailOTP, WithdrawalRequest
from app.utils.email_service import (
    send_withdrawal_otp,
    send_withdrawal_email,
    send_ride_passenger_email,
    send_ride_driver_email,
    send_withdrawal_approved_email,
    send_withdrawal_paid_email,
    send_withdrawal_rejected_email,
)
from app.utils.security import get_elapsed_seconds, is_otp_expired, generate_otp
from app.routes.auth import get_current_user
from sqlalchemy import func
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wallet", tags=["Wallet"])


class TopupRequest(BaseModel):
    user_id: int
    amount: float
    payment_method: Optional[str] = "razorpay"
    idempotency_key: Optional[str] = None


class WithdrawOTPRequest(BaseModel):
    # `user_id` is accepted only for older clients. The acting user is always
    # the authenticated session; a different id is rejected.
    user_id: Optional[int] = None
    amount: float


class WithdrawRequest(BaseModel):
    user_id: Optional[int] = None
    amount: float
    otp: Optional[str] = None
    idempotency_key: Optional[str] = None


class PayRequest(BaseModel):
    # `passenger_id` is accepted only for older clients; it must equal the
    # authenticated user. `driver_id` and `idempotency_key` are mandatory.
    passenger_id: Optional[int] = None
    driver_id: int
    fare: float
    vehicle_type: Optional[str] = None
    vehicle_number: Optional[str] = None
    driver_name: Optional[str] = None
    payment_method: Optional[str] = "QR"
    idempotency_key: str


MAX_PAYMENT_AMOUNT = Decimal(os.getenv("MAX_PAYMENT_AMOUNT", "50000"))


def to_money(value: float) -> Decimal:
    """Validate a client-supplied rupee amount and return it as a 2-dp Decimal."""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise HTTPException(status_code=400, detail="Amount is not valid.")
    try:
        dec = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Amount is not valid.")
    if dec <= 0:
        raise HTTPException(status_code=400, detail="Amount must be at least ₹0.01.")
    if Decimal(str(value)) != dec:
        raise HTTPException(status_code=400, detail="Amount can have at most two decimal places.")
    return dec


def own_user_id(claimed: Optional[int], current_user: User) -> int:
    """The acting user always comes from the session; a conflicting id is refused."""
    if claimed is not None and claimed != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to act for another user.")
    return current_user.id


def wallet_to_dict(wallet: Wallet):
    return {
        "id": wallet.id,
        "user_id": wallet.user_id,
        "balance": float(wallet.balance),
        "is_frozen": wallet.is_frozen,
        "updated_at": wallet.updated_at.isoformat() if wallet.updated_at else None,
    }


def get_or_create_wallet(user_id: int, db: Session, for_update: bool = False) -> Wallet:
    query = db.query(Wallet).filter(Wallet.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    wallet = query.first()
    if not wallet:
        wallet = Wallet(user_id=user_id, balance=Decimal("0.00"), is_frozen=False)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        if for_update:
            wallet = db.query(Wallet).filter(Wallet.user_id == user_id).with_for_update().first()
    return wallet


@router.get("/{user_id}")
def get_user_wallet(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this wallet.")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    wallet = get_or_create_wallet(user_id, db)
    return {"success": True, "wallet": wallet_to_dict(wallet)}


@router.get("/{user_id}/transactions")
def get_user_transactions(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view these transactions.")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    wallet = get_or_create_wallet(user_id, db)

    txns = db.query(Transaction).filter(
        or_(
            Transaction.passenger_id == user_id,
            Transaction.driver_id == user_id,
            Transaction.wallet_id == wallet.id,
        )
    ).order_by(Transaction.created_at.asc(), Transaction.id.asc()).all()

    user_ids = set()
    for t in txns:
        if t.passenger_id:
            user_ids.add(t.passenger_id)
        if t.driver_id:
            user_ids.add(t.driver_id)

    user_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        user_map = {u.id: u.name for u in users}

    formatted_txns = []
    running_balance = Decimal("0.00")
    last_balance = None     # wallet balance shown on the most recent row that moved money

    for t in txns:
        amount_dec = Decimal(str(t.amount))
        is_credit = False
        change = amount_dec

        if t.status == "failed":
            # A failed tap moved no money: shown with its amount and reason, but never in the running balance.
            who = user_map.get(t.driver_id, "the driver") if t.passenger_id == user_id else user_map.get(t.passenger_id)
            reason = (t.description or "Payment failed").replace("NFC payment failed: ", "", 1)
            shown_balance = last_balance if last_balance is not None else float(running_balance)
            formatted_txns.append({
                "id": t.reference or f"TXN-{t.id}",
                "reference": t.reference,
                "type": "Failed Ride Payment",
                "description": (
                    f"\u20b9{float(abs(amount_dec)):.2f} payment to {who} failed: {reason}"
                    if t.passenger_id == user_id else
                    f"\u20b9{float(abs(amount_dec)):.2f} payment {f'from {who} ' if who else ''}failed: {reason}"
                ),
                "amount": float(abs(amount_dec)),
                "fare": float(abs(amount_dec)),
                "is_credit": False,
                "payment_method": t.payment_method.upper() if t.payment_method else "NFC",
                "status": "Failed",
                "failure_code": t.failure_code,
                "failure_reason": reason,
                "balance_after": shown_balance,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "timestamp": int(t.created_at.timestamp() * 1000) if t.created_at else 0,
                "passenger_id": t.passenger_id,
                "driver_id": t.driver_id,
                "driver": user_map.get(t.driver_id, "Driver"),
                "passenger": user_map.get(t.passenger_id, "Passenger"),
                "transaction_type": t.transaction_type,
            })
            continue

        if t.transaction_type == "withdrawal_reversal":
            # Refund of a rejected withdrawal: money returned to the wallet.
            is_credit = True
            change = abs(amount_dec)
            type_label = "Withdrawal Reversal"
            description = t.description or f"₹{float(change):.2f} returned to wallet"
        elif t.transaction_type == "deposit" and t.passenger_id != user_id:
            # A driver's own deposit is filed under the driver id; it is not a ride payment.
            is_credit = True
            change = abs(amount_dec)
            type_label = "Add Money (Razorpay)" if t.payment_method == "razorpay" or t.provider == "RAZORPAY" else "Deposit"
            description = t.description or f"₹{float(change):.2f} credited to wallet"
        elif t.passenger_id == user_id:
            if t.payment_method in ("razorpay", "topup", "payment_gateway", "deposit", "upi") or t.transaction_type == "deposit" or t.amount < 0:
                is_credit = True
                change = abs(amount_dec)
                type_label = "Add Money (Razorpay)" if t.payment_method == "razorpay" or t.provider == "RAZORPAY" else "Deposit"
                description = t.description or f"₹{float(change):.2f} credited to wallet"
            elif t.payment_method == "bank_transfer" or t.transaction_type == "withdrawal":
                is_credit = False
                change = abs(amount_dec)
                type_label = "Withdrawal"
                description = t.description or f"₹{float(change):.2f} transferred to bank account"
            else:
                is_credit = False
                change = abs(amount_dec)
                d_name = user_map.get(t.driver_id, f"Driver #{t.driver_id}" if t.driver_id else "Driver")
                type_label = "Ride Payment"
                description = f"₹{float(change):.2f} paid to {d_name}"
        elif t.driver_id == user_id:
            if t.payment_method == "bank_transfer" or t.transaction_type == "withdrawal":
                is_credit = False
                change = abs(amount_dec)
                type_label = "Withdrawal"
                description = t.description or f"₹{float(change):.2f} transferred to bank account"
            else:
                is_credit = True
                change = abs(amount_dec)
                p_name = user_map.get(t.passenger_id, f"Passenger #{t.passenger_id}" if t.passenger_id else "Passenger")
                type_label = "Ride Payment Received"
                description = f"₹{float(change):.2f} received from {p_name}"
        else:
            is_credit = t.amount > 0
            change = abs(amount_dec)
            type_label = "Deposit" if is_credit else "Payment"
            description = t.description or f"₹{float(change):.2f} {'credited to' if is_credit else 'debited from'} wallet"

        if is_credit:
            running_balance += change
        else:
            running_balance -= change

        final_balance_after = float(t.balance_after) if t.balance_after is not None else float(running_balance)
        last_balance = final_balance_after

        formatted_txns.append({
            "id": t.reference or f"TXN-{t.id}",
            "reference": t.reference,
            "type": type_label,
            "description": description,
            "amount": float(change),
            "fare": -float(change) if is_credit else float(change),
            "is_credit": is_credit,
            "payment_method": t.payment_method.upper() if t.payment_method else "WALLET",
            "status": t.status.title() if t.status else "Completed",
            "balance_after": final_balance_after,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "timestamp": int(t.created_at.timestamp() * 1000) if t.created_at else 0,
            "passenger_id": t.passenger_id,
            "driver_id": t.driver_id,
            "driver": user_map.get(t.driver_id, "Driver"),
            "passenger": user_map.get(t.passenger_id, "Passenger"),
            "transaction_type": t.transaction_type,
        })

    formatted_txns.reverse()

    return {
        "success": True,
        "transactions": formatted_txns
    }




def _lock_order(*user_ids):
    """Stable order for touching two wallets, so opposing payments cannot deadlock."""
    return sorted(set(user_ids))


def _debit(db: Session, user_id: int, amount: Decimal) -> bool:
    """Atomic conditional debit: succeeds only if the wallet is not frozen and has funds."""
    return db.query(Wallet).filter(
        Wallet.user_id == user_id, Wallet.is_frozen.is_(False), Wallet.balance >= amount
    ).update({Wallet.balance: Wallet.balance - amount}, synchronize_session=False) == 1


def _credit(db: Session, user_id: int, amount: Decimal, allow_frozen: bool = False) -> bool:
    q = db.query(Wallet).filter(Wallet.user_id == user_id)
    if not allow_frozen:
        q = q.filter(Wallet.is_frozen.is_(False))
    return q.update({Wallet.balance: Wallet.balance + amount}, synchronize_session=False) == 1


# ───────────────────────────── withdrawals ──────────────────────────────────

@router.post("/withdraw/request-otp")
def request_withdrawal_otp(
    data: WithdrawOTPRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generates and emails a single-use withdrawal OTP to the authenticated
    user's own address. The OTP is bound to the user and to the exact amount.
    - 5-minute expiration, 60-second cooldown (HTTP 429), prior OTPs invalidated.
    """
    own_user_id(data.user_id, current_user)
    withdraw_dec = to_money(data.amount)

    user = current_user
    if not (user.bank_account_number and user.bank_account_number.strip()) and not (user.bank_upi_id and user.bank_upi_id.strip()):
        raise HTTPException(
            status_code=400,
            detail="No saved payout destination found (Bank account or UPI ID). Please update your bank details in profile first."
        )

    wallet = get_or_create_wallet(user.id, db)
    if wallet.is_frozen:
        raise HTTPException(status_code=400, detail="Your wallet is frozen. Withdrawals are disabled.")

    if wallet.balance < withdraw_dec:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient wallet balance (Available: ₹{float(wallet.balance):.2f})."
        )

    clean_email = user.email.strip().lower()

    existing_otp = db.query(EmailOTP).filter(
        func.lower(EmailOTP.email) == clean_email,
        or_(
            EmailOTP.reason == "withdraw_balance",
            EmailOTP.purpose.in_(["withdraw_balance", "withdrawal"]),
        )
    ).order_by(EmailOTP.created_at.desc()).first()

    if existing_otp and existing_otp.created_at:
        elapsed = get_elapsed_seconds(existing_otp.created_at)
        if elapsed < 60:
            remaining_seconds = max(1, min(60, int(60 - elapsed)))
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {remaining_seconds} seconds before requesting another withdrawal OTP."
            )

    db.query(EmailOTP).filter(
        func.lower(EmailOTP.email) == clean_email,
        or_(
            EmailOTP.reason == "withdraw_balance",
            EmailOTP.purpose.in_(["withdraw_balance", "withdrawal"]),
        ),
        EmailOTP.used == False,
    ).update({"used": True}, synchronize_session=False)

    otp_code = generate_otp()
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    db.add(EmailOTP(
        email=user.email,
        otp=otp_code,
        reason="withdraw_balance",
        purpose="withdraw_balance",
        attempts=0,
        is_verified=False,
        used=False,
        expires_at=expires_at,
        otp_metadata=json.dumps({"amount": str(withdraw_dec), "user_id": user.id}),
    ))
    db.commit()

    email_sent = send_withdrawal_otp(to_email=user.email, otp=otp_code, amount=float(withdraw_dec))

    dest_str = f"Bank Account (ending in {user.bank_account_number.strip()[-4:]})" if user.bank_account_number else f"UPI ID ({user.bank_upi_id})"

    return {
        "success": True,
        "message": f"Withdrawal OTP has been sent to {user.email}. Target destination: {dest_str}",
        "otp_required": True,
        "email_sent": email_sent
    }


def _withdrawal_replay(db: Session, key: str, user: User, amount: Decimal):
    existing = db.query(WithdrawalRequest).filter(
        WithdrawalRequest.idempotency_key == key, WithdrawalRequest.user_id == user.id
    ).first()
    if not existing:
        return None
    if existing.amount != amount:
        raise HTTPException(status_code=409, detail="This idempotency key was used for a different withdrawal.")
    wallet = get_or_create_wallet(user.id, db)
    return {
        "success": True,
        "message": "Withdrawal request already submitted. Awaiting admin review.",
        "wallet": wallet_to_dict(wallet),
        "request_id": existing.id,
        "request_status": existing.status,
        "reference": existing.reference,
        "idempotent": True,
    }


@router.post("/withdraw")
def withdraw_to_bank(
    data: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submits a withdrawal request for the authenticated user.

    Requires the emailed OTP, which must belong to this user and be bound to the
    exact amount. The OTP is consumed, the balance reserved, and the request
    created in ONE transaction. Replays with the same idempotency key (scoped to
    the user) return the original request.
    """
    own_user_id(data.user_id, current_user)
    user = current_user
    withdraw_dec = to_money(data.amount)

    scoped_key = None
    if data.idempotency_key:
        if len(data.idempotency_key) > 100:
            raise HTTPException(status_code=400, detail="Idempotency key is too long.")
        scoped_key = f"wd:{user.id}:{data.idempotency_key}"
        replay = _withdrawal_replay(db, scoped_key, user, withdraw_dec)
        if replay:
            return replay

    has_bank = user.bank_account_number and user.bank_account_number.strip()
    has_upi = user.bank_upi_id and user.bank_upi_id.strip()
    if not has_bank and not has_upi:
        raise HTTPException(
            status_code=400,
            detail="No saved payout destination found. Please add bank or UPI details in your Profile first."
        )

    if not data.otp or not data.otp.strip():
        raise HTTPException(status_code=400, detail="Email OTP is required for withdrawal confirmation.")

    clean_email = user.email.strip().lower()
    db_otp = db.query(EmailOTP).filter(
        func.lower(EmailOTP.email) == clean_email,
        or_(
            EmailOTP.reason == "withdraw_balance",
            EmailOTP.purpose.in_(["withdraw_balance", "withdrawal"]),
        ),
        EmailOTP.used == False,
    ).order_by(EmailOTP.created_at.desc()).first()

    if not db_otp:
        raise HTTPException(status_code=400, detail="No withdrawal OTP found. Please request a new OTP.")

    if db_otp.attempts >= 5:
        db_otp.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Too many incorrect OTP attempts. Please request a new OTP.")

    if is_otp_expired(db_otp.expires_at):
        db_otp.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new OTP.")

    if db_otp.otp != data.otp.strip():
        db_otp.attempts += 1
        if db_otp.attempts >= 5:
            db_otp.used = True
        db.commit()
        if db_otp.attempts >= 5:
            raise HTTPException(status_code=400, detail="Too many incorrect OTP attempts. Please request a new OTP.")
        remaining = max(0, 5 - db_otp.attempts)
        raise HTTPException(status_code=400, detail=f"Invalid OTP code. ({remaining} attempts remaining)")

    # The OTP must have been issued to this user for exactly this amount.
    try:
        meta = json.loads(db_otp.otp_metadata) if db_otp.otp_metadata else None
    except ValueError:
        meta = None
    if (
        not isinstance(meta, dict)
        or meta.get("user_id") != user.id
        or Decimal(str(meta.get("amount", "-1"))) != withdraw_dec
    ):
        db_otp.attempts += 1
        if db_otp.attempts >= 5:
            db_otp.used = True
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="This OTP was not issued for this withdrawal amount. Please request a new OTP.",
        )

    wallet = get_or_create_wallet(user.id, db)
    if wallet.is_frozen:
        raise HTTPException(status_code=400, detail="Your wallet is frozen. Withdrawals are disabled.")

    # ── One transaction: consume the OTP, reserve the funds, record the request ──
    consumed = db.query(EmailOTP).filter(
        EmailOTP.id == db_otp.id, EmailOTP.used == False
    ).update({"used": True, "is_verified": True}, synchronize_session=False)
    if consumed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This OTP has already been used. Please request a new OTP.")

    if not _debit(db, user.id, withdraw_dec):
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Insufficient wallet balance or wallet unavailable.",
        )
    db.refresh(wallet)

    dest_desc = f"Bank Account (XXXX XXXX {user.bank_account_number.strip()[-4:]})" if has_bank else f"UPI ID ({user.bank_upi_id})"
    ref_code = f"WD-{uuid.uuid4().hex[:10].upper()}"
    desc = f"₹{withdraw_dec:.2f} withdrawal hold — pending admin approval to {dest_desc}"

    hold_txn = Transaction(
        reference=ref_code,
        passenger_id=user.id if user.account_type == "passenger" else None,
        driver_id=user.id if user.account_type == "driver" else None,
        wallet_id=wallet.id,
        amount=withdraw_dec,
        payment_method="bank_transfer",
        status="pending",
        otp_verified=True,
        fraud_status="clear",
        transaction_type="withdrawal_hold",
        description=desc,
        balance_after=wallet.balance,
        idempotency_key=scoped_key,
    )
    db.add(hold_txn)
    try:
        db.flush()
        wr = WithdrawalRequest(
            user_id=user.id,
            wallet_id=wallet.id,
            hold_transaction_id=hold_txn.id,
            amount=withdraw_dec,
            destination_desc=dest_desc,
            reference=ref_code,
            otp_verified=True,
            status="pending",
            idempotency_key=scoped_key,
        )
        db.add(wr)
        db.commit()
    except IntegrityError:
        # A concurrent request with the same idempotency key won the race.
        db.rollback()
        replay = _withdrawal_replay(db, scoped_key, user, withdraw_dec) if scoped_key else None
        if replay:
            return replay
        raise HTTPException(status_code=409, detail="Could not record the withdrawal. Please try again.")
    db.refresh(wallet)
    db.refresh(hold_txn)
    db.refresh(wr)

    try:
        send_withdrawal_email(
            to_email=user.email,
            user_name=user.name,
            amount=float(withdraw_dec),
            reference=ref_code,
            destination=dest_desc,
            status="Pending Admin Review",
        )
    except Exception as e:
        logger.warning(f"[WithdrawalEmail] Notification delivery failed: {e}")

    return {
        "success": True,
        "message": f"Withdrawal request of ₹{withdraw_dec:.2f} submitted and is pending admin review. Your balance has been reserved.",
        "wallet": wallet_to_dict(wallet),
        "request_id": wr.id,
        "request_status": wr.status,
        "reference": wr.reference,
    }


@router.get("/withdraw/history")
def get_withdrawal_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Returns the authenticated user's withdrawal request history.
    User identity is derived from the session - no user_id parameter accepted.
    """
    requests = db.query(WithdrawalRequest).filter(
        WithdrawalRequest.user_id == current_user.id
    ).order_by(WithdrawalRequest.created_at.desc()).all()

    return {
        "success": True,
        "withdrawal_requests": [
            {
                "id": wr.id,
                "reference": wr.reference,
                "amount": float(wr.amount),
                "destination_desc": wr.destination_desc,
                "status": wr.status,
                "admin_note": wr.admin_note,
                "created_at": wr.created_at.isoformat() if wr.created_at else None,
                "reviewed_at": wr.reviewed_at.isoformat() if wr.reviewed_at else None,
                "paid_at": wr.paid_at.isoformat() if wr.paid_at else None,
            }
            for wr in requests
        ]
    }


# ───────────────────────────── ride payment ─────────────────────────────────

def _pay_response(txn: Transaction, wallet: Wallet, driver_name: str, message: str, idempotent: bool = False):
    body = {
        "success": True,
        "message": message,
        "wallet": wallet_to_dict(wallet),
        "transaction": {
            "id": txn.id,
            "reference": txn.reference,
            "status": txn.status,
            "amount": float(txn.amount),
            "driver_id": txn.driver_id,
            "driver_name": driver_name,
            "created_at": txn.created_at.isoformat() if txn.created_at else None,
        },
    }
    if idempotent:
        body["idempotent"] = True
    return body


@router.post("/pay")
def pay_fare(
    data: PayRequest,
    background_tasks: BackgroundTasks = None,       # injected by FastAPI; optional for direct callers
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Passenger wallet -> driver wallet (internal ledger; Razorpay is not involved).

    - The payer is the authenticated passenger; `passenger_id` is never trusted.
    - `driver_id` is mandatory and must be another, active driver. There is no
      fallback to any other driver.
    - Both wallets are checked and changed in ONE transaction with atomic
      conditional updates: nothing is debited unless the recipient can be
      credited, and a failed request changes nothing.
    - `idempotency_key` is mandatory and scoped to the payer; a replay returns
      the original transaction, a conflicting reuse is refused.
    - Fraud gate (app/services/fraud_gate.py): with TAPGO_FRAUD_MODE=enforce a flagged payment answers
      {"success": false, "status": "otp_required", "challenge_id", ...} and moves no money until
      POST /api/wallet/pay/verify-otp succeeds.
    """
    passenger = current_user
    own_user_id(data.passenger_id, passenger)
    if passenger.account_type != "passenger" or passenger.status != "active":
        raise HTTPException(status_code=403, detail="Only active passenger accounts can pay.")

    fare_dec = to_money(data.fare)
    if fare_dec > MAX_PAYMENT_AMOUNT:
        raise HTTPException(status_code=400, detail=f"Payments are limited to ₹{MAX_PAYMENT_AMOUNT:.2f} each.")

    key = (data.idempotency_key or "").strip()
    if len(key) < 8 or len(key) > 100:
        raise HTTPException(status_code=400, detail="A valid idempotency key is required.")
    scoped_key = f"pay:{passenger.id}:{key}"

    def replay():
        existing = db.query(Transaction).filter(Transaction.idempotency_key == scoped_key).first()
        if not existing:
            return None
        if existing.driver_id != data.driver_id or existing.amount != fare_dec:
            raise HTTPException(status_code=409, detail="This idempotency key was used for a different payment.")
        if existing.status != "completed":
            return _otp_failed_response(existing, existing.failure_code, idempotent=True)
        drv = db.get(User, existing.driver_id)
        return _pay_response(
            existing, get_or_create_wallet(passenger.id, db), drv.name if drv else "Driver",
            f"Payment of ₹{fare_dec:.2f} completed.", idempotent=True,
        )

    done = replay()
    if done:
        return done

    from app.services import payment_otp
    from app.services.fraud_gate import evaluate_payment

    pending = payment_otp.pending_for_key(db, scoped_key)
    if pending is not None:
        if pending.driver_id != data.driver_id or pending.amount != fare_dec:
            raise HTTPException(status_code=409, detail="This idempotency key was used for a different payment.")
        now = datetime.utcnow()
        return _wallet_otp_outcome(db, payment_otp.expire_if_due(db, pending, now)
                                   or payment_otp.final_outcome(db, pending, now), background_tasks)

    driver = db.get(User, data.driver_id)
    if not driver or driver.account_type != "driver" or driver.status != "active" or driver.id == passenger.id:
        raise HTTPException(status_code=400, detail="The recipient is not an eligible driver.")

    # Wallet rows must exist before the money transaction starts (creating one commits).
    p_wallet = get_or_create_wallet(passenger.id, db)
    d_wallet = get_or_create_wallet(driver.id, db)
    if p_wallet.is_frozen:
        raise HTTPException(status_code=400, detail="Your passenger wallet is frozen. Payment failed.")
    if d_wallet.is_frozen:
        raise HTTPException(status_code=400, detail="The driver cannot receive payments right now.")
    if p_wallet.balance < fare_dec:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient wallet balance (₹{float(p_wallet.balance):.2f}). Please add funds first."
        )

    now = datetime.utcnow()
    decision = evaluate_payment(db, passenger, driver, fare_dec, now, scoped_key, "wallet")
    if decision["action"] == "otp_required":
        try:
            out = payment_otp.open_challenge(db, passenger=passenger, driver=driver, channel="wallet",
                                             scoped_key=scoped_key, amount=fare_dec, now=now,
                                             assessment_id=decision.get("assessment_id"))
        except payment_otp.ChallengeConflict:
            raise HTTPException(status_code=409, detail="This idempotency key was used for a different payment.")
        return _wallet_otp_outcome(db, out, background_tasks)

    steps = {
        passenger.id: lambda: _debit(db, passenger.id, fare_dec),
        driver.id: lambda: _credit(db, driver.id, fare_dec),
    }
    for uid in _lock_order(passenger.id, driver.id):
        if not steps[uid]():
            db.rollback()
            if uid == passenger.id:
                db.refresh(p_wallet)
                if p_wallet.is_frozen:
                    raise HTTPException(status_code=400, detail="Your passenger wallet is frozen. Payment failed.")
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient wallet balance (₹{float(p_wallet.balance):.2f}). Please add funds first."
                )
            raise HTTPException(status_code=400, detail="The driver cannot receive payments right now.")

    db.refresh(p_wallet)
    ref_code = f"TXN{uuid.uuid4().hex[:10].upper()}"
    txn = Transaction(
        reference=ref_code,
        passenger_id=passenger.id,
        driver_id=driver.id,
        wallet_id=p_wallet.id,
        amount=fare_dec,
        payment_method=(data.payment_method or "QR")[:20],
        status="completed",
        otp_verified=False,
        fraud_status="clear",
        transaction_type="ride_payment",
        description=f"₹{fare_dec:.2f} paid to {driver.name}",
        balance_after=p_wallet.balance,
        idempotency_key=scoped_key,
        created_at=now,
    )
    db.add(txn)
    try:
        db.commit()
    except IntegrityError:
        # Another request with the same key committed first: nothing of ours persists.
        db.rollback()
        done = replay()
        if done:
            return done
        raise HTTPException(status_code=409, detail="Could not record the payment. Please try again.")
    db.refresh(p_wallet)
    db.refresh(txn)

    # Post-commit notifications (never affect the financial record)
    try:
        if passenger.email:
            send_ride_passenger_email(
                to_email=passenger.email,
                passenger_name=passenger.name,
                fare=float(fare_dec),
                driver_name=driver.name,
                reference=ref_code,
                status="Successful",
                vehicle_type=driver.vehicle_type or data.vehicle_type,
                vehicle_registration=driver.vehicle_registration or data.vehicle_number,
                payment_method=txn.payment_method,
                balance_after=float(p_wallet.balance),
                created_at=txn.created_at,
            )
    except Exception as e:
        logger.warning(f"[RideEmail] Passenger receipt failed: {e}")

    try:
        if driver.email:
            send_ride_driver_email(
                to_email=driver.email,
                driver_name=driver.name,
                fare=float(fare_dec),
                passenger_name=passenger.name,
                reference=ref_code,
                payment_method=txn.payment_method,
            )
    except Exception as e:
        logger.warning(f"[RideEmail] Driver credit receipt failed: {e}")

    return _pay_response(txn, p_wallet, driver.name, f"Payment of ₹{fare_dec:.2f} completed.")


# ───────────────────────────── ride payment OTP step-up ─────────────────────

_WALLET_OTP_MESSAGES = {
    "OTP_FAILED": "Wrong code entered too many times. The payment was cancelled and nothing was charged.",
    "OTP_EXPIRED": "The verification code expired. The payment was cancelled and nothing was charged.",
    "OTP_CANCELLED": "The payment was cancelled. Nothing was charged.",
    "OTP_UNAVAILABLE": "This payment needs email verification, but no code could be sent to your registered "
                       "email. The payment was declined and nothing was charged.",
    "INSUFFICIENT_BALANCE": "Insufficient wallet balance. Nothing was charged.",
    "WALLET_FROZEN": "Your passenger wallet is frozen. Payment failed.",
    "PASSENGER_INACTIVE": "Your account is not active. Payment failed.",
    "DRIVER_UNAVAILABLE": "The driver cannot receive payments right now.",
}


def _otp_failed_response(txn: Optional[Transaction], code: Optional[str], idempotent: bool = False):
    from fastapi.responses import JSONResponse
    content = {"success": False, "status": "Failed", "code": code or "FAILED",
               "detail": _WALLET_OTP_MESSAGES.get(code, "The payment could not be completed. Nothing was charged.")}
    if txn is not None:
        content["reference"] = txn.reference
    if idempotent:
        content["idempotent"] = True
    return JSONResponse(status_code=400, content=content)


def _send_otp_failure_notice(**kwargs):
    from app.utils.nfc_failure_email import send_nfc_failure_email
    try:
        send_nfc_failure_email(**kwargs)
    except Exception as e:
        logger.warning(f"[RideEmail] Failure notice failed: {e}")


def _wallet_otp_outcome(db: Session, out, background_tasks: BackgroundTasks):
    from fastapi.responses import JSONResponse
    from app.services import payment_otp
    now = datetime.utcnow()
    for notice in out.notices:
        if background_tasks is not None:
            background_tasks.add_task(_send_otp_failure_notice, **notice)
        else:
            _send_otp_failure_notice(**notice)
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
        txn = out.txn
        passenger, driver = db.get(User, txn.passenger_id), db.get(User, txn.driver_id)
        p_wallet = get_or_create_wallet(passenger.id, db)
        if not out.idempotent:
            try:
                if passenger.email:
                    send_ride_passenger_email(
                        to_email=passenger.email, passenger_name=passenger.name, fare=float(txn.amount),
                        driver_name=driver.name, reference=txn.reference, status="Successful",
                        vehicle_type=driver.vehicle_type, vehicle_registration=driver.vehicle_registration,
                        payment_method=txn.payment_method, balance_after=float(txn.balance_after),
                        created_at=txn.created_at,
                    )
            except Exception as e:
                logger.warning(f"[RideEmail] Passenger receipt failed: {e}")
            try:
                if driver.email:
                    send_ride_driver_email(
                        to_email=driver.email, driver_name=driver.name, fare=float(txn.amount),
                        passenger_name=passenger.name, reference=txn.reference, payment_method=txn.payment_method,
                    )
            except Exception as e:
                logger.warning(f"[RideEmail] Driver credit receipt failed: {e}")
        return _pay_response(txn, p_wallet, driver.name if driver else "Driver",
                             f"Payment of ₹{float(txn.amount):.2f} completed.", idempotent=out.idempotent)
    return _otp_failed_response(out.txn, out.code, idempotent=out.idempotent)


class PayOtpRequest(BaseModel):
    challenge_id: Optional[str] = None
    otp: Optional[str] = None


def _own_wallet_challenge(data: PayOtpRequest, passenger: User, db: Session):
    from app.services import payment_otp
    ch = payment_otp.get_challenge(db, data.challenge_id)
    if ch is None or ch.channel != "wallet" or ch.passenger_id != passenger.id:
        raise HTTPException(status_code=404, detail="Verification not found for this payment.")
    return ch


@router.post("/pay/verify-otp")
def verify_pay_otp(data: PayOtpRequest, background_tasks: BackgroundTasks,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services import payment_otp
    ch = _own_wallet_challenge(data, current_user, db)
    return _wallet_otp_outcome(db, payment_otp.verify(db, ch, data.otp, datetime.utcnow()), background_tasks)


@router.post("/pay/resend-otp")
def resend_pay_otp(data: PayOtpRequest, background_tasks: BackgroundTasks,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    from app.services import payment_otp
    ch = _own_wallet_challenge(data, current_user, db)
    now = datetime.utcnow()
    out, refused = payment_otp.resend(db, ch, now)
    if refused:
        return JSONResponse(status_code=429 if refused[0] == "resend_cooldown" else 400,
                            content={"success": False, "status": "otp_required", "code": refused[0],
                                     "detail": refused[1], **payment_otp.public_view(ch, current_user, now)})
    return _wallet_otp_outcome(db, out, background_tasks)


@router.post("/pay/cancel-otp")
def cancel_pay_otp(data: PayOtpRequest, background_tasks: BackgroundTasks,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services import payment_otp
    ch = _own_wallet_challenge(data, current_user, db)
    return _wallet_otp_outcome(db, payment_otp.cancel(db, ch, datetime.utcnow()), background_tasks)
