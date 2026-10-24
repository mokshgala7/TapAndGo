"""Regression: scripts/seed_driver_demo_history.py may only delete its own driver-27 demo rows.

The passenger demo seed (DEMO-P69-*, DEMO-P70-*) shares payment_source='demo_seed' and the
'DEMO-' prefix, so the driver script's cleanup must not rely on those alone.
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


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, BACKEND / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


driver_seed = _load("seed_driver_demo_scope", "seed_driver_demo_history.py")
passenger_seed = _load("seed_passenger_demo_scope", "seed_passenger_demo_history.py")

ANCHOR = date(2026, 10, 20)
KEEP_REFS = {
    "QR897BBC7F73",          # genuine ride to driver 27
    "REAL-OTHER-1",          # genuine ride, unrelated driver
    "DEMO-OTHER-0001",       # someone else's demo row (marker + DEMO- prefix, not driver 27's)
    "DEMO-TXN-999999",       # driver-style reference but a different driver and wallet
    "DEMO-WD-999999",        # driver-style reference on driver 27 but without the demo marker
}


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
    _add_user(db, 2, "Real Passenger", balance=1553)
    _add_user(db, 6, "Other Driver", account_type="driver", balance=0)
    _add_user(db, 27, "Rakesh Sharma", account_type="driver", balance=25)
    _add_user(db, 69, "Moksh Gala", balance=0)
    _add_user(db, 70, "Aarav Sharma", balance=0)
    db.commit()
    w = {u: db.query(Wallet).filter(Wallet.user_id == u).one().id for u in (2, 6, 27)}

    def tx(ref, **kw):
        base = dict(reference=ref, amount=Decimal("25.00"), payment_method="QR", status="completed",
                    otp_verified=True, transaction_type="ride_payment",
                    created_at=datetime(2026, 10, 20, 14, 56, 42))
        base.update(kw)
        db.add(Transaction(**base))

    tx("QR897BBC7F73", passenger_id=2, driver_id=27, wallet_id=w[2], balance_after=Decimal("1553.00"))
    tx("REAL-OTHER-1", passenger_id=2, driver_id=6, wallet_id=w[2], created_at=datetime(2026, 10, 21, 9, 0))
    tx("DEMO-OTHER-0001", passenger_id=2, driver_id=6, payment_source="demo_seed",
       created_at=datetime(2026, 10, 21, 10, 0))
    tx("DEMO-TXN-999999", passenger_id=2, driver_id=6, wallet_id=w[6], payment_source="demo_seed",
       created_at=datetime(2026, 10, 21, 11, 0))
    tx("DEMO-WD-999999", driver_id=27, wallet_id=w[27], payment_method="bank_transfer",
       transaction_type="withdrawal", created_at=datetime(2026, 10, 21, 12, 0))
    db.commit()
    db.close()
    yield e
    from app.main import app
    app.dependency_overrides.clear()


def _rows(env, where="1=1"):
    with env.engine.connect() as c:
        return [dict(r) for r in c.execute(text(f"SELECT * FROM transactions WHERE {where} ORDER BY id")).mappings()]


def _driver_owned(env):
    return _rows(env, "payment_source='demo_seed' AND driver_id=27 AND "
                      "(reference LIKE 'DEMO-TXN-%' OR reference LIKE 'DEMO-WD-%')")


def _passenger_demo(env):
    return _rows(env, "reference LIKE 'DEMO-P69-%' OR reference LIKE 'DEMO-P70-%'")


def _kept(env):
    return [r for r in _rows(env) if r["reference"] in KEEP_REFS]


def _seed_both(env):
    passenger_seed.do_seed(env.engine, ANCHOR, apply=True)
    driver_seed.do_seed(env.engine, ANCHOR, apply=True)


@pytest.fixture
def seeded(env):
    with env.engine.begin() as c:
        c.execute(text("UPDATE transactions SET created_at='2026-10-21 12:00:00' WHERE reference='DEMO-WD-999999'"))
    _seed_both(env)
    assert len(_driver_owned(env)) == driver_seed.N_TOTAL
    assert len(_passenger_demo(env)) == 120
    return env


def test_driver_reset_removes_only_its_own_rows(seeded):
    passenger_before, kept_before = _passenger_demo(seeded), _kept(seeded)
    driver_seed.do_reset(seeded.engine, apply=True)
    assert _driver_owned(seeded) == []
    assert _passenger_demo(seeded) == passenger_before
    assert _kept(seeded) == kept_before
    assert len(kept_before) == len(KEEP_REFS)


def test_driver_reseed_keeps_passenger_demo_and_unrelated_rows(seeded):
    passenger_before, kept_before = _passenger_demo(seeded), _kept(seeded)
    # Force the driver seed to rebuild (it deletes its own rows first) by altering one owned row.
    with seeded.engine.begin() as c:
        c.execute(text("UPDATE transactions SET amount = amount + 1 WHERE reference = 'DEMO-TXN-000001'"))
    driver_seed.do_seed(seeded.engine, ANCHOR, apply=True)
    assert len(_driver_owned(seeded)) == driver_seed.N_TOTAL
    assert _passenger_demo(seeded) == passenger_before
    assert _kept(seeded) == kept_before


def test_driver_seed_is_idempotent_alongside_passenger_demo(seeded):
    before = _rows(seeded)
    driver_seed.do_seed(seeded.engine, ANCHOR, apply=True)   # identical dataset → nothing to do
    assert _rows(seeded) == before


def test_driver_reset_count_ignores_other_demo_rows(seeded, capsys):
    driver_seed.do_reset(seeded.engine, apply=False)
    assert f"would remove {driver_seed.N_TOTAL} synthetic transactions" in capsys.readouterr().out


def test_passenger_dry_run_after_driver_seed_plans_120_inserts_no_deletes(env, capsys):
    with env.engine.begin() as c:
        c.execute(text("UPDATE transactions SET created_at='2026-10-21 12:00:00' WHERE reference='DEMO-WD-999999'"))
    driver_seed.do_seed(env.engine, ANCHOR, apply=True)
    before = _rows(env)
    passenger_seed.do_seed(env.engine, ANCHOR, apply=False)
    out = capsys.readouterr().out
    assert "Would insert 120 rows (69: 60, 70: 60)" in out
    assert "owned rows already present: 0" in out
    assert _rows(env) == before


def test_driver_cleanup_sql_requires_every_ownership_condition():
    sql = driver_seed.OWNED_SQL
    for part in ("payment_source = :m", "driver_id = :d", "wallet_id = :w", "reference LIKE :p_txn",
                 "reference LIKE :p_wd"):
        assert part in sql
    params = driver_seed._owned_params(123)
    assert params["p_txn"] == "DEMO-TXN-%" and params["p_wd"] == "DEMO-WD-%"
    assert not any(v.startswith("DEMO-P") for v in (params["p_txn"], params["p_wd"]))
