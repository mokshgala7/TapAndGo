"""
Email OTP step-up for ride payments the fraud gate sent to `otp_required` (QR, NFC and wallet pay share it).

Fail-closed rules
─────────────────
- No wallet is debited or credited and no completed Transaction exists until the OTP is verified. The debit, the
  credit, the completed Transaction and the challenge's `completed` status commit in ONE database transaction.
- Only an HMAC-SHA256 of the code is stored (keyed with PAYMENT_OTP_SECRET, else SECRET_KEY, and bound to the
  challenge id). The code is never logged and never returned by any API; comparison is constant-time.
- TTL 5 minutes; 3 wrong attempts; single use; at most 2 resends, 30 s apart (a resend issues a new code and a new
  5-minute window; the old code stops working).
- A challenge is bound to passenger, driver, amount, channel and the route's scoped idempotency key (plus card UID
  for NFC and payment request for QR). One pending challenge per (passenger, key): a replay returns it without a
  new email. One pending challenge per passenger: a new one supersedes (cancels) the old one.
- Wrong x3 / expiry / cancel / supersede / undeliverable email: the challenge is closed and a FAILED Transaction is
  recorded with failure_code OTP_FAILED / OTP_EXPIRED / OTP_CANCELLED / OTP_UNAVAILABLE (the existing failed-tap
  mechanism), the QR request becomes Failed, and the owner gets the existing failure email. No money moves.
- A passenger with no email on file (or a send failure) is DECLINED: the payment never proceeds without an OTP.
"""
import hashlib
import hmac
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import NFCCard, PaymentOtpChallenge, PaymentRequest, Transaction, User
from app.services.fraud_gate import otp_recipient
from app.utils.email_service import send_payment_otp
from app.utils.security import generate_otp

logger = logging.getLogger(__name__)

OTP_TTL_SECONDS = 300
MAX_ATTEMPTS = 3
MAX_RESENDS = 2
RESEND_COOLDOWN_SECONDS = 30

OTP_EMAIL_TIMEOUT_S = float(os.getenv("TAPGO_OTP_EMAIL_TIMEOUT_SECONDS", "10"))   # a slow mail provider must not hold the request
_EMAIL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="otp-mail")

PAYMENT_METHODS = {"nfc": "NFC", "qr": "QR", "wallet": "wallet"}
FAILURE_STATUS = {"OTP_FAILED": "failed", "OTP_EXPIRED": "expired", "OTP_CANCELLED": "cancelled"}
FAILURE_DESCRIPTIONS = {
    "OTP_FAILED": "verification code entered wrongly 3 times",
    "OTP_EXPIRED": "verification code expired",
    "OTP_CANCELLED": "payment cancelled during verification",
    "OTP_UNAVAILABLE": "verification code could not be sent",
    "INSUFFICIENT_BALANCE": "insufficient balance",
    "WALLET_FROZEN": "wallet frozen",
    "CARD_BLOCKED": "card blocked",
    "CARD_LOST": "card reported lost",
    "PASSENGER_INACTIVE": "passenger account not active",
    "DRIVER_UNAVAILABLE": "driver cannot receive payments",
}


class ChallengeConflict(Exception):
    """The idempotency key already belongs to a different pending payment."""


@dataclass
class Outcome:
    kind: str                                   # otp_required | otp_invalid | completed | failed
    challenge: Optional[PaymentOtpChallenge] = None
    txn: Optional[Transaction] = None
    code: Optional[str] = None                  # failure code when kind == "failed"
    attempts_left: Optional[int] = None
    idempotent: bool = False
    notices: list = field(default_factory=list)  # failure-email kwargs for the route to send after the response


# ── helpers ──────────────────────────────────────────────────────────────────

def _secret() -> bytes:
    # PAYMENT_OTP_SECRET is mandatory in enforce mode (validate_fraud_config); the SECRET_KEY fallback only
    # serves off/shadow, where no OTP is issued.
    return (os.getenv("PAYMENT_OTP_SECRET") or settings.SECRET_KEY).encode()


def otp_hash(public_id: str, otp: str) -> str:
    return hmac.new(_secret(), f"{public_id}:{otp}".encode(), hashlib.sha256).hexdigest()


def mask_email(email: Optional[str]) -> str:
    """m***@g***.com: enough for the passenger to recognise, useless to a bystander at the POS."""
    email = (email or "").strip()
    if "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    name, dot, tld = domain.rpartition(".")
    if not dot:
        name, tld = domain, ""
    return f"{local[:1]}***@{name[:1]}***" + (f".{tld}" if tld else "")


