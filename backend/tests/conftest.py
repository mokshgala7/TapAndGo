"""Test isolation for the Tap&Go backend.

This module is imported by pytest before any test module, so the environment
below is in place before `app.config` / `app.database` / `app.main` load.

- `.env` is never read (TAPGO_TESTING=1, see app/config.py).
- The database is an in-memory SQLite database (app/database.py refuses
  anything else while TAPGO_TESTING=1).
- Every external provider uses obviously fake values: no real e-mail, storage,
  or payment account can be reached. Individual tests that exercise those
  integrations mock the client (boto3, supabase, razorpay) themselves.
"""
import os

os.environ["TAPGO_TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["REVIEW_DEMO_MODE"] = "false"
# The mandatory 10-minute OTP rule is exercised in tests/test_ten_minute_rule.py; the older payment tests make
# several payments in a row and switch it on explicitly where they need it.
os.environ["TAPGO_TEN_MINUTE_RULE"] = "off"
os.environ.pop("ENVIRONMENT", None)
os.environ.pop("ENV", None)

# Fake, non-functional credentials.
os.environ["AWS_ACCESS_KEY_ID"] = "AKIATESTFAKEFAKEFAKE"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test-fake-secret-not-real"
os.environ["AWS_REGION"] = "ap-south-1"
os.environ["SES_FROM_EMAIL"] = "tapandgosupport@gmail.com"
for name in (
    "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "RESEND_API_KEY",
    "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
    "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET",
    "ADMIN_EMAIL", "ADMIN_PASSWORD", "ALLOW_MOCK_PAYMENTS",
):
    os.environ[name] = ""

import pytest  # noqa: E402


class _FakeBucket:
    def __init__(self):
        self.objects = {}

    def upload(self, path, file, file_options=None):
        self.objects[path] = file
        return {"path": path}

    def remove(self, paths):
        for p in paths:
            self.objects.pop(p, None)

    def create_signed_url(self, path, expires_in):
        return {"signedURL": f"https://storage.test/{path}?exp={expires_in}"}


class _FakeStorage:
    def __init__(self):
        self.bucket = _FakeBucket()

    def from_(self, _name):
        return self.bucket


class _FakeSupabase:
    def __init__(self):
        self.storage = _FakeStorage()


@pytest.fixture(autouse=True)
def _fake_storage_backend(monkeypatch):
    """Document uploads go to an in-memory fake, never to a real bucket."""
    import app.utils.storage_service as storage_service

    monkeypatch.setattr(storage_service, "_supabase", _FakeSupabase())
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests may never open a network connection (SES, Razorpay, Supabase...)."""
    import socket

    def refuse(self, *args, **kwargs):
        raise RuntimeError("Network access is disabled in tests; mock the client instead.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    yield
