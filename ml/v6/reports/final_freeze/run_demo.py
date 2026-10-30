"""
run_demo.py  –  Offline demonstration of the frozen V6 reference candidate (synthetic inputs only).

Uses the existing interface `integration/inference.py` (FraudScorerV6) unchanged. No database, network, backend, real
customer data or GPS. It illustrates documented BEHAVIOUR; it does not prove real-world fraud-detection effectiveness.
    cd experiments/passenger_fraud_v6 && PYTHONDONTWRITEBYTECODE=1 python3 reports/final_freeze/run_demo.py
Writes reports/final_freeze/demo_output.json and prints a table.
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

from integration.inference import FraudScorerV6  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 9, 1, 9, 0, tzinfo=IST)          # fictional demo date


def history(n=80, typical=100.0, hours=(8, 9, 17, 18), seed=0):
    """A fictional passenger's earlier completed rides: drivers DRV-A / DRV-B alternate (so DRV-A is familiar)."""
    r = np.random.default_rng(seed); rows = []
    for i in range(n):
        ts = (NOW - timedelta(days=90)) + timedelta(days=i * 90 / n)
        ts = ts.replace(hour=hours[i % len(hours)], minute=int(r.integers(0, 50)), second=0)
        rows.append({"timestamp": ts.isoformat(), "amount": round(typical * float(np.exp(r.normal(0, 0.12)))),
                     "driver_id": ("DRV-A", "DRV-B")[i % 2], "payment_method": "QR", "vehicle_type": "auto_rickshaw",
                     "status": "completed"})
    return rows


def ride(amount, driver="DRV-A", hour=12, minute=7, at=None, **extra):
    ts = at or (NOW + timedelta(days=1)).replace(hour=hour, minute=minute)
    return {"timestamp": ts.isoformat(), "amount": amount, "driver_id": driver, "payment_method": "QR",
            "vehicle_type": "auto_rickshaw", **extra}


def main() -> None:
    s = FraudScorerV6.load()
    day, night = history(), history(hours=(22, 23, 1, 2))
    last = (NOW + timedelta(days=1)).replace(hour=10, minute=0)
    with_last = day + [{"timestamp": last.isoformat(), "amount": 100, "driver_id": "DRV-A", "payment_method": "QR",
                        "vehicle_type": "auto_rickshaw", "status": "completed", "idempotency_key": "REQ-1"}]
    cases = [
        ("1 normal fare (₹100, usual ~₹100, familiar driver)", ride(100), day),
        ("2 unusually high fare ₹500, unfamiliar driver", ride(500, "DRV-NEW"), day),
        ("3 same ₹500 anomaly, FAMILIAR driver", ride(500, "DRV-A"), day),
        ("3b familiar driver ₹200 / ₹300 (monotone)", ride(200, "DRV-A"), day),
        ("3c", ride(300, "DRV-A"), day),
        ("4 new passenger, no history, ₹100", ride(100), []),
        ("4b new passenger, no history, ₹300", ride(300), []),
        ("5 unusual night ride 02:07 (day commuter)", ride(100, hour=2), day),
        ("5b same 02:07 ride (habitual night traveller)", ride(100, hour=2), night),
        ("6 repeat +599 s", ride(100, "DRV-B", at=last + timedelta(seconds=599)), with_last),
        ("6b repeat +600 s", ride(100, "DRV-B", at=last + timedelta(seconds=600)), with_last),
        ("6c repeat +601 s", ride(100, "DRV-B", at=last + timedelta(seconds=601)), with_last),
        ("7 invalid: timestamp without timezone", {"timestamp": "2026-09-02 12:07:00", "amount": 100, "driver_id": "DRV-A"}, day),
        ("7b invalid: negative amount", ride(-50), day),
        ("7c refused: location field supplied", ride(100, latitude=19.07), day),
        ("7d duplicate request (same idempotency_key)", ride(100, "DRV-B", at=last + timedelta(minutes=30), idempotency_key="REQ-1"), with_last),
    ]
    out = {"model_version": s.model_version, "threshold": s.threshold, "policy": s.policy,
           "disclaimer": "Synthetic demonstration inputs; illustrates behaviour only; not evidence of real-world performance.",
           "cases": []}
    print(f"V6 {s.model_version}  threshold {s.threshold:.6f}  step-up rules {s.policy['step_up_rules']}\n")
    print(f"{'case':52s} {'status':17s} {'score':>7s} {'flag':5s} {'anomaly':9s} {'stage':12s} {'10min':5s} {'amt':5s} {'night':5s} action")
    for name, t, h in cases:
        r = s.score_safe(t, h)
        fa, ru = r.get("passenger_fare_anomaly") or {}, r.get("rules") or {}
        rec = {"case": name, "scoring_status": r["scoring_status"], "risk_score": r["risk_score"], "model_flag": r["model_flag"],
               "passenger_fare_anomaly": fa or None,
               "rules": ({"rapid_repeat_10min": ru["rapid_repeat_10min"]["triggered"],
                          "elapsed_seconds": ru["rapid_repeat_10min"]["elapsed_seconds"],
                          "amount_anomalous": ru["amount_anomalous"], "night_behaviour_anomalous": ru["night_behaviour_anomalous"]} if ru else None),
               "recommended_action": r["recommended_action"], "warnings": r.get("warnings"), "error": r.get("error")}
        out["cases"].append(rec)
        sc = "-" if r["risk_score"] is None else f"{r['risk_score']:.3f}"
        rr = rec["rules"] or {}
        print(f"{name:52s} {r['scoring_status']:17s} {sc:>7s} {str(r['model_flag']):5s} {fa.get('level', '-'):9s} "
              f"{fa.get('history_stage', '-'):12s} {str(rr.get('rapid_repeat_10min', '-')):5s} {str(rr.get('amount_anomalous', '-')):5s} "
              f"{str(rr.get('night_behaviour_anomalous', '-')):5s} {r['recommended_action']}")
    (HERE / "demo_output.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("\nSynthetic inputs only; this shows behaviour, not real-world fraud-detection performance.")


if __name__ == "__main__":
    main()
