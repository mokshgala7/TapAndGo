"""
verify_metrics.py  –  Cross-check the reported V6 metrics against the SAVED artifacts (no re-scoring, no retraining).

Sources: evaluation/final_metrics.json, evaluation/confusion_matrices/*.csv, raw event files (row counts),
artifacts/cache/final_scores.joblib (recompute AP/confusion from stored scores as an independent check).
    cd experiments/passenger_fraud_v6 && PYTHONDONTWRITEBYTECODE=1 python3 reports/final_freeze/verify_metrics.py
Writes reports/final_freeze/VERIFIED_METRICS.json
"""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V6 = HERE.parents[1]

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402

REPORTED = {"T3_fresh": {"pr_auc": 0.440, "precision": 0.226, "recall": 0.491, "fpr": 0.0217,
                         "tp": 1493, "fp": 5127, "fn": 1547, "tn": 230623},
            "T4_shift": {"pr_auc": 0.199, "fpr": 0.0325}}
TOL = {"pr_auc": 0.0005, "precision": 0.0005, "recall": 0.0005, "fpr": 0.00005}
RAW = {"T3_fresh": "data/synthetic/D6_fresh/events.csv", "T4_shift": "data/synthetic/D6_shift/events.csv",
       "T5_scenario": "data/synthetic/D6_scenario/events.csv"}


def main() -> None:
    fm = json.loads((V6 / "evaluation/final_metrics.json").read_text())
    sc = joblib.load(V6 / "artifacts/cache/final_scores.joblib")
    thr = fm["threshold"]
    out = {"note": "ALL METRICS ARE ON SYNTHETIC DATA; no real-world fraud validation exists", "threshold": thr,
           "model": fm["selected"], "sets": {}, "discrepancies": []}
    for name, r in fm["sets"].items():
        v = r["v6"]
        cm = pd.read_csv(V6 / "evaluation/confusion_matrices" / f"{name}__v6.csv", index_col=0)
        tn, fp, fn, tp = int(cm.loc["actual_legit", "pred_legit"]), int(cm.loc["actual_legit", "pred_fraud"]), \
            int(cm.loc["actual_fraud", "pred_legit"]), int(cm.loc["actual_fraud", "pred_fraud"])
        y, s = sc[name]["frame"].fraud_label.to_numpy(), sc[name]["s6"]
        f = s >= thr
        rec = {"tp": int((f & (y == 1)).sum()), "fp": int((f & (y == 0)).sum()), "fn": int((~f & (y == 1)).sum()),
               "tn": int((~f & (y == 0)).sum()), "pr_auc": float(average_precision_score(y, s))}
        row = {"status": r["status"], "rows": r["rows"], "fraud": r["fraud"],
               "metrics": {k: v[k] for k in ("pr_auc", "roc_auc", "precision", "recall", "f1", "fpr", "specificity", "flagged_pct",
                                             "tp", "fp", "fn", "tn")},
               "confusion_csv": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
               "confusion_total_equals_rows": tp + fp + fn + tn == r["rows"],
               "json_equals_csv": (tp, fp, fn, tn) == (v["tp"], v["fp"], v["fn"], v["tn"]),
               "recomputed_from_stored_scores_equal": rec["tp"] == tp and rec["fp"] == fp and rec["fn"] == fn and rec["tn"] == tn
               and abs(rec["pr_auc"] - v["pr_auc"]) < 1e-12,
               "otp_challenges_per_10k_rides_model_only": round(1e4 * v["flagged_pct"], 1)}
        if "v6_cluster_bootstrap95" in r:
            row["bootstrap95"] = {k: r["v6_cluster_bootstrap95"][k] for k in ("precision", "recall", "pr_auc") if k in r["v6_cluster_bootstrap95"]}
        p = r["v6_policy_model_or_10min"]
        row["policy_model_or_10min"] = {k: p[k] for k in ("precision", "recall", "fpr", "flagged_pct", "tp", "fp")}
        if name in RAW:
            n_raw = sum(1 for _ in open(V6 / RAW[name])) - 1
            row["raw_event_rows"] = n_raw
            row["rows_equal_raw_file"] = n_raw == r["rows"]
        if name in REPORTED:
            chk = {}
            for k, want in REPORTED[name].items():
                got = v[k]
                ok = (got == want) if isinstance(want, int) else abs(got - want) <= TOL[k]
                chk[k] = {"reported": want, "verified": got, "match": bool(ok)}
                if not ok:
                    out["discrepancies"].append({"set": name, "metric": k, "reported": want, "verified": got})
            row["reported_vs_verified"] = chk
        out["sets"][name] = row
    out["acceptance_criteria"] = {k: (v["status"] if isinstance(v, dict) else v) for k, v in fm["acceptance_criteria"].items()}
    out["hypotheses"] = {k: {"value": v["value"], "status": v["status"]} for k, v in fm["hypotheses"].items()}
    t3 = fm["sets"]["T3_fresh"]
    out["comparison_T3_same_rows"] = {w: {k: t3[w][k] for k in ("pr_auc", "precision", "recall", "fpr")} for w in ("v6", "v4", "v5")}
    sg = t3["subgroups"]["v6"]
    out["T3_cost_of_expensive_legit_rides"] = {"legit_long_or_airport_fpr": sg["legit_expensive_long_or_airport"]["fpr"],
                                               "legit_long_or_airport_rows": sg["legit_expensive_long_or_airport"]["legit"],
                                               "legit_normal_fpr": sg["by_scenario"]["legit_normal"]["fpr"]}
    out["ten_minute_rule_T3"] = t3["rules"]["rapid_repeat_10min"]
    out["ten_minute_rule_validation"] = fm["sets"]["validation"]["rules"]["rapid_repeat_10min"]
    out["all_reported_values_verified"] = not out["discrepancies"]
    (HERE / "VERIFIED_METRICS.json").write_text(json.dumps(out, indent=1, default=float))
    for n in ("T3_fresh", "T4_shift"):
        r = out["sets"][n]
        print(n, "rows", r["rows"], "raw", r.get("raw_event_rows"), "| CM total ok", r["confusion_total_equals_rows"], "| json=csv", r["json_equals_csv"],
              "| recomputed ok", r["recomputed_from_stored_scores_equal"], "|", {k: (v["verified"], v["match"]) for k, v in r["reported_vs_verified"].items()})
    print("discrepancies:", out["discrepancies"]); print("all sets CM totals ok:", all(r["confusion_total_equals_rows"] and r["recomputed_from_stored_scores_equal"] for r in out["sets"].values()))
    print("10-min T3:", {k: out["ten_minute_rule_T3"][k] for k in ("extra_fraud_caught", "extra_legit_challenged", "legit_challenges_per_extra_fraud")},
          "| policy T3 flagged", out["sets"]["T3_fresh"]["policy_model_or_10min"]["flagged_pct"], "model-only", out["sets"]["T3_fresh"]["metrics"]["flagged_pct"])


if __name__ == "__main__":
    main()
