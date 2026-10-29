"""
test_fraud_requirements.py
──────────────────────────
Requirement tests for the vendored V6 fraud model (no database): the 10-minute rule, IST day/night boundaries,
night-traveller behaviour, fare anomalies (incl. familiar drivers), progressive learning / profile activation,
duplicate handling and invalid inputs. They call FraudScorerFinal.score_safe and assess_ride_payment directly.

Scores here come from hand-built histories: SYNTHETIC DATA - not evidence of real-world performance.
"""
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.tapgo_fraud_risk import RiskConfig, assess_ride_payment, load_scorer

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
ENFORCE = RiskConfig(db_timezone="UTC", mode="enforce", model="v6")
SHADOW = RiskConfig(db_timezone="UTC", mode="shadow", model="v6")
NOW = datetime(2026, 10, 14, 13, 0, tzinfo=IST)  # a Wednesday, 13:00 IST (day)


@pytest.fixture(scope="module")
def scorer():
    return load_scorer("v6")


def ride(at, amount, driver="d1", status="completed", key=None, method="QR"):
    return {"timestamp": at.isoformat(), "amount": amount, "driver_id": driver, "payment_method": method,
            "vehicle_type": "auto_rickshaw", "status": status, "idempotency_key": key}


def tx(at, amount, driver="d9", key="new-key", method="QR"):
    return {"timestamp": at.isoformat() if isinstance(at, datetime) else at, "amount": amount, "driver_id": driver,
            "payment_method": method, "vehicle_type": "auto_rickshaw", "idempotency_key": key}


def day_history(n, end, lo=120, hi=180, drivers=None, hour=9):
    """n completed day rides, one per day before `end`, fares cycling deterministically in [lo, hi]."""
    out = []
    for i in range(n):
        d = (end - timedelta(days=n - i)).replace(hour=hour, minute=15)
        fare = lo + (i * 37) % (hi - lo + 1)
        drv = drivers[i] if drivers else f"d{i % 7}"
        out.append(ride(d, fare, driver=drv, key=f"h{i}"))
    return out


def score(scorer, t, hist):
    out = scorer.score_safe(t, hist)
    assert out["scoring_status"] == "scored", out.get("error")
    return out


# ── 1. Mandatory 10-minute rule ──────────────────────────────────────────────

@pytest.mark.parametrize("gap,triggered,elapsed", [(599, True, 599), (600, True, 600), (601, False, 601),
                                                   (600.4, True, 600)])  # sub-second: floored to whole seconds
def test_ten_minute_boundaries(scorer, gap, triggered, elapsed):
    prev = NOW - timedelta(seconds=gap)
    hist = day_history(30, NOW - timedelta(hours=2)) + [ride(prev, 150, key="prev")]
    out = score(scorer, tx(NOW, 150), hist)
    rule = out["rules"]["rapid_repeat_10min"]
    assert rule["triggered"] is triggered
    assert rule["elapsed_seconds"] == elapsed
    a = assess_ride_payment("p1", "d9", 150, [], ENFORCE)  # sanity: the service API is importable/usable
    assert a.status == "scored"


def test_ten_minute_rule_forces_step_up_in_enforce():
    hist = day_history(30, NOW - timedelta(hours=2)) + [ride(NOW - timedelta(seconds=600), 150, key="prev")]
    rows = [_row(h) for h in hist]
    a = assess_ride_payment("p1", "d9", 150, rows, ENFORCE, at=NOW, idempotency_key="k")
    assert a.status == "scored" and a.backend_action == "step_up_otp"
    assert "rapid_repeat_10min" in a.reasons


def test_failed_ride_does_not_reset_reference(scorer):
    base = day_history(30, NOW - timedelta(hours=2))
    failed_5m = base + [ride(NOW - timedelta(minutes=5), 150, status="failed", key="f1")]
    out = score(scorer, tx(NOW, 150), failed_5m)
    assert out["rules"]["rapid_repeat_10min"]["triggered"] is False
    completed_9m = base + [ride(NOW - timedelta(minutes=9), 150, key="c1")]
    out = score(scorer, tx(NOW, 150), completed_9m)
    assert out["rules"]["rapid_repeat_10min"]["triggered"] is True
    assert out["rules"]["rapid_repeat_10min"]["elapsed_seconds"] == 540


