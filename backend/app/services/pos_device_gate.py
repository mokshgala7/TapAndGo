"""Optional POS device identification (admin hardening, Phase 6).

The current firmware sends no device id and must keep working unchanged. A newer build MAY add these headers to its
requests: X-Device-Id (required for anything below), X-Firmware-Version, X-Battery (0-100).

  - No X-Device-Id header, a malformed one, or a path that is not POS-facing: the request passes through untouched.
  - Header present for a REGISTERED device: last_seen_at / firmware_version / battery_pct are updated (best effort,
    after the request has been let through, at most once per REPORT_INTERVAL_S unless the values changed).
  - Only when POS_DEVICE_ENFORCEMENT_ENABLED is true (default OFF) AND the header is present AND that device is
    registered and disabled: the request gets HTTP 403 {"code": "DEVICE_DISABLED"} and never reaches the payment route.
  - Any error in here (database down, bad data) lets the request through: this layer can never stop or slow a payment.

It is a plain ASGI middleware (registered once in app/main.py), so no payment route file is touched.
"""
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Optional

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.database import SessionLocal
from app.models import PosDevice

logger = logging.getLogger("tapgo.pos_device")

POS_PATH_PREFIXES = ("/api/nfc/pay", "/api/qr/", "/api/wallet/pos/")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{3,64}$")
REPORT_INTERVAL_S = 30

_last_report: dict = {}
_lock = threading.Lock()


def enforcement_enabled() -> bool:
    return os.getenv("POS_DEVICE_ENFORCEMENT_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def parse_battery(raw: Optional[str]) -> Optional[int]:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def parse_firmware(raw: Optional[str]) -> Optional[str]:
    text = (raw or "").strip()[:40]
    return text if text and re.match(r"^[\w.\-+ ]+$", text) else None


def is_disabled(device_id: str) -> bool:
    """True only for a registered device that an administrator disabled."""
    db = SessionLocal()
    try:
        status = db.query(PosDevice.status).filter(PosDevice.device_id == device_id).scalar()
        return status == "disabled"
    finally:
        db.close()


def report(device_id: str, firmware: Optional[str], battery: Optional[int]) -> None:
    """Record that a registered device was seen. Never raises."""
    try:
        key = (device_id, firmware, battery)
        now = time.monotonic()
        with _lock:
            last = _last_report.get(device_id)
            if last and last[0] == key and now - last[1] < REPORT_INTERVAL_S:
                return
            _last_report[device_id] = (key, now)
        db = SessionLocal()
        try:
            row = db.query(PosDevice).filter(PosDevice.device_id == device_id).first()
            if row is None:
                return
            row.last_seen_at = datetime.utcnow()
            if firmware:
                row.firmware_version = firmware
            if battery is not None:
                row.battery_pct = battery
            db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("pos device report skipped: %s", type(exc).__name__)


def _spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True, name="pos-device-report").start()


class PosDeviceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        device_id = firmware = battery = None
        for name, value in scope.get("headers", ()):
            if name == b"x-device-id":
                device_id = value.decode("latin-1").strip()
            elif name == b"x-firmware-version":
                firmware = value.decode("latin-1")
            elif name == b"x-battery":
                battery = value.decode("latin-1")
        if (device_id is None or not DEVICE_ID_RE.match(device_id)
                or not scope.get("path", "").startswith(POS_PATH_PREFIXES)):
            return await self.app(scope, receive, send)      # today's behaviour: nothing changes without the header
        try:
            if enforcement_enabled() and await run_in_threadpool(is_disabled, device_id):
                response = JSONResponse(status_code=403, content={
                    "success": False, "status": "Failed", "code": "DEVICE_DISABLED",
                    "message": "This POS device has been disabled. Please contact Tap & Go support."})
                return await response(scope, receive, send)
            _spawn(report, device_id, parse_firmware(firmware), parse_battery(battery))
        except Exception as exc:  # noqa: BLE001 - never let this layer stop a payment
            logger.warning("pos device gate skipped: %s", type(exc).__name__)
        return await self.app(scope, receive, send)
