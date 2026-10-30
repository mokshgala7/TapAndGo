"""Latency of FraudScorerV6.score() with real histories and interface-vs-batch score parity on 300 T3 rides.
    PYTHONDONTWRITEBYTECODE=1 python3 training/benchmark_inference.py      -> evaluation/inference_benchmark.json"""
import json, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(V6))
import joblib, numpy as np, pandas as pd
from integration.inference import FraudScorerV6

sc = FraudScorerV6.load()
ev = pd.read_csv(V6 / "data/synthetic/D6_fresh/events.csv"); ev["tt"] = pd.to_datetime(ev.timestamp, format="ISO8601", utc=True)
fs = joblib.load(V6 / "artifacts/cache/final_scores.joblib")["T3_fresh"]; batch = dict(zip(fs["frame"].event_id, fs["s6"]))
sample = ev[ev.tt > ev.tt.min() + pd.Timedelta(days=60)].sample(300, random_state=7)
nn = lambda v: None if pd.isna(v) else v
lat, diffs, nph = [], [], []
for r in sample.itertuples():
    ph = [{"timestamp": h.timestamp, "amount": h.amount, "driver_id": h.driver_id, "payment_method": nn(h.payment_method),
           "vehicle_type": nn(h.vehicle_type), "status": h.status} for h in ev[(ev.passenger_id == r.passenger_id) & (ev.tt < r.tt)].itertuples()]
    t = {"timestamp": r.timestamp, "amount": r.amount, "driver_id": r.driver_id, "payment_method": nn(r.payment_method), "vehicle_type": nn(r.vehicle_type)}
    t0 = time.perf_counter(); out = sc.score(t, ph); lat.append((time.perf_counter() - t0) * 1000)
    diffs.append(abs(out["risk_score"] - round(float(batch[r.event_id]), 6))); nph.append(len(ph))
res = {"rides": len(lat), "latency_ms": {"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95)), "max": float(max(lat))},
       "median_passenger_history": float(np.median(nph)), "max_abs_diff_rounded6": float(max(diffs)),
       "mismatches_gt_1e-6": int(sum(d > 1e-6 for d in diffs))}
(V6 / "evaluation/inference_benchmark.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res))
