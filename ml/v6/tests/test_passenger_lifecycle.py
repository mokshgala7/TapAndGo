"""Passenger-learning lifecycle and day/night personalisation on the FROZEN V6 bundle (final requirements verification).

Shared model + passenger-specific personalisation: history statistics shrink toward train-population priors (k = 5)
from the first ride, and the personal profile is activated at exactly 100 eligible (completed, de-duplicated) rides.
No per-passenger model is trained."""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from conftest import V6
from integration.inference import DEFAULT_BUNDLE

IST = timezone(timedelta(hours=5, minutes=30))
T = datetime(2026, 9, 1, 9, 0, tzinfo=IST)


def hist(n, day_fare=100.0, night_fare=None, night_every=0, seed=0, failed_every=0):
    r = np.random.default_rng(seed); out = []
    for i in range(n):
        ts = (T - timedelta(days=200)) + timedelta(days=i * 198 / max(n, 1))
        night = night_every and i % night_every == 0
        ts = ts.replace(hour=23 if night else (9 if i % 2 else 18), minute=int(r.integers(0, 50)), second=0)
        fare = (night_fare if night else day_fare) * float(np.exp(r.normal(0, 0.10)))
        out.append({"timestamp": ts.isoformat(), "amount": round(fare), "driver_id": ("D1", "D2")[i % 2],
                    "payment_method": "QR", "vehicle_type": "auto_rickshaw", "status": "completed", "idempotency_key": f"K{i}"})
        if failed_every and i % failed_every == 0:
            out.append({**out[-1], "timestamp": (ts + timedelta(minutes=3)).isoformat(), "status": "failed",
                        "idempotency_key": f"F{i}"})
    return sorted(out, key=lambda x: x["timestamp"])


def tx(amount, hour=12, minute=7, driver="D1"):
    return {"timestamp": (T + timedelta(days=1)).replace(hour=hour, minute=minute).isoformat(), "amount": amount,
            "driver_id": driver, "payment_method": "QR", "vehicle_type": "auto_rickshaw"}


# ── 99 / 100 / 101 transition and eligible counting ──
@pytest.mark.parametrize("n,stage,active", [(0, "none", 0), (1, "insufficient", 0), (19, "insufficient", 0),
                                            (20, "developing", 0), (99, "developing", 0), (100, "personal", 1),
                                            (101, "personal", 1)])
def test_profile_activation_exactly_at_100(scorer, n, stage, active):
    h = hist(n)
    r = scorer.score(tx(300), h)
    assert r["history"]["prior_completed_rides"] == n
    assert r["passenger_fare_anomaly"]["history_stage"] == stage
    assert int(scorer.features(tx(300), h).iloc[0]["profile_active"]) == active


def test_activation_changes_the_model_score(scorer):
    """At 100 the shared model's input profile_active flips; the frozen model's output responds to it."""
    f = scorer.features(tx(300), hist(100))[scorer.feature_names]
    off = f.copy(); off["profile_active"] = 0
    p_on, p_off = scorer.model.predict_proba(f.to_numpy(float))[0, 1], scorer.model.predict_proba(off.to_numpy(float))[0, 1]
    assert p_on != p_off
    s99, s100 = scorer.score(tx(300), hist(99))["risk_score"], scorer.score(tx(300), hist(100))["risk_score"]
    assert s99 != s100


def test_failed_rides_do_not_count(scorer):
    h = hist(99, failed_every=10)
    assert sum(x["status"] == "failed" for x in h) == 10
    r = scorer.score(tx(300), h)
    assert r["history"]["prior_completed_rides"] == 99 and r["passenger_fare_anomaly"]["history_stage"] == "developing"


def test_duplicate_history_rows_do_not_count(scorer):
    h = hist(99)
    dup = {**h[-1], "timestamp": (datetime.fromisoformat(h[-1]["timestamp"]) + timedelta(hours=1)).isoformat()}  # same key
    r = scorer.score(tx(300), h + [dup])
    assert r["history"]["prior_completed_rides"] == 99 and r["passenger_fare_anomaly"]["history_stage"] == "developing"
    assert "duplicate_history_rows_ignored" in r["warnings"]
    assert r["risk_score"] == scorer.score(tx(300), h)["risk_score"]


def test_identical_duplicate_row_without_key_is_refused_safely(scorer):
    h = [{k: v for k, v in x.items() if k != "idempotency_key"} for x in hist(99)]
    r = scorer.score_safe(tx(300), h + [dict(h[-1])])
    assert r["scoring_status"] == "invalid_input" and r["risk_score"] is None and r["recommended_action"] == "apply_fallback_policy"


def test_identical_duplicate_row_with_key_counts_once(scorer):
    h = hist(99)
    r = scorer.score(tx(300), h + [dict(h[-1])])
    assert r["history"]["prior_completed_rides"] == 99 and "duplicate_history_rows_ignored" in r["warnings"]


