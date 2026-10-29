"""
test_new_account_policy.py
──────────────────────────
The fixed "new-account policy" (app/services/fraud_gate.py): every passenger who is NOT in TAPGO_FRAUD_ENFORCE_USER_IDS
follows a plain amount rule instead of the personal model, when TAPGO_NEWUSER_POLICY=enforce:

    amount <= TAPGO_NEWUSER_OTP_ABOVE (default 300 rupees)  pays normally;  amount > it needs the email OTP (all three
    channels, entered on the POS);  the 10-minute rule does NOT apply;  the V6 score is only recorded.

Passengers in the allowlist (the personal-model users) behave exactly as before. Mail is mocked.
"""
import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import FraudAssessment, User, Wallet
from app.services import fraud_gate
from app.services.fraud_gate import FraudConfigError
from tests.test_fraud_gate import (  # noqa: F401 - fixtures are imported by name so pytest finds them here
    UID, add_history, balances, completed, last_otp, mail, qr_confirm, qr_create, rows, scene, tap,
)

SECRET = "unit-test-secret-not-a-real-one"
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.setenv("TAPGO_NEWUSER_POLICY", "enforce")
    monkeypatch.setenv("PAYMENT_OTP_SECRET", SECRET)
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.delenv("TAPGO_FRAUD_ENFORCE_USER_IDS", raising=False)
    monkeypatch.delenv("TAPGO_NEWUSER_OTP_ABOVE", raising=False)
    monkeypatch.delenv("TAPGO_RISK_DISABLED", raising=False)


def pay(scene, channel, amount, key=None):
    """One payment attempt on a channel. Returns (response json, http status, key)."""
    key = key or f"pol-{uuid.uuid4().hex}"
    c, drv, pax = scene["env"].client, scene["driver_headers"], scene["pax_headers"]
    if channel == "nfc":
        r = c.post("/api/nfc/pay", json={"card_uid": UID, "amount": amount, "idempotency_key": key}, headers=drv)
    elif channel == "qr":
        r = qr_confirm(scene, qr_create(scene, amount), key=key)
    else:
        r = c.post("/api/wallet/pay", json={"driver_id": scene["driver_id"], "fare": amount, "idempotency_key": key}, headers=pax)
    return r.json(), r.status_code, key


def outcome(body):
    if body.get("status") == "otp_required":
        return "otp"
    if body.get("success") is True:
        return "paid"
    return "declined"


def set_balance(scene, amount):
    db = scene["env"].db()
    try:
        db.query(Wallet).filter(Wallet.user_id == scene["pax_id"]).update({"balance": Decimal(str(amount))})
        db.commit()
    finally:
        db.close()


def set_email(scene, email):
    db = scene["env"].db()
    try:
        db.query(User).filter(User.id == scene["pax_id"]).update({"email": email})
        db.commit()
    finally:
        db.close()


def assessments(scene):
    return rows(scene, FraudAssessment, passenger_id=scene["pax_id"])


# ── the boundary on every channel ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
@pytest.mark.parametrize("amount,expected", [(150, "paid"), (300, "paid"), (301, "otp"), (500, "otp")])
def test_amount_boundary_on_every_channel(scene, policy, channel, amount, expected):
    before = balances(scene)
    body, _, _ = pay(scene, channel, amount)
    assert outcome(body) == expected, body
    if expected == "paid":
        assert balances(scene)[0] == before[0] - amount and scene["mail"]["otp"] == []
    else:
        assert balances(scene) == before and len(scene["mail"]["otp"]) == 1 and completed(scene) == []


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_a_just_over_amount_with_paise_needs_an_otp_and_the_threshold_itself_does_not(scene, policy, channel):
    assert outcome(pay(scene, channel, 300.0)[0]) == "paid"
    assert outcome(pay(scene, channel, 300.01)[0]) == "otp"


