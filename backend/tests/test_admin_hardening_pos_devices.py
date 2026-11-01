"""Phase 6 of the admin hardening: POS device registry (admin) and the opt-in X-Device-Id header."""
import pytest

from app.models import ActivityLog, PosDevice
from app.services import pos_device_gate as gate
from helpers import Env


@pytest.fixture
def env(monkeypatch):
    e = Env()
    e.ah = e.admin_headers(e.add_admin())
    e.driver = e.add_user("drv@example.com", account_type="driver")
    e.passenger = e.add_user("pax@example.com")
    monkeypatch.setattr(gate, "SessionLocal", e.Session)          # the middleware talks to this test database
    monkeypatch.setattr(gate, "_spawn", lambda fn, *a: fn(*a))    # report synchronously so tests are deterministic
    gate._last_report.clear()
    monkeypatch.delenv("POS_DEVICE_ENFORCEMENT_ENABLED", raising=False)
    return e


def register(env, device_id="POS-001", **extra):
    return env.client.post("/api/admin/pos-devices", headers=env.ah, json={"device_id": device_id, **extra})


class TestAdminRegistry:
    def test_register_list_detail(self, env):
        res = register(env, label="Front seat", vehicle_ref="MH01AB1234", driver_id=env.driver)
        assert res.status_code == 201
        body = res.json()
        assert body["status"] == "active" and body["driver_name"] == "Drv" and body["last_seen_at"] is None
        listing = env.client.get("/api/admin/pos-devices", headers=env.ah).json()
        assert listing["total"] == 1 and listing["items"][0]["device_id"] == "POS-001"
        assert env.client.get(f"/api/admin/pos-devices/{body['id']}", headers=env.ah).json()["label"] == "Front seat"

    def test_validation_and_duplicates(self, env):
        assert register(env, "bad id!").status_code == 422
        assert register(env, "ab").status_code == 422
        assert register(env).status_code == 201
        assert register(env).status_code == 409
        assert register(env, "POS-002", driver_id=env.passenger).status_code == 404      # must be a driver
        assert register(env, "POS-003", driver_id=99999).status_code == 404

    def test_assign_unassign_update_disable_enable(self, env):
        pk = register(env).json()["id"]
        a = env.client.post(f"/api/admin/pos-devices/{pk}/assign", headers=env.ah, json={"driver_id": env.driver, "vehicle_ref": "MH02"}).json()
        assert a["driver_id"] == env.driver and a["vehicle_ref"] == "MH02"
        only_vehicle = env.client.post(f"/api/admin/pos-devices/{pk}/assign", headers=env.ah, json={"vehicle_ref": None}).json()
        assert only_vehicle["vehicle_ref"] is None and only_vehicle["driver_id"] == env.driver     # driver untouched
        cleared = env.client.post(f"/api/admin/pos-devices/{pk}/assign", headers=env.ah, json={"driver_id": None}).json()
        assert cleared["driver_id"] is None
        assert env.client.post(f"/api/admin/pos-devices/{pk}/assign", headers=env.ah, json={}).status_code == 422
        assert env.client.put(f"/api/admin/pos-devices/{pk}", headers=env.ah, json={"label": "Rear", "notes": "n"}).json()["label"] == "Rear"
        assert env.client.post(f"/api/admin/pos-devices/{pk}/disable", headers=env.ah).json()["status"] == "disabled"
        assert env.client.get("/api/admin/pos-devices?status=disabled", headers=env.ah).json()["total"] == 1
        assert env.client.post(f"/api/admin/pos-devices/{pk}/enable", headers=env.ah).json()["status"] == "active"
        assert env.client.post("/api/admin/pos-devices/999/disable", headers=env.ah).status_code == 404

    def test_every_action_is_logged(self, env):
        pk = register(env).json()["id"]
        env.client.post(f"/api/admin/pos-devices/{pk}/assign", headers=env.ah, json={"driver_id": env.driver})
        env.client.put(f"/api/admin/pos-devices/{pk}", headers=env.ah, json={"label": "x"})
        env.client.post(f"/api/admin/pos-devices/{pk}/disable", headers=env.ah)
        env.client.post(f"/api/admin/pos-devices/{pk}/enable", headers=env.ah)
        db = env.db()
        try:
            actions = [r.action for r in db.query(ActivityLog).filter(ActivityLog.entity_type == "pos_device").order_by(ActivityLog.id)]
        finally:
            db.close()
        assert actions == ["register", "assign", "update", "disable", "enable"]

    def test_admin_only(self, env):
        assert env.client.get("/api/admin/pos-devices").status_code == 401
        assert env.client.post("/api/admin/pos-devices", json={"device_id": "POS-9"}).status_code == 401
        assert env.client.get("/api/admin/pos-devices", headers=env.user_headers(env.driver)).status_code == 401