# ── 2. Day / night boundaries (Asia/Kolkata) ─────────────────────────────────

@pytest.mark.parametrize("ist_hm,period,utc_iso", [((5, 59), "night", "2026-10-14T00:29:00+00:00"),
                                                   ((6, 0), "day", "2026-10-14T00:30:00+00:00"),
                                                   ((21, 59), "day", "2026-10-14T16:29:00+00:00"),
                                                   ((22, 0), "night", "2026-10-14T16:30:00+00:00")])
def test_day_night_boundaries(scorer, ist_hm, period, utc_iso):
    at = datetime(2026, 10, 14, *ist_hm, tzinfo=IST)
    hist = day_history(30, at - timedelta(days=1))
    for t in (at, at.isoformat(), utc_iso, at.astimezone(UTC), at.strftime("%Y-%m-%dT%H:%M:%S+05:30")):
        out = score(scorer, tx(t, 150), hist)
        assert out["passenger_fare_anomaly"]["period"] == period, t


# ── 3. Night behaviour ───────────────────────────────────────────────────────

def night_history(n, end):
    out = []
    for i in range(n):
        d = (end - timedelta(days=n - i)).replace(hour=23, minute=10)
        out.append(ride(d, 180 + (i * 29) % 81, driver=f"d{i % 5}", key=f"n{i}"))  # night fares 180-260
    return out


def test_regular_night_traveller_not_flagged_for_night(scorer):
    at = datetime(2026, 10, 14, 23, 20, tzinfo=IST)
    hist = night_history(60, at.replace(hour=0, minute=0))
    out = score(scorer, tx(at, 220), hist)
    assert out["passenger_fare_anomaly"]["period"] == "night"
    assert out["model_flag"] is False, out["risk_score"]
    assert out["rules"]["night_behaviour_anomalous"] is False
    a = assess_ride_payment("p1", "d9", 220, [_row(h) for h in hist], ENFORCE, at=at, idempotency_key="k")
    assert a.backend_action == "proceed", a.reasons


def test_night_fare_ten_times_night_norm_flagged(scorer):
    at = datetime(2026, 10, 14, 23, 20, tzinfo=IST)
    hist = night_history(60, at.replace(hour=0, minute=0))
    out = score(scorer, tx(at, 2200), hist)
    assert out["model_flag"] is True, out["risk_score"]


def test_night_alone_never_triggers_for_day_passenger_normal_fare(scorer):
    """A first night ride at a normal fare: the model may score it higher, but must not cross the OTP threshold."""
    at = datetime(2026, 10, 14, 22, 30, tzinfo=IST)
    hist = day_history(40, at.replace(hour=0, minute=0))
    out = score(scorer, tx(at, 150), hist)
    assert out["model_flag"] is False, out["risk_score"]


# ── 4. Fare anomalies, familiar driver ───────────────────────────────────────

FAMILIAR = {}


def test_day_passenger_paying_5000_flagged(scorer):
    hist = day_history(25, NOW.replace(hour=0, minute=0))
    out = score(scorer, tx(NOW, 5000, driver="stranger"), hist)
    FAMILIAR["unfamiliar"] = out["risk_score"]
    assert out["model_flag"] is True, out["risk_score"]


def test_familiar_driver_does_not_suppress_anomaly(scorer):
    drivers = ["fam"] * 20 + [f"o{i}" for i in range(5)]
    hist = day_history(25, NOW.replace(hour=0, minute=0), drivers=drivers)
    out = score(scorer, tx(NOW, 5000, driver="fam"), hist)
    FAMILIAR["familiar"] = out["risk_score"]
    print(f"\n[SYNTHETIC] Rs5000 risk_score: familiar driver (20 rides) = {out['risk_score']}, "
          f"threshold = {scorer.threshold:.4f}")
    assert out["model_flag"] is True, out["risk_score"]
    assert out["risk_score"] >= scorer.threshold


