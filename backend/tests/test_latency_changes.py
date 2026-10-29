"""
test_latency_changes.py
───────────────────────
Payment latency. A normal payment on a remote database is dominated by network round trips (one per SQL statement), not by
the model, so the changes are: fewer statements per payment, the shadow score and record produced AFTER the response,
columns-only history, and a startup warm-up of the model. Enforced passengers still fail closed.
"""
import logging
import threading
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models import FraudAssessment, Transaction, User
from app.services import fraud_gate, fraud_risk_shadow
from tests.test_fraud_gate import (  # noqa: F401 - fixtures are imported by name so pytest finds them here
    UID, add_history, balances, completed, enforce, mail, rows, scene, tap,
)


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))

    def run(self):
        for fn, args, kwargs in self.tasks:
            fn(*args, **kwargs)


def count_statements(engine):
    box = {"n": 0}

    def hook(conn, cursor, statement, params, context, executemany):
        box["n"] += 1

    event.listen(engine, "before_cursor_execute", hook)
    return box, lambda: event.remove(engine, "before_cursor_execute", hook)


def load_pair(scene):
    db = scene["env"].db()
    pax, drv = db.get(User, scene["pax_id"]), db.get(User, scene["driver_id"])
    _ = (pax.id, pax.email, drv.id, drv.vehicle_type)            # loaded: reading them later costs nothing
    return db, pax, drv


# ── shadow: nothing fraud-related is on the critical path ─────────────────────────────────────────────

def test_a_shadow_decision_is_made_without_touching_the_database_and_recorded_afterwards(scene):
    db, pax, drv = load_pair(scene)
    bg = FakeBackgroundTasks()
    box, stop = count_statements(scene["env"].engine)
    try:
        d = fraud_gate.evaluate_payment(db, pax, drv, 150, datetime.utcnow(), "k-shadow-0001", "nfc", background_tasks=bg)
    finally:
        stop()
    assert d["action"] == "proceed" and d["assessment_id"] is None and d["ml_status"] == "deferred"
    assert box["n"] == 0 and len(bg.tasks) == 1 and rows(scene, FraudAssessment) == []
    bg.run()                                                      # what runs after the response
    (a,) = rows(scene, FraudAssessment)
    assert (a.mode, a.decision, a.channel, int(a.amount)) == ("shadow", "proceed", "nfc", 150) and a.ml_status == "scored"
    db.close()


def test_the_payment_itself_is_not_part_of_its_own_history(scene):
    r, _ = tap(scene, amount=150)
    assert r.json()["success"] is True
    (a,) = rows(scene, FraudAssessment)
    assert a.rule_10min is False and a.elapsed_seconds is None   # a first payment: no earlier ride, not "0 seconds ago"
    (t,) = completed(scene)
    assert t.amount == 150


def test_a_second_payment_sees_only_the_first_as_history(scene):
    tap(scene, amount=150)
    tap(scene, amount=150)
    first, second = sorted(rows(scene, FraudAssessment), key=lambda a: a.id)
    assert first.rule_10min is False
    assert second.rule_10min is True and second.elapsed_seconds is not None   # seconds after the first, never itself