class TestDeviceHeader:
    def pay(self, env, **headers):
        return env.client.post("/api/nfc/pay", json={}, headers=headers)

    def test_without_the_header_nothing_changes(self, env, monkeypatch):
        monkeypatch.setenv("POS_DEVICE_ENFORCEMENT_ENABLED", "true")
        register(env)
        pk = env.db().query(PosDevice).first().id
        env.client.post(f"/api/admin/pos-devices/{pk}/disable", headers=env.ah)
        res = self.pay(env)
        assert res.status_code == 401 and res.json().get("code") != "DEVICE_DISABLED"      # reached the route as today

    def test_header_updates_last_seen_firmware_battery(self, env):
        register(env)
        assert self.pay(env, **{"X-Device-Id": "POS-001", "X-Firmware-Version": "1.4.2", "X-Battery": "87"}).status_code == 401
        d = env.client.get("/api/admin/pos-devices", headers=env.ah).json()["items"][0]
        assert d["last_seen_at"] and d["firmware_version"] == "1.4.2" and d["battery_pct"] == 87

    def test_unregistered_or_malformed_ids_are_ignored(self, env):
        assert self.pay(env, **{"X-Device-Id": "NOT-REGISTERED"}).status_code == 401
        assert self.pay(env, **{"X-Device-Id": "bad id!"}).status_code == 401
        assert env.db().query(PosDevice).count() == 0                                       # never auto-registers

    def test_bad_battery_is_ignored(self, env):
        register(env)
        self.pay(env, **{"X-Device-Id": "POS-001", "X-Battery": "500"})
        assert env.client.get("/api/admin/pos-devices", headers=env.ah).json()["items"][0]["battery_pct"] is None

    def test_disabled_device_is_not_blocked_while_the_flag_is_off(self, env):
        pk = register(env).json()["id"]
        env.client.post(f"/api/admin/pos-devices/{pk}/disable", headers=env.ah)
        assert self.pay(env, **{"X-Device-Id": "POS-001"}).status_code == 401              # flag off: reaches the route

    def test_disabled_device_is_blocked_when_enforcement_is_on(self, env, monkeypatch):
        monkeypatch.setenv("POS_DEVICE_ENFORCEMENT_ENABLED", "true")
        pk = register(env).json()["id"]
        assert self.pay(env, **{"X-Device-Id": "POS-001"}).status_code == 401              # active device passes
        env.client.post(f"/api/admin/pos-devices/{pk}/disable", headers=env.ah)
        res = self.pay(env, **{"X-Device-Id": "POS-001"})
        assert res.status_code == 403 and res.json()["code"] == "DEVICE_DISABLED" and res.json()["success"] is False
        for path in ("/api/nfc/pay/status", "/api/qr/create-request", "/api/wallet/pos/pending-otp"):
            assert env.client.get(path, headers={"X-Device-Id": "POS-001"}).status_code == 403
        env.client.post(f"/api/admin/pos-devices/{pk}/enable", headers=env.ah)
        assert self.pay(env, **{"X-Device-Id": "POS-001"}).status_code == 401              # enabled again

    def test_non_pos_paths_and_admin_calls_are_never_blocked(self, env, monkeypatch):
        monkeypatch.setenv("POS_DEVICE_ENFORCEMENT_ENABLED", "true")
        pk = register(env).json()["id"]
        env.client.post(f"/api/admin/pos-devices/{pk}/disable", headers=env.ah)
        headers = {**env.ah, "X-Device-Id": "POS-001"}
        assert env.client.get("/api/admin/pos-devices", headers=headers).status_code == 200

    def test_database_failure_lets_the_request_through(self, env, monkeypatch):
        monkeypatch.setenv("POS_DEVICE_ENFORCEMENT_ENABLED", "true")

        def boom():
            raise RuntimeError("db down")
        monkeypatch.setattr(gate, "SessionLocal", boom)
        assert self.pay(env, **{"X-Device-Id": "POS-001"}).status_code == 401              # not 500, not 403