# ── new passengers: shared patterns + limited personal history ──
def test_new_passenger_uses_shared_population_baseline(scorer):
    r = scorer.score(tx(500), [])
    assert r["passenger_fare_anomaly"]["basis"] == "population_prior"
    assert r["passenger_fare_anomaly"]["typical_fare_inr"] == pytest.approx(math.exp(scorer.P3.med_log["all"]), abs=0.01)
    assert r["model_flag"] is True and r["passenger_fare_anomaly"]["level"] in ("elevated", "high")
    assert scorer.score(tx(100), [])["model_flag"] is False


def test_personal_history_blends_in_from_the_first_rides(scorer):
    pop = math.exp(scorer.P3.med_log["all"])
    typ = {n: scorer.score(tx(250), hist(n, day_fare=250.0))["passenger_fare_anomaly"]["typical_fare_inr"] for n in (0, 1, 5, 20, 99)}
    assert typ[0] == pytest.approx(pop, abs=0.01)
    assert abs(typ[1] - 250) < abs(typ[0] - 250) and abs(typ[5] - 250) < abs(typ[1] - 250) and abs(typ[99] - 250) < 15


def test_missing_history_is_not_treated_as_safe(scorer):
    """Less personal history may never lower risk (monotone in history_uncertainty / log1p_n_prior)."""
    for c, sign in (("history_uncertainty", 1), ("history_insufficient", 1), ("no_history", 1), ("log1p_n_prior", -1)):
        assert scorer.model.get_params()["monotone_constraints"][scorer.feature_names.index(c)] == sign


# ── personal typical fare and day/night profiles influence the score ──
def test_personal_typical_fare_changes_the_assessment(scorer):
    low, high = scorer.score(tx(250), hist(150, 100.0)), scorer.score(tx(250), hist(150, 250.0))
    assert low["model_flag"] and low["passenger_fare_anomaly"]["level"] == "high"
    assert not high["model_flag"] and high["passenger_fare_anomaly"]["level"] == "none"


def test_day_ordinary_not_flagged_and_day_expensive_assessed(scorer):
    h = hist(150)
    assert scorer.score(tx(100, hour=13), h)["model_flag"] is False
    r = scorer.score(tx(250, hour=13), h)
    assert r["model_flag"] is True and r["rules"]["amount_anomalous"] is True


def test_night_traveller_not_flagged_for_riding_at_night(scorer):
    trav, day_only = hist(150, 100.0, night_fare=100.0, night_every=3), hist(150)
    rt, rd = scorer.score(tx(100, hour=23), trav), scorer.score(tx(100, hour=23), day_only)
    assert rt["model_flag"] is False and rt["rules"]["night_behaviour_anomalous"] is False
    assert rd["rules"]["night_behaviour_anomalous"] is True           # unusual night ride is reported for the day passenger
    assert rd["model_flag"] is False and rd["recommended_action"] == "no_additional_verification"   # rule flag != OTP


def test_expensive_night_fare_assessed_against_night_profile(scorer):
    pricier_nights = hist(150, 100.0, night_fare=200.0, night_every=3)
    same_nights = hist(150, 100.0, night_fare=100.0, night_every=3)
    a = scorer.score(tx(200, hour=23), pricier_nights)
    b = scorer.score(tx(200, hour=23), same_nights)
    c = scorer.score(tx(400, hour=23), pricier_nights)
    assert a["risk_score"] < b["risk_score"]       # ₹200 is more usual at night for this passenger
    assert c["risk_score"] > a["risk_score"] and c["model_flag"]
    assert scorer.features(tx(200, hour=23), pricier_nights).iloc[0]["night_amount_high"] == 0.0


def test_night_profile_evolves_with_history(scorer):
    shares = [scorer.features(tx(100, hour=2), hist(n) if n else []).iloc[0]["night_share_s"] for n in (0, 5, 20, 100)]
    assert shares[0] > shares[1] > shares[2] > shares[3]             # population prior -> personal (day-only) share
    rule = {n: scorer.score(tx(100, hour=2), hist(n))["rules"]["night_behaviour_anomalous"] for n in (19, 20)}
    assert rule == {19: False, 20: True}


@pytest.mark.parametrize("hh,mm,night", [(5, 59, True), (6, 0, False), (21, 59, False), (22, 0, True)])
def test_day_night_boundaries(scorer, hh, mm, night):
    assert bool(scorer.features(tx(100, hour=hh, minute=mm), hist(30)).iloc[0]["is_night"]) is night


# ── artifact integrity and determinism ──
def test_frozen_bundle_unchanged_since_final_freeze():
    man = json.loads((V6 / "reports/final_freeze/PROTECTED_ARTIFACT_MANIFEST.json").read_text())
    want = man["artifacts"]["experiments/passenger_fraud_v6/artifacts/passenger_fraud_v6_bundle.joblib"]["sha256"]
    assert hashlib.sha256(DEFAULT_BUNDLE.read_bytes()).hexdigest() == want


def test_lifecycle_scoring_deterministic(scorer):
    h = hist(100)
    assert len({scorer.score(tx(300), h)["risk_score"] for _ in range(5)}) == 1
