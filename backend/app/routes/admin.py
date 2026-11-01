"""Live administrative APIs for the Tap&Go control centre.

The routes deliberately sit beside the existing authentication API so the
Passenger and Driver flows remain unchanged.  All list endpoints use MySQL
records; no seed or client-side demo data is returned.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
import csv
import hashlib
import json
import os
import secrets
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    ActivityLog, Admin, AdminSession, EditRequest, FraudAlert, FraudAssessment, ProjectSetting, SupportTicket,
    Transaction, User, UserDocument, Wallet, WithdrawalRequest,
)
from app.utils.security import hash_password, verify_password
from app.utils.storage_service import get_signed_url

router = APIRouter(prefix="/api/admin", tags=["Administration"])


class AdminLogin(BaseModel):
    email: str
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    status: Optional[str] = None


class ActionRequest(BaseModel):
    action: str = Field(pattern="^(activate|suspend|approve|reject|delete)$")


class WalletAction(BaseModel):
    frozen: bool


class EditReview(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    reason: Optional[str] = Field(default=None, max_length=500)   # optional rejection reason


class FraudReview(BaseModel):
    action: str = Field(pattern="^(safe|block|freeze)$")


class SettingUpdate(BaseModel):
    value: Optional[str] = None


ADMIN_SESSION_HOURS = 12
_WEAK_ADMIN_PASSWORDS = {"admin@123", "admin123", "admin", "password", "changeme"}

# Process-local throttle for administrator password guessing.
_LOGIN_FAILURES: dict = {}
_LOGIN_LOCK = threading.Lock()
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60


def _throttle_key(request: Optional[Request], email: str) -> str:
    host = request.client.host if request is not None and request.client else "?"
    return f"{email}|{host}"


def _throttled(key: str) -> bool:
    now = time.time()
    with _LOGIN_LOCK:
        recent = [t for t in _LOGIN_FAILURES.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
        _LOGIN_FAILURES[key] = recent
        return len(recent) >= LOGIN_MAX_FAILURES


def _record_failure(key: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.setdefault(key, []).append(time.time())


def _clear_failures(key: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.pop(key, None)


def ensure_default_admin(db: Session) -> Optional[Admin]:
    """Provision the first administrator ONLY from explicit environment values.

    No default account or password is ever created: ADMIN_EMAIL and
    ADMIN_PASSWORD must both be set in the environment, and the password must
    not be a well-known one. Existing administrators are never modified.
    """
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD") or ""
    if not email or not password:
        return None
    if password.lower() in _WEAK_ADMIN_PASSWORDS or len(password) < 10:
        import logging
        logging.getLogger(__name__).warning(
            "ADMIN_PASSWORD is weak or too short; default administrator not provisioned."
        )
        return None
    admin = db.query(Admin).filter(func.lower(Admin.email) == email).first()
    if not admin:
        admin = Admin(email=email, password_hash=hash_password(password), name="Tap&Go Administrator")
        db.add(admin)
        db.commit()
        db.refresh(admin)
    return admin


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_admin(
    authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)
) -> Admin:
    """Authenticate an administrator from a server-issued bearer session token.

    A client-supplied identifier (e.g. X-Admin-Id) is never trusted.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Administrator login is required.")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Administrator login is required.")
    session = db.query(AdminSession).filter(AdminSession.token_hash == _hash_token(token)).first()
    if not session or session.revoked_at is not None or session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Administrator session is invalid or expired.")
    admin = db.query(Admin).filter(Admin.id == session.admin_id, Admin.is_active.is_(True)).first()
    if not admin:
        raise HTTPException(status_code=401, detail="Administrator session is invalid or expired.")
    return admin


def to_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def document_rows(user: User, db: Session):
    """Expose every stored document attribute and future document-table entry."""
    rows = []
    for column in User.__table__.columns:
        value = getattr(user, column.name)
        if value and (column.name.endswith("_document") or column.name == "profile_photo"):
            rows.append({
                "id": f"user-{column.name}",
                "type": column.name.replace("_", " ").title(),
                "file_path": get_signed_url(value),
                "created_at": user.created_at.isoformat() if user.created_at else None,
            })
    for document in db.query(UserDocument).filter(UserDocument.user_id == user.id).all():
        rows.append({
            "id": document.id,
            "type": document.document_type,
            "file_path": get_signed_url(document.file_path),
            "created_at": document.created_at.isoformat() if document.created_at else None,
        })
    return rows


