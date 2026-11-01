"""Admin-only POS device registry (admin hardening, Phase 6). Every action is written to activity_logs."""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Admin, PosDevice, User
from app.routes.admin import current_admin, log

router = APIRouter(prefix="/api/admin/pos-devices", tags=["POS Devices"])

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{3,64}$")


class DeviceCreate(BaseModel):
    device_id: str
    label: Optional[str] = Field(default=None, max_length=100)
    driver_id: Optional[int] = None
    vehicle_ref: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=1000)


class DeviceUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=1000)


class DeviceAssign(BaseModel):
    """Send driver_id and/or vehicle_ref; a field sent as null clears it, a field left out is not touched."""
    driver_id: Optional[int] = None
    vehicle_ref: Optional[str] = Field(default=None, max_length=100)


def _driver(db: Session, driver_id: int) -> User:
    driver = db.get(User, driver_id)
    if not driver or driver.account_type != "driver":
        raise HTTPException(status_code=404, detail="Driver not found.")
    return driver


def _row(device: PosDevice, drivers: dict) -> dict:
    driver = drivers.get(device.driver_id)
    return {
        "id": device.id, "device_id": device.device_id, "label": device.label, "status": device.status,
        "driver_id": device.driver_id, "driver_name": driver.name if driver else None,
        "vehicle_ref": device.vehicle_ref, "notes": device.notes,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "firmware_version": device.firmware_version, "battery_pct": device.battery_pct,
        "created_at": device.created_at.isoformat() if device.created_at else None,
    }


def _rows(db: Session, devices) -> list:
    ids = {d.driver_id for d in devices if d.driver_id}
    drivers = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    return [_row(d, drivers) for d in devices]


def _get(db: Session, pk: int) -> PosDevice:
    device = db.get(PosDevice, pk)
    if not device:
        raise HTTPException(status_code=404, detail="POS device not found.")
    return device


@router.get("")
def list_devices(
    search: str = "", status: Optional[str] = Query(default=None, pattern="^(active|disabled)$"),
    page: int = 1, page_size: int = 50, admin: Admin = Depends(current_admin), db: Session = Depends(get_db),
):
    query = db.query(PosDevice)
    if status:
        query = query.filter(PosDevice.status == status)
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(PosDevice.device_id.ilike(term), PosDevice.label.ilike(term), PosDevice.vehicle_ref.ilike(term)))
    total = query.count()
    size = min(page_size, 100)
    devices = query.order_by(PosDevice.created_at.desc(), PosDevice.id.desc()).offset((max(page, 1) - 1) * size).limit(size).all()
    return {"items": _rows(db, devices), "total": total, "page": page, "page_size": size}


@router.post("", status_code=201)
def register_device(payload: DeviceCreate, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    device_id = payload.device_id.strip()
    if not DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=422, detail="Device ID must be 3-64 letters, digits or . _ : -")
    if payload.driver_id is not None:
        _driver(db, payload.driver_id)
    if db.query(PosDevice).filter(PosDevice.device_id == device_id).first():
        raise HTTPException(status_code=409, detail="A POS device with this ID is already registered.")
    device = PosDevice(device_id=device_id, label=(payload.label or "").strip() or None, driver_id=payload.driver_id,
                       vehicle_ref=(payload.vehicle_ref or "").strip() or None,
                       notes=(payload.notes or "").strip() or None, status="active")
    db.add(device)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A POS device with this ID is already registered.")
    log(db, admin, "register", "pos_device", device.id, f"Registered POS device {device_id}")
    db.commit()
    db.refresh(device)
    return _rows(db, [device])[0]


@router.get("/{device_pk}")
def device_detail(device_pk: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return _rows(db, [_get(db, device_pk)])[0]


@router.put("/{device_pk}")
def update_device(device_pk: int, payload: DeviceUpdate, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    device = _get(db, device_pk)
    for field in payload.model_fields_set:
        setattr(device, field, (getattr(payload, field) or "").strip() or None)
    log(db, admin, "update", "pos_device", device.id, f"Updated POS device {device.device_id}")
    db.commit()
    db.refresh(device)
    return _rows(db, [device])[0]


@router.post("/{device_pk}/assign")
def assign_device(device_pk: int, payload: DeviceAssign, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    device = _get(db, device_pk)
    sent = payload.model_fields_set
    notes = []
    if "driver_id" in sent:
        if payload.driver_id is not None:
            _driver(db, payload.driver_id)
        device.driver_id = payload.driver_id
        notes.append(f"driver {payload.driver_id if payload.driver_id is not None else 'unassigned'}")
    if "vehicle_ref" in sent:
        device.vehicle_ref = (payload.vehicle_ref or "").strip() or None
        notes.append(f"vehicle {device.vehicle_ref or 'unassigned'}")
    if not notes:
        raise HTTPException(status_code=422, detail="Send driver_id and/or vehicle_ref.")
    log(db, admin, "assign", "pos_device", device.id, f"POS device {device.device_id}: " + ", ".join(notes))
    db.commit()
    db.refresh(device)
    return _rows(db, [device])[0]


def _set_status(device_pk: int, status: str, admin: Admin, db: Session) -> dict:
    device = _get(db, device_pk)
    device.status = status
    log(db, admin, "disable" if status == "disabled" else "enable", "pos_device", device.id,
        f"{'Disabled' if status == 'disabled' else 'Enabled'} POS device {device.device_id}")
    db.commit()
    db.refresh(device)
    return _rows(db, [device])[0]


@router.post("/{device_pk}/disable")
def disable_device(device_pk: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return _set_status(device_pk, "disabled", admin, db)


@router.post("/{device_pk}/enable")
def enable_device(device_pk: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return _set_status(device_pk, "active", admin, db)
