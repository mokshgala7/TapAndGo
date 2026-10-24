"""Safety, idempotency and ledger checks for scripts/seed_driver_demo_history.py.

Runs against an isolated in-memory database wired into the app (no network, no real DB).
"""
import importlib.util
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models import Transaction, Wallet
from helpers import Env

BACKEND = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("seed_driver_demo", BACKEND / "scripts" / "seed_driver_demo_history.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

ANCHOR = date(2026, 10, 20)


@pytest.fixture
def env():
    e = Env()
    for i in range(1, 27):  # ids 1..26, so the driver below becomes user 27
        e.add_user(f"p{i}@test.local", balance=1553 if i == 2 else 0)
    e.driver = e.add_user("driver27@test.local", account_type="driver", name="Rakesh Sharma", balance=25)
    assert e.driver == 27
    db = e.db()
    pw = db.query(Wallet).filter(Wallet.user_id == 2).one()
    db.add(Transaction(reference="QR897BBC7F73", passenger_id=2, driver_id=27, wallet_id=pw.id,
                       amount=Decimal("25.00"), payment_method="QR", status="completed", otp_verified=True,
                       transaction_type="ride_payment", description="₹25.00 paid to Rakesh Sharma via QR",
                       balance_after=Decimal("1553.00"), created_at=datetime(2026, 10, 20, 14, 56, 42)))
    db.commit()
    db.close()
    e.headers = e.user_headers(27)
    yield e
    from app.main import app
    app.dependency_overrides.clear()


def _dump(env):
    with env.engine.connect() as c:
        return {t: c.execute(text(f"SELECT * FROM {t} ORDER BY 1")).all()
                for t in ("users", "wallets", "transactions")}


def _syn(env):
    with env.engine.connect() as c:
        return c.execute(text("SELECT * FROM transactions WHERE payment_source='demo_seed' ORDER BY created_at, id")).mappings().all()


def test_dry_run_writes_nothing(env):
    before = _dump(env)
    seed.do_seed(env.engine, ANCHOR, apply=False)
    assert _dump(env) == before


def test_apply_is_exact_clean_idempotent_and_reconciled(env):
    before = _dump(env)
    seed.do_seed(env.engine, ANCHOR, apply=True)
    seed.do_seed(env.engine, ANCHOR, apply=True)  # second run must be a no-op
    rows = _syn(env)
    assert len(rows) == 1000 and len({r["reference"] for r in rows}) == 1000
    assert {(r["transaction_type"], r["status"]) for r in rows} == {("ride_payment", "completed"), ("withdrawal", "completed")}
    assert all(r["reference"].startswith("DEMO-") for r in rows)
    assert all(r["provider"] is None and r["provider_transaction_id"] is None and r["utr"] is None
               and r["idempotency_key"] is None and r["payer_name"] is None for r in rows)
    stamps = [datetime.fromisoformat(r["created_at"]) for r in rows]
    assert min(stamps) >= datetime(2025, 10, 19, 18, 30)   # 2025-10-20 00:00 IST
    assert max(stamps) < datetime(2026, 10, 19, 18, 30)    # before 2026-10-20 00:00 IST

    after = _dump(env)
    assert after["wallets"] == before["wallets"]
    assert [r for r in after["transactions"] if r[0] == before["transactions"][0][0]] == before["transactions"]
    assert all(b in after["users"] for b in before["users"])

    # the real history endpoint: names, directions, and a ledger that ends on the real balance
    body = env.client.get("/api/wallet/27/transactions", headers=env.headers).json()["transactions"]
    assert len(body) == 1001
    syn = [t for t in body if t["reference"].startswith("DEMO-")]
    rides = [t for t in syn if t["type"] == "Ride Payment Received"]
    wds = [t for t in syn if t["type"] == "Withdrawal"]
    assert len(rides) + len(wds) == 1000 and all(t["is_credit"] for t in rides) and not any(t["is_credit"] for t in wds)
    assert all(t["status"] == "Completed" for t in syn)
    assert len({t["passenger"] for t in rides}) > 10 and not any(t["passenger"] == "Passenger" for t in rides)
    net = sum((t["amount"] if t["is_credit"] else -t["amount"]) for t in body)
    assert round(net, 2) == 25.0  # == the untouched wallet balance
    assert all(t["balance_after"] >= 0 for t in syn)
    wallet = env.client.get("/api/wallet/27", headers=env.headers).json()["wallet"]
    assert float(wallet["balance"]) == 25.0


def test_reset_restores_original_state(env):
    before = _dump(env)
    seed.do_seed(env.engine, ANCHOR, apply=True)
    seed.do_reset(env.engine, apply=True)
    assert _dump(env) == before


def test_refuses_wrong_driver_identity(env):
    with env.engine.begin() as c:
        c.execute(text("UPDATE users SET name='Someone Else' WHERE id=27"))
    with pytest.raises(seed.SeedError):
        seed.do_seed(env.engine, ANCHOR, apply=True)
    assert _syn(env) == []


def test_refuses_genuine_rows_inside_window(env):
    with env.engine.begin() as c:
        c.execute(text("UPDATE transactions SET created_at='2026-03-01 10:00:00' WHERE reference='QR897BBC7F73'"))
    with pytest.raises(seed.SeedError):
        seed.do_seed(env.engine, ANCHOR, apply=True)
    assert _syn(env) == []


def test_cli_refuses_non_supabase_and_unconfirmed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    assert seed.main(["seed"]) == 1
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.abcdef.supabase.co/postgres")
    monkeypatch.setenv("SUPABASE_URL", "https://abcdef.supabase.co")
    assert seed.main(["seed", "--apply"]) == 1                                    # no --confirm-project
    assert seed.main(["seed", "--apply", "--confirm-project", "wrongref"]) == 1   # mismatched ref
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@other-host.example.com/postgres")
    assert seed.main(["seed", "--apply", "--confirm-project", "abcdef"]) == 1     # host not the Supabase project


def test_admin_kpis_and_flag_ignore_synthetic_rows(env):
    from helpers import admin_headers
    ah = admin_headers(env.Session, env.add_admin())
    before = env.client.get("/api/admin/dashboard", headers=ah).json()
    seed.do_seed(env.engine, ANCHOR, apply=True)
    after = env.client.get("/api/admin/dashboard", headers=ah).json()
    assert before["total_transactions"] == 1 and after == before  # users, revenue, counts unaffected
    body = env.client.get("/api/wallet/27/transactions", headers=env.headers).json()["transactions"]
    assert sum(t["is_synthetic"] for t in body) == 1000
    assert [t for t in body if not t["is_synthetic"]][0]["reference"] == "QR897BBC7F73"