def user_row(user: User, db: Session, detailed: bool = False):
    wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
    data = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "account_type": user.account_type,
        "status": user.status or "active",
        "city": user.city,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "wallet_balance": float(wallet.balance) if wallet else 0,
        "wallet_frozen": bool(wallet.is_frozen) if wallet else False,
    }
    if detailed:
        for column in User.__table__.columns:
            if column.name not in {"password_hash"}:
                data[column.name] = to_value(getattr(user, column.name))
        data["documents"] = document_rows(user, db)
    return data


def log(db: Session, admin: Admin, action: str, entity_type: str, entity_id: Optional[int], details: str = ""):
    db.add(ActivityLog(
        admin_id=admin.id, action=action, entity_type=entity_type,
        entity_id=entity_id, details=details,
    ))


@router.post("/login")
def login(payload: AdminLogin, request: Request, db: Session = Depends(get_db)):
    input_email = payload.email.strip().lower()
    input_password = payload.password
    key = _throttle_key(request, input_email)
    if _throttled(key):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    admin = db.query(Admin).filter(func.lower(Admin.email) == input_email).first()

    valid = False
    if admin and admin.is_active and verify_password(input_password, admin.password_hash):
        valid = True

    if not valid:
        # An administrator account that lives in the users table is mirrored into
        # the admins table, but ONLY after its own password has been verified.
        user_admin = db.query(User).filter(
            (func.lower(User.email) == input_email) | (User.phone == input_email),
            User.account_type == "admin"
        ).first()
        if user_admin and verify_password(input_password, user_admin.password_hash):
            if not admin:
                admin = Admin(
                    email=user_admin.email,
                    password_hash=user_admin.password_hash,
                    name=user_admin.name or "Tap&Go Administrator"
                )
                db.add(admin)
                db.commit()
                db.refresh(admin)
            if admin.is_active:
                valid = True

    if not valid or not admin:
        _record_failure(key)
        raise HTTPException(status_code=401, detail="Invalid administrator credentials.")

    _clear_failures(key)
    raw_token = secrets.token_urlsafe(32)
    db.add(AdminSession(
        admin_id=admin.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(hours=ADMIN_SESSION_HOURS),
    ))
    log(db, admin, "login", "admin", admin.id, "Administrator signed in")
    db.commit()
    # `token` is also inside `admin` so the existing website code, which stores
    # `result.admin`, keeps the token without further changes.
    return {
        "success": True,
        "token": raw_token,
        "admin": {"id": admin.id, "name": admin.name, "email": admin.email, "token": raw_token},
    }


@router.post("/logout")
def logout(
    authorization: Optional[str] = Header(default=None),
    admin: Admin = Depends(current_admin),
    db: Session = Depends(get_db),
):
    token = (authorization or "")[len("Bearer "):].strip()
    session = db.query(AdminSession).filter(AdminSession.token_hash == _hash_token(token)).first()
    if session:
        session.revoked_at = datetime.utcnow()
        db.commit()
    return {"success": True}


