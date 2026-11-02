"""
test_user_amount_override.py
────────────────────────────
Per-user fraud amount override (app/services/fraud_gate.py, env FRAUD_USER_AMOUNT_LIMITS, default "4:60,69:170,70:270"):
a payment by a listed passenger for an amount STRICTLY above that passenger's limit is flagged and needs the email OTP
on every channel; equal to the limit is not flagged. Everyone else behaves exactly as before. Mail is mocked.
"""
import logging
import re
import uuid
from decimal import Decimal

import pytest

from app.models import FraudAssessment, NFCCard, PaymentOtpChallenge, User
from app.services import fraud_gate
from tests.helpers import Env
from tests.test_fraud_gate import last_otp, mail, rows  # noqa: F401 - fixture imported by name so pytest finds it here

SECRET = "unit-test-secret-not-a-real-one"
UIDS = {4: "04A2B3C4D5E604", 69: "04A2B3C4D5E669", 70: "04A2B3C4D5E670", 5: "04A2B3C4D5E605"}
LIMITS = {4: 60, 69: 170, 70: 270}


@pytest.fixture
def logs():
    """Everything the fraud gate logs (its handler stops propagation, so caplog would miss it)."""
    class _Capture(logging.Handler):
        def __init__(self):
            super().__init__(logging.DEBUG)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())

    handler, lg = _Capture(), logging.getLogger("tapgo.fraud_gate")
    lg.addHandler(handler)
    yield handler.lines
    lg.removeHandler(handler)


