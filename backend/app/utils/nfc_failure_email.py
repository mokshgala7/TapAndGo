"""
Email sent to a card's owner when an NFC tap did not complete.

Kept in its own module on purpose: it reuses the shared theme and delivery (send_email, which
records every attempt in email_logs) from email_service without changing that file. It mirrors
send_ride_passenger_email(status="Failed") and adds the reason, which that function cannot show.
No PDF is attached to a failure.
"""
import hashlib
import html
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional

from app.models import EmailLog
from app.utils.email_service import _render_payment_theme, send_email

logger = logging.getLogger(__name__)

# Reason line shown to the card owner, per failure code.
FAILURE_EMAIL_REASONS = {
    "INSUFFICIENT_BALANCE": "Insufficient wallet balance. Please add money and try again.",
    "CARD_BLOCKED": "Your card is blocked. If this wasn't you, contact support.",
    "CARD_LOST": "This card was reported lost. If this wasn't you, contact support.",
    "WALLET_FROZEN": "Your wallet is frozen. Contact support.",
    "PASSENGER_INACTIVE": "Your Tap & Go account is not active. Contact support.",
    "AMOUNT_INVALID": "The fare entered at the terminal was not valid. Please ask the driver to try again.",
    "OTP_FAILED": "The verification code was entered wrongly too many times. If this wasn't you, block your card.",
    "OTP_EXPIRED": "The verification code was not entered in time.",
    "OTP_CANCELLED": "The payment was cancelled before the verification code was entered.",
    "OTP_UNAVAILABLE": "This payment needed email verification, but the code could not be sent to you.",
}


def send_nfc_failure_email(
    *,
    to_email: str,
    passenger_name: str,
    fare: Optional[float],
    driver_name: str,
    reference: str,
    code: str,
    vehicle_type: Optional[str] = None,
    vehicle_registration: Optional[str] = None,
    wallet_balance: Optional[float] = None,
    created_at: Optional[datetime] = None,
    payment_mode: str = "Card (NFC)",
    time_zone: str = "UTC",
    reference_label: str = "Transaction ID",
) -> bool:
    """Returns True when the email was handed to the provider. Never raises for delivery problems.
    `time_zone="IST"` shows the time in Indian Standard Time (the default stays UTC, as before);
    `reference_label` names the reference row (declined attempts that never became a transaction use "Reference")."""
    reason = FAILURE_EMAIL_REASONS.get(code, "The payment could not be completed.")
    first_name = html.escape(passenger_name.split()[0]) if passenger_name and passenger_name.split() else "there"
    fare_str = f"₹{fare:.2f}" if fare else "—"
    moment = created_at or datetime.utcnow()
    when = ((moment + timedelta(hours=5, minutes=30)).strftime("%d %B %Y, %I:%M %p IST") if time_zone == "IST"
            else moment.strftime("%d %B %Y, %I:%M %p UTC"))
    card = "card " if payment_mode == "Card (NFC)" else ""

    rows = [
        ("Driver", html.escape(driver_name or "Driver")),
        ("Payment Mode", html.escape(payment_mode)),
        (html.escape(reference_label), f'<span style="font-family:monospace;">{html.escape(reference)}</span>'),
        ("Date &amp; Time", when),
        ("Status", "FAILED"),
        ("Reason", html.escape(reason)),
    ]
    if vehicle_type:
        rows.insert(1, ("Vehicle Type", html.escape(vehicle_type)))
    if vehicle_registration:
        rows.insert(2 if vehicle_type else 1, ("Vehicle Number", html.escape(vehicle_registration)))
    if code == "INSUFFICIENT_BALANCE" and wallet_balance is not None:
        rows.append(("Current Wallet Balance", f"₹{wallet_balance:.2f}"))
    rows.append(("Amount Deducted", "₹0.00 — nothing was charged"))

    body = _render_payment_theme(
        title="Ride Payment Failed — Tap & Go",
        badge_label="PAYMENT FAILED",
        status_label="FAILED",
        status_color="#EF4444",
        heading="Ride Payment Failed",
        intro_html=f"Hi {first_name}, your {'card ' if payment_mode == 'Card (NFC)' else ''}payment could not be completed. {html.escape(reason)}",
        amount_str=fare_str,
        amount_label="RIDE FARE",
        rows=rows,
        accent_gradient="linear-gradient(90deg,#EF4444,#DC2626)",
    )

    plain = (
        "Tap & Go Ride Payment Failed\n\n"
        f"Hi {passenger_name.split()[0] if passenger_name and passenger_name.split() else 'there'},\n\n"
        f"Your {card}payment could not be completed. {reason}\n\n"
        f"Fare: {fare_str}\nDriver: {driver_name}\n{reference_label}: {reference}\nDate & Time: {when}\n"
        + (f"Current Wallet Balance: ₹{wallet_balance:.2f}\n" if code == "INSUFFICIENT_BALANCE" and wallet_balance is not None else "")
        + "Amount Deducted: ₹0.00 (nothing was charged)\n\n"
        "Tap & Go Smart Cashless Transit Payments\nSupport: tapandgosupport@gmail.com"
    )

    return send_email(
        to_email=to_email,
        subject="Tap & Go - Ride Payment Failed",
        html_content=body,
        email_type="ride_passenger_payment_failed",
        reference=reference,
        text_content=plain,
    )


