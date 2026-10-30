"""Deterministic re-verification of the V5 audit's claims against the FROZEN V4 and V5 scorers (read-only).
Writes only passenger_fraud_v6/audit/v4_v5_verification.json.
    PYTHONDONTWRITEBYTECODE=1 python3 audit/scripts/verify_v4_v5_claims.py"""
import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parents[2]; V5 = V6.parent / "passenger_fraud_v5"; V4 = V6.parent / "passenger_fraud_v4"
sys.path.insert(0, str(V4)); sys.path.insert(0, str(V5))
import numpy as np
from v5.inference import FraudScorerV5
from integration.inference import FraudScorerV4

IST = timezone(timedelta(hours=5, minutes=30)); T = datetime(2026, 9, 1, 9, 0, tzinfo=IST)
s5, s4 = FraudScorerV5.load(), FraudScorerV4.load()
MK = {"vehicle_median_log_fare_7d": {"auto_rickshaw": 4.63, "taxi": 5.19, "all": 4.9}}

def hist(n, amount, hours, drivers=("D1", "D2"), sigma=0.12, seed=0):
    r = np.random.default_rng(seed); out = []
    for i in range(n):
        ts = (T - timedelta(days=90)) + timedelta(days=i * 90 / max(n, 1))
        ts = ts.replace(hour=int(hours[i % len(hours)]), minute=int(r.integers(0, 50)))
        out.append({"timestamp": ts.isoformat(), "amount": max(10, round(amount * float(np.exp(r.normal(0, sigma))))),
                    "driver_id": drivers[i % len(drivers)], "payment_method": "QR", "vehicle_type": "auto_rickshaw", "status": "completed"})
    return sorted(out, key=lambda x: x["timestamp"])

def dhist(n=150, seed=1):
    r = np.random.default_rng(seed); st = T - timedelta(hours=12 * n + 24)
    return [{"timestamp": (st + timedelta(hours=12 * i)).isoformat(), "amount": round(110 * float(np.exp(r.normal(0, .2)))),
             "passenger_key": f"P{int(r.integers(0, 40))}", "status": "completed", "passenger_fare_z": float(r.normal(0, .8)),
             "passenger_prior_rides": int(r.integers(5, 80)), "pair_prior_rides": int(r.integers(0, 5))} for i in range(n)]
DH = dhist(); DH4 = [{k: v for k, v in d.items() if k in ("timestamp", "amount", "passenger_key", "status")} for d in DH]
tx = lambda amount, hour=12, driver="D1", sec=None: {"timestamp": ((T + timedelta(days=1)).replace(hour=hour, minute=7) if sec is None else sec).isoformat(),
                                                     "amount": amount, "driver_id": driver, "payment_method": "QR", "vehicle_type": "auto_rickshaw"}
def both(t, ph):
    a, b = s5.score(t, ph, DH, MK), s4.score(t, ph, DH4)
    return {"v5": a["risk_score"], "v5_flag": a["model_flag"], "v4": b["risk_score"], "v4_flag": b["model_flag"],
            "v5_rule_keys": sorted(a["rules"]), "v4_rule_keys": sorted(b["rules"]), "v4_night_rule": b["rules"]["night_behaviour_anomalous"],
            "v4_amount_rule": b["rules"]["amount_anomalous"], "rapid_v5": a["rules"]["rapid_repeat_10min"]["triggered"],
            "rapid_v4": b["rules"]["rapid_repeat_10min"]["triggered"]}
out = {"thresholds": {"v5": s5.threshold, "v4": s4.threshold}}
day, night = hist(80, 100, (8, 9, 17, 18)), hist(80, 100, (22, 23, 1, 2))
out["fare_familiar"] = {f: both(tx(f, driver="D1"), day) for f in (100, 200, 300, 500)}
out["fare_unfamiliar"] = {f: both(tx(f, driver="NEW"), day) for f in (100, 200, 300, 500)}
out["day_night_0200"] = {"day_commuter": both(tx(100, hour=2), day), "night_traveller": both(tx(100, hour=2), night)}
out["cold_start_x3"] = {n: both(tx(300), hist(n, 100, (9, 18)) if n else []) for n in (0, 1, 5, 19, 50, 150)}
D = T + timedelta(days=1)
base = day + [{"timestamp": D.isoformat(), "amount": 100, "driver_id": "D1", "payment_method": "QR", "vehicle_type": "auto_rickshaw", "status": "completed"}]
out["ten_minute"] = {g: both(tx(100, driver="D2", sec=D + timedelta(seconds=g)), base) for g in (599, 600, 601)}
fail = base + [{"timestamp": (D + timedelta(minutes=8)).isoformat(), "amount": 100, "driver_id": "D1", "payment_method": "QR",
                "vehicle_type": "auto_rickshaw", "status": "failed"}]
out["failed_ride_reference_13min"] = both(tx(100, driver="D2", sec=D + timedelta(minutes=13)), fail)
e5 = s5.score_safe({"timestamp": "2026-09-02 09:00:00", "amount": 100, "driver_id": "D1"}, day, DH, MK)
e4 = s4.score_safe({"timestamp": "2026-09-02 09:00:00", "amount": 100, "driver_id": "D1"}, day, DH4)
out["naive_timestamp"] = {"v5": {k: e5[k] for k in ("scoring_status", "risk_score", "recommended_action")},
                          "v4": {k: e4[k] for k in ("scoring_status", "risk_score", "recommended_action")}}
(V6 / "audit" / "v4_v5_verification.json").write_text(json.dumps(out, indent=1, default=str))
for k in ("fare_familiar", "fare_unfamiliar", "day_night_0200", "cold_start_x3", "ten_minute"):
    print(k, {kk: (round(v["v5"], 3), v["v5_flag"], round(v["v4"], 3), v["v4_flag"]) + ((v["rapid_v5"], v["rapid_v4"]) if k == "ten_minute" else (v["v4_night_rule"],) if k.startswith("day") else ()) for kk, v in out[k].items()})
print("failed ref", out["failed_ride_reference_13min"]["rapid_v5"], out["failed_ride_reference_13min"]["rapid_v4"], "| rule keys v5", out["fare_familiar"][100]["v5_rule_keys"], "v4", out["fare_familiar"][100]["v4_rule_keys"])
print("naive ts", out["naive_timestamp"])
