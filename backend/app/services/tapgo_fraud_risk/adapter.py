"""
adapter.py  –  Convert Tap & Go backend records into scorer inputs. Pure functions: no database, no network.

Backend facts this adapter relies on (read from `Tap@Go Hosted/backend/app/models.py` and `routes/qr.py`):
  * `transactions`: passenger_id, driver_id, amount (Numeric), payment_method, status, transaction_type, idempotency_key,
    created_at (a NAIVE DateTime). The QR route compares times with `datetime.utcnow()`, so stored times are evidently
    UTC; the timezone is nevertheless an explicit, required setting (never silently assumed).
  * ride payments are `transaction_type = "ride_payment"`; failed attempts are rolled back, not stored.
  * vehicle type lives on the driver's `users.vehicle_type` (nullable).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

RIDE_TYPES = {"ride_payment"}


class AdapterError(ValueError):
    """Backend data cannot be converted safely (the service turns this into a fail-safe result)."""


def _get(row: Any, name: str):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def to_aware_iso(ts: Any, db_timezone: str) -> str:
    """A backend timestamp -> ISO-8601 with offset. Naive values are interpreted in `db_timezone` (explicit config)."""
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError as e:
            raise AdapterError(f"unparseable timestamp {ts!r}") from e
    if not isinstance(ts, datetime):
        raise AdapterError(f"timestamp must be a datetime or ISO string, got {type(ts).__name__}")
    if ts.tzinfo is None or ts.utcoffset() is None:
        ts = ts.replace(tzinfo=ZoneInfo(db_timezone))
    return ts.isoformat()


def _amount(v: Any) -> float:
    if isinstance(v, Decimal):
        return float(v)
    return v                     # the scorer validates type/range and fails explicitly


def history_from_transactions(rows: Iterable[Any], passenger_id: Any, db_timezone: str,
                              vehicle_types: Mapping[Any, str | None] | None = None) -> list[dict]:
    """This passenger's earlier ride payments (any status) in scorer format. Rows of other passengers or other
    transaction types are ignored; the scorer itself counts only completed rides and de-duplicates idempotency keys."""
    out = []
    for r in rows:
        if _get(r, "passenger_id") != passenger_id or _get(r, "transaction_type") not in RIDE_TYPES:
            continue
        drv = _get(r, "driver_id")
        out.append({"timestamp": to_aware_iso(_get(r, "created_at"), db_timezone), "amount": _amount(_get(r, "amount")),
                    "driver_id": drv, "payment_method": _get(r, "payment_method"),
                    "vehicle_type": (vehicle_types or {}).get(drv), "status": str(_get(r, "status") or "").lower(),
                    "idempotency_key": _get(r, "idempotency_key")})
    return out


def transaction_for_scoring(passenger_id: Any, driver_id: Any, amount: Any, at: Any, db_timezone: str,
                            payment_method: str | None = "QR", vehicle_type: str | None = None,
                            idempotency_key: str | None = None) -> dict:
    """The ride payment about to be executed (before the wallet transfer)."""
    if at is None:
        at = datetime.now(timezone.utc)
    return {"timestamp": to_aware_iso(at, db_timezone), "amount": _amount(amount), "driver_id": driver_id,
            "payment_method": payment_method, "vehicle_type": vehicle_type, "idempotency_key": idempotency_key}