def test_the_threshold_is_configurable_and_exclusive(scene, policy, monkeypatch):
    monkeypatch.setenv("TAPGO_NEWUSER_OTP_ABOVE", "100")
    assert outcome(pay(scene, "nfc", 100)[0]) == "paid"
    assert outcome(pay(scene, "nfc", 101)[0]) == "otp"


def test_policy_off_is_the_default_and_changes_nothing(scene, monkeypatch):
    monkeypatch.delenv("TAPGO_NEWUSER_POLICY", raising=False)
    monkeypatch.delenv("TAPGO_FRAUD_ENFORCE_USER_IDS", raising=False)
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    for channel in ("nfc", "qr", "wallet"):
        assert outcome(pay(scene, channel, 500)[0]) == "paid"
    assert scene["mail"]["otp"] == []
    assert {a.mode for a in assessments(scene)} == {"shadow"}                 # still the plain shadow record


# ── the 10-minute rule does not apply; the model does not decide ──────────────────────────────────────

@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_back_to_back_normal_payments_are_not_stopped_by_the_ten_minute_rule(scene, policy, channel):
    first = pay(scene, channel, 150)[0]
    second = pay(scene, channel, 150)[0]
    assert outcome(first) == outcome(second) == "paid" and scene["mail"]["otp"] == []


def test_a_scoring_failure_never_blocks_a_normal_payment_and_never_waives_the_rule(scene, policy, monkeypatch):
    monkeypatch.setattr(fraud_gate, "run_assessment", lambda *a, **k: (None, None))        # the model is "down"
    assert outcome(pay(scene, "nfc", 150)[0]) == "paid"
    assert outcome(pay(scene, "nfc", 500)[0]) == "otp"
    ml = {a.ml_status for a in assessments(scene)}
    assert ml == {"error"}                                                    # recorded as a failure, not as low risk


def test_the_ml_switched_off_changes_nothing_for_this_group(scene, policy, monkeypatch):
    monkeypatch.setenv("TAPGO_RISK_DISABLED", "1")
    assert outcome(pay(scene, "qr", 150)[0]) == "paid"
    assert outcome(pay(scene, "qr", 500)[0]) == "otp"


# ── what is recorded ───────────────────────────────────────────────────────────────────────────────

def test_decisions_are_recorded_in_existing_columns_with_a_clear_reason(scene, policy):
    pay(scene, "nfc", 150)
    pay(scene, "nfc", 500)
    by_amount = {int(a.amount): a for a in assessments(scene)}
    low, high = by_amount[150], by_amount[500]
    assert (low.mode, low.decision, low.reasons, low.enforced_by_allowlist) == ("newuser", "proceed", None, False)
    assert (high.mode, high.decision, high.reasons) == ("newuser", "otp_required", "new_account_policy")
    assert high.challenge_id is not None                                      # linked to the OTP challenge
    assert low.ml_status == "scored" and low.risk_score is not None           # the shadow score is still stored


# ── the OTP path keeps every rule ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_insufficient_balance_is_checked_before_any_otp_email(scene, policy, channel):
    set_balance(scene, 100)
    body, status, _ = pay(scene, channel, 500)
    assert outcome(body) == "declined" and scene["mail"]["otp"] == [], body
    assert "INSUFFICIENT" in str(body.get("code", body.get("detail", ""))).upper()


@pytest.mark.parametrize("channel", ["nfc", "qr", "wallet"])
def test_retrying_the_same_payment_does_not_send_another_code(scene, policy, channel):
    token = qr_create(scene, 500) if channel == "qr" else None
    key = f"pol-retry-{channel}-0001"

    def attempt():
        if channel == "qr":
            return qr_confirm(scene, token, key=key).json()
        return pay(scene, channel, 500, key=key)[0]

    first = attempt()
    assert first["status"] == "otp_required"
    for _ in range(3):
        again = attempt()
        assert again["status"] == "otp_required" and again["challenge_id"] == first["challenge_id"]
    assert len(scene["mail"]["otp"]) == 1


