"""Safety and dashboard checks for scripts/seed_passenger_demo_history.py.

Runs against an isolated in-memory database wired into the app (no network, no real DB).
"""
import importlib.util
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models import Transaction, User, Wallet
from app.utils.security import hash_password
from helpers import Env

BACKEND = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("seed_passenger_demo", BACKEND / "scripts" / "seed_passenger_demo_history.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

ANCHOR = date(2026, 10, 20)


def _add_user(db, uid, name, account_type="passenger", balance=None):
    db.add(User(id=uid, name=name, email=f"u{uid}@test.local", phone=str(9000000000 + uid),
                password_hash=hash_password("Passw0rd!x"), account_type=account_type, status="active"))
    db.flush()
    if balance is not None:
        db.add(Wallet(user_id=uid, balance=Decimal(str(balance)), is_frozen=False))


@pytest.fixture
def env():
    e = Env()
    db = e.db()
    _add_user(db, 27, "Rakesh Sharma", account_type="driver", balance=25)
    _add_user(db, 2, "Other Passenger", balance=100)
    _add_user(db, 69, "Moksh Gala", balance=0)
    _add_user(db, 70, "Aarav Sharma", balance=0)
    db.commit()
    w2 = db.query(Wallet).filter(Wallet.user_id == 2).one()
    # A genuine ride and a row from the *driver* demo seed: neither may ever be touched.
    db.add(Transaction(reference="QR897BBC7F73", passenger_id=2, driver_id=27, wallet_id=w2.id,
                       amount=Decimal("25.00"), payment_method="QR", status="completed", otp_verified=True,
                       transaction_type="ride_payment", balance_after=Decimal("100.00"),
                       created_at=datetime(2026, 10, 20, 14, 56, 42)))
    db.add(Transaction(reference="DEMO-TXN-000001", passenger_id=2, driver_id=27, amount=Decimal("80.00"),
                       payment_method="QR", status="completed", transaction_type="ride_payment",
                       payment_source="demo_seed", balance_after=Decimal("80.00"),
                       created_at=datetime(2026, 9, 1, 8, 0, 0)))
    db.commit()
    db.close()
    yield e
    from app.main import app
    app.dependency_overrides.clear()


def _dump(env, owned=False):
    with env.engine.connect() as c:
        tx = c.execute(text("SELECT * FROM transactions WHERE reference NOT LIKE 'DEMO-P%' ORDER BY id")).all()
        return {"users": c.execute(text("SELECT * FROM users ORDER BY id")).all(),
                "wallets": c.execute(text("SELECT * FROM wallets ORDER BY id")).all(),
                "transactions": tx}


def _owned(env, pid=None):
    with env.engine.connect() as c:
        q = "SELECT * FROM transactions WHERE payment_source='demo_seed' AND reference LIKE 'DEMO-P%'"
        if pid:
            q += f" AND passenger_id={pid}"
        return c.execute(text(q + " ORDER BY created_at, id")).mappings().all()


# ---------------------------------------------------------------- plan
@pytest.mark.parametrize("pid", [69, 70])
def test_plan_is_consistent(pid):
    rows = seed.build_plan(pid, ANCHOR)
    assert len(rows) == 60
    assert sum(r["kind"] == "ride" for r in rows) == 48
    assert all(r["reference"].startswith(f"DEMO-P{pid}-") for r in rows)
    bal = Decimal(0)
    for r in rows:
        bal += r["amount"] if r["kind"] == "topup" else -r["amount"]
        assert bal == r["balance_after"] >= 0
    assert bal == 0
    assert rows == seed.build_plan(pid, ANCHOR)     # deterministic


# ---------------------------------------------------------------- script safety
def test_dry_run_writes_nothing(env):
    before = _dump(env)
    seed.do_seed(env.engine, ANCHOR, apply=False)
    assert _dump(env) == before and not _owned(env)


def test_apply_inserts_only_marked_rows_and_keeps_wallets(env):
    before = _dump(env)
    seed.do_seed(env.engine, ANCHOR, apply=True)
    assert _dump(env) == before          # users, wallets and every other transaction untouched
    rows = _owned(env)
    assert len(rows) == 120
    assert Counter_of(rows, "passenger_id") == {69: 60, 70: 60}
    for r in rows:
        assert r["payment_source"] == "demo_seed" and r["driver_id"] is None and r["status"] == "completed"
        assert r["reference"].startswith(f"DEMO-P{r['passenger_id']}-")
        for col in ("provider", "provider_transaction_id", "utr", "payer_name", "idempotency_key",
                    "payment_request_id", "email_received_at", "raw_email_id", "related_transaction_id"):
            assert r[col] is None, col
    assert env.balance(69) == 0 and env.balance(70) == 0


def Counter_of(rows, key):
    from collections import Counter
    return dict(Counter(r[key] for r in rows))


def test_apply_is_idempotent(env):
    seed.do_seed(env.engine, ANCHOR, apply=True)
    first = [dict(r) for r in _owned(env)]
    seed.do_seed(env.engine, ANCHOR, apply=True)
    assert [dict(r) for r in _owned(env)] == first


def test_reset_removes_only_owned_rows(env):
    before = _dump(env)
    seed.do_seed(env.engine, ANCHOR, apply=True)
    seed.do_reset(env.engine, apply=False)
    assert len(_owned(env)) == 120
    seed.do_reset(env.engine, apply=True)
    assert not _owned(env)
    assert _dump(env) == before          # driver-seed DEMO-TXN row and genuine row still there


@pytest.mark.parametrize("setup, message", [
    ("UPDATE wallets SET balance = 5 WHERE user_id = 69", "not 0.00"),
    ("UPDATE users SET name = 'Someone Else' WHERE id = 70", "not the active passenger"),
    ("UPDATE users SET status = 'suspended' WHERE id = 69", "not the active passenger"),
    ("DELETE FROM wallets WHERE user_id = 70", "no wallet"),
    ("INSERT INTO transactions (reference, passenger_id, amount, payment_method, status, otp_verified, "
     "fraud_status, transaction_type) VALUES ('REAL-1', 69, 10, 'QR', 'completed', 0, 'clear', 'ride_payment')",
     "genuine transaction"),
    ("INSERT INTO transactions (reference, passenger_id, driver_id, amount, payment_method, status, otp_verified, "
     "fraud_status, payment_source) VALUES ('DEMO-P70-X', 2, 27, 10, 'QR', 'completed', 0, 'clear', 'demo_seed')",
     "not owned"),
])
def test_refuses_unsafe_state(env, setup, message):
    with env.engine.begin() as c:
        c.execute(text(setup))
    before, owned_before = _dump(env), _owned(env)
    with pytest.raises(seed.SeedError, match=message):
        seed.do_seed(env.engine, ANCHOR, apply=True)
    assert _dump(env) == before and _owned(env) == owned_before


def test_apply_requires_confirm_project():
    assert seed.main(["seed", "--apply"]) == 1


# ---------------------------------------------------------------- dashboards
def test_passenger_sees_only_own_demo_history(env):
    seed.do_seed(env.engine, ANCHOR, apply=True)
    for pid in (69, 70):
        res = env.client.get(f"/api/wallet/{pid}/transactions", headers=env.user_headers(pid))
        assert res.status_code == 200
        txns = res.json()["transactions"]
        assert len(txns) == 60
        assert all(t["passenger_id"] == pid and t["is_synthetic"] for t in txns)
        rides = [t for t in txns if t["transaction_type"] == "ride_payment"]
        assert len(rides) == 48 and all(t["type"] == "Ride Payment" and not t["is_credit"] for t in rides)
        names = {d for v in seed.PASSENGERS[pid]["drivers"].values() for d in v}
        assert all(t["driver"] in names and t["driver"] in t["description"] and "(demo)" in t["description"]
                   for t in rides)
        topups = [t for t in txns if t["transaction_type"] == "deposit"]
        assert len(topups) == 12 and all(t["is_credit"] and "Demo" in t["description"] for t in topups)
        assert txns[0]["balance_after"] == 0.0


def test_passengers_cannot_read_each_other(env):
    seed.do_seed(env.engine, ANCHOR, apply=True)
    assert env.client.get("/api/wallet/70/transactions", headers=env.user_headers(69)).status_code == 403
    assert env.client.get("/api/wallet/69/transactions", headers=env.user_headers(70)).status_code == 403
    assert env.client.get("/api/wallet/69/transactions").status_code in (401, 403)


def test_admin_filters_by_passenger_with_metadata_and_pages(env):
    seed.do_seed(env.engine, ANCHOR, apply=True)
    h = env.admin_headers(env.add_admin())
    res = env.client.get("/api/admin/transactions?passenger_id=69&page=1&page_size=25", headers=h).json()
    assert res["total"] == 60 and len(res["items"]) == 25 and res["page"] == 1
    item = res["items"][0]
    for key in ("transaction_type", "description", "is_demo", "passenger_id", "driver", "status", "amount", "created_at"):
        assert key in item
    assert all(i["passenger_id"] == 69 and i["is_demo"] for i in res["items"])
    page3 = env.client.get("/api/admin/transactions?passenger_id=69&page=3&page_size=25", headers=h).json()
    assert len(page3["items"]) == 10
    refs = {i["reference"] for p in (1, 2, 3) for i in env.client.get(
        f"/api/admin/transactions?passenger_id=69&page={p}&page_size=25", headers=h).json()["items"]}
    assert len(refs) == 60
    rides = [i for i in res["items"] if i["transaction_type"] == "ride_payment"]
    assert rides and all(i["driver"] for i in rides)
    both = env.client.get("/api/admin/transactions?page_size=100", headers=h).json()
    assert {i["passenger_id"] for i in both["items"]} >= {69, 70}
    genuine = env.client.get("/api/admin/transactions?passenger_id=2", headers=h).json()["items"]
    assert {i["reference"]: i["is_demo"] for i in genuine} == {"QR897BBC7F73": False, "DEMO-TXN-000001": True}


def test_admin_transactions_require_admin(env):
    assert env.client.get("/api/admin/transactions?passenger_id=69").status_code in (401, 403)
    assert env.client.get("/api/admin/transactions", headers=env.user_headers(69)).status_code in (401, 403)


def test_admin_totals_exclude_demo_rows(env):
    h = env.admin_headers(env.add_admin())
    before = env.client.get("/api/admin/dashboard", headers=h).json()
    seed.do_seed(env.engine, ANCHOR, apply=True)
    after = env.client.get("/api/admin/dashboard", headers=h).json()
    for key in ("total_transactions", "revenue", "wallet_balance", "total_passengers"):
        assert after[key] == before[key], key
