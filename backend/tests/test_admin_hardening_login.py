"""Phase 8 of the admin hardening: persistent login throttle and the optional email second factor."""
import re
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import AdminSession, EmailOTP, LoginAttempt
from app.routes import admin as admin_routes
from app.services import admin_login_security as sec
from helpers import Env

EMAIL, PASSWORD = "admin@test.local", "Adm1n-Strong-Pass"


@pytest.fixture
def env(monkeypatch):
    admin_routes._LOGIN_FAILURES.clear()
    monkeypatch.delenv("ADMIN_2FA_ENABLED", raising=False)
    e = Env()
    e.admin_id = e.add_admin(EMAIL, PASSWORD)
    return e


def login(env, password=PASSWORD, **extra):
    return env.client.post("/api/admin/login", json={"email": EMAIL, "password": password, **extra})


class TestPersistentThrottle:
    def test_failures_are_stored_and_survive_losing_process_memory(self, env):
        for _ in range(5):
            assert login(env, "bad").status_code == 401
        admin_routes._LOGIN_FAILURES.clear()            # simulates a restart / another worker process
        assert login(env).status_code == 429             # even the right password, as today
        db = env.db()
        try:
            assert db.query(LoginAttempt).count() == 5
        finally:
            db.close()

    def test_error_behaviour_is_unchanged(self, env):
        r = login(env, "bad")
        assert r.status_code == 401 and r.json()["detail"] == "Invalid administrator credentials."
        for _ in range(4):
            login(env, "bad")
        r = login(env)
        assert r.status_code == 429 and r.json()["detail"] == "Too many failed attempts. Try again later."

    def test_old_failures_age_out(self, env):
        db = env.db()
        try:
            for _ in range(5):
                db.add(LoginAttempt(key=f"{EMAIL}|testclient", ip="testclient", attempted_at=datetime.utcnow() - timedelta(minutes=16)))
            db.commit()
        finally:
            db.close()
        assert login(env).status_code == 200

    def test_success_clears_the_failures(self, env):
        for _ in range(3):
            login(env, "bad")
        assert login(env).status_code == 200
        db = env.db()
        try:
            assert db.query(LoginAttempt).count() == 0
        finally:
            db.close()

    def test_per_ip_cap_across_emails(self, env):
        db = env.db()
        try:
            for i in range(sec.LOGIN_IP_MAX_FAILURES):
                db.add(LoginAttempt(key=f"other{i}@x.test|testclient", ip="testclient"))
            db.commit()
        finally:
            db.close()
        assert login(env).status_code == 429

    def test_other_ips_are_not_affected(self, env):
        db = env.db()
        try:
            for _ in range(5):
                db.add(LoginAttempt(key=f"{EMAIL}|10.0.0.9", ip="10.0.0.9"))
            db.commit()
        finally:
            db.close()
        assert login(env).status_code == 200

    def test_falls_back_to_memory_when_the_database_throttle_fails(self, env):
        with patch.object(sec, "is_throttled", return_value=None), patch.object(sec, "record_failure", return_value=False):
            for _ in range(5):
                assert login(env, "bad").status_code == 401
            assert login(env).status_code == 429          # the in-memory throttle caught it
        admin_routes._LOGIN_FAILURES.clear()
        assert login(env).status_code == 200              # and a database problem alone never blocks login

    def test_real_database_errors_do_not_block_login(self, env):
        class Broken:
            def query(self, *a, **k):
                raise RuntimeError("db down")

            def rollback(self):
                pass
        assert sec.is_throttled(Broken(), "k", "ip") is None
        assert sec.record_failure(Broken(), "k", "ip") is False