@router.get("/dashboard")
def dashboard(admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    count = lambda *criteria: db.query(func.count(User.id)).filter(*criteria).scalar() or 0
    # Failed taps moved no money: they are counted separately, never in the transaction totals.
    transaction_count = db.query(func.count(Transaction.id)).filter(Transaction.status != "failed").scalar() or 0
    today_transactions = db.query(func.count(Transaction.id)).filter(
        Transaction.status != "failed",
        func.date(Transaction.created_at) == datetime.utcnow().date(),
    ).scalar() or 0
    failed_today = db.query(func.count(Transaction.id)).filter(
        Transaction.status == "failed",
        func.date(Transaction.created_at) == datetime.utcnow().date(),
    ).scalar() or 0
    wallet_balance = db.query(func.coalesce(func.sum(Wallet.balance), 0)).scalar() or 0
    revenue = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.status == "completed"
    ).scalar() or 0
    from app.services.fraud_alert_sync import sync_flagged_assessments
    sync_flagged_assessments(db)   # keeps the "Fraud Alerts" tile in step with the Fraud Centre; never raises
    return {
        "total_drivers": count(User.account_type == "driver"),
        "active_drivers": count(User.account_type == "driver", User.status == "active"),
        "pending_drivers": count(User.account_type == "driver", User.status == "pending"),
        "suspended_drivers": count(User.account_type == "driver", User.status == "suspended"),
        "total_passengers": count(User.account_type == "passenger"),
        "active_passengers": count(User.account_type == "passenger", User.status == "active"),
        "total_transactions": transaction_count,
        "today_transactions": today_transactions,
        "failed_today": failed_today,
        "wallet_balance": float(wallet_balance),
        "revenue": float(revenue),
        "fraud_alerts": db.query(func.count(FraudAlert.id)).filter(FraudAlert.status == "open").scalar() or 0,
        "pending_edit_requests": db.query(func.count(EditRequest.id)).filter(EditRequest.status == "pending").scalar() or 0,
        "pending_withdrawal_requests": db.query(func.count(WithdrawalRequest.id)).filter(WithdrawalRequest.status == "pending").scalar() or 0,
        "open_support_tickets": db.query(func.count(SupportTicket.id)).filter(SupportTicket.status.in_(["open", "in_progress"])).scalar() or 0,
    }


@router.get("/users")
def users(
    account_type: Optional[str] = Query(default=None, pattern="^(driver|passenger)$"),
    search: str = "", status: Optional[str] = None, page: int = 1, page_size: int = 20,
    admin: Admin = Depends(current_admin), db: Session = Depends(get_db),
):
    query = db.query(User)
    if account_type:
        query = query.filter(User.account_type == account_type)
    if status:
        query = query.filter(User.status == status)
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(User.name.ilike(term), User.email.ilike(term), User.phone.ilike(term)))
    total = query.count()
    records = query.order_by(User.created_at.desc()).offset((max(page, 1) - 1) * min(page_size, 100)).limit(min(page_size, 100)).all()
    return {"items": [user_row(user, db) for user in records], "total": total, "page": page, "page_size": min(page_size, 100)}