# ── 5. Progressive learning and profile activation ───────────────────────────

@pytest.mark.parametrize("ride_no,stage", [(1, "none"), (2, "insufficient"), (20, "insufficient"), (99, "developing"),
                                           (100, "developing"), (101, "personal")])
def test_profile_activation(scorer, ride_no, stage):
    prior = ride_no - 1
    hist = day_history(prior, NOW.replace(hour=0, minute=0))
    # failed attempts interleaved: must not count
    hist += [ride(NOW - timedelta(hours=3, minutes=i), 150, status="failed", key=f"fx{i}") for i in range(5)]
    out = score(scorer, tx(NOW, 150), hist)
    assert out["history"]["prior_completed_rides"] == prior
    assert out["passenger_fare_anomaly"]["history_stage"] == stage
    assert (stage == "personal") == (prior >= 100)


def test_detection_from_first_transaction(scorer):
    out = score(scorer, tx(NOW, 150), [])
    assert out["risk_score"] is not None
    out = score(scorer, tx(NOW, 5000), [])
    assert out["model_flag"] is True, out["risk_score"]


def test_duplicates_do_not_inflate_count(scorer):
    hist = day_history(99, NOW.replace(hour=0, minute=0))
    dup = dict(hist[-1], timestamp=(datetime.fromisoformat(hist[-1]["timestamp"]) + timedelta(seconds=1)).isoformat())
    failed = [ride(NOW - timedelta(hours=5, minutes=i), 150, status="failed", key=f"ff{i}") for i in range(3)]
    failed_dup = [dict(failed[0])]  # the same failed attempt recorded twice (same idempotency key)
    out = score(scorer, tx(NOW, 150), hist + [dup] + failed + failed_dup)
    assert out["history"]["prior_completed_rides"] == 99
    assert out["passenger_fare_anomaly"]["history_stage"] == "developing"
    assert "duplicate_history_rows_ignored" in out["warnings"]


# ── 6. Invalid inputs are never low risk ─────────────────────────────────────

BAD = {
    "amount_zero": lambda h: (tx(NOW, 0), h),
    "amount_negative": lambda h: (tx(NOW, -50), h),
    "amount_nan": lambda h: (tx(NOW, math.nan), h),
    "amount_none": lambda h: (tx(NOW, None), h),
    "amount_string": lambda h: (tx(NOW, "abc"), h),
    "amount_huge": lambda h: (tx(NOW, 1e9), h),
    "naive_timestamp": lambda h: (tx(NOW.replace(tzinfo=None), 150), h),
    "missing_driver": lambda h: (tx(NOW, 150, driver=None), h),
    "history_at_tx_time": lambda h: (tx(NOW, 150), h + [ride(NOW, 140, key="same-time")]),
    "history_after_tx": lambda h: (tx(NOW, 150), h + [ride(NOW + timedelta(minutes=1), 140, key="future")]),
}


@pytest.mark.parametrize("case", sorted(BAD))
def test_invalid_inputs_never_low_risk(scorer, case):
    t, hist = BAD[case](day_history(30, NOW.replace(hour=0, minute=0)))
    out = scorer.score_safe(t, hist)
    assert out["scoring_status"] != "scored"
    assert out["risk_score"] is None and out["model_flag"] is None
    assert out["risk_tier"] != "low"


def test_numeric_string_amount_is_rejected(scorer):
    """Requirement: a string amount is invalid input. The scorer float()-coerces numeric strings."""
    out = scorer.score_safe(tx(NOW, "150"), day_history(30, NOW.replace(hour=0, minute=0)))
    if out["scoring_status"] == "scored":
        pytest.xfail("DEFECT (vendored scorer, read-only): _amount() accepts numeric strings like '150'. "
                     "The backend gate always passes Decimal, so this is not reachable from the routes.")