def test_qr_confirm_pressed_again_returns_the_same_challenge_and_no_new_email(scene, policy):
    token = qr_create(scene, 500)
    a = qr_confirm(scene, token, key="qr-spam-0001").json()
    b = qr_confirm(scene, token, key="qr-spam-0002").json()
    assert a["status"] == b["status"] == "otp_required" and a["challenge_id"] == b["challenge_id"]
    assert len(scene["mail"]["otp"]) == 1


def test_no_email_declines_only_above_the_threshold(scene, policy):
    set_email(scene, "")
    assert outcome(pay(scene, "nfc", 150)[0]) == "paid"
    body, _, _ = pay(scene, "nfc", 500)
    assert body["code"] == "OTP_UNAVAILABLE" and scene["mail"]["otp"] == []
    set_email(scene, "maya.pax@example.com")


def test_an_email_that_cannot_be_sent_declines_a_big_payment_but_not_a_small_one(scene, policy):
    scene["mail"]["fail_send"] = True
    assert outcome(pay(scene, "wallet", 150)[0]) == "paid"
    before = balances(scene)
    body, status, _ = pay(scene, "wallet", 500)
    assert outcome(body) == "declined" and body["code"] == "OTP_UNAVAILABLE"
    assert balances(scene) == before


def test_a_correct_code_entered_on_the_pos_completes_a_big_payment(scene, policy):
    before = balances(scene)
    body, _, _ = pay(scene, "qr", 500)
    cid = body["challenge_id"]
    assert cid and len(scene["mail"]["otp"]) == 1
    # find the QR token of the request through its challenge (the POS knows it: it created the QR)
    db = scene["env"].db()
    try:
        from app.models import PaymentRequest
        token = db.query(PaymentRequest).filter(PaymentRequest.provider == "QR_WALLET").one().utr
    finally:
        db.close()
    r = scene["env"].client.post(f"/api/qr/{token}/pos/verify-otp", json={"otp": last_otp(scene)}, headers=scene["driver_headers"])
    assert r.json()["success"] is True and balances(scene) == (before[0] - 500, before[1] + 500)


# ── who gets the policy ────────────────────────────────────────────────────────────────────────────

def test_the_personal_model_users_are_unchanged(scene, policy, monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", str(scene["pax_id"]))
    add_history(scene)
    assert outcome(pay(scene, "nfc", 150)[0]) == "paid"                      # normal fare: the model passes it
    body, _, _ = pay(scene, "nfc", 150)                                       # seconds later: the 10-minute rule applies
    assert outcome(body) == "otp"
    for a in assessments(scene):
        assert a.mode == "enforce" and a.enforced_by_allowlist is True
        assert "new_account_policy" not in (a.reasons or "")


def test_the_same_quick_second_payment_is_fine_for_a_policy_user(scene, policy):
    add_history(scene)
    assert outcome(pay(scene, "nfc", 150)[0]) == "paid"
    assert outcome(pay(scene, "nfc", 150)[0]) == "paid"


@pytest.mark.parametrize("uid,personal", [(4, True), (69, True), (70, True), (5, False), (71, False), (1000, False)])
def test_group_membership_comes_only_from_the_env_list(monkeypatch, uid, personal):
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "4,69,70")
    monkeypatch.setenv("TAPGO_NEWUSER_POLICY", "enforce")
    assert fraud_gate.effective_mode(uid) == (("enforce", True) if personal else ("shadow", False))
    monkeypatch.setenv("TAPGO_FRAUD_ENFORCE_USER_IDS", "")
    assert fraud_gate.effective_mode(uid) == ("shadow", False)               # an empty list means nobody is personal


def test_mode_off_and_mode_enforce_do_not_use_the_policy(scene, policy, monkeypatch):
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "off")
    assert outcome(pay(scene, "nfc", 500)[0]) == "paid" and scene["mail"]["otp"] == []
    monkeypatch.setenv("TAPGO_FRAUD_MODE", "enforce")
    add_history(scene)
    pay(scene, "nfc", 150)
    assert all(a.mode in ("off", "enforce") for a in assessments(scene))