@router.get("/users/{user_id}")
def user_detail(user_id: int, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    data = user_row(user, db, detailed=True)
    data["transactions"] = transaction_rows(db.query(Transaction).filter(
        or_(Transaction.passenger_id == user.id, Transaction.driver_id == user.id)
    ).order_by(Transaction.created_at.desc()).limit(50).all(), db)
    return data


@router.put("/users/{user_id}")
def update_user(user_id: int, payload: UserUpdate, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(user, key, value)
    log(db, admin, "update", "user", user.id, "Updated user profile")
    db.commit()
    db.refresh(user)
    return user_row(user, db, detailed=True)


@router.post("/users/{user_id}/action")
def user_action(user_id: int, payload: ActionRequest, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if payload.action == "delete":
        wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
        if wallet:
            db.query(Transaction).filter(Transaction.wallet_id == wallet.id).update({Transaction.wallet_id: None}, synchronize_session=False)
            db.delete(wallet)
        db.query(UserDocument).filter(UserDocument.user_id == user.id).delete()
        db.query(EditRequest).filter(EditRequest.user_id == user.id).delete()
        db.query(Transaction).filter(Transaction.passenger_id == user.id).update({Transaction.passenger_id: None}, synchronize_session=False)
        db.query(Transaction).filter(Transaction.driver_id == user.id).update({Transaction.driver_id: None}, synchronize_session=False)
        db.query(FraudAlert).filter(FraudAlert.user_id == user.id).update({FraudAlert.user_id: None}, synchronize_session=False)
        db.query(ActivityLog).filter(ActivityLog.user_id == user.id).update({ActivityLog.user_id: None}, synchronize_session=False)
        db.delete(user)
    elif payload.action == "approve":
        user.status = "active"
    elif payload.action == "reject":
        user.status = "rejected"
    else:
        user.status = "active" if payload.action == "activate" else "suspended"
    log(db, admin, payload.action, "user", user_id, f"{payload.action.title()} user")
    db.commit()
    return {"success": True, "action": payload.action}


def transaction_rows(rows, db: Session):
    user_ids = {value for row in rows for value in (row.passenger_id, row.driver_id) if value}
    people = {person.id: person.name for person in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    return [{
        "id": row.id, "reference": row.reference, "passenger": people.get(row.passenger_id),
        "driver": people.get(row.driver_id), "amount": float(row.amount), "payment_method": row.payment_method,
        "status": row.status, "otp_verified": row.otp_verified, "fraud_status": row.fraud_status,
        "failure_code": row.failure_code,
        "failure_reason": (row.description or "").replace("NFC payment failed: ", "", 1) if row.status == "failed" else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows]


@router.get("/transactions")
def transactions(
    search: str = "", status: Optional[str] = None, payment_method: Optional[str] = None,
    page: int = 1, page_size: int = 20, admin: Admin = Depends(current_admin), db: Session = Depends(get_db),
):
    query = db.query(Transaction)
    if search.strip():
        query = query.filter(Transaction.reference.ilike(f"%{search.strip()}%"))
    if status:
        query = query.filter(Transaction.status == status)
    if payment_method:
        query = query.filter(Transaction.payment_method == payment_method)
    total = query.count()
    rows = query.order_by(Transaction.created_at.desc()).offset((max(page, 1) - 1) * min(page_size, 100)).limit(min(page_size, 100)).all()
    return {"items": transaction_rows(rows, db), "total": total, "page": page, "page_size": min(page_size, 100)}


@router.get("/transactions/export")
def export_transactions(admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Transaction ID", "Passenger", "Driver", "Amount", "Method", "Status", "Date", "Failure Reason"])
    for row in transaction_rows(db.query(Transaction).order_by(Transaction.created_at.desc()).all(), db):
        writer.writerow([row["reference"], row["passenger"] or "", row["driver"] or "", row["amount"], row["payment_method"], row["status"], row["created_at"], row["failure_reason"] or ""])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tapgo-transactions.csv"})


@router.get("/wallets")
def wallets(search: str = "", page: int = 1, page_size: int = 20, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    query = db.query(Wallet, User).join(User, Wallet.user_id == User.id)
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(User.name.ilike(term), User.email.ilike(term)))
    total = query.count()
    rows = query.order_by(Wallet.updated_at.desc()).offset((max(page, 1) - 1) * min(page_size, 100)).limit(min(page_size, 100)).all()
    return {"items": [{"id": wallet.id, "user_id": user.id, "name": user.name, "email": user.email, "account_type": user.account_type, "balance": float(wallet.balance), "is_frozen": wallet.is_frozen, "updated_at": wallet.updated_at.isoformat() if wallet.updated_at else None} for wallet, user in rows], "total": total, "page": page, "page_size": min(page_size, 100)}


@router.post("/wallets/{wallet_id}")
def set_wallet_state(wallet_id: int, payload: WalletAction, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    wallet = db.get(Wallet, wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found.")
    wallet.is_frozen = payload.frozen
    log(db, admin, "freeze" if payload.frozen else "unfreeze", "wallet", wallet.id, "Changed wallet state")
    db.commit()
    return {"success": True, "is_frozen": wallet.is_frozen}


@router.get("/documents")
def documents(search: str = "", page: int = 1, page_size: int = 30, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    query = db.query(User)
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(User.name.ilike(term), User.email.ilike(term)))
    records = query.order_by(User.created_at.desc()).all()
    rows = [{"user_id": user.id, "user_name": user.name, "account_type": user.account_type, **document} for user in records for document in document_rows(user, db)]
    start, size = (max(page, 1) - 1) * min(page_size, 100), min(page_size, 100)
    return {"items": rows[start:start + size], "total": len(rows), "page": page, "page_size": size}


@router.get("/edit-requests")
def edit_requests(status: Optional[str] = None, page: int = 1, page_size: int = 20, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    query = db.query(EditRequest, User).join(User, EditRequest.user_id == User.id)
    if status:
        query = query.filter(EditRequest.status == status)
    total = query.count()
    rows = query.order_by(EditRequest.created_at.desc()).offset((max(page, 1) - 1) * min(page_size, 100)).limit(min(page_size, 100)).all()

    type_titles = {
        "phone": "Phone Number Change",
        "bank": "Bank Details Change",
        "documents": "Document Edit",
    }

    def current_value(request, user):
        """What the user has on file now for the field (the 'before' side when previous_value was not captured)."""
        if request.field_name == "phone":
            return user.phone
        if request.field_name == "bank":
            return json.dumps({
                "bank_account_holder": user.bank_account_holder, "bank_account_number": user.bank_account_number,
                "bank_ifsc": user.bank_ifsc, "bank_upi_id": user.bank_upi_id,
            })
        return None

    return {
        "items": [
            {
                "id": request.id,
                "user_id": user.id,
                "user_name": user.name,
                "user_email": user.email,
                "account_type": user.account_type,
                "request_type": type_titles.get(request.field_name, request.field_name.replace("_", " ").title()),
                "field_name": request.field_name,
                "previous_value": request.previous_value,
                "new_value": request.new_value,
                "current_value": current_value(request, user),
                "reason": request.reason or f"Request for {request.field_name} modification permission",
                "admin_note": request.admin_note,
                "status": request.status,
                "created_at": request.created_at.isoformat() if request.created_at else None,
                "reviewed_at": request.reviewed_at.isoformat() if request.reviewed_at else None
            }
            for request, user in rows
        ],
        "total": total,
        "page": page,
        "page_size": min(page_size, 100)
    }


@router.post("/edit-requests/{request_id}/review")
def review_edit_request(request_id: int, payload: EditReview, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    request = db.get(EditRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Edit request not found.")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail="This request has already been reviewed.")
    user = db.get(User, request.user_id)
    # Explicit map: "reject" + "d" used to be stored as the invalid status "rejectd",
    # which the admin "rejected" filter could never match.
    new_status = {"approve": "approved", "reject": "rejected"}[payload.action]
    # Claim the review atomically so two administrators cannot both decide it.
    claimed = db.query(EditRequest).filter(
        EditRequest.id == request_id, EditRequest.status == "pending"
    ).update(
        {"status": new_status, "reviewed_by": admin.id, "reviewed_at": datetime.utcnow(),
         **({"admin_note": (payload.reason or "").strip() or None} if payload.action == "reject" else {})},
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This request has already been reviewed.")
    db.refresh(request)

    if user:
        if payload.action == "approve":
            if request.field_name == "bank":
                user.bank_request_status = "approved"
                user.bank_locked = 0  # UNLOCKED for user to edit!
            elif request.field_name == "phone":
                user.phone_request_status = "approved"  # UNLOCKED for user to edit!
            elif request.field_name == "documents":
                user.doc_request_status = "approved"  # UNLOCKED for document upload!
        else:  # reject
            if request.field_name == "bank":
                user.bank_request_status = "rejected"
                user.bank_locked = 1
            elif request.field_name == "phone":
                user.phone_request_status = "rejected"
            elif request.field_name == "documents":
                user.doc_request_status = "rejected"

    log(db, admin, payload.action, "edit_request", request.id, f"Reviewed edit request #{request.id} for user #{request.user_id} ({request.field_name}): {payload.action}")
    db.commit()

    # Tell the user the outcome (a delivery failure never undoes the decision).
    if user and user.email:
        try:
            from app.utils.email_service import send_edit_request_decision_email
            send_edit_request_decision_email(
                to_email=user.email,
                user_name=user.name,
                request_type=request.field_name,
                approved=(payload.action == "approve"),
            )
        except Exception:
            pass
    return {"success": True, "status": request.status}


# Stored alert statuses behind each filter value. The review endpoint stores the action name (safe / block / freeze).
FRAUD_STATUS_FILTERS = {
    "open": ["open", "flagged"], "safe": ["safe"], "blocked": ["block", "blocked"], "reviewed": ["freeze", "reviewed"],
}


@router.get("/fraud-alerts")
def fraud_alerts(
    status: Optional[str] = Query(default=None, pattern="^(open|flagged|reviewed|safe|blocked|all)$"),
    page: int = 1, page_size: int = 20, admin: Admin = Depends(current_admin), db: Session = Depends(get_db),
):
    """Flagged alerts (open) by default; `status` selects open / reviewed / safe / blocked, or `all`."""
    from app.services.fraud_alert_sync import assessment_id_of, sync_flagged_assessments
    sync_flagged_assessments(db)
    query = db.query(FraudAlert)
    wanted = (status or "open").lower()
    if wanted == "flagged":
        wanted = "open"
    if wanted != "all":
        query = query.filter(FraudAlert.status.in_(FRAUD_STATUS_FILTERS[wanted]))
    total = query.count()
    size = min(page_size, 100)
    rows = query.order_by(FraudAlert.created_at.desc()).offset((max(page, 1) - 1) * size).limit(size).all()

    user_ids = {alert.user_id for alert in rows if alert.user_id}
    people = {u.id: u.name for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    assessment_ids = {assessment_id_of(alert) for alert in rows} - {None}
    assessed = {a.id: a for a in db.query(FraudAssessment).filter(FraudAssessment.id.in_(assessment_ids)).all()} if assessment_ids else {}
    txn_ids = {alert.transaction_id for alert in rows if alert.transaction_id}
    txns = {t.id: t for t in db.query(Transaction).filter(Transaction.id.in_(txn_ids)).all()} if txn_ids else {}

    def amount_of(alert):
        assessment = assessed.get(assessment_id_of(alert))
        if assessment is not None:
            return float(assessment.amount)
        txn = txns.get(alert.transaction_id)
        return float(txn.amount) if txn is not None else None

    return {"items": [{
        "id": alert.id, "user_id": alert.user_id, "user_name": people.get(alert.user_id),
        "transaction_id": alert.transaction_id, "amount": amount_of(alert),
        "risk_score": alert.risk_score, "reason": alert.reason, "status": alert.status,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "reviewed_at": alert.reviewed_at.isoformat() if alert.reviewed_at else None,
    } for alert in rows], "total": total, "page": page, "page_size": size}


@router.post("/fraud-alerts/{alert_id}/review")
def review_fraud_alert(alert_id: int, payload: FraudReview, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    alert = db.get(FraudAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Fraud alert not found.")
    alert.status, alert.reviewed_at = payload.action, datetime.utcnow()
    user = db.get(User, alert.user_id) if alert.user_id else None
    if user and payload.action == "block":
        user.status = "suspended"
    if user and payload.action == "freeze":
        wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
        if wallet:
            wallet.is_frozen = True
    log(db, admin, payload.action, "fraud_alert", alert.id, "Reviewed fraud alert")
    db.commit()
    return {"success": True, "status": alert.status}


@router.get("/activity-logs")
def activity_logs(page: int = 1, page_size: int = 30, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    query = db.query(ActivityLog)
    total = query.count()
    rows = query.order_by(ActivityLog.created_at.desc()).offset((max(page, 1) - 1) * min(page_size, 100)).limit(min(page_size, 100)).all()
    return {"items": [{"id": row.id, "action": row.action, "entity_type": row.entity_type, "entity_id": row.entity_id, "details": row.details, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows], "total": total, "page": page, "page_size": min(page_size, 100)}


@router.get("/settings")
def get_settings(admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    return {"items": [{"key": item.key, "value": item.value, "updated_at": item.updated_at.isoformat() if item.updated_at else None} for item in db.query(ProjectSetting).order_by(ProjectSetting.key).all()]}


@router.put("/settings/{key}")
def update_setting(key: str, payload: SettingUpdate, admin: Admin = Depends(current_admin), db: Session = Depends(get_db)):
    setting = db.get(ProjectSetting, key)
    if not setting:
        setting = ProjectSetting(key=key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
    log(db, admin, "update", "setting", None, key)
    db.commit()
    return {"key": setting.key, "value": setting.value}


# ── Withdrawal Request Admin Routes ──────────────────────────────────────────

from app.utils.email_service import (
    send_withdrawal_approved_email,
    send_withdrawal_paid_email,
    send_withdrawal_rejected_email,
)


class WithdrawalRejectRequest(BaseModel):
    admin_note: Optional[str] = None


def wr_to_dict(wr: WithdrawalRequest) -> dict:
    return {
        "id": wr.id,
        "user_id": wr.user_id,
        "wallet_id": wr.wallet_id,
        "hold_transaction_id": wr.hold_transaction_id,
        "amount": float(wr.amount),
        "destination_desc": wr.destination_desc,
        "reference": wr.reference,
        "status": wr.status,
        "admin_note": wr.admin_note,
        "reviewed_at": wr.reviewed_at.isoformat() if wr.reviewed_at else None,
        "paid_at": wr.paid_at.isoformat() if wr.paid_at else None,
        "created_at": wr.created_at.isoformat() if wr.created_at else None,
    }


@router.get("/withdrawal-requests")
def list_withdrawal_requests(
    status: Optional[str] = Query(default=None),
    page: int = 1,
    page_size: int = 20,
    admin: Admin = Depends(current_admin),
    db: Session = Depends(get_db),
):
    """List all withdrawal requests, filterable by status."""
    query = db.query(WithdrawalRequest)
    if status:
        query = query.filter(WithdrawalRequest.status == status)
    total = query.count()
    items = query.order_by(WithdrawalRequest.created_at.desc()).offset(
        (max(page, 1) - 1) * min(page_size, 100)
    ).limit(min(page_size, 100)).all()
    return {
        "items": [wr_to_dict(w) for w in items],
        "total": total,
        "page": page,
        "page_size": min(page_size, 100),
    }


def _claim_transition(db: Session, request_id: int, from_status: str, to_status: str, admin: Admin, **extra) -> bool:
    """Atomically move a withdrawal request between states.

    A conditional UPDATE (WHERE status = from_status) decides the single winner
    of concurrent approve/reject/pay calls, on any database, without relying on
    row locks. Returns True only for the caller that performed the transition.
    """
    values = {"status": to_status, "admin_id": admin.id, **extra}
    return db.query(WithdrawalRequest).filter(
        WithdrawalRequest.id == request_id, WithdrawalRequest.status == from_status
    ).update(values, synchronize_session=False) == 1


@router.patch("/withdrawal-requests/{request_id}/approve")
def approve_withdrawal(
    request_id: int,
    admin: Admin = Depends(current_admin),
    db: Session = Depends(get_db),
):
    """
    Approve a pending withdrawal request. Balance is already reserved.
    Idempotent: if the request is no longer pending, its current state is returned.
    """
    wr = db.get(WithdrawalRequest, request_id)
    if not wr:
        raise HTTPException(status_code=404, detail="Withdrawal request not found.")

    if not _claim_transition(db, request_id, "pending", "approved", admin, reviewed_at=datetime.utcnow()):
        db.rollback()
        db.refresh(wr)
        return {"success": True, "message": f"Request is already in status '{wr.status}'.", "withdrawal_request": wr_to_dict(wr)}

    if wr.hold_transaction_id:
        db.query(Transaction).filter(Transaction.id == wr.hold_transaction_id).update(
            {"status": "approved"}, synchronize_session=False
        )

    log(db, admin, "approve", "withdrawal_request", wr.id, f"Approved withdrawal #{wr.reference} for user {wr.user_id}")
    db.commit()
    db.refresh(wr)

    user = db.get(User, wr.user_id)
    if user:
        try:
            send_withdrawal_approved_email(
                to_email=user.email,
                user_name=user.name,
                amount=float(wr.amount),
                reference=wr.reference,
            )
        except Exception:
            pass

    return {"success": True, "withdrawal_request": wr_to_dict(wr)}


@router.patch("/withdrawal-requests/{request_id}/pay")
def mark_withdrawal_paid(
    request_id: int,
    admin: Admin = Depends(current_admin),
    db: Session = Depends(get_db),
):
    """
    Mark an approved withdrawal as paid out (approved -> paid only).
    No balance change - the balance was reserved at submission.
    Idempotent: if already paid, returns the current state.
    """
    wr = db.get(WithdrawalRequest, request_id)
    if not wr:
        raise HTTPException(status_code=404, detail="Withdrawal request not found.")

    if not _claim_transition(db, request_id, "approved", "paid", admin, paid_at=datetime.utcnow()):
        db.rollback()
        db.refresh(wr)
        if wr.status == "paid":
            return {"success": True, "message": "Request is already marked as paid.", "withdrawal_request": wr_to_dict(wr)}
        raise HTTPException(status_code=400, detail=f"Cannot mark as paid from status '{wr.status}'. Must be 'approved' first.")

    if wr.hold_transaction_id:
        db.query(Transaction).filter(Transaction.id == wr.hold_transaction_id).update(
            {"status": "completed", "transaction_type": "withdrawal"}, synchronize_session=False
        )

    log(db, admin, "pay", "withdrawal_request", wr.id, f"Marked withdrawal #{wr.reference} as paid for user {wr.user_id}")
    db.commit()
    db.refresh(wr)

    user = db.get(User, wr.user_id)
    if user:
        try:
            send_withdrawal_paid_email(
                to_email=user.email,
                user_name=user.name,
                amount=float(wr.amount),
                reference=wr.reference,
            )
        except Exception:
            pass

    return {"success": True, "withdrawal_request": wr_to_dict(wr)}


@router.patch("/withdrawal-requests/{request_id}/reject")
def reject_withdrawal(
    request_id: int,
    payload: WithdrawalRejectRequest,
    admin: Admin = Depends(current_admin),
    db: Session = Depends(get_db),
):
    """
    Reject a pending withdrawal request and return the reserved balance.
    Only 'pending' requests can be rejected. The status change, the refund and
    the audit transaction commit together (or not at all); the conditional
    status update guarantees at most one refund even under concurrent calls.
    """
    wr = db.get(WithdrawalRequest, request_id)
    if not wr:
        raise HTTPException(status_code=404, detail="Withdrawal request not found.")

    note = payload.admin_note.strip() if payload.admin_note else None
    if not _claim_transition(
        db, request_id, "pending", "rejected", admin, admin_note=note, reviewed_at=datetime.utcnow()
    ):
        db.rollback()
        db.refresh(wr)
        if wr.status == "rejected":
            return {"success": True, "message": "Request is already rejected.", "withdrawal_request": wr_to_dict(wr)}
        raise HTTPException(status_code=400, detail=f"Cannot reject from status '{wr.status}'. Only 'pending' requests can be rejected.")

    wallet = db.query(Wallet).filter(Wallet.id == wr.wallet_id).first()
    if not wallet:
        db.rollback()
        raise HTTPException(status_code=500, detail="Wallet not found for this withdrawal request.")

    reversal_amount = wr.amount
    # Atomic increment; works even if the wallet has since been frozen (it is the user's own money).
    db.query(Wallet).filter(Wallet.id == wallet.id).update(
        {Wallet.balance: Wallet.balance + reversal_amount}, synchronize_session=False
    )
    db.flush()
    db.refresh(wallet)

    if wr.hold_transaction_id:
        db.query(Transaction).filter(Transaction.id == wr.hold_transaction_id).update(
            {"status": "cancelled"}, synchronize_session=False
        )

    user = db.get(User, wr.user_id)
    db.add(Transaction(
        reference=f"REV-{wr.reference}",
        passenger_id=wr.user_id if user and user.account_type == "passenger" else None,
        driver_id=wr.user_id if user and user.account_type == "driver" else None,
        wallet_id=wallet.id,
        amount=reversal_amount,
        payment_method="bank_transfer",
        status="completed",
        otp_verified=True,
        fraud_status="clear",
        transaction_type="withdrawal_reversal",
        description=f"Reversal of rejected withdrawal {wr.reference}",
        balance_after=wallet.balance,
    ))

    log(db, admin, "reject", "withdrawal_request", wr.id,
        f"Rejected withdrawal #{wr.reference} for user {wr.user_id}. Balance restored.")
    db.commit()
    db.refresh(wr)

    if user:
        try:
            send_withdrawal_rejected_email(
                to_email=user.email,
                user_name=user.name,
                amount=float(wr.amount),
                reference=wr.reference,
                admin_note=payload.admin_note,
            )
        except Exception:
            pass

    return {"success": True, "withdrawal_request": wr_to_dict(wr)}
