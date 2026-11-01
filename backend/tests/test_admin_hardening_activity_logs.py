"""Phase 9 of the admin hardening: the audit log names the administrator, and NFC block takes a reason."""
import pytest

from app.models import ActivityLog, NFCCard
from helpers import Env


@pytest.fixture
def env():
    return Env()


def test_audit_log_shows_admin_name_and_email(env):
    admin_id = env.add_admin("boss@test.local")
    headers = env.admin_headers(admin_id)
    uid = env.add_user("rider@example.com")
    env.client.post(f"/api/admin/users/{uid}/action", headers=headers, json={"action": "suspend"})
    items = env.client.get("/api/admin/activity-logs", headers=headers).json()["items"]
    entry = next(i for i in items if i["action"] == "suspend")
    assert entry["admin_name"] == "Admin" and entry["admin_email"] == "boss@test.local"
    for key in ("id", "action", "entity_type", "entity_id", "details", "created_at"):
        assert key in entry                                              # existing fields are unchanged


def test_log_row_without_an_admin_still_lists(env):
    headers = env.admin_headers(env.add_admin())
    db = env.db()
    try:
        db.add(ActivityLog(admin_id=None, action="system", entity_type="x")); db.commit()
    finally:
        db.close()
    items = env.client.get("/api/admin/activity-logs", headers=headers).json()["items"]
    assert any(i["action"] == "system" and i["admin_name"] is None for i in items)


@pytest.mark.parametrize("sent,stored", [("Lost in a bus", "Lost in a bus"), (None, "Blocked by admin"), ("   ", "Blocked by admin")])
def test_nfc_block_reason_is_stored_with_a_default(env, sent, stored):
    headers = env.admin_headers(env.add_admin())
    uid = env.add_user("rider@example.com")
    db = env.db()
    try:
        card = NFCCard(user_id=uid, card_reference="NFC-1", status="active"); db.add(card); db.commit(); card_id = card.id
    finally:
        db.close()
    body = {"action": "block", **({"reason": sent} if sent is not None else {})}
    assert env.client.post(f"/api/nfc/admin/{card_id}/action", headers=headers, json=body).status_code == 200
    db = env.db()
    try:
        assert db.get(NFCCard, card_id).blocked_reason == stored
    finally:
        db.close()