# ── declined before any transaction exists (QR confirm / wallet pay: insufficient balance) ──────────────────────
# These declines write no Transaction row (the QR request stays Pending so the passenger can top up and retry with the
# same key), so the email is deduplicated on a reference derived from the scoped idempotency key: one email per
# attempt, however many times the same attempt is retried, double-submitted or polled. Two layers: a process-local
# claim (closes the window before email_logs is written) and a SENT row in email_logs (survives restarts).

DECLINE_EMAIL_TYPE = "ride_passenger_payment_failed"
_DECLINE_PREFIX = {"qr": "QRDECL", "wallet": "WPDECL", "nfc": "NFDECL"}
_DECLINE_MODE = {"qr": "QR", "wallet": "Wallet", "nfc": "Card (NFC)"}
_CLAIM_TTL_SECONDS = 600
_claims: dict = {}
_claims_lock = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="decline-mail")


def decline_reference(channel: str, scoped_key: str) -> str:
    """Stable, non-reversible reference for one declined attempt (the key itself is never put in an email)."""
    return _DECLINE_PREFIX.get(channel, "DECL") + hashlib.sha256(scoped_key.encode()).hexdigest()[:10].upper()


def _claim(reference: str) -> bool:
    now = time.monotonic()
    with _claims_lock:
        for ref in [r for r, t in _claims.items() if now - t > _CLAIM_TTL_SECONDS]:
            del _claims[ref]
        if reference in _claims:
            return False
        _claims[reference] = now
        return True


def _release(reference: str) -> None:
    with _claims_lock:
        _claims.pop(reference, None)


def build_decline_notice(db, *, passenger, driver, amount, code: str, channel: str, scoped_key: str) -> Optional[dict]:
    """Keyword arguments for send_nfc_failure_email, or None when nothing should be sent (no email on file, already
    sent for this attempt, or any problem: this never raises). Contains no balance, OTP or card data."""
    try:
        email = (getattr(passenger, "email", None) or "").strip()
        if not email:
            return None
        reference = decline_reference(channel, scoped_key)
        if not _claim(reference):
            return None
        try:
            with db.begin_nested():
                already = db.query(EmailLog.id).filter(
                    EmailLog.email_type == DECLINE_EMAIL_TYPE, EmailLog.reference == reference,
                    EmailLog.status == "SENT").first()
        except Exception:  # noqa: BLE001 - a failed check must not stop the notice (the claim still prevents repeats)
            already = None
        if already:
            return None
        return dict(to_email=email, passenger_name=passenger.name, fare=float(amount),
                    driver_name=(driver.name if driver else "Driver"), reference=reference, code=code,
                    vehicle_type=driver.vehicle_type if driver else None,
                    vehicle_registration=driver.vehicle_registration if driver else None,
                    created_at=datetime.utcnow(), payment_mode=_DECLINE_MODE.get(channel, "Wallet"),
                    time_zone="IST", reference_label="Reference")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PaymentEmail] Could not prepare the decline notice: {type(e).__name__}")
        return None


def send_decline_notice(**notice) -> bool:
    """Send one prepared notice; releases the claim when delivery fails so a retry may try again. Never raises."""
    reference = notice.get("reference")
    try:
        if send_nfc_failure_email(**notice):
            return True
        logger.warning("[PaymentEmail] Decline notice was not delivered")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PaymentEmail] Decline notice failed: {type(e).__name__}")
    if reference:
        _release(reference)
    return False


def queue_decline_notice(db, background_tasks, *, passenger, driver, amount, code: str, channel: str,
                         scoped_key: str) -> None:
    """Prepare and hand off the notice without ever blocking or failing the payment response. Uses the request's
    BackgroundTasks when the response is a normal return; otherwise (a route that raises HTTPException, which drops
    background tasks) a small worker pool, so the response never waits for the mail provider."""
    try:
        notice = build_decline_notice(db, passenger=passenger, driver=driver, amount=amount, code=code,
                                      channel=channel, scoped_key=scoped_key)
        if notice is None:
            return
        if background_tasks is not None:
            background_tasks.add_task(send_decline_notice, **notice)
        else:
            _POOL.submit(send_decline_notice, **notice)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[PaymentEmail] Could not queue the decline notice: {type(e).__name__}")
