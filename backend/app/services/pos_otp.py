"""
POS-side view of a payment OTP challenge, for QR and wallet payments.

The emailed payment code is entered ONLY on the driver's POS for every channel (NFC already worked that way). These
helpers build the small JSON the POS receives; the verification itself is the unchanged payment_otp machinery
(single use, 5-minute expiry, attempt limit stored in the DB, resend cooldown, HMAC-hashed code, binding to passenger /
driver / amount / channel / idempotency key, no money before a verified code).

What the POS may see: the amount, a MASKED email hint, counters and the outcome. Never the passenger's email, name,
balance, the code or its hash.
"""
from datetime import datetime
from typing import Optional

from fastapi.responses import JSONResponse

from app.models import PaymentOtpChallenge, Transaction, User
from app.services import payment_otp

MESSAGES = {
    "OTP_FAILED": "Wrong OTP entered too many times. Payment cancelled.",
    "OTP_EXPIRED": "OTP expired. Payment cancelled.",
    "OTP_CANCELLED": "Payment cancelled.",
    "OTP_UNAVAILABLE": "Verification needed but no OTP could be sent. Payment declined.",
    "INSUFFICIENT_BALANCE": "Insufficient balance.",
    "WALLET_FROZEN": "The passenger's wallet is frozen.",
    "PASSENGER_INACTIVE": "The passenger's account is not active.",
    "DRIVER_UNAVAILABLE": "This terminal cannot receive payments right now.",
    "CHALLENGE_INVALID": "This verification is not valid for this payment.",
    "DRIVER_NOT_ALLOWED": "Only an active driver terminal can use this.",
}

PASSENGER_REFUSAL = {
    "success": False,
    "code": "OTP_ENTRY_POS_ONLY",
    "detail": "The verification code can only be entered on the driver's POS screen. Check your email for the code "
              "and tell it to the driver's terminal; you can cancel this payment here.",
}


def passenger_refusal() -> JSONResponse:
    """The website / passenger-authenticated verify and resend endpoints no longer take a payment OTP."""
    return JSONResponse(status_code=403, content=dict(PASSENGER_REFUSAL))


def error(code: str, http_status: int) -> JSONResponse:
    return JSONResponse(status_code=http_status, content={"success": False, "status": "Failed", "code": code,
                                                          "message": MESSAGES[code]})


def driver_allowed(driver: User) -> bool:
    return driver.account_type == "driver" and driver.status == "active"


def outcome_response(db, out: "payment_otp.Outcome", now: Optional[datetime] = None) -> JSONResponse:
    """POS response for an OTP outcome (verify / resend / cancel). HTTP 200 for every business result, like NFC."""
    now = now or datetime.utcnow()
    ch = out.challenge
    if out.kind == "otp_required":
        return JSONResponse(status_code=200, content={
            "success": False, "status": "otp_required",
            **payment_otp.public_view(ch, db.get(User, ch.passenger_id), now)})
    if out.kind == "otp_invalid":
        n = out.attempts_left
        return JSONResponse(status_code=200, content={
            "success": False, "status": "otp_invalid", "attempts_left": n,
            "message": f"Wrong OTP, {n} attempt{'s' if n != 1 else ''} left."})
    if out.kind == "completed":
        body = {"success": True, "status": "Completed", "reference": out.txn.reference, "amount": float(out.txn.amount)}
        if out.idempotent:
            body["idempotent"] = True
        return JSONResponse(status_code=200, content=body)
    code = out.code if out.code in MESSAGES else "OTP_CANCELLED"
    body = {"success": False, "status": "Failed", "code": code, "message": MESSAGES[code]}
    if out.txn is not None:
        body["reference"] = out.txn.reference
    if out.idempotent:
        body["idempotent"] = True
    return JSONResponse(status_code=200, content=body)


def status_body(db, ch: PaymentOtpChallenge, now: Optional[datetime] = None) -> dict:
    """Read-only outcome lookup for the POS. A challenge whose time has run out is reported as failed/OTP_EXPIRED; the
    row itself is closed (and the passenger told) by the next verify / cancel call or the passenger's page."""
    now = now or datetime.utcnow()
    if ch.status == "pending":
        if now >= ch.expires_at:
            return {"status": "failed", "transaction_ref": None, "amount": float(ch.amount), "failure_code": "OTP_EXPIRED"}
        return {"status": "otp_pending", "transaction_ref": None, "amount": float(ch.amount), "failure_code": None,
                **payment_otp.public_view(ch, db.get(User, ch.passenger_id), now)}
    txn = db.get(Transaction, ch.transaction_id) if ch.transaction_id else None
    ref = txn.reference if txn is not None else None
    if ch.status == "completed":
        return {"status": "completed", "transaction_ref": ref, "amount": float(ch.amount), "failure_code": None}
    return {"status": "failed", "transaction_ref": ref, "amount": float(ch.amount), "failure_code": ch.failure_code}


def passenger_status_body(db, ch: PaymentOtpChallenge, now: Optional[datetime] = None) -> dict:
    """What the paying passenger's page may poll: where the payment stands, the masked hint, a countdown. No code input."""
    now = now or datetime.utcnow()
    txn = db.get(Transaction, ch.transaction_id) if ch.transaction_id else None
    base = {"success": True, "amount": float(ch.amount), "reference": txn.reference if txn is not None else None}
    if ch.status == "pending":
        return {**base, "status": "AwaitingOtp", "otp": payment_otp.public_view(ch, db.get(User, ch.passenger_id), now),
                "message": "A code was sent to your email. Enter it on the driver's POS screen."}
    if ch.status == "completed":
        return {**base, "status": "Completed"}
    return {**base, "status": "Failed", "code": ch.failure_code or "FAILED",
            "message": MESSAGES.get(ch.failure_code or "", "The payment could not be completed. Nothing was charged.")}