@pytest.mark.parametrize("amount", [0, -50, None, 1e9, pytest.param("abc", marks=pytest.mark.xfail(
    raises=ValueError, strict=True,
    reason="DEFECT (vendored service.py, read-only): _audit() calls float(amount) and raises ValueError for a "
           "non-numeric string, breaking the 'never raises' contract. app/services/fraud_gate.py catches it and "
           "treats it as an ML failure (OTP in enforce mode)."))])
def test_invalid_inputs_enforce_requires_otp(amount):
    for cfg, action in ((ENFORCE, "step_up_otp"), (SHADOW, "proceed_unchanged")):
        a = assess_ride_payment("p1", "d9", amount, [], cfg, at=NOW, idempotency_key="k")
        assert a.status != "scored"
        assert a.backend_action == action
        assert (a.risk or {}).get("risk_score") is None


def test_missing_driver_enforce_requires_otp():
    a = assess_ride_payment("p1", None, 150, [], ENFORCE, at=NOW, idempotency_key="k")
    assert a.status == "invalid_input" and a.backend_action == "step_up_otp"


def test_history_after_transaction_enforce_requires_otp():
    rows = [_row(ride(NOW + timedelta(seconds=5), 150, key="skew"))]
    a = assess_ride_payment("p1", "d9", 150, rows, ENFORCE, at=NOW, idempotency_key="k")
    assert a.status == "invalid_input" and a.backend_action == "step_up_otp"


def _row(h):
    """Scorer-format history dict -> backend Transaction-like dict (naive UTC created_at)."""
    ts = datetime.fromisoformat(h["timestamp"]).astimezone(UTC).replace(tzinfo=None)
    return {"passenger_id": "p1", "driver_id": h["driver_id"], "amount": h["amount"], "payment_method": h["payment_method"],
            "status": h["status"], "transaction_type": "ride_payment", "idempotency_key": h["idempotency_key"],
            "created_at": ts}


# ── night traveller: 30 night rides at the normal fare, paying at 23:00 IST ──

def _thirty_night_rides(end):
    """30 completed night rides (22:30-23:50 IST, one per day) at fares 190-210."""
    out = []
    for i in range(30):
        d = (end - timedelta(days=30 - i)).replace(hour=22 + (i % 2), minute=30 + (i % 3) * 10)
        out.append(ride(d, 190 + (i * 7) % 21, driver=f"d{i % 4}", key=f"nt{i}"))
    return out


def test_regular_night_traveller_normal_fare_at_2300_not_flagged(scorer):
    at = datetime(2026, 10, 14, 23, 0, tzinfo=IST)
    hist = _thirty_night_rides(at.replace(hour=0, minute=0))
    out = score(scorer, tx(at, 200), hist)
    assert out["passenger_fare_anomaly"]["period"] == "night"
    assert out["model_flag"] is False, out["risk_score"]
    assert out["rules"]["night_behaviour_anomalous"] is False
    a = assess_ride_payment("p1", "d9", 200, [_row(h) for h in hist], ENFORCE, at=at, idempotency_key="k")
    assert a.backend_action == "proceed", a.reasons
    print(f"\n[SYNTHETIC] night traveller, normal fare: risk_score={out['risk_score']} threshold={scorer.threshold:.4f}")


def test_regular_night_traveller_10x_fare_at_2300_flagged(scorer):
    at = datetime(2026, 10, 14, 23, 0, tzinfo=IST)
    hist = _thirty_night_rides(at.replace(hour=0, minute=0))
    out = score(scorer, tx(at, 2000), hist)
    assert out["model_flag"] is True, out["risk_score"]
    a = assess_ride_payment("p1", "d9", 2000, [_row(h) for h in hist], ENFORCE, at=at, idempotency_key="k")
    assert a.backend_action == "step_up_otp" and "model_flag" in a.reasons
