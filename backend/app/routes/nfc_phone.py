"""Tap & Pay with the passenger's PHONE on the POS terminal (ESP32-S3 + PN532).

The PN532 firmware only reads a tag UID and posts it to POST /api/nfc/pay. An Android phone that
emulates a card shows a RANDOM 4-byte UID (first byte 0x08, ISO 14443-3) that changes on every tap,
so the UID cannot name the passenger. Instead the passenger presses "Tap & Pay" in the signed-in
mobile app, which calls POST /api/nfc/phone/arm: the backend then knows which account (the e-mail
the app is logged in with) is holding a phone at a reader for the next ~90 seconds.

When the POS posts an unknown random-style UID, exactly one armed passenger is claimed for it and the
tap is processed by the UNCHANGED card handler (app/routes/nfc_pay.py): same checks, same failed-tap
records, same idempotency, same receipts and e-mails. Nothing is written to nfc_cards, so the
website's card list and the admin card flows are not affected.

Fail-closed rules
  - a UID that belongs to a registered card always goes straight to the card handler;
  - only random-style UIDs (NFC_PHONE_UID_PREFIXES, default "08", 4 bytes) are considered a phone;
  - zero or more than one armed passenger -> the card handler answers "Card not recognised";
  - an arm is single use and expires (NFC_PHONE_ARM_SECONDS, default 90);
  - NFC_PHONE_ALLOWED_EMAILS (comma separated, or *) restricts who may arm; unset = every passenger.

This router must be included BEFORE nfc_pay.router so its POST /api/nfc/pay is matched first; every
request that is not a phone tap is passed to the original handler untouched.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.models import NFCCard, Transaction, User
from app.routes import nfc_pay
from app.routes.auth import get_current_user
from app.routes.wallet import get_or_create_wallet
from app.services import payment_otp

logger = logging.getLogger(__name__)

router = APIRouter(tags=["NFC Phone Payment"])


class NfcPhoneArm(Base):
    __tablename__ = "nfc_phone_arms"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    # armed -> processing -> paid | failed | awaiting_otp ; or cancelled | expired
    status = Column(String(20), nullable=False, default="armed", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    reference = Column(String(64), nullable=True)
    amount = Column(Numeric(12, 2), nullable=True)
    driver_name = Column(String(100), nullable=True)
    failure_code = Column(String(40), nullable=True)
    message = Column(Text, nullable=True)


def arm_seconds() -> int:
    try:
        return max(15, min(300, int(os.getenv("NFC_PHONE_ARM_SECONDS", "90"))))
    except ValueError:
        return 90


def phone_uid_prefixes() -> set:
    raw = os.getenv("NFC_PHONE_UID_PREFIXES", "08")
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def looks_like_phone_uid(uid: Optional[str]) -> bool:
    """Random-style 4-byte UID as an Android card emulator presents it."""
    return bool(uid) and len(uid) == 8 and uid[:2].upper() in phone_uid_prefixes()


def email_may_use_phone_tap(email: Optional[str]) -> bool:
    raw = os.getenv("NFC_PHONE_ALLOWED_EMAILS", "")
    allowed = {e.strip().lower() for e in raw.split(",") if e.strip()}
    if not allowed or "*" in allowed:
        return True
    return bool(email) and email.strip().lower() in allowed


def _expire_due(db: Session, now: datetime) -> None:
    db.query(NfcPhoneArm).filter(
        NfcPhoneArm.status == "armed", NfcPhoneArm.expires_at < now
    ).update({"status": "expired"}, synchronize_session=False)
    # A tap whose emailed code was never entered on the POS (the code itself lasts 5 minutes).
    db.query(NfcPhoneArm).filter(
        NfcPhoneArm.status == "awaiting_otp", NfcPhoneArm.expires_at < now - timedelta(minutes=10)
    ).update({"status": "expired", "message": "The verification code was not entered in time. Nothing was charged."},
             synchronize_session=False)
    db.commit()


def _arm_view(arm: NfcPhoneArm, now: datetime) -> dict:
    return {
        "success": True,
        "arm_id": arm.id,
        "status": arm.status,
        "seconds_left": max(0, int((arm.expires_at - now).total_seconds())) if arm.status == "armed" else 0,
        "reference": arm.reference,
        "amount": float(arm.amount) if arm.amount is not None else None,
        "driver_name": arm.driver_name,
        "failure_code": arm.failure_code,
        "message": arm.message,
    }


# ── passenger endpoints (signed-in mobile app) ───────────────────────────────

def _require_passenger(user: User) -> None:
    if user.account_type != "passenger":
        raise HTTPException(status_code=403, detail="Only passenger accounts can pay with a phone.")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Your account is not active.")
    if not email_may_use_phone_tap(user.email):
        raise HTTPException(status_code=403, detail="Phone Tap & Pay is not enabled for this account yet.")


@router.post("/api/nfc/phone/arm")
def arm_phone(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The passenger is about to hold the phone at a POS reader."""
    _require_passenger(current_user)
    wallet = get_or_create_wallet(current_user.id, db)
    if wallet.is_frozen:
        raise HTTPException(status_code=400, detail="Your wallet is frozen. Payments are disabled.")
    now = datetime.utcnow()
    _expire_due(db, now)
    # One live arm per passenger: a new press replaces an earlier one that has not been used.
    db.query(NfcPhoneArm).filter(
        NfcPhoneArm.user_id == current_user.id, NfcPhoneArm.status == "armed"
    ).update({"status": "cancelled"}, synchronize_session=False)
    arm = NfcPhoneArm(user_id=current_user.id, status="armed", created_at=now,
                      expires_at=now + timedelta(seconds=arm_seconds()))
    db.add(arm)
    db.commit()
    db.refresh(arm)
    return _arm_view(arm, now)


