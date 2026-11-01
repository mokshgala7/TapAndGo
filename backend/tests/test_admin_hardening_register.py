"""Phase 1 of the admin hardening: public registration can never create an admin."""
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models import EmailOTP, User
from app.schemas import UserRegisterForm
from helpers import Env

PASSWORD = "Passw0rd!x"


def form(**over):
    base = dict(name="Asha Verma", email="a@example.com", phone="9876543210", password=PASSWORD)
    base.update(over)
    return base


@pytest.fixture
def env():
    return Env()


class TestSchemaValidator:
    def test_default_stays_passenger(self):
        assert UserRegisterForm(**form()).account_type == "passenger"

    @pytest.mark.parametrize("raw,expected", [("passenger", "passenger"), ("DRIVER", "driver"), (" Driver ", "driver")])
    def test_passenger_and_driver_are_normalised(self, raw, expected):
        assert UserRegisterForm(**form(account_type=raw)).account_type == expected

    @pytest.mark.parametrize("raw", ["admin", "ADMIN", " Admin ", "superuser", ""])
    def test_everything_else_is_rejected(self, raw):
        with pytest.raises(ValidationError):
            UserRegisterForm(**form(account_type=raw))


class TestRegisterEndpoint:
    def _verified_code(self, env, email):
        db = env.db()
        try:
            db.add(EmailOTP(email=email, otp="123456", reason="create_account", purpose="create_account",
                            attempts=0, is_verified=True, used=False,
                            expires_at=datetime.utcnow() + timedelta(minutes=10)))
            db.commit()
        finally:
            db.close()
        return "123456"

    def _register(self, env, email, phone, account_type):
        code = self._verified_code(env, email)
        return env.client.post("/api/auth/register", data={
            "account_type": account_type, "name": "Asha Verma", "email": email, "phone": phone,
            "email_otp": code, "password": PASSWORD})

    @pytest.mark.parametrize("raw", ["admin", "ADMIN", "root"])
    def test_admin_registration_is_rejected_and_creates_nothing(self, env, raw):
        res = self._register(env, "evil@example.com", "9111111111", raw)
        assert res.status_code == 422
        assert env.db().query(User).filter(User.email == "evil@example.com").first() is None
        # the verified code was not consumed by the rejected request
        otp = env.db().query(EmailOTP).filter(EmailOTP.email == "evil@example.com").first()
        assert otp.used is False

    @pytest.mark.parametrize("raw,stored", [("passenger", "passenger"), ("driver", "driver"), ("Driver", "driver")])
    def test_passenger_and_driver_still_register(self, env, raw, stored):
        email = f"{stored}-{raw}@example.com".lower()
        res = self._register(env, email, "9" + str(abs(hash(email)) % 10**9).zfill(9), raw)
        assert res.status_code == 200 and res.json()["success"] is True
        assert env.db().query(User).filter(User.email == email).first().account_type == stored
