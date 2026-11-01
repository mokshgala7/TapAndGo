"""Administrator sign-in hardening (admin hardening, Phase 8).

1. Persistent throttle. Failed sign-ins are rows in `login_attempts`: 5 failures per 15 minutes per "email|ip", plus a
   cap per IP across all emails. If the database cannot be used, every function here reports that (None / False) and
   the caller falls back to the in-memory throttle in app/routes/admin.py, so a database problem never blocks login.

2. Optional email second factor, only when ADMIN_2FA_ENABLED is true (default OFF, in which case nothing here runs).
   After the password is verified, a 6-digit code is e-mailed (EmailOTP, reason/purpose "admin_login", 5-minute expiry,
   max 5 wrong attempts, single use) and must be sent back with the same credentials.
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from app.models import Admin, EmailOTP, LoginAttempt
from app.utils.email_service import send_email
from app.utils.security import generate_otp, is_otp_expired

logger = logging.getLogger("tapgo.admin_login")

LOGIN_MAX_FAILURES = 5                 # per email + IP
LOGIN_IP_MAX_FAILURES = 20             # per IP, whatever the email
LOGIN_WINDOW = timedelta(minutes=15)
PRUNE_AFTER = timedelta(days=1)

PURPOSE = "admin_login"
OTP_VALID = timedelta(minutes=5)
OTP_RESEND_AFTER = timedelta(seconds=60)


# ── persistent throttle ──────────────────────────────────────────────────────

def is_throttled(db, key: str, ip: Optional[str]) -> Optional[bool]:
    """True / False from the database, or None when it cannot be read (caller falls back to memory)."""
    try:
        since = datetime.utcnow() - LOGIN_WINDOW
        by_key = db.query(LoginAttempt.id).filter(LoginAttempt.key == key, LoginAttempt.attempted_at >= since).count()
        if by_key >= LOGIN_MAX_FAILURES:
            return True
        if ip:
            by_ip = db.query(LoginAttempt.id).filter(LoginAttempt.ip == ip, LoginAttempt.attempted_at >= since).count()
            if by_ip >= LOGIN_IP_MAX_FAILURES:
                return True
        return False
    except Exception as exc:  # noqa: BLE001
        _rollback(db)
        logger.warning("login throttle read failed, using memory: %s", type(exc).__name__)
        return None


def record_failure(db, key: str, ip: Optional[str]) -> bool:
    """True when the failure is stored in the database; False means the caller must record it in memory."""
    try:
        now = datetime.utcnow()
        db.add(LoginAttempt(key=key[:255], ip=(ip or "")[:64] or None, attempted_at=now))
        db.query(LoginAttempt).filter(LoginAttempt.attempted_at < now - PRUNE_AFTER).delete(synchronize_session=False)
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        _rollback(db)
        logger.warning("login failure not stored, using memory: %s", type(exc).__name__)
        return False


def clear_failures(db, key: str) -> None:
    try:
        db.query(LoginAttempt).filter(LoginAttempt.key == key).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        _rollback(db)
        logger.warning("login failures not cleared: %s", type(exc).__name__)


def _rollback(db) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        pass


# ── optional second factor ───────────────────────────────────────────────────

def two_factor_enabled() -> bool:
    return os.getenv("ADMIN_2FA_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _active_codes(db, email: str):
    return db.query(EmailOTP).filter(
        EmailOTP.email == email, EmailOTP.reason == PURPOSE, EmailOTP.purpose == PURPOSE, EmailOTP.used == False,  # noqa: E712
    )


def send_code(db, admin: Admin) -> str:
    """E-mail a fresh code. Returns "sent", "recent" (one was sent a moment ago, nothing new is sent) or "failed"."""
    email = admin.email.strip().lower()
    latest = _active_codes(db, email).order_by(EmailOTP.created_at.desc()).first()
    if latest is not None and latest.created_at and datetime.utcnow() - latest.created_at < OTP_RESEND_AFTER \
            and not is_otp_expired(latest.expires_at):
        return "recent"
    _active_codes(db, email).update({EmailOTP.used: True}, synchronize_session=False)     # older codes stop working
    code = generate_otp()
    db.add(EmailOTP(email=email, otp=code, reason=PURPOSE, purpose=PURPOSE, attempts=0, used=False,
                    expires_at=datetime.utcnow() + OTP_VALID))
    db.commit()
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:420px">'
        '<h2 style="margin:0 0 12px">Tap &amp; Go administrator sign-in</h2>'
        '<p>Use this code to finish signing in. It expires in 5 minutes and works once.</p>'
        f'<p style="font-size:30px;font-weight:800;letter-spacing:6px;margin:16px 0">{code}</p>'
        '<p style="color:#6b6458;font-size:13px">If you did not try to sign in, change your password.</p></div>'
    )
    try:
        ok = send_email(to_email=email, subject="Tap & Go admin sign-in code", html_content=html,
                        email_type="admin_login_otp", redact_recipient=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin login code not sent: %s", type(exc).__name__)
        ok = False
    return "sent" if ok else "failed"


def check_code(db, admin: Admin, submitted: str) -> str:
    """Verify a submitted code. Returns "ok" (and consumes it), "wrong", "locked" or "expired" (also: none active)."""
    from app.routes.auth import OTP_MAX_ATTEMPTS, _consume_otp, _verify_otp_code
    row = _active_codes(db, admin.email.strip().lower()).order_by(EmailOTP.created_at.desc()).first()
    if row is None:
        return "expired"
    if row.attempts >= OTP_MAX_ATTEMPTS:
        row.used = True
        db.commit()
        return "locked"
    if is_otp_expired(row.expires_at):
        row.used = True
        db.commit()
        return "expired"
    outcome, _ = _verify_otp_code(db, row, (submitted or "").strip())
    if outcome == "ok":
        if not _consume_otp(db, row):          # lost a race with another request using the same code
            db.rollback()
            return "expired"
        db.commit()
        return "ok"
    return {"locked": "locked", "gone": "expired"}.get(outcome, "wrong")
