"""
gates.py  –  Mandatory requirement gates G1–G10 (audit/REQUIREMENT_TEST_SPECIFICATION.md).

`run_model_gates(scorer)` runs every gate that needs a fitted model (G1–G8) on deterministic in-memory fixtures;
`gate_causality` (G9) and `gate_parity` (G10) need data. Each gate returns {"pass": bool, "detail": ...}.
Fixtures never come from training data.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from features.feature_builder import FEATURE_SETS, LOCATION_TOKENS, PASSENGER_HISTORY_FEATURES, build_matrix, X

IST = timezone(timedelta(hours=5, minutes=30))
T = datetime(2026, 9, 1, 9, 0, tzinfo=IST)
DAY_H, NIGHT_H = (8, 9, 17, 18), (22, 23, 1, 2)


def profile(n=80, median=100.0, hours=DAY_H, sigma=0.12, seed=0, drivers=("D1", "D2")):
    r = np.random.default_rng(seed); out = []
    for i in range(n):
        ts = (T - timedelta(days=90)) + timedelta(days=i * 90 / max(n, 1))
        ts = ts.replace(hour=int(hours[i % len(hours)]), minute=int(r.integers(0, 50)), second=0)
        out.append({"timestamp": ts.isoformat(), "amount": max(10.0, round(median * float(np.exp(r.normal(0, sigma))))),
                    "driver_id": drivers[i % len(drivers)], "payment_method": "QR", "vehicle_type": "auto_rickshaw",
                    "status": "completed"})
    return sorted(out, key=lambda x: x["timestamp"])


def tx(amount, driver="D1", hour=12, minute=7, when=None, **extra):
    ts = when if when is not None else (T + timedelta(days=1)).replace(hour=hour, minute=minute)
    return {"timestamp": ts.isoformat(), "amount": amount, "driver_id": driver, "payment_method": "QR",
            "vehicle_type": "auto_rickshaw", **extra}


def _g(ok, detail):
    return {"pass": bool(ok), "detail": detail}


def gate_g1(s) -> dict:
    out, ok = {}, True
    for med in (60.0, 100.0, 250.0):
        h = profile(median=med)
        sig = {}
        for drv in ("D1", "NEW"):
            r = [s.score(tx(med * m, drv), h) for m in (1, 2, 3, 5)]
            sc = [x["risk_score"] for x in r]; fl = [x["model_flag"] for x in r]
            lv = [x["passenger_fare_anomaly"]["level"] for x in r]; z = [x["passenger_fare_anomaly"]["z"] for x in r]
            sig[drv] = (lv, z)
            checks = {"G1a_monotone": all(a <= b + 1e-12 for a, b in zip(sc, sc[1:])),
                      "G1b_levels": lv[0] == "none" and lv[1] in ("elevated", "high") and lv[2] == "high" and lv[3] == "high"
                      and all(a <= b for a, b in zip(z, z[1:])),
                      "G1c_flag_x3_x5": fl[2] and fl[3], "G1d_x1_not_flagged": not fl[0]}
            ok &= all(checks.values())
            out[f"M{int(med)}_{drv}"] = {"scores": sc, "flags": fl, "levels": lv, "checks": checks}
        same = sig["D1"] == sig["NEW"]
        out[f"M{int(med)}_G1e_signal_identical_familiar_vs_unfamiliar"] = same
        ok &= same
    return _g(ok, out)


def gate_g2(s) -> dict:
    var, stab = profile(sigma=0.45, seed=4), profile()
    rv, rs = s.score(tx(160), var), s.score(tx(160), stab)
    ok = rv["passenger_fare_anomaly"]["level"] != "high" and rv["risk_score"] <= rs["risk_score"] + 1e-12 and not rv["model_flag"]
    return _g(ok, {"variable": (rv["risk_score"], rv["model_flag"], rv["passenger_fare_anomaly"]["level"]),
                   "stable": (rs["risk_score"], rs["model_flag"], rs["passenger_fare_anomaly"]["level"])})


def gate_g3(s) -> dict:
    day, night = profile(hours=DAY_H), profile(hours=NIGHT_H)
    c2, n2 = s.score(tx(100, hour=2), day), s.score(tx(100, hour=2), night)
    c13, n13 = s.score(tx(100, hour=13), day), s.score(tx(100, hour=13), night)
    sparse = s.score(tx(100, hour=2), profile(n=5, hours=DAY_H))
    d = {"G3a": c2["rules"]["night_behaviour_anomalous"] and not n2["rules"]["night_behaviour_anomalous"]
         and not n2["model_flag"] and c2["risk_score"] >= n2["risk_score"] - 1e-12,
         "G3b": c2["risk_score"] >= c13["risk_score"] - 1e-12,
         "G3c": not n13["model_flag"],
         "G3d": sparse["scoring_status"] == "scored" and not sparse["rules"]["night_behaviour_anomalous"]
         and "passenger_history_insufficient_lt20" in sparse["warnings"]}
    # boundaries in IST, also expressed in UTC
    bnd = {}
    for hh, mm, want in ((5, 59, True), (6, 0, False), (21, 59, False), (22, 0, True)):
        when = (T + timedelta(days=1)).replace(hour=hh, minute=mm)
        for label, w in (("ist", when), ("utc", when.astimezone(timezone.utc))):
            f = s.features(tx(100, when=w), day).iloc[0]
            bnd[f"{hh:02d}:{mm:02d}_{label}"] = bool(f["is_night"]) == want
    d["G3e"] = all(bnd.values())
    naive = s.score_safe({"timestamp": "2026-09-02 09:00:00", "amount": 100, "driver_id": "D1"}, day)
    d["G3f"] = naive["scoring_status"] == "invalid_input" and naive["risk_score"] is None
    return _g(all(d.values()), {"checks": d, "boundaries": bnd,
                                "scores": {"commuter_0200": c2["risk_score"], "traveller_0200": n2["risk_score"],
                                           "commuter_1300": c13["risk_score"], "traveller_1300": n13["risk_score"]}})


def gate_g4(s) -> dict:
    d, detail = {}, {}
    r100, r300 = s.score(tx(100), []), s.score(tx(300), [])
    d["G4a"] = (r100["scoring_status"] == r300["scoring_status"] == "scored" and not r100["model_flag"]
                and r300["passenger_fare_anomaly"]["basis"] == "population_prior"
                and r300["passenger_fare_anomaly"]["history_stage"] == "none"
                and "new_passenger_no_completed_history" in r300["warnings"])
    detail["n0"] = {"100": (r100["risk_score"], r100["model_flag"]), "300": (r300["risk_score"], r300["model_flag"])}
    okb = True
    for n in (1, 5, 19, 50, 150):
        h = profile(n=n)
        a, b = s.score(tx(100), h), s.score(tx(500), h)
        detail[f"n{n}"] = {"100": (a["risk_score"], a["model_flag"]), "500": (b["risk_score"], b["model_flag"])}
        okb &= b["model_flag"] and not a["model_flag"] and b["risk_score"] >= a["risk_score"]
    d["G4b"] = okb
    stages = {n: s.score(tx(100), profile(n=n) if n else [])["passenger_fare_anomaly"]["history_stage"] for n in (0, 1, 19, 20, 99, 100)}
    d["G4c"] = stages == {0: "none", 1: "insufficient", 19: "insufficient", 20: "developing", 99: "developing", 100: "personal"}
    detail["stages"] = stages
    return _g(all(d.values()), {"checks": d, **detail})


def gate_g5(s) -> dict:
    D = T + timedelta(days=1)
    base = profile() + [{"timestamp": D.isoformat(), "amount": 100, "driver_id": "D1", "payment_method": "QR",
                         "vehicle_type": "auto_rickshaw", "status": "completed", "idempotency_key": "K-LAST"}]
    d = {}
    for g, want in ((599, True), (600, True), (601, False)):
        r = s.score(tx(100, "D2", when=D + timedelta(seconds=g)), base)["rules"]["rapid_repeat_10min"]
        d[f"G5a_{g}"] = r["triggered"] is want and r["elapsed_seconds"] == g
    fail = base + [{"timestamp": (D + timedelta(minutes=8)).isoformat(), "amount": 100, "driver_id": "D1",
                    "payment_method": "QR", "vehicle_type": "auto_rickshaw", "status": "failed"}]
    r = s.score(tx(100, "D2", when=D + timedelta(minutes=13)), fail)["rules"]["rapid_repeat_10min"]
    d["G5b"] = r["elapsed_seconds"] == 780 and not r["triggered"]
    dup = s.score_safe(tx(100, "D2", when=D + timedelta(minutes=30), idempotency_key="K-LAST"), base)
    d["G5c"] = dup["scoring_status"] == "duplicate_request" and dup["risk_score"] is None and dup["recommended_action"] == "apply_fallback_policy"
    same = s.score_safe(tx(100, "D1", when=D), base)
    d["G5d"] = same["scoring_status"] == "duplicate_request"
    ml = s.score(tx(100, "D1", when=D + timedelta(minutes=5)), base)
    d["G5e_multileg_rule_triggers_by_design"] = ml["rules"]["rapid_repeat_10min"]["triggered"]
    miss = s.score_safe({"amount": 100, "driver_id": "D1"}, base)
    d["G5f"] = miss["scoring_status"] == "invalid_input"
    return _g(all(d.values()), d)


def gate_g6(s) -> dict:
    h = profile()
    bad = [({**tx(100), "amount": 0}, h), ({**tx(100), "amount": float("nan")}, h), ({**tx(100), "amount": True}, h),
           ({**tx(100), "driver_id": None}, h), ({**tx(100), "timestamp": "garbage"}, h), (tx(100), "x"), (tx(100), None),
           (tx(100), h + [{**h[-1], "timestamp": (T + timedelta(days=5)).isoformat()}])]
    res = [s.score_safe(t, hh) for t, hh in bad]
    ok = all(r["risk_score"] is None and r["recommended_action"] == "apply_fallback_policy" and r["scoring_status"] != "scored" for r in res)

    class Boom:
        n_features_in_ = len(s.feature_names)

        def predict_proba(self, Xa):
            raise RuntimeError("boom")

    class NaN:
        n_features_in_ = len(s.feature_names)

        def predict_proba(self, Xa):
            return np.full((len(Xa), 2), np.nan)
    from integration.inference import FraudScorerV6
    for m in (Boom(), NaN()):
        b = FraudScorerV6({"model": m, "metadata": s.meta}).score_safe(tx(100), h)
        ok &= b["scoring_status"] == "prediction_error" and b["risk_score"] is None and b["recommended_action"] == "apply_fallback_policy"
    return _g(ok, {"statuses": [r["scoring_status"] for r in res]})


def gate_g7(s) -> dict:
    names_ok = not [c for c in s.feature_names if any(t in c.lower() for t in LOCATION_TOKENS)]
    refused = [s.score_safe({**tx(100), k: v}, profile())["scoring_status"] == "invalid_input"
               for k, v in (("latitude", 19.07), ("longitude", 72.87), ("gps", "19.0,72.8"), ("pickup_location", "x"),
                            ("distance_km", 12.0))]
    hist_refused = s.score_safe(tx(100), [{**profile()[0], "lat": 19.0}])["scoring_status"] == "invalid_input"
    return _g(names_ok and all(refused) and hist_refused, {"feature_names_clean": names_ok, "transaction_location_refused": refused,
                                                           "history_location_refused": hist_refused})


def gate_g8(s) -> dict:
    params = list(inspect.signature(s.score).parameters)
    ok = params == ["transaction", "passenger_history"] and set(s.feature_names) <= PASSENGER_HISTORY_FEATURES \
        and not [c for c in s.feature_names if c.startswith("pay_") or c.startswith("driver_n") or c.startswith("drv_")]
    return _g(ok, {"score_params": params, "n_features": len(s.feature_names)})


def run_model_gates(s) -> dict:
    res = {}
    for name, fn in (("G1", gate_g1), ("G2", gate_g2), ("G3", gate_g3), ("G4", gate_g4), ("G5", gate_g5), ("G6", gate_g6),
                     ("G7", gate_g7), ("G8", gate_g8)):
        try:
            res[name] = fn(s)
        except Exception as e:          # an exception is a failed gate, never a pass
            res[name] = _g(False, f"exception: {type(e).__name__}: {e}")
    return res


def gate_causality(events: pd.DataFrame, P3, n_pax: int = 200) -> dict:
    """G9: mutate every ride after a cut; earlier rows' features must not change."""
    pax = events.passenger_id.drop_duplicates().sample(n_pax, random_state=0)
    ev = events[events.passenger_id.isin(pax)].reset_index(drop=True)
    ts = pd.to_datetime(ev.timestamp, format="ISO8601", utc=True)
    cut = ts.sort_values().iloc[len(ts) // 2]
    later = ts > cut
    ev2 = ev.copy()
    ev2.loc[later, "amount"] = ev2.loc[later, "amount"] * 9 + 7
    ev2.loc[later, "driver_id"] = ev2.loc[later, "driver_id"].astype(str) + "-MUT"
    ev2.loc[later, "fraud_label"] = 1 - ev2.loc[later, "fraud_label"]
    early = pd.Series(~later.to_numpy(), index=ev.index)
    a, b = build_matrix(ev, early, P3), build_matrix(ev2, early, P3)
    cols = FEATURE_SETS["P6_fam"]
    changed = [c for c in cols if not np.allclose(a[c].to_numpy(float), b[c].to_numpy(float))]
    return _g(not changed and len(a) > 1000, {"rows_checked": int(len(a)), "changed": changed})


def gate_parity(s, events: pd.DataFrame, matrix: pd.DataFrame, n: int = 25, seed: int = 4) -> dict:
    """G10: interface features == batch features on random validation rides."""
    ev = events.assign(tt=pd.to_datetime(events.timestamp, format="ISO8601", utc=True))
    mat = matrix.set_index("event_id")
    nn = lambda v: None if pd.isna(v) else v          # noqa: E731
    worst = 0.0
    for r in ev[ev.split.astype(str).str.startswith("validation")].sample(n, random_state=seed).itertuples():
        ph = [{"timestamp": h.timestamp, "amount": h.amount, "driver_id": h.driver_id, "payment_method": nn(h.payment_method),
               "vehicle_type": nn(h.vehicle_type), "status": h.status}
              for h in ev[(ev.passenger_id == r.passenger_id) & (ev.tt < r.tt)].itertuples()]
        t = {"timestamp": r.timestamp, "amount": r.amount, "driver_id": r.driver_id,
             "payment_method": nn(r.payment_method), "vehicle_type": nn(r.vehicle_type)}
        f = s.features(t, ph).iloc[0]
        worst = max(worst, float(np.abs(f[s.feature_names].to_numpy(float) - X(mat.loc[[r.event_id]], s.feature_names)[0]).max()))
    return _g(worst <= 1e-9, {"rows": n, "max_abs_diff": worst})
