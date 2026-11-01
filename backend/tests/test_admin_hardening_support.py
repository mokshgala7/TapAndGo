"""Phase 7 of the admin hardening: drivers and passengers can raise tickets and read the admin's reply (/api/support/my)."""
from unittest.mock import patch

import pytest

from helpers import Env


@pytest.fixture
def env():
    with patch("app.routes.support.send_support_ticket_created", return_value=True), \
         patch("app.routes.support.send_support_ticket_reply", return_value=True, create=True):
        yield Env()


FORM = dict(name="Dev Driver", email="drv@example.com", phone="9876543210", category="technical",
            priority="medium", subject="POS not reading", message="The terminal does not read cards.")


@pytest.mark.parametrize("account_type", ["driver", "passenger"])
def test_ticket_roundtrip_with_admin_reply(env, account_type):
    uid = env.add_user(f"{account_type}@example.com", account_type=account_type)
    headers = env.user_headers(uid)
    created = env.client.post("/api/support/", json=FORM, headers=headers)
    assert created.status_code == 200 and created.json()["ticket"]["status"] == "open"
    ticket_id = created.json()["ticket"]["id"]

    mine = env.client.get("/api/support/my", headers=headers).json()["tickets"]
    assert [t["id"] for t in mine] == [ticket_id] and mine[0]["admin_reply"] is None

    admin = env.admin_headers(env.add_admin())
    with patch("app.routes.support.send_support_ticket_reply", return_value=True, create=True):
        reply = env.client.patch(f"/api/admin/support/admin/{ticket_id}/reply", headers=admin,
                                 json={"admin_reply": "Try restarting it.", "status": "resolved"})
    assert reply.status_code == 200, reply.text

    ticket = env.client.get("/api/support/my", headers=headers).json()["tickets"][0]
    assert ticket["admin_reply"] == "Try restarting it." and ticket["status"] == "resolved"
    assert ticket["subject"] == "POS not reading" and ticket["created_at"]


def test_users_only_see_their_own_tickets(env):
    d = env.add_user("d@example.com", account_type="driver")
    p = env.add_user("p@example.com")
    env.client.post("/api/support/", json=FORM, headers=env.user_headers(d))
    assert env.client.get("/api/support/my", headers=env.user_headers(p)).json()["tickets"] == []
    assert env.client.get("/api/support/my").status_code == 401
