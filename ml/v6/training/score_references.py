"""
score_references.py  –  Score the FROZEN V4 and V5 models (read-only, their own code) on V6 evaluation rows and on
the G1/G3/G4 deterministic fixtures, so V6 can be compared on identical inputs. Runs in its own process because
V4/V5 and V6 use the same package names. Never writes outside passenger_fraud_v6/.
    PYTHONDONTWRITEBYTECODE=1 python3 training/score_references.py
Writes artifacts/cache/reference_scores.joblib and evaluation/reference_probes.json
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent
V5, V4 = V6.parent / "passenger_fraud_v5", V6.parent / "passenger_fraud_v4"
sys.path[:0] = [str(V4), str(V5)]

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from features import v3_features as F3  # noqa: E402   (V4 package)
from features.feature_builder import FEATURE_SETS as V4_SETS, DriverPriors  # noqa: E402
from integration.inference import FraudScorerV4  # noqa: E402
from v5 import features_v5 as F5  # noqa: E402
from v5.inference import FraudScorerV5  # noqa: E402
from v5.matrix import build_full_matrix  # noqa: E402

SYN = V6 / "data" / "synthetic"
IST = timezone(timedelta(hours=5, minutes=30)); T = datetime(2026, 9, 1, 9, 0, tzinfo=IST)


def sets():
    dev = pd.concat([pd.read_csv(SYN / "D6_dev/open_events.csv"), pd.read_csv(SYN / "D6_dev/sealed_events.csv")], ignore_index=True)
    led = pd.read_csv(SYN / "D6_dev/driver_ledger.csv")
    out = {"validation": (dev, dev.split.isin(["validation_temporal", "validation_unseen"]), led),
           "T1_temporal": (dev, dev.split.eq("test_temporal"), led), "T2_unseen": (dev, dev.split.eq("test_unseen"), led)}
    for u, name in (("D6_fresh", "T3_fresh"), ("D6_shift", "T4_shift"), ("D6_scenario", "T5_scenario")):
        out[name] = (pd.read_csv(SYN / u / "events.csv"), None, pd.read_csv(SYN / u / "driver_ledger.csv"))
    return out


# deterministic fixtures, identical to training/gates.py (duplicated: this process cannot import V6 packages)
def profile(n=80, median=100.0, hours=(8, 9, 17, 18), sigma=0.12, seed=0, drivers=("D1", "D2")):
    r = np.random.default_rng(seed); out = []
    for i in range(n):
        ts = (T - timedelta(days=90)) + timedelta(days=i * 90 / max(n, 1))
        ts = ts.replace(hour=int(hours[i % len(hours)]), minute=int(r.integers(0, 50)), second=0)
        out.append({"timestamp": ts.isoformat(), "amount": max(10.0, round(median * float(np.exp(r.normal(0, sigma))))),
                    "driver_id": drivers[i % len(drivers)], "payment_method": "QR", "vehicle_type": "auto_rickshaw", "status": "completed"})
    return sorted(out, key=lambda x: x["timestamp"])


def tx(amount, driver="D1", hour=12):
    return {"timestamp": (T + timedelta(days=1)).replace(hour=hour, minute=7).isoformat(), "amount": amount, "driver_id": driver,
            "payment_method": "QR", "vehicle_type": "auto_rickshaw"}


def driver_hist(n=150, seed=1):
    r = np.random.default_rng(seed); st = T - timedelta(hours=12 * n + 24)
    return [{"timestamp": (st + timedelta(hours=12 * i)).isoformat(), "amount": round(110 * float(np.exp(r.normal(0, .2)))),
             "passenger_key": f"P{int(r.integers(0, 40))}", "status": "completed", "passenger_fare_z": float(r.normal(0, .8)),
             "passenger_prior_rides": int(r.integers(5, 80)), "pair_prior_rides": int(r.integers(0, 5))} for i in range(n)]


def probes(s4, s5):
    DH = driver_hist(); DH4 = [{k: v for k, v in d.items() if k in ("timestamp", "amount", "passenger_key", "status")} for d in DH]
    MK = {"vehicle_median_log_fare_7d": {"auto_rickshaw": 4.63, "taxi": 5.19, "all": 4.9}}
    both = lambda t, h: {"v4": (s4.score(t, h, DH4)["risk_score"], s4.score(t, h, DH4)["model_flag"]),   # noqa: E731
                         "v5": (s5.score(t, h, DH, MK)["risk_score"], s5.score(t, h, DH, MK)["model_flag"])}
    out = {"G1": {}, "G3": {}, "G4": {}}
    for med in (60.0, 100.0, 250.0):
        h = profile(median=med)
        for drv in ("D1", "NEW"):
            out["G1"][f"M{int(med)}_{drv}"] = {m: both(tx(med * m, drv), h) for m in (1, 2, 3, 5)}
    day, night = profile(), profile(hours=(22, 23, 1, 2))
    out["G3"] = {"commuter_0200": both(tx(100, hour=2), day), "traveller_0200": both(tx(100, hour=2), night),
                 "commuter_1300": both(tx(100, hour=13), day), "traveller_1300": both(tx(100, hour=13), night)}
    for n in (0, 1, 5, 19, 50, 150):
        h = profile(n=n) if n else []
        out["G4"][f"n{n}"] = {"100": both(tx(100), h), "500": both(tx(500), h)}

    def g1_pass(who):
        ok = True
        for k, v in out["G1"].items():
            sc = [v[m][who][0] for m in (1, 2, 3, 5)]; fl = [v[m][who][1] for m in (1, 2, 3, 5)]
            ok &= all(a <= b + 1e-12 for a, b in zip(sc, sc[1:])) and fl[2] and fl[3] and not fl[0]
        return bool(ok)

    def g4_pass(who):
        return bool(all(v["500"][who][1] and not v["100"][who][1] for k, v in out["G4"].items() if k != "n0")
                    and not out["G4"]["n0"]["100"][who][1])
    out["summary"] = {w: {"G1_fare_anomaly": g1_pass(w), "G4b_cold_start": g4_pass(w)} for w in ("v4", "v5")}
    return out


def main() -> None:
    s4, s5 = FraudScorerV4.load(), FraudScorerV5.load()
    m5 = s5.meta
    P3 = F3.Priors(**m5["priors_v4"]["passenger"]); PD = DriverPriors(**m5["priors_v4"]["driver"]); P5 = F5.V5Priors(**m5["priors_v5"])
    cols4, cols5 = V4_SETS[s4.meta["feature_set"]], s5.feature_names
    res = {}
    for name, (ev, mask, led) in sets().items():
        fr = build_full_matrix(ev, mask, led, P3, PD, P5, report_source=ev)
        res[name] = {"event_id": fr.event_id.to_numpy(), "s4": s4.model.predict_proba(fr[cols4].to_numpy(float))[:, 1],
                     "s5": s5.model.predict_proba(fr[cols5].to_numpy(float))[:, 1]}
        print(f"  references scored on {name}: {len(fr)} rows", flush=True)
    joblib.dump({"thresholds": {"v4": s4.threshold, "v5": s5.threshold}, "sets": res}, V6 / "artifacts/cache/reference_scores.joblib")
    pr = probes(s4, s5)
    (V6 / "evaluation/reference_probes.json").write_text(json.dumps(pr, indent=1, default=str))
    print(json.dumps(pr["summary"]))


if __name__ == "__main__":
    main()