def seconds_left(ch: PaymentOtpChallenge, now: datetime) -> int:
    return max(0, math.ceil((ch.expires_at - now).total_seconds()))


def public_view(ch: PaymentOtpChallenge, passenger: Optional[User], now: datetime) -> dict:
    """What a client may see about a challenge. Never the code, the full email or a balance. The hint is of the
    address the code is actually sent to (the demo redirect inbox when that is active)."""
    return {
        "challenge_id": ch.public_id,
        "email_hint": mask_email(otp_recipient(passenger)[0] if passenger else None),
        "expires_in_seconds": seconds_left(ch, now),
        "attempts_left": max(0, MAX_ATTEMPTS - (ch.attempts or 0)),
        "resends_left": max(0, MAX_RESENDS - (ch.resend_count or 0)),
    }


def get_challenge(db, public_id: Optional[str]) -> Optional[PaymentOtpChallenge]:
    if not isinstance(public_id, str) or not public_id or len(public_id) > 36:
        return None
    return db.query(PaymentOtpChallenge).filter(PaymentOtpChallenge.public_id == public_id).first()


def pending_for_key(db, scoped_key: str) -> Optional[PaymentOtpChallenge]:
    return db.query(PaymentOtpChallenge).filter(
        PaymentOtpChallenge.idempotency_key == scoped_key, PaymentOtpChallenge.status == "pending").first()


def _send(ch: PaymentOtpChallenge, passenger: User, driver: User, otp: str) -> bool:
    """Email the code. Runs in a worker thread with a hard timeout: a slow or failing provider declines the payment
    (the caller closes the challenge) instead of holding the request. False on any problem."""
    to, redirected = otp_recipient(passenger)
    try:
        fut = _EMAIL_POOL.submit(send_payment_otp, to_email=to.strip(), otp=otp, amount=float(ch.amount),
                                 driver_name=driver.name, expires_minutes=OTP_TTL_SECONDS // 60, channel=ch.channel,
                                 demo_for=passenger.id if redirected else None)
        return bool(fut.result(timeout=OTP_EMAIL_TIMEOUT_S))
    except FutureTimeout:
        logger.warning(f"[PaymentOTP] email send timed out for challenge {ch.public_id}")
        return False
    except Exception as e:  # noqa: BLE001 - a send problem declines the payment, never crashes it
        logger.warning(f"[PaymentOTP] send failed for challenge {ch.public_id}: {type(e).__name__}")
        return False


def _notice(ch: PaymentOtpChallenge, passenger: User, driver: User, txn: Transaction, code: str) -> Optional[dict]:
    if not passenger or not (passenger.email or "").strip():
        return None
    return dict(to_email=passenger.email, passenger_name=passenger.name, fare=float(ch.amount),
                driver_name=driver.name if driver else "Driver", reference=txn.reference, code=code,
                vehicle_type=driver.vehicle_type if driver else None,
                vehicle_registration=driver.vehicle_registration if driver else None, created_at=txn.created_at,
                payment_mode={"nfc": "Card (NFC)", "qr": "QR", "wallet": "Wallet"}.get(ch.channel, "Wallet"))


def _failed_txn(db, *, passenger_id, driver_id, channel, amount, scoped_key, code, now, payment_request_id=None):
    from app.routes.wallet import get_or_create_wallet
    wallet_id = get_or_create_wallet(passenger_id, db).id if passenger_id else None
    return Transaction(
        reference=f"{'QR' if channel == 'qr' else 'TXN'}{uuid.uuid4().hex[:10].upper()}",
        passenger_id=passenger_id, driver_id=driver_id, wallet_id=wallet_id, amount=amount,
        payment_method=PAYMENT_METHODS[channel], status="failed", otp_verified=False, fraud_status="otp_failed",
        transaction_type="ride_payment",
        description=f"{PAYMENT_METHODS[channel]} payment failed: {FAILURE_DESCRIPTIONS.get(code, code.lower())}",
        balance_after=None, idempotency_key=scoped_key, failure_code=code, payment_request_id=payment_request_id,
        created_at=now,
    )


# ── lifecycle ────────────────────────────────────────────────────────────────