def test_no_user_id_is_hard_coded_in_the_code(  # noqa: D103
):
    pattern = re.compile(r"(user_?id|passenger_?id|driver_?id|\.id|\bid)\s*(==|!=|in)\s*[\(\[\{]?\s*(4|69|70)\b")
    roots = [BACKEND / "app", BACKEND.parent / "frontend" / "src"]
    hits = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in (".py", ".js", ".jsx") or "tapgo_fraud_risk" in path.parts:
                continue
            for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(BACKEND.parent)}:{n}")
    assert hits == []


# ── configuration is validated like the other fraud variables ─────────────────────────────────────

@pytest.mark.parametrize("value", ["on", "true", "ENFORCE2", "1", " yes "])
def test_a_bad_policy_value_stops_the_app(monkeypatch, value):
    monkeypatch.setenv("TAPGO_NEWUSER_POLICY", value)
    with pytest.raises(FraudConfigError, match="TAPGO_NEWUSER_POLICY"):
        fraud_gate.validate_fraud_config()


@pytest.mark.parametrize("value", ["abc", "0", "-5", "nan", "inf", "-inf", "1e12", "300,5", "3 00", "₹300"])
def test_a_bad_threshold_stops_the_app(monkeypatch, value):
    monkeypatch.setenv("TAPGO_NEWUSER_OTP_ABOVE", value)
    with pytest.raises(FraudConfigError, match="TAPGO_NEWUSER_OTP_ABOVE"):
        fraud_gate.validate_fraud_config()


@pytest.mark.parametrize("value,expected", [("", Decimal("300")), ("300", Decimal("300")), ("250.50", Decimal("250.50")),
                                            (" 500 ", Decimal("500")), ("1e2", Decimal("1E+2"))])
def test_good_thresholds_parse(monkeypatch, value, expected):
    monkeypatch.setenv("TAPGO_NEWUSER_OTP_ABOVE", value)
    assert fraud_gate.newuser_otp_above() == expected


def test_the_policy_needs_the_otp_secret(monkeypatch):
    monkeypatch.setenv("TAPGO_NEWUSER_POLICY", "enforce")
    monkeypatch.delenv("TAPGO_FRAUD_MODE", raising=False)
    monkeypatch.delenv("PAYMENT_OTP_SECRET", raising=False)
    with pytest.raises(FraudConfigError, match="PAYMENT_OTP_SECRET"):
        fraud_gate.validate_fraud_config()
    monkeypatch.setenv("PAYMENT_OTP_SECRET", SECRET)
    assert fraud_gate.validate_fraud_config() == "shadow"


def test_the_policy_is_only_warned_about_when_it_cannot_apply(monkeypatch):
    monkeypatch.setenv("TAPGO_NEWUSER_POLICY", "enforce")
    monkeypatch.delenv("PAYMENT_OTP_SECRET", raising=False)
    for mode in ("off", "enforce"):
        monkeypatch.setenv("TAPGO_FRAUD_MODE", mode)
        if mode == "enforce":
            with pytest.raises(FraudConfigError, match="TAPGO_FRAUD_MODE=enforce"):       # existing rule, unchanged
                fraud_gate.validate_fraud_config()
        else:
            assert fraud_gate.validate_fraud_config() == "off"                        # ignored, nothing to protect


def test_defaults_start_cleanly_and_change_nothing(monkeypatch):
    for name in ("TAPGO_NEWUSER_POLICY", "TAPGO_NEWUSER_OTP_ABOVE", "TAPGO_FRAUD_MODE", "TAPGO_FRAUD_ENFORCE_USER_IDS",
                 "PAYMENT_OTP_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert fraud_gate.validate_fraud_config() == "shadow"
    assert fraud_gate.newuser_policy() == "off" and fraud_gate.newuser_otp_above() == Decimal("300")
