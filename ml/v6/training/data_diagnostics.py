"""Pre-training shortcut diagnostics (pre-registration §5) on D6_dev OPEN rows (never the sealed file), compared
with the same statistics on V4's D4_dev open rows. Writes evaluation/data_diagnostics.json.
    PYTHONDONTWRITEBYTECODE=1 python3 training/data_diagnostics.py"""
import json, sys
from pathlib import Path
sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent
import numpy as np, pandas as pd

def stats(op):
    op = op.assign(_t=pd.to_datetime(op.timestamp, format="ISO8601", utc=True)).sort_values("_t", kind="mergesort")
    seen, fam, med, ratio = set(), [], {}, []
    hist = {}
    for r in op[["passenger_id", "driver_id", "status", "amount"]].itertuples(index=False):
        fam.append((r.passenger_id, r.driver_id) in seen)
        h = hist.get(r.passenger_id, [])
        ratio.append(r.amount / np.median(h) if len(h) >= 5 else np.nan)
        if r.status == "completed":
            seen.add((r.passenger_id, r.driver_id)); h.append(r.amount); hist[r.passenger_id] = h
    op["fam"], op["ratio"] = fam, ratio
    fr, lg = op[op.fraud_label == 1], op[op.fraud_label == 0]
    hi = op.ratio >= 2
    out = {"fraud_share_by_driver_type": fr.driver_type.value_counts(normalize=True).round(4).to_dict(),
           "legit_share_by_driver_type": lg.driver_type.value_counts(normalize=True).round(4).to_dict(),
           "familiar_share": {"fraud": round(float(fr.fam.mean()), 4), "legit": round(float(lg.fam.mean()), 4)},
           "fraud_rate_ge2x_familiar": round(float(op[hi & op.fam].fraud_label.mean()), 4),
           "fraud_rate_ge2x_unfamiliar": round(float(op[hi & ~op.fam].fraud_label.mean()), 4),
           "n_ge2x_familiar": int((hi & op.fam).sum()), "n_ge2x_unfamiliar": int((hi & ~op.fam).sum()),
           "fraud_by_scenario": fr.scenario.value_counts().to_dict(), "prevalence": round(float(op.fraud_label.mean()), 4)}
    worst = max(out["fraud_share_by_driver_type"], key=lambda t: out["fraud_share_by_driver_type"][t] / max(out["legit_share_by_driver_type"].get(t, 1e-9), 1e-9))
    out["shortcut_gate"] = {"worst_type": worst, "fraud_share": out["fraud_share_by_driver_type"][worst],
                            "legit_share": out["legit_share_by_driver_type"].get(worst, 0.0),
                            "violates_(>40% fraud and <10% legit)": bool(out["fraud_share_by_driver_type"][worst] > 0.40 and out["legit_share_by_driver_type"].get(worst, 0) < 0.10)}
    return out

res = {"D6_dev_open": stats(pd.read_csv(V6 / "data/synthetic/D6_dev/open_events.csv")),
       "D4_dev_open_reference": stats(pd.read_csv(V6.parent / "passenger_fraud_v4/data/synthetic/D4_dev/open_events.csv"))}
(V6 / "evaluation").mkdir(exist_ok=True)
(V6 / "evaluation/data_diagnostics.json").write_text(json.dumps(res, indent=1, default=int))
for k, v in res.items():
    print(k, {kk: v[kk] for kk in ("fraud_share_by_driver_type", "legit_share_by_driver_type", "familiar_share", "fraud_rate_ge2x_familiar", "fraud_rate_ge2x_unfamiliar", "shortcut_gate", "prevalence")})