def final_outcome(db, ch: PaymentOtpChallenge, now: datetime) -> Outcome:
    """The settled result of a challenge (for replays), or its pending view."""
    if ch.status == "pending":
        return Outcome("otp_required", ch, attempts_left=max(0, MAX_ATTEMPTS - (ch.attempts or 0)), idempotent=True)
    txn = db.get(Transaction, ch.transaction_id) if ch.transaction_id else None
    if ch.status == "completed":
        return Outcome("completed", ch, txn=txn, idempotent=True)
    return Outcome("failed", ch, txn=txn, code=ch.failure_code, idempotent=True)


def finalize_failure(db, ch: PaymentOtpChallenge, code: str, now: datetime) -> Outcome:
    """Close a pending challenge as failed: record the failed payment, fail the QR request, move no money."""
    status = FAILURE_STATUS.get(code, "failed")
    claimed = db.query(PaymentOtpChallenge).filter(
        PaymentOtpChallenge.id == ch.id, PaymentOtpChallenge.status == "pending",
    ).update({"status": status, "failure_code": code, "resolved_at": now}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        db.refresh(ch)
        return final_outcome(db, ch, now)
    txn = _failed_txn(db, passenger_id=ch.passenger_id, driver_id=ch.driver_id, channel=ch.channel,
                      amount=ch.amount, scoped_key=ch.idempotency_key, code=code, now=now,
                      payment_request_id=ch.payment_request_id)
    db.add(txn)
    if ch.payment_request_id:
        db.query(PaymentRequest).filter(
            PaymentRequest.id == ch.payment_request_id, PaymentRequest.status == "AwaitingOtp",
        ).update({"status": "Failed"}, synchronize_session=False)
    try:
        db.flush()
        db.query(PaymentOtpChallenge).filter(PaymentOtpChallenge.id == ch.id).update(
            {"transaction_id": txn.id}, synchronize_session=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        db.refresh(ch)
        return final_outcome(db, ch, now)
    db.refresh(ch)
    passenger, driver = db.get(User, ch.passenger_id), db.get(User, ch.driver_id)
    notice = _notice(ch, passenger, driver, txn, code)
    return Outcome("failed", ch, txn=txn, code=code, notices=[notice] if notice else [])


def decline_without_challenge(db, *, passenger, driver, channel, scoped_key, amount, now,
                              payment_request_id=None) -> Outcome:
    """OTP was required but cannot be delivered (no email on file): record the declined payment."""
    txn = _failed_txn(db, passenger_id=passenger.id, driver_id=driver.id, channel=channel, amount=amount,
                      scoped_key=scoped_key, code="OTP_UNAVAILABLE", now=now, payment_request_id=payment_request_id)
    db.add(txn)
    if payment_request_id:
        db.query(PaymentRequest).filter(
            PaymentRequest.id == payment_request_id, PaymentRequest.status.in_(["Pending", "AwaitingOtp"]),
        ).update({"status": "Failed"}, synchronize_session=False)
    db.commit()
    return Outcome("failed", None, txn=txn, code="OTP_UNAVAILABLE")


def expire_if_due(db, ch: Optional[PaymentOtpChallenge], now: datetime) -> Optional[Outcome]:
    if ch is not None and ch.status == "pending" and now >= ch.expires_at:
        return finalize_failure(db, ch, "OTP_EXPIRED", now)
    return None


def open_challenge(db, *, passenger: User, driver: User, channel: str, scoped_key: str, amount: Decimal,
                   now: datetime, card_uid: Optional[str] = None, payment_request_id: Optional[int] = None,
                   assessment_id: Optional[int] = None) -> Outcome:
    """Create (or replay) the challenge for this payment and email the code. Commits."""
    from app.services.fraud_gate import link_challenge
    from app.models import Wallet
    amount = Decimal(str(amount))
    # Serialise challenge creation per passenger (row lock on their wallet, held until the commit below): two taps
    # of the same key at once now see each other's challenge (one challenge, one email) instead of creating two, and
    # the "one pending challenge per passenger" supersede step cannot interleave. No-op on SQLite.
    db.query(Wallet).filter(Wallet.user_id == passenger.id).with_for_update().first()
    existing = pending_for_key(db, scoped_key)
    if existing is not None:
        if (existing.passenger_id, existing.driver_id, existing.amount, existing.channel) != \
                (passenger.id, driver.id, amount, channel):
            raise ChallengeConflict()
        expired = expire_if_due(db, existing, now)
        return expired or Outcome("otp_required", existing, attempts_left=MAX_ATTEMPTS - (existing.attempts or 0),
                                  idempotent=True)

    notices = []
    for old in db.query(PaymentOtpChallenge).filter(
            PaymentOtpChallenge.passenger_id == passenger.id, PaymentOtpChallenge.status == "pending").all():
        notices += finalize_failure(db, old, "OTP_CANCELLED", now).notices      # superseded by this payment

    if not (passenger.email or "").strip():
        out = decline_without_challenge(db, passenger=passenger, driver=driver, channel=channel,
                                        scoped_key=scoped_key, amount=amount, now=now,
                                        payment_request_id=payment_request_id)
        out.notices = notices
        return out

    otp = generate_otp()
    ch = PaymentOtpChallenge(
        public_id=str(uuid.uuid4()), passenger_id=passenger.id, driver_id=driver.id, channel=channel,
        idempotency_key=scoped_key, amount=amount, card_uid=card_uid, payment_request_id=payment_request_id,
        attempts=0, resend_count=0, last_sent_at=now, expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
        status="pending", created_at=now, otp_hash="",
    )
    ch.otp_hash = otp_hash(ch.public_id, otp)
    db.add(ch)
    db.flush()
    link_challenge(db, assessment_id, ch.id)
    db.commit()
    db.refresh(ch)

    if not _send(ch, passenger, driver, otp):
        out = finalize_failure(db, ch, "OTP_UNAVAILABLE", now)
        out.notices = notices + out.notices
        return out
    return Outcome("otp_required", ch, attempts_left=MAX_ATTEMPTS, notices=notices)


def resend(db, ch: PaymentOtpChallenge, now: datetime):
    """(Outcome, None) on success, (None, (error_code, detail)) when refused."""
    if ch.status != "pending":
        return final_outcome(db, ch, now), None
    expired = expire_if_due(db, ch, now)
    if expired:
        return expired, None
    if (ch.resend_count or 0) >= MAX_RESENDS:
        return None, ("resend_limit", "No more codes can be sent for this payment.")
    wait = RESEND_COOLDOWN_SECONDS - int((now - ch.last_sent_at).total_seconds())
    if wait > 0:
        return None, ("resend_cooldown", f"Please wait {wait} seconds before requesting a new code.")
    otp = generate_otp()
    updated = db.query(PaymentOtpChallenge).filter(
        PaymentOtpChallenge.id == ch.id, PaymentOtpChallenge.status == "pending",
        PaymentOtpChallenge.resend_count == (ch.resend_count or 0),
    ).update({"otp_hash": otp_hash(ch.public_id, otp), "resend_count": (ch.resend_count or 0) + 1,
              "last_sent_at": now, "expires_at": now + timedelta(seconds=OTP_TTL_SECONDS)},
             synchronize_session=False)
    db.commit()
    db.refresh(ch)
    if updated != 1:
        return None, ("resend_cooldown", "A new code was just sent.")
    if not _send(ch, db.get(User, ch.passenger_id), db.get(User, ch.driver_id), otp):
        return finalize_failure(db, ch, "OTP_UNAVAILABLE", now), None
    return Outcome("otp_required", ch, attempts_left=MAX_ATTEMPTS - (ch.attempts or 0)), None


def cancel(db, ch: PaymentOtpChallenge, now: datetime) -> Outcome:
    if ch.status != "pending":
        return final_outcome(db, ch, now)
    if now >= ch.expires_at:                      # the POS cancels when its countdown reaches zero
        return finalize_failure(db, ch, "OTP_EXPIRED", now)
    return finalize_failure(db, ch, "OTP_CANCELLED", now)


def verify(db, ch: PaymentOtpChallenge, otp, now: datetime) -> Outcome:
    """Check the code; on success move the money exactly once."""
    if ch.status != "pending":
        return final_outcome(db, ch, now)
    expired = expire_if_due(db, ch, now)
    if expired:
        return expired

    # Reserve one of the MAX_ATTEMPTS slots atomically BEFORE comparing, so parallel guesses can never exceed the
    # limit (a conditional UPDATE: at most MAX_ATTEMPTS comparisons happen in total, however many requests race).
    reserved = db.query(PaymentOtpChallenge).filter(
        PaymentOtpChallenge.id == ch.id, PaymentOtpChallenge.status == "pending",
        PaymentOtpChallenge.attempts < MAX_ATTEMPTS,
    ).update({"attempts": PaymentOtpChallenge.attempts + 1}, synchronize_session=False)
    db.commit()
    db.refresh(ch)
    if reserved != 1:
        if ch.status != "pending":
            return final_outcome(db, ch, now)
        return finalize_failure(db, ch, "OTP_FAILED", now)               # every attempt is used up
    candidate = otp if isinstance(otp, str) else ""
    ok = hmac.compare_digest(otp_hash(ch.public_id, candidate.strip()), ch.otp_hash) and candidate.strip().isdigit()
    if ok:
        return _complete(db, ch, now)
    if ch.status != "pending":
        return final_outcome(db, ch, now)
    if ch.attempts >= MAX_ATTEMPTS:
        return finalize_failure(db, ch, "OTP_FAILED", now)
    return Outcome("otp_invalid", ch, attempts_left=MAX_ATTEMPTS - ch.attempts)


def _complete(db, ch: PaymentOtpChallenge, now: datetime) -> Outcome:
    from app.routes.wallet import _credit, _debit, _lock_order, get_or_create_wallet

    passenger, driver = db.get(User, ch.passenger_id), db.get(User, ch.driver_id)
    if not passenger or passenger.account_type != "passenger" or passenger.status != "active":
        return finalize_failure(db, ch, "PASSENGER_INACTIVE", now)
    if not driver or driver.account_type != "driver" or driver.status != "active":
        return finalize_failure(db, ch, "DRIVER_UNAVAILABLE", now)
    if ch.channel == "nfc":
        card = db.query(NFCCard).filter(NFCCard.card_uid == ch.card_uid).first() if ch.card_uid else None
        if card is None or card.user_id != passenger.id or card.status != "active":
            code = "CARD_LOST" if card is not None and card.status in ("lost", "replaced") else "CARD_BLOCKED"
            return finalize_failure(db, ch, code, now)

    # Wallet rows must exist before the money transaction starts (creating one commits).
    p_wallet = get_or_create_wallet(passenger.id, db)
    get_or_create_wallet(driver.id, db)

    claimed = db.query(PaymentOtpChallenge).filter(
        PaymentOtpChallenge.id == ch.id, PaymentOtpChallenge.status == "pending",
    ).update({"status": "completed", "resolved_at": now}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        db.refresh(ch)
        return final_outcome(db, ch, now)

    amount = Decimal(str(ch.amount))
    steps = {passenger.id: lambda: _debit(db, passenger.id, amount), driver.id: lambda: _credit(db, driver.id, amount)}
    for uid in _lock_order(passenger.id, driver.id):
        if not steps[uid]():
            db.rollback()                       # undoes the claim and any partial debit/credit
            db.refresh(ch)
            if uid == passenger.id:
                db.refresh(p_wallet)
                return finalize_failure(db, ch, "WALLET_FROZEN" if p_wallet.is_frozen else "INSUFFICIENT_BALANCE", now)
            return finalize_failure(db, ch, "DRIVER_UNAVAILABLE", now)

    db.refresh(p_wallet)
    method = PAYMENT_METHODS[ch.channel]
    txn = Transaction(
        reference=f"{'QR' if ch.channel == 'qr' else 'TXN'}{uuid.uuid4().hex[:10].upper()}",
        passenger_id=passenger.id, driver_id=driver.id, wallet_id=p_wallet.id, amount=amount,
        payment_method=method, status="completed", otp_verified=True, fraud_status="otp_verified",
        transaction_type="ride_payment", description=f"₹{amount:.2f} paid to {driver.name} via {method}",
        balance_after=p_wallet.balance, idempotency_key=ch.idempotency_key,
        payment_request_id=ch.payment_request_id, created_at=now,
    )
    db.add(txn)
    if ch.payment_request_id:
        moved = db.query(PaymentRequest).filter(
            PaymentRequest.id == ch.payment_request_id, PaymentRequest.status == "AwaitingOtp",
        ).update({"status": "Completed", "verified_at": now, "payer_name": passenger.name}, synchronize_session=False)
        if moved != 1:
            db.rollback()
            db.refresh(ch)
            return finalize_failure(db, ch, "OTP_CANCELLED", now)
    try:
        db.flush()
        db.query(PaymentOtpChallenge).filter(PaymentOtpChallenge.id == ch.id).update(
            {"transaction_id": txn.id}, synchronize_session=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        db.refresh(ch)
        return final_outcome(db, ch, now)
    db.refresh(ch)
    db.refresh(txn)
    return Outcome("completed", ch, txn=txn)
