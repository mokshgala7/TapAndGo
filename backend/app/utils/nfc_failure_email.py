"""
Email sent to a card's owner when an NFC tap did not complete.

Kept in its own module on purpose: it reuses the shared theme and delivery (send_email, which
records every attempt in email_logs) from email_service without changing that file. It mirrors
send_ride_passenger_email(status="Failed") and adds the reason, which that function cannot show.
No PDF is attached to a failure.
"""
import html
import logging
from datetime import datetime
from typing import Optional

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
) -> bool:
    """Returns True when the email was handed to the provider. Never raises for delivery problems."""
    reason = FAILURE_EMAIL_REASONS.get(code, "The payment could not be completed.")
    first_name = html.escape(passenger_name.split()[0]) if passenger_name and passenger_name.split() else "there"
    fare_str = f"₹{fare:.2f}" if fare else "—"
    when = (created_at or datetime.utcnow()).strftime("%d %B %Y, %I:%M %p UTC")

    rows = [
        ("Driver", html.escape(driver_name or "Driver")),
        ("Payment Mode", html.escape(payment_mode)),
        ("Transaction ID", f'<span style="font-family:monospace;">{html.escape(reference)}</span>'),
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
        f"Your card payment could not be completed. {reason}\n\n"
        f"Fare: {fare_str}\nDriver: {driver_name}\nTransaction ID: {reference}\nDate & Time: {when}\n"
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
