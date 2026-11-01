"""Phase 3 of the admin hardening: edit-request before/after values and an optional rejection reason."""
import json
from unittest.mock import patch

import pytest

from app.models import EditRequest, User
from helpers import Env


@pytest.fixture
def env():
    return Env()


def make_request(env, user_id, field="bank", previous=None, new=None):
    db = env.db()
    try:
        row = EditRequest(user_id=user_id, field_name=field, previous_value=previous, new_value=new,
                          reason="please", status="pending")
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def test_list_returns_before_and_after_values_and_requester(env):
    admin = env.admin_headers(env.add_admin())
    uid = env.add_user("d@example.com", account_type="driver", bank_account_number="111122223333", bank_ifsc="HDFC0001234")
    new = json.dumps({"bank_account_number": "999988887777"})
    make_request(env, uid, "bank", previous="old-value", new=new)
    item = env.client.get("/api/admin/edit-requests", headers=admin).json()["items"][0]
    assert item["previous_value"] == "old-value" and item["new_value"] == new
    assert json.loads(item["current_value"])["bank_account_number"] == "111122223333"
    assert item["user_email"] == "d@example.com" and item["admin_note"] is None
    # existing keys are unchanged
    for key in ("id", "user_id", "user_name", "account_type", "request_type", "field_name", "reason", "status", "created_at", "reviewed_at"):
        assert key in item


def test_phone_request_shows_current_phone(env):
    admin = env.admin_headers(env.add_admin())
    uid = env.add_user("p@example.com", phone="9876500000")
    make_request(env, uid, "phone")
    assert env.client.get("/api/admin/edit-requests", headers=admin).json()["items"][0]["current_value"] == "9876500000"


def test_reject_stores_reason_and_keeps_bank_lock(env):
    admin = env.admin_headers(env.add_admin())
    uid = env.add_user("d@example.com", account_type="driver")
    rid = make_request(env, uid, "bank")
    with patch("app.utils.email_service.send_edit_request_decision_email", return_value=True):
        res = env.client.post(f"/api/admin/edit-requests/{rid}/review", headers=admin, json={"action": "reject", "reason": "  Photo unclear  "})
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    db = env.db()
    try:
        row = db.get(EditRequest, rid)
        assert row.status == "rejected" and row.admin_note == "Photo unclear"
        user = db.get(User, uid)
        assert user.bank_locked == 1 and user.bank_request_status == "rejected"      # bank-lock behaviour unchanged
    finally:
        db.close()
    listed = env.client.get("/api/admin/edit-requests?status=rejected", headers=admin).json()["items"][0]
    assert listed["admin_note"] == "Photo unclear"


def test_reject_without_reason_and_approve_still_work(env):
    admin = env.admin_headers(env.add_admin())
    uid = env.add_user("d@example.com", account_type="driver")
    r1, r2 = make_request(env, uid, "bank"), make_request(env, uid, "phone")
    with patch("app.utils.email_service.send_edit_request_decision_email", return_value=True):
        assert env.client.post(f"/api/admin/edit-requests/{r1}/review", headers=admin, json={"action": "reject"}).status_code == 200
        assert env.client.post(f"/api/admin/edit-requests/{r2}/review", headers=admin, json={"action": "approve", "reason": "ignored"}).status_code == 200
    db = env.db()
    try:
        assert db.get(EditRequest, r1).admin_note is None
        assert db.get(EditRequest, r2).admin_note is None and db.get(EditRequest, r2).status == "approved"
    finally:
        db.close()


def test_overlong_reason_is_rejected(env):
    admin = env.admin_headers(env.add_admin())
    uid = env.add_user("d@example.com", account_type="driver")
    rid = make_request(env, uid, "bank")
    assert env.client.post(f"/api/admin/edit-requests/{rid}/review", headers=admin, json={"action": "reject", "reason": "x" * 501}).status_code == 422