def test_a_failing_background_record_never_breaks_a_shadow_payment(scene, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(fraud_gate, "_assess_and_store", boom)
    before = balances(scene)
    with caplog.at_level(logging.WARNING, logger="tapgo.fraud_gate"):
        r, _ = tap(scene, amount=150)
    assert r.status_code == 200 and r.json()["success"] is True
    assert balances(scene) == (before[0] - 150, before[1] + 150)
    assert any("deferred_assessment_failed" in m for m in caplog.messages)
    assert "scoring exploded" not in " ".join(caplog.messages)


def test_a_gate_error_for_a_shadow_passenger_still_lets_the_payment_through(scene, monkeypatch):
    monkeypatch.setattr(fraud_gate, "_evaluate_payment", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
    r, _ = tap(scene, amount=150)
    assert r.json()["success"] is True


# ── enforced passengers: unchanged, synchronous, fail closed ──────────────────────────────────────────

def test_an_enforced_passenger_is_decided_and_recorded_before_the_response(scene, monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(scene["pax_id"]))
    monkeypatch.setenv("PAYMENT_OTP_SECRET", "unit-test-secret-not-a-real-one")
    db, pax, drv = load_pair(scene)
    bg = FakeBackgroundTasks()
    d = fraud_gate.evaluate_payment(db, pax, drv, 150, datetime.utcnow(), "k-enf-0001", "nfc", background_tasks=bg)
    assert bg.tasks == [] and d["assessment_id"] is not None and d["mode"] == "enforce"
    assert len(rows(scene, FraudAssessment)) == 1
    db.close()


def test_an_enforced_passenger_still_fails_closed_when_the_model_is_down(scene, monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(scene["pax_id"]))
    monkeypatch.setenv("PAYMENT_OTP_SECRET", "unit-test-secret-not-a-real-one")
    monkeypatch.setattr(fraud_gate, "run_assessment", lambda *a, **k: (None, None))
    before = balances(scene)
    r, _ = tap(scene, amount=150)
    assert r.json()["status"] == "otp_required" and balances(scene) == before


# ── fewer round trips ───────────────────────────────────────────────────────────────────────────────

def test_a_normal_nfc_payment_stays_within_its_statement_budget(scene):
    """Regression guard: it was 25 statements before this change (every extra one is a network round trip)."""
    add_history(scene, n=30)
    box, stop = count_statements(scene["env"].engine)
    try:
        r, _ = tap(scene, amount=150)
    finally:
        stop()
    assert r.json()["success"] is True
    assert box["n"] <= 20, box["n"]


def test_commit_keep_loaded_leaves_objects_loaded_and_restores_the_setting(scene):
    from app.database import commit_keep_loaded
    db, pax, drv = load_pair(scene)
    pax.phone = pax.phone                                          # no change, just a pending flush
    box, stop = count_statements(scene["env"].engine)
    try:
        commit_keep_loaded(db)
        _ = (pax.email, pax.name)                                  # still loaded: no re-SELECT
    finally:
        stop()
    assert box["n"] == 0 and db.expire_on_commit is True
    db.close()


def test_the_history_query_reads_only_what_the_scorer_needs(scene):
    add_history(scene, n=5)
    db, pax, drv = load_pair(scene)
    seen = []

    def hook(conn, cursor, statement, params, context, executemany):
        if "FROM transactions" in statement and "ORDER BY" in statement and "LIMIT" in statement:
            seen.append(statement)

    event.listen(scene["env"].engine, "before_cursor_execute", hook)
    try:
        assessment, audit = fraud_risk_shadow.run_assessment(db, pax.id, drv, Decimal("150"), datetime.utcnow(), "k-cols", "shadow")
    finally:
        event.remove(scene["env"].engine, "before_cursor_execute", hook)
    assert assessment is not None and assessment.status == "scored" and audit["history_rows"] == 5
    assert seen and "transactions.description" not in seen[0] and "transactions.reference" not in seen[0]
    db.close()


# ── warm-up ───────────────────────────────────────────────────────────────────────────────────────────

def test_warm_up_loads_the_model_and_never_raises(monkeypatch):
    assert fraud_risk_shadow.warm_up() is True
    import app.services.tapgo_fraud_risk.service as svc

    def boom(model="v6"):
        raise RuntimeError("model file missing")

    monkeypatch.setattr(svc, "load_scorer", boom)
    assert fraud_risk_shadow.warm_up() is False                    # a failure only means the first payment warms up


def test_warm_up_is_skipped_when_the_ml_is_off_and_under_tests(monkeypatch):
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    assert fraud_risk_shadow.warm_up() is False
    assert fraud_risk_shadow.start_warm_up() is None
    monkeypatch.delenv("TAPGO_RISK_DISABLED")
    assert fraud_risk_shadow.start_warm_up() is None               # TAPGO_TESTING=1 in this suite


def test_the_warm_up_thread_is_a_daemon_and_cannot_block_startup(monkeypatch):
    monkeypatch.delenv("TAPGO_TESTING", raising=False)
    started = threading.Event()
    release = threading.Event()

    def slow(model="v6"):
        started.set()
        release.wait(5)
        return True

    monkeypatch.setattr(fraud_risk_shadow, "warm_up", slow)
    thread = fraud_risk_shadow.start_warm_up()
    try:
        assert thread is not None and thread.daemon is True        # returned at once; startup did not wait
        assert started.wait(2)
    finally:
        release.set()
        thread.join(2)
        monkeypatch.setenv("TAPGO_TESTING", "1")
