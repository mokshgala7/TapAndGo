"""
lifecycle_probe.py  –  Measure the passenger-learning lifecycle and day/night personalisation of the FROZEN V6 model
(read-only: no retraining, threshold unchanged). Synthetic in-memory passengers only.
    cd experiments/passenger_fraud_v6 && PYTHONDONTWRITEBYTECODE=1 python3 reports/final_freeze/lifecycle_probe.py
Writes reports/final_freeze/lifecycle_probe.json
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V6 = HERE.parents[1]
sys.path.insert(0, str(V6))

import numpy as np  # noqa: E402
import xgboost as xgb  # noqa: E402

from integration.inference import FraudScorerV6  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
T = datetime(2026, 9, 1, 9, 0, tzinfo=IST)


def hist(n, day_fare=100.0, night_fare=None, night_every=0, seed=0, failed_every=0, start_days=200):
    """n COMPLETED rides (plus optional failed rides). Every `night_every`-th ride is at 23:xx with `night_fare`."""
    r = np.random.default_rng(seed); out = []
    for i in range(n):
        ts = (T - timedelta(days=start_days)) + timedelta(days=i * (start_days - 2) / max(n, 1))
        night = night_every and i % night_every == 0
        ts = ts.replace(hour=23 if night else (9 if i % 2 else 18), minute=int(r.integers(0, 50)), second=0)
        fare = (night_fare if night else day_fare) * float(np.exp(r.normal(0, 0.10)))
        out.append({"timestamp": ts.isoformat(), "amount": round(fare), "driver_id": ("D1", "D2")[i % 2],
                    "payment_method": "QR", "vehicle_type": "auto_rickshaw", "status": "completed"})
        if failed_every and i % failed_every == 0:
            out.append({**out[-1], "timestamp": (ts + timedelta(minutes=3)).isoformat(), "status": "failed"})
    return sorted(out, key=lambda x: x["timestamp"])


def tx(amount, hour=12, driver="D1"):
    return {"timestamp": (T + timedelta(days=1)).replace(hour=hour, minute=7).isoformat(), "amount": amount, "driver_id": driver,
            "payment_method": "QR", "vehicle_type": "auto_rickshaw"}


def main() -> None:
    s = FraudScorerV6.load()
    booster = s.model.get_booster()

    def contrib(t, h):
        f = s.features(t, h)[s.feature_names]
        c = booster.predict(xgb.DMatrix(f.to_numpy(float), feature_names=s.feature_names), pred_contribs=True)[0]
        return dict(zip(s.feature_names, c[:-1].round(5).tolist()))

    def summary(t, h):
        r = s.score(t, h)
        return {"score": r["risk_score"], "flag": r["model_flag"], "level": r["passenger_fare_anomaly"]["level"],
                "z": r["passenger_fare_anomaly"]["z"], "typical": r["passenger_fare_anomaly"]["typical_fare_inr"],
                "stage": r["passenger_fare_anomaly"]["history_stage"], "basis": r["passenger_fare_anomaly"]["basis"],
                "n_prior": r["history"]["prior_completed_rides"], "rules": {k: (v["triggered"] if isinstance(v, dict) else v) for k, v in r["rules"].items()},
                "action": r["recommended_action"]}
    out = {"threshold": s.threshold}
    # 1. lifecycle across history lengths
    out["lifecycle"] = {}
    for n in (0, 1, 5, 19, 20, 50, 98, 99, 100, 101, 150, 300):
        h = hist(n) if n else []
        row = {f: summary(tx(f), h) for f in (100, 200, 300, 500)}
        f = s.features(tx(300), h).iloc[0]
        row["profile_active_input"] = int(f["profile_active"]); row["history_uncertainty"] = float(f["history_uncertainty"])
        row["profile_active_contribution_logodds_at_300"] = contrib(tx(300), h)["profile_active"]
        out["lifecycle"][n] = row
    # global importance of profile_active in the frozen model
    gain = booster.get_score(importance_type="total_gain"); tot = sum(gain.values())
    idx = s.feature_names.index("profile_active")
    out["profile_active_total_gain_share"] = gain.get(f"f{idx}", gain.get("profile_active", 0.0)) / tot
    out["profile_active_used_in_any_split"] = (f"f{idx}" in gain) or ("profile_active" in gain)
    # 2. eligible counting
    out["counting"] = {"99_completed_plus_failed": summary(tx(300), hist(99, failed_every=10)),
                       "100_completed_plus_failed": summary(tx(300), hist(100, failed_every=10))}
    h99 = hist(99); dup = dict(h99[-1]); dup["timestamp"] = (datetime.fromisoformat(h99[-1]["timestamp"]) + timedelta(hours=1)).isoformat()
    h99k = [dict(x, idempotency_key=f"K{i}") for i, x in enumerate(h99)]
    dupk = dict(h99k[-1]); dupk["timestamp"] = dup["timestamp"]
    out["counting"]["99_plus_same_key_duplicate_row"] = summary(tx(300), h99k + [dupk])
    try:
        s.score(tx(300), h99 + [dict(h99[-1])])
        out["counting"]["99_plus_identical_duplicate_row"] = "scored"
    except Exception as e:  # noqa: BLE001
        out["counting"]["99_plus_identical_duplicate_row"] = f"{type(e).__name__}: {e}"
    # 3. personal typical fare
    out["typical_fare"] = {"pax_typical_100_charged_250": summary(tx(250), hist(150, 100)),
                           "pax_typical_250_charged_250": summary(tx(250), hist(150, 250))}
    # 4. day/night personal profiles (night rides every 3rd ride => ~33% night share)
    nh_hi, nh_same, day_only = hist(150, 100, night_fare=200, night_every=3), hist(150, 100, night_fare=100, night_every=3), hist(150, 100)
    out["day_night"] = {
        "night_200_pax_night_typical_200": summary(tx(200, hour=23), nh_hi),
        "night_200_pax_night_typical_100": summary(tx(200, hour=23), nh_same),
        "night_400_pax_night_typical_200": summary(tx(400, hour=23), nh_hi),
        "night_100_day_only_pax": summary(tx(100, hour=23), day_only),
        "night_100_night_traveller": summary(tx(100, hour=23), nh_same),
        "day_100_day_only_pax": summary(tx(100, hour=13), day_only),
        "day_250_day_only_pax": summary(tx(250, hour=13), day_only),
        "contrib_night_200_typical_200": {k: v for k, v in contrib(tx(200, hour=23), nh_hi).items() if abs(v) > 0.05},
        "contrib_night_200_typical_100": {k: v for k, v in contrib(tx(200, hour=23), nh_same).items() if abs(v) > 0.05}}
    # 5. personalisation strengthening: day-only passenger at 02:07, ₹100, as history grows
    out["night_personalisation_by_n"] = {}
    for n in (0, 5, 19, 20, 50, 99, 100, 150):
        h = hist(n) if n else []
        f = s.features(tx(100, hour=2), h).iloc[0]
        r = s.score(tx(100, hour=2), h)
        out["night_personalisation_by_n"][n] = {"night_share_s": round(float(f["night_share_s"]), 4), "night_rarity": round(float(f["night_rarity"]), 4),
                                                "score": r["risk_score"], "night_rule": r["rules"]["night_behaviour_anomalous"]}
    (HERE / "lifecycle_probe.json").write_text(json.dumps(out, indent=1, default=str))
    print("lifecycle (n: stage, profile_active, contrib, scores 100/200/300/500, flags)")
    for n, row in out["lifecycle"].items():
        print(f"  n={n:>3} {row[100]['stage']:12s} pa={row['profile_active_input']} c={row['profile_active_contribution_logodds_at_300']:+.4f} "
              f"scores={[row[f]['score'] for f in (100, 200, 300, 500)]} flags={[row[f]['flag'] for f in (100, 200, 300, 500)]} "
              f"levels={[row[f]['level'] for f in (100, 200, 300, 500)]}")
    print("profile_active gain share", out["profile_active_total_gain_share"], "used:", out["profile_active_used_in_any_split"])
    for k, v in out["counting"].items():
        print(" ", k, v if isinstance(v, str) else (v["n_prior"], v["stage"], v["score"]))
    for sect in ("typical_fare", "day_night"):
        for k, v in out[sect].items():
            print(" ", k, v if k.startswith("contrib") else (v["score"], v["flag"], v["level"], v["typical"], v["rules"]))
    print("night personalisation by n:", out["night_personalisation_by_n"])


if __name__ == "__main__":
    main()