class TestTwoFactor:
    @pytest.fixture(autouse=True)
    def _mail(self, env, monkeypatch):       # `env` first, so its flag reset runs before the flag is switched on
        monkeypatch.setenv("ADMIN_2FA_ENABLED", "true")
        self.sent = []
        with patch.object(sec, "send_email", side_effect=lambda **kw: self.sent.append(kw) or True):
            yield

    def code(self):
        return re.search(r">(\d{6})<", self.sent[-1]["html_content"]).group(1)

    def sessions(self, env):
        db = env.db()
        try:
            return db.query(AdminSession).count()
        finally:
            db.close()

    def test_flag_off_by_default_means_unchanged_login(self, env, monkeypatch):
        monkeypatch.delenv("ADMIN_2FA_ENABLED")
        r = login(env)
        assert r.status_code == 200 and r.json()["token"] and "otp_required" not in r.json()
        assert self.sent == []

    def test_password_alone_does_not_log_in(self, env):
        r = login(env)
        assert r.status_code == 200 and r.json()["otp_required"] is True and r.json()["success"] is False
        assert "token" not in r.json() and "admin" not in r.json()
        assert self.sessions(env) == 0 and len(self.sent) == 1 and self.sent[0]["to_email"] == EMAIL

    def test_wrong_password_never_sends_a_code(self, env):
        assert login(env, "bad").status_code == 401
        assert self.sent == []

    def test_correct_code_logs_in_once(self, env):
        login(env)
        r = login(env, otp=self.code())
        assert r.status_code == 200 and r.json()["success"] is True and r.json()["token"]
        assert env.client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200
        assert login(env, otp=self.code()).status_code == 401      # single use

    def test_wrong_code_is_rejected_and_five_wrong_lock_it(self, env):
        login(env)
        real = self.code()
        wrong = "000000" if real != "000000" else "111111"
        for _ in range(5):
            assert login(env, otp=wrong).status_code == 401
        # throttle (5 failures) now refuses before the code is even looked at; clear it to test the code lock itself
        db = env.db()
        try:
            db.query(LoginAttempt).delete(); db.commit()
        finally:
            db.close()
        r = login(env, otp=real)
        assert r.status_code == 401 and self.sessions(env) == 0

    def test_expired_code_is_rejected(self, env):
        login(env)
        db = env.db()
        try:
            db.query(EmailOTP).update({EmailOTP.expires_at: datetime.utcnow() - timedelta(seconds=1)}); db.commit()
        finally:
            db.close()
        r = login(env, otp=self.code())
        assert r.status_code == 401 and "expired" in r.json()["detail"].lower()

    def test_code_expiry_is_five_minutes(self, env):
        login(env)
        db = env.db()
        try:
            row = db.query(EmailOTP).filter(EmailOTP.reason == "admin_login").one()
            assert row.purpose == "admin_login" and row.attempts == 0 and row.used is False
            assert timedelta(minutes=4, seconds=50) < row.expires_at - datetime.utcnow() <= timedelta(minutes=5)
        finally:
            db.close()

    def test_resend_is_rate_limited_then_replaces_the_old_code(self, env):
        login(env); login(env)
        assert len(self.sent) == 1                                  # second request inside 60 s sends nothing new
        db = env.db()
        try:
            db.query(EmailOTP).update({EmailOTP.created_at: datetime.utcnow() - timedelta(minutes=2)}); db.commit()
        finally:
            db.close()
        old = self.code()
        login(env)
        assert len(self.sent) == 2
        if self.code() != old:
            assert login(env, otp=old).status_code == 401           # the superseded code no longer works
        assert login(env, otp=self.code()).status_code == 200

    def test_email_failure_is_reported_not_silent(self, env):
        with patch.object(sec, "send_email", return_value=False):
            assert login(env).status_code == 503

    def test_code_for_one_admin_is_useless_for_another(self, env):
        env.add_admin("second@test.local", "Second-Strong-Pass-1")
        login(env)
        r = env.client.post("/api/admin/login", json={"email": "second@test.local", "password": "Second-Strong-Pass-1", "otp": self.code()})
        assert r.status_code == 401
