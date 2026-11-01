"""Phase 5 of the admin hardening: date/passenger/driver filters, vehicle, balance-after and type columns."""
import csv
import io
from datetime import datetime
from decimal import Decimal

import pytest

from app.models import Transaction
from helpers import Env


@pytest.fixture
def env():
    e = Env()
    e.ah = e.admin_headers(e.add_admin())
    e.p1 = e.add_user("p1@example.com")
    e.p2 = e.add_user("p2@example.com")
    e.d1 = e.add_user("d1@example.com", account_type="driver", vehicle_type="auto", vehicle_registration="MH01AB1234")
    e.d2 = e.add_user("d2@example.com", account_type="driver", vehicle_type="taxi", vehicle_registration="MH02CD5678")
    db = e.db()
    try:
        rows = [
            ("T1", e.p1, e.d1, "2026-10-01 10:00", "ride_payment", "50.00", "wallet"),
            ("T2", e.p1, e.d2, "2026-10-15 23:59", "ride_payment", "75.00", "nfc"),
            ("T3", e.p2, e.d1, "2026-10-16 00:00", "ride_payment", "20.00", "qr"),
            ("T4", e.p2, None, "2026-11-01 09:30", "deposit", "500.00", "razorpay"),
        ]
        for ref, p, d, at, kind, amount, method in rows:
            db.add(Transaction(reference=ref, passenger_id=p, driver_id=d, amount=Decimal(amount), payment_method=method,
                               status="completed", transaction_type=kind, balance_after=Decimal("123.45"),
                               created_at=datetime.strptime(at, "%Y-%m-%d %H:%M")))
        db.commit()
    finally:
        db.close()
    return e


def refs(env, query=""):
    res = env.client.get(f"/api/admin/transactions{query}", headers=env.ah)
    assert res.status_code == 200, res.text
    return {i["reference"] for i in res.json()["items"]}


def test_no_params_returns_everything_as_before(env):
    body = env.client.get("/api/admin/transactions", headers=env.ah).json()
    assert body["total"] == 4 and body["page"] == 1 and body["page_size"] == 20
    assert refs(env) == {"T1", "T2", "T3", "T4"}
    item = next(i for i in body["items"] if i["reference"] == "T1")
    for key in ("id", "reference", "passenger", "driver", "amount", "payment_method", "status", "otp_verified",
                "fraud_status", "failure_code", "failure_reason", "created_at"):
        assert key in item                                           # every existing field is still there


def test_new_columns(env):
    item = next(i for i in env.client.get("/api/admin/transactions?search=T1", headers=env.ah).json()["items"])
    assert item["transaction_type"] == "ride_payment" and item["balance_after"] == 123.45
    assert item["vehicle_type"] == "auto" and item["vehicle_registration"] == "MH01AB1234"
    deposit = next(i for i in env.client.get("/api/admin/transactions?search=T4", headers=env.ah).json()["items"])
    assert deposit["vehicle_type"] is None and deposit["transaction_type"] == "deposit"


def test_filters(env):
    assert refs(env, "?from_date=2026-10-16") == {"T3", "T4"}
    assert refs(env, "?to_date=2026-10-15") == {"T1", "T2"}                        # to_date is inclusive
    assert refs(env, "?from_date=2026-10-15&to_date=2026-10-16") == {"T2", "T3"}
    assert refs(env, f"?passenger_id={env.p1}") == {"T1", "T2"}
    assert refs(env, f"?driver_id={env.d1}") == {"T1", "T3"}
    assert refs(env, f"?passenger_id={env.p2}&driver_id={env.d1}&from_date=2026-10-01") == {"T3"}
    assert refs(env, "?payment_method=nfc") == {"T2"}                              # existing filter still works
    assert refs(env, "?status=completed&search=T") == {"T1", "T2", "T3", "T4"}
    assert env.client.get("/api/admin/transactions?from_date=not-a-date", headers=env.ah).status_code == 422


def test_pagination_with_filters(env):
    body = env.client.get(f"/api/admin/transactions?driver_id={env.d1}&page_size=1&page=2", headers=env.ah).json()
    assert body["total"] == 2 and len(body["items"]) == 1


def test_csv_export_has_new_columns_and_honours_filters(env):
    res = env.client.get(f"/api/admin/transactions/export?driver_id={env.d1}&to_date=2026-10-15", headers=env.ah)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0] == ["Transaction ID", "Passenger", "Driver", "Amount", "Method", "Status", "Date",
                       "Type", "Balance After", "Vehicle Type", "Vehicle Registration", "Failure Reason"]
    assert [r[0] for r in rows[1:]] == ["T1"]
    assert rows[1][7:11] == ["ride_payment", "123.45", "auto", "MH01AB1234"]
    assert len(list(csv.reader(io.StringIO(env.client.get("/api/admin/transactions/export", headers=env.ah).text)))) == 5   # header + all 4


def test_requires_admin(env):
    assert env.client.get("/api/admin/transactions").status_code == 401
    assert env.client.get("/api/admin/transactions/export").status_code == 401