def _own_arm(db: Session, arm_id: int, user: User) -> NfcPhoneArm:
    arm = db.get(NfcPhoneArm, arm_id)
    if arm is None or arm.user_id != user.id:
        raise HTTPException(status_code=404, detail="Tap & Pay session not found.")
    return arm


@router.get("/api/nfc/phone/arm/{arm_id}")
def arm_status(arm_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    arm = _own_arm(db, arm_id, current_user)
    now = datetime.utcnow()
    _expire_due(db, now)
    db.refresh(arm)
    return _arm_view(arm, now)


@router.post("/api/nfc/phone/arm/{arm_id}/cancel")
def arm_cancel(arm_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    arm = _own_arm(db, arm_id, current_user)
    db.query(NfcPhoneArm).filter(
        NfcPhoneArm.id == arm.id, NfcPhoneArm.status == "armed"
    ).update({"status": "cancelled"}, synchronize_session=False)
    db.commit()
    db.refresh(arm)
    return _arm_view(arm, datetime.utcnow())


# ── POS terminal: POST /api/nfc/pay (phone taps handled here, everything else delegated) ──

class _CardQuery:
    """Stands in for db.query(NFCCard): the handler's one lookup finds the phone's owner."""

    def __init__(self, card: NFCCard):
        self._card = card

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._card


class _PhoneDb:
    """The request's Session, except that the card lookup answers with a transient (never saved) card
    owned by the armed passenger. Every other call goes to the real Session."""

    def __init__(self, db: Session, card: NFCCard):
        self._db = db
        self._card = card

    def query(self, *entities, **kwargs):
        if len(entities) == 1 and entities[0] is NFCCard:
            return _CardQuery(self._card)
        return self._db.query(*entities, **kwargs)

    def __getattr__(self, name):
        return getattr(self._db, name)


def _replay_passenger(db: Session, driver: User, key: str) -> Optional[int]:
    """A POS retry of an already-recorded tap: the passenger that tap was for."""
    if not (8 <= len(key) <= 100):
        return None
    txn = db.query(Transaction).filter(Transaction.idempotency_key == f"nfc:{driver.id}:{key}").first()
    return txn.passenger_id if txn is not None else None


def _claim_single_arm(db: Session, now: datetime) -> Optional[NfcPhoneArm]:
    """The one passenger currently holding a phone out, claimed for this tap. None if zero or several."""
    _expire_due(db, now)
    armed = db.query(NfcPhoneArm).filter(NfcPhoneArm.status == "armed", NfcPhoneArm.expires_at >= now).all()
    if len(armed) != 1:
        if len(armed) > 1:
            logger.warning("[NFCPhone] %d passengers armed at once: phone tap not attributed", len(armed))
        return None
    arm = armed[0]
    won = db.query(NfcPhoneArm).filter(
        NfcPhoneArm.id == arm.id, NfcPhoneArm.status == "armed"
    ).update({"status": "processing"}, synchronize_session=False)
    db.commit()
    return arm if won == 1 else None


def _response_body(resp) -> dict:
    if isinstance(resp, dict):
        return resp
    try:
        return json.loads(resp.body)
    except Exception:  # noqa: BLE001
        return {}


def _finish_arm(db: Session, arm_id: int, resp, driver_name: str) -> None:
    body = _response_body(resp)
    if body.get("status") == "otp_invalid":
        return  # wrong code: the challenge is still open, the arm keeps waiting
    values = {"driver_name": driver_name[:100] if driver_name else None}
    if body.get("success") is True:
        values.update(status="paid", reference=body.get("reference"), amount=Decimal(str(body.get("amount", 0))))
    elif body.get("status") == "otp_required":
        # Only when the server's fraud check is enforcing: the code is typed on the POS screen.
        values.update(status="awaiting_otp", message="Enter the code from your email on the driver's screen.")
    else:
        values.update(status="failed", failure_code=str(body.get("code") or "")[:40] or None,
                      reference=body.get("reference"),
                      message=str(body.get("message") or "The payment was not completed.")[:500])
    db.query(NfcPhoneArm).filter(NfcPhoneArm.id == arm_id).update(values, synchronize_session=False)
    db.commit()


@router.post("/api/nfc/pay")
def nfc_pay_with_phone(
    data: nfc_pay.NFCPayRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    uid = nfc_pay.normalize_card_uid(data.card_uid)
    driver = current_user
    # Not a phone tap -> the original handler, exactly as before.
    if (not looks_like_phone_uid(uid) or driver.account_type != "driver" or driver.status != "active"):
        return nfc_pay.nfc_pay(data, background_tasks, current_user, db)
    if db.query(NFCCard.id).filter(NFCCard.card_uid == uid).first() is not None:
        return nfc_pay.nfc_pay(data, background_tasks, current_user, db)

    arm: Optional[NfcPhoneArm] = None
    owner_id = _replay_passenger(db, driver, (data.idempotency_key or "").strip())
    if owner_id is None:
        arm = _claim_single_arm(db, datetime.utcnow())
        if arm is None:
            return nfc_pay.nfc_pay(data, background_tasks, current_user, db)
        owner_id = arm.user_id
    elif owner_id is not None and db.get(User, owner_id) is None:
        return nfc_pay.nfc_pay(data, background_tasks, current_user, db)

    stub = NFCCard(user_id=owner_id, card_reference=f"PHONE-{owner_id}", card_uid=uid,
                   card_type="mobile", status="active")
    arm_id = arm.id if arm is not None else None
    driver_name = driver.name
    try:
        resp = nfc_pay.nfc_pay(data, background_tasks, current_user, _PhoneDb(db, stub))
    except Exception:
        db.rollback()
        if arm_id is not None:
            db.query(NfcPhoneArm).filter(NfcPhoneArm.id == arm_id).update(
                {"status": "failed", "message": "The payment could not be completed."},
                synchronize_session=False)
            db.commit()
        raise
    if arm_id is not None:
        _finish_arm(db, arm_id, resp, driver_name)
    return resp


@router.post("/api/nfc/pay/verify-otp")
def nfc_verify_otp_with_phone(
    data: nfc_pay.NFCOtpRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The code typed on the POS for a phone tap. The server's fraud check (when it asks for a code)
    re-checks the card when the code is accepted; for a phone that card is the armed passenger's."""
    ch = payment_otp.get_challenge(db, data.challenge_id)
    if (ch is None or ch.channel != "nfc" or not looks_like_phone_uid(ch.card_uid)
            or db.query(NFCCard.id).filter(NFCCard.card_uid == ch.card_uid).first() is not None):
        return nfc_pay.nfc_verify_otp(data, background_tasks, current_user, db)

    passenger_id = ch.passenger_id
    stub = NFCCard(user_id=passenger_id, card_reference=f"PHONE-{passenger_id}", card_uid=ch.card_uid,
                   card_type="mobile", status="active")
    driver_name = current_user.name
    resp = nfc_pay.nfc_verify_otp(data, background_tasks, current_user, _PhoneDb(db, stub))
    arm = db.query(NfcPhoneArm).filter(
        NfcPhoneArm.user_id == passenger_id, NfcPhoneArm.status == "awaiting_otp"
    ).order_by(NfcPhoneArm.id.desc()).first()
    if arm is not None:
        _finish_arm(db, arm.id, resp, driver_name)
    return resp
