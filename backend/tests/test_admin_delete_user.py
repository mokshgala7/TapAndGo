"""Admin "delete user": removes a clean account (sessions included), refuses an account with financial history,
and turns any leftover foreign-key error into a clean 409. SQLite only enforces foreign keys when asked, so the
fixture switches that on to behave like Postgres (where this used to fail with ForeignKeyViolation -> HTTP 500)."""
from decimal import Decimal

import pytest

from app.models import (
    ActivityLog, EditRequest, FraudAlert, NFCCard, NFCCardOrder, PaymentOrder, PosDevice, SupportTicket, Transaction,
    User, UserDocument, UserSession, Wallet, WithdrawalRequest,
)
from app.routes import admin as admin_routes
from helpers import Env

FINANCIAL = "This account has financial history. Suspend it instead."


@pytest.fixture
def env():
    e = Env()
    with e.engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    e.ah = e.admin_headers(e.add_admin())
    return e


def delete(env, uid):
    return env.client.post(f"/api/admin/users/{uid}/action", headers=env.ah, json={"action": "delete"})


def add(env, *rows):
    db = env.db()
    try:
        db.add_all(rows); db.commit()
    finally:
        db.close()


def count(env, model, **filters):
    db = env.db()
    try:
        return db.query(model).filter_by(**filters).count()
    finally:
        db.close()


def clean_user(env, email="clean@example.com", **kw):
    uid = env.add_user(email, balance=0, **kw)
    env.user_headers(uid)                              # creates a live user_sessions row, the original failure
    return uid


class TestCleanAccountIsDeleted:
    def test_account_with_a_session_is_deleted(self, env):
        uid = clean_user(env)
        assert count(env, UserSession, user_id=uid) == 1
        res = delete(env, uid)
        assert res.status_code == 200 and res.json() == {"success": True, "action": "delete"}
        assert count(env, User, id=uid) == 0 and count(env, UserSession, user_id=uid) == 0 and count(env, Wallet, user_id=uid) == 0

    def test_other_links_are_cleaned_up_or_detached(self, env):
        uid = clean_user(env, account_type="driver")
        other = clean_user(env, "other@example.com")
        add(env,
            UserDocument(user_id=uid, document_type="rc", file_path="uploads/rc/x.png"),
            EditRequest(user_id=uid, field_name="bank", status="pending"),
            SupportTicket(user_id=uid, name="D", email="d@example.com", phone="9000000000", subject="s", message="m"),
            NFCCard(user_id=uid, card_reference="NFC-DEL-1", status="active"),
            PosDevice(device_id="POS-DEL-1", driver_id=uid),
            FraudAlert(user_id=uid, risk_score=50, status="open"),
            ActivityLog(user_id=uid, action="x", entity_type="user"),
            SupportTicket(user_id=other, name="O", email="o@example.com", phone="9000000001", subject="keep", message="m"))
        assert delete(env, uid).status_code == 200
        for model in (UserDocument, EditRequest, SupportTicket, NFCCard):
            assert count(env, model, user_id=uid) == 0
        assert count(env, SupportTicket, user_id=other) == 1                       # someone else's data is untouched
        db = env.db()
        try:
            assert db.query(PosDevice).filter_by(device_id="POS-DEL-1").one().driver_id is None     # device kept, unassigned
            assert db.query(FraudAlert).one().user_id is None                                       # alert kept, unlinked
            assert db.query(ActivityLog).filter_by(action="x").one().user_id is None
        finally:
            db.close()

    def test_user_without_a_wallet_can_be_deleted(self, env):
        uid = env.add_user("nowallet@example.com")
        assert delete(env, uid).status_code == 200 and count(env, User, id=uid) == 0

    def test_deletion_is_audited(self, env):
        uid = clean_user(env)
        delete(env, uid)
        assert count(env, ActivityLog, action="delete", entity_type="user", entity_id=uid) == 1