def score_lines(lines, uid=None):
    return [ln for ln in lines if ln.startswith("fraud_assessment user_id=" + (f"{uid} " if uid else ""))]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.setenv("PAYMENT_OTP_SECRET", SECRET)
    for name in ("FRAUD_USER_AMOUNT_LIMITS", "TAPGO_FRAUD_MODE", "TAPGO_FRAUD_ENFORCE_USER_IDS", "TAPGO_NEWUSER_POLICY",
                 "TAPGO_RISK_DISABLED"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def scene(mail):
    env = Env()
    driver_id = env.add_user("drv@override.local", account_type="driver", balance=0, name="Ravi Driver",
                             vehicle_type="auto_rickshaw")
    pax = {}
    for uid, card_uid in UIDS.items():
        pax[uid] = env.add_user(f"pax{uid}@override.local", account_type="passenger", balance=100000,
                                name=f"Pax {uid}", id=uid)
    db = env.db()
    try:
        for uid, card_uid in UIDS.items():
            db.add(NFCCard(user_id=uid, card_reference=f"NFC-OVR{uid:04d}", card_uid=card_uid, status="active"))
        db.commit()
    finally:
        db.close()
    assert pax == {4: 4, 69: 69, 70: 70, 5: 5}
    return {"env": env, "driver_id": driver_id, "driver_headers": env.user_headers(driver_id), "mail": mail}


def pay(scene, uid, channel, amount):
    c, key = scene["env"].client, f"ovr-{uuid.uuid4().hex}"
    if channel == "nfc":
        r = c.post("/api/nfc/pay", json={"card_uid": UIDS[uid], "amount": amount, "idempotency_key": key},
                   headers=scene["driver_headers"])
    elif channel == "qr":
        t = c.post("/api/qr/create-request", json={"amount": amount}, headers=scene["driver_headers"])
        assert t.status_code == 200, t.text
        r = c.post(f"/api/qr/{t.json()['token']}/confirm", json={"idempotency_key": key},
                   headers=scene["env"].user_headers(uid))
    else:
        r = c.post("/api/wallet/pay", json={"driver_id": scene["driver_id"], "fare": amount, "idempotency_key": key},
                   headers=scene["env"].user_headers(uid))
    return r.json()


def outcome(body):
    if body.get("status") == "otp_required":
        return "otp"
    return "paid" if body.get("success") is True else "declined"


def latest(scene, uid):
    found = rows(scene, FraudAssessment, passenger_id=uid)
    assert found
    return found[-1]


def override_reasons(row):
    return [r for r in (row.reasons or "").split(",") if r.startswith("user_limit_override")]


# ── the two users, every channel, the exact boundary ────────────────────────────────────────────────

@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
@pytest.mark.parametrize("uid,amount,flagged", [
    (4, 60, False), (4, 61, True), (4, 60.5, True),
    (69, 170, False), (69, 171, True), (69, 170.5, True),
    (70, 270, False), (70, 271, True), (70, 270.01, True),
])
def test_limit_is_strictly_greater_than_on_every_channel(scene, channel, uid, amount, flagged):
    body = pay(scene, uid, channel, amount)
    row = latest(scene, uid)
    if flagged:
        assert outcome(body) == "otp"
        assert row.decision == "otp_required"
        assert len(override_reasons(row)) == 1
        assert f"> limit {LIMITS[uid]}" in row.reasons
        assert len(scene["mail"]["otp"]) == 1
    else:
        assert outcome(body) == "paid"
        assert row.decision == "proceed" and override_reasons(row) == []
        assert scene["mail"]["otp"] == []


def test_a_correct_code_completes_a_flagged_payment_through_the_existing_otp_flow(scene):
    body = pay(scene, 69, "nfc", 171)
    assert outcome(body) == "otp" and scene["env"].balance(69) == Decimal("100000.00")
    r = scene["env"].client.post("/api/nfc/pay/verify-otp", json={
        "challenge_id": body["challenge_id"], "otp": last_otp(scene), "idempotency_key": _key_of(scene, 69)},
        headers=scene["driver_headers"])
    assert r.status_code == 200 and r.json().get("success") is True
    assert scene["env"].balance(69) == Decimal("99829.00")


def _key_of(scene, uid):
    return latest(scene, uid).idempotency_key.split(":")[-1] if ":" in (latest(scene, uid).idempotency_key or "") else \
        latest(scene, uid).idempotency_key


# ── everyone else is unchanged ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_another_user_paying_a_large_amount_is_unchanged(scene, channel):
    body = pay(scene, 5, channel, 5000)
    assert outcome(body) == "paid" and scene["mail"]["otp"] == []
    row = latest(scene, 5)
    assert row.decision == "proceed" and override_reasons(row) == []
    assert row.ml_status != "off"                                   # the model still scored this user's payment


def test_the_override_runs_with_the_ml_in_enforce_mode_and_never_removes_a_flag(scene, monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    body = pay(scene, 69, "nfc", 100)                                # first ever payment, under the limit: normal rules
    first = latest(scene, 69)
    assert override_reasons(first) == []
    body = pay(scene, 69, "nfc", 500)                                # within 10 minutes AND over the limit: both reasons
    row = latest(scene, 69)
    assert outcome(body) == "otp" and "rule_10min" in row.reasons and len(override_reasons(row)) == 1
    assert row.ml_status != "off"                                    # the model still ran for this user


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("uid,over,at_limit", [(4, 61, 60), (69, 171, 170), (70, 271, 270)])
def test_the_override_applies_in_every_mode(scene, monkeypatch, mode, uid, over, at_limit):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", mode)
    assert outcome(pay(scene, uid, "wallet", over)) == "otp"
    assert latest(scene, uid).mode == mode
    assert outcome(pay(scene, 5, "wallet", at_limit)) == "paid"      # not listed: untouched


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_a_listed_user_who_is_also_enforced_gets_one_otp_not_two(scene, monkeypatch, mode, channel):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", mode)
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "4,69,70")
    body = pay(scene, 4, channel, 61)
    assert outcome(body) == "otp" and len(scene["mail"]["otp"]) == 1
    assert len(rows(scene, PaymentOtpChallenge, passenger_id=4)) == 1
    assert len(override_reasons(latest(scene, 4))) == 1


# ── configuration ───────────────────────────────────────────────────────────────────────────────────

def test_defaults_when_the_variable_is_unset():
    assert fraud_gate.user_amount_limits() == {4: Decimal("60"), 69: Decimal("170"), 70: Decimal("270")}


def test_blank_value_uses_the_defaults(monkeypatch):
    monkeypatch.setenv("FRAUD_USER_AMOUNT_LIMITS", "   ")
    assert fraud_gate.user_amount_limits() == {4: Decimal("60"), 69: Decimal("170"), 70: Decimal("270")}


def test_env_value_replaces_the_defaults(monkeypatch):
    monkeypatch.setenv("FRAUD_USER_AMOUNT_LIMITS", " 12 : 99.5 , 13:1000 ")
    assert fraud_gate.user_amount_limits() == {12: Decimal("99.5"), 13: Decimal("1000")}
    assert fraud_gate.user_limit_override(69, Decimal("5000"), True) is None
    assert fraud_gate.user_limit_override(12, Decimal("99.51"), True) is not None
    assert fraud_gate.user_limit_override(12, Decimal("99.5"), True) is None


@pytest.mark.parametrize("raw,expected", [
    ("69:170,garbage,70:270", {69: 170, 70: 270}),
    ("69:abc,70:270", {70: 270}),
    ("69:170:1,70:270", {70: 270}),
    ("0:5,-3:5,70:270", {70: 270}),
    ("69:0,70:-5,71:nan,72:inf,5:5", {5: 5}),
    ("69:170,,70:270,", {69: 170, 70: 270}),
    ("junk", {}), (",,,", {}), ("69:170;70:270", {}), ("٩:170", {}),
])
def test_bad_entries_are_ignored_and_never_crash(monkeypatch, raw, expected):
    monkeypatch.setenv("FRAUD_USER_AMOUNT_LIMITS", raw)
    assert fraud_gate.user_amount_limits() == {k: Decimal(v) for k, v in expected.items()}


def test_a_bad_value_is_logged_and_a_payment_still_works(scene, monkeypatch, logs):
    monkeypatch.setenv("FRAUD_USER_AMOUNT_LIMITS", f"69:oops-{uuid.uuid4().hex[:6]},70:270")
    assert outcome(pay(scene, 69, "nfc", 5000)) == "paid"          # entry ignored: no override for 69
    assert outcome(pay(scene, 70, "nfc", 271)) == "otp"            # valid entry still works
    assert any("user_amount_limit_ignored" in ln for ln in logs)


# ── the risk-score line in the Render logs ─────────────────────────────────────────────────────────

LINE = re.compile(r"^fraud_assessment user_id=(\d+) amount=(\d+\.\d{2}) mode=(off|shadow|enforce) "
                  r"ml_risk=(n/a|\d\.\d{2}) base_limit=(\d+) base_rule_flag=(true|false) decision=(proceed|otp_required)$")


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
@pytest.mark.parametrize("uid,amount,flag", [(4, 60, "false"), (4, 61, "true"), (69, 170, "false"), (69, 171, "true"),
                                              (70, 270, "false"), (70, 271, "true")])
def test_the_risk_score_line_is_logged_for_flagged_and_unflagged_payments(scene, logs, channel, uid, amount, flag):
    pay(scene, uid, channel, amount)
    lines = score_lines(logs, uid)
    assert len(lines) == 1, lines
    m = LINE.match(lines[0])
    assert m, lines[0]
    assert (int(m[1]), float(m[2]), m[5], m[6]) == (uid, float(amount), str(LIMITS[uid]), flag)
    assert m[7] == ("otp_required" if flag == "true" else "proceed")
    assert m[4] != "n/a"                                           # the model scored it


@pytest.mark.parametrize("mode,expected", [("off", "n/a"), ("shadow", None), ("enforce", None)])
def test_the_line_shows_n_a_only_when_there_is_no_score(scene, monkeypatch, logs, mode, expected):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", mode)
    pay(scene, 69, "nfc", 100)
    (line,) = score_lines(logs, 69)
    assert (expected is None) == ("ml_risk=n/a" not in line)
    assert f"mode={mode}" in line


def test_no_score_line_for_unlisted_users_and_no_sensitive_data_in_it(scene, logs):
    pay(scene, 5, "nfc", 5000)
    assert score_lines(logs, 5) == []
    pay(scene, 4, "nfc", 61)
    (line,) = score_lines(logs, 4)
    assert not any(tok in line for tok in (UIDS[4], "@", "otp=", "challenge", "postgres", "password"))


def test_a_failing_log_helper_never_breaks_a_payment(scene, monkeypatch):
    monkeypatch.setattr(fraud_gate.logger, "info", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert outcome(pay(scene, 4, "nfc", 61)) == "otp"
    assert outcome(pay(scene, 5, "nfc", 100)) == "paid"


def test_an_unreadable_limit_lookup_never_breaks_a_payment(scene, monkeypatch):
    monkeypatch.setattr(fraud_gate, "user_amount_limits", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert fraud_gate.user_limit_override(69, Decimal("500"), True) is None
    assert outcome(pay(scene, 69, "nfc", 500)) == "paid"


def test_invalid_amounts_are_not_flagged_by_the_override():
    assert fraud_gate.user_limit_override(69, Decimal("0.00"), False) is None