class TestFinancialHistoryIsNeverDeleted:
    def assert_refused(self, env, uid):
        res = delete(env, uid)
        assert res.status_code == 409 and res.json()["detail"] == FINANCIAL
        assert count(env, User, id=uid) == 1 and count(env, UserSession, user_id=uid) == 1     # nothing was touched

    def test_wallet_balance_above_zero(self, env):
        uid = env.add_user("rich@example.com", balance=10)
        env.user_headers(uid)
        self.assert_refused(env, uid)
        assert env.balance(uid) == 10.0

    def test_passenger_transaction(self, env):
        uid = clean_user(env)
        add(env, Transaction(reference="T-P1", passenger_id=uid, amount=Decimal("20"), status="completed"))
        self.assert_refused(env, uid)
        db = env.db()
        try:
            assert db.query(Transaction).filter_by(reference="T-P1").one().passenger_id == uid    # not detached
        finally:
            db.close()

    def test_driver_transaction(self, env):
        driver = clean_user(env, account_type="driver")
        rider = env.add_user("rider@example.com", balance=100)
        add(env, Transaction(reference="T-D1", passenger_id=rider, driver_id=driver, amount=Decimal("20"), status="completed"))
        self.assert_refused(env, driver)

    def test_withdrawal_request(self, env):
        uid = clean_user(env)
        db = env.db()
        try:
            wallet_id = db.query(Wallet).filter_by(user_id=uid).one().id
        finally:
            db.close()
        add(env, WithdrawalRequest(user_id=uid, wallet_id=wallet_id, amount=Decimal("5"), destination_desc="UPI ID (a@b)",
                                   reference="WD-1", status="rejected"))
        self.assert_refused(env, uid)

    def test_topup_order_and_card_order(self, env):
        a, b = clean_user(env, "a@example.com"), clean_user(env, "b@example.com")
        add(env,
            PaymentOrder(order_id="order_1", user_id=a, amount_paise=10000),
            NFCCardOrder(order_reference="ORD-1", user_id=b, recipient_name="B", phone="9000000002", address_line1="x",
                         area="y", city="z", state="s", pincode="400001"))
        self.assert_refused(env, a)
        self.assert_refused(env, b)

    def test_suspend_still_works_on_such_an_account(self, env):
        uid = env.add_user("rich@example.com", balance=10)
        res = env.client.post(f"/api/admin/users/{uid}/action", headers=env.ah, json={"action": "suspend"})
        assert res.status_code == 200 and env.db().get(User, uid).status == "suspended"


class TestLeftoverForeignKeysGiveA409NotA500:
    def test_unknown_reference_is_a_clean_409(self, env, monkeypatch):
        uid = clean_user(env)
        add(env, Transaction(reference="T-X", passenger_id=uid, amount=Decimal("1"), status="completed"))
        monkeypatch.setattr(admin_routes, "_FINANCIAL_LINKS", ())       # pretend the guard did not know about it
        res = delete(env, uid)
        assert res.status_code == 409 and res.json()["detail"] == admin_routes.LINKED_RECORDS_MESSAGE
        assert count(env, User, id=uid) == 1 and count(env, UserSession, user_id=uid) == 1      # rolled back as a whole


class TestUnchangedBehaviour:
    @pytest.mark.parametrize("action,status", [("suspend", "suspended"), ("activate", "active"), ("approve", "active"), ("reject", "rejected")])
    def test_other_actions(self, env, action, status):
        uid = env.add_user("u@example.com", balance=5)
        res = env.client.post(f"/api/admin/users/{uid}/action", headers=env.ah, json={"action": action})
        assert res.status_code == 200 and res.json() == {"success": True, "action": action}
        assert env.db().get(User, uid).status == status

    def test_unknown_user_and_auth(self, env):
        assert delete(env, 9999).status_code == 404
        assert env.client.post("/api/admin/users/1/action", json={"action": "delete"}).status_code == 401
