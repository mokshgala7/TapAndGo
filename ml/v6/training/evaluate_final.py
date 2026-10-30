"""
evaluate_final.py  –  Final evaluation of the FROZEN V6 bundle (pre-registration §8–§10) against frozen V4 and V5
on identical rows. Order: verify bundle hash → generate post-freeze universes (refuses if present) → score references
(separate process) → read sealed D6_dev tests → evaluate. Nothing changes the model or threshold.
    PYTHONDONTWRITEBYTECODE=1 python3 training/evaluate_final.py [--reuse-post-freeze]
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V6))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from features import v3_features as F3  # noqa: E402
from features.feature_builder import X, build_matrix  # noqa: E402
from training.metrics import (AP_IMPL, binary_metrics, cluster_bootstrap, paired_bootstrap_ap,  # noqa: E402
                              precision_at_alert_rate, recall_at_fpr, threshold_at_fpr, wilson)

SYN, EVAL, ART, CACHE = V6 / "data/synthetic", V6 / "evaluation", V6 / "artifacts", V6 / "artifacts/cache"
CM = EVAL / "confusion_matrices"
POST = ("D6_fresh", "D6_shift", "D6_scenario")
FPR_POINTS = (0.005, 0.01, 0.02, 0.05, 0.10)
KEYS = ["n", "fraud_cases", "legit_cases", "prevalence", "precision", "recall", "f1", "fpr", "specificity", "roc_auc",
        "pr_auc", "tp", "fp", "tn", "fn", "flagged", "flagged_pct"]
DAY_ARCH = ["commuter_auto", "commuter_taxi", "occasional", "student_budget"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sl(y, flag, mask):
    m = np.asarray(mask, bool); yy, ff = y[m], np.asarray(flag)[m]
    tp, fp = int((ff & (yy == 1)).sum()), int((ff & (yy == 0)).sum())
    return {"rows": int(m.sum()), "fraud": int(yy.sum()), "legit": int((1 - yy).sum()), "tp": tp, "fp": fp,
            "recall": tp / yy.sum() if yy.sum() else None, "recall_wilson95": wilson(tp, int(yy.sum())),
            "fpr": fp / (1 - yy).sum() if (1 - yy).sum() else None, "fpr_wilson95": wilson(fp, int((1 - yy).sum()))}


def familiar(events, ids):
    ev = events.assign(_t=pd.to_datetime(events.timestamp, format="ISO8601", utc=True)).sort_values("_t", kind="mergesort")
    seen, fam = set(), {}
    for r in ev[["event_id", "passenger_id", "driver_id", "status"]].itertuples(index=False):
        fam[r.event_id] = (r.passenger_id, r.driver_id) in seen
        if r.status == "completed":
            seen.add((r.passenger_id, r.driver_id))
    return np.array([fam[i] for i in ids])


def subgroups(fr, flag):
    y, sc = fr.fraud_label.to_numpy(), fr.scenario
    out = {"by_scenario": {s: sl(y, flag, sc == s) for s in sorted(sc.unique())},
           "by_history_bucket": {b: sl(y, flag, fr.history_bucket == b) for b in ["0", "1-4", "5-19", "20-99", "100+"]},
           "by_daypart": {d: sl(y, flag, fr.daypart == d) for d in ("day", "night")},
           "familiar_driver": sl(y, flag, fr._familiar), "unfamiliar_driver": sl(y, flag, ~fr._familiar)}
    for s in ("passenger_amount_anomaly", "driver_overcharge"):
        out[f"{s}_familiar"] = sl(y, flag, (sc == s) & fr._familiar)
        out[f"{s}_unfamiliar"] = sl(y, flag, (sc == s) & ~fr._familiar)
    out["legit_expensive_long_or_airport"] = sl(y, flag, sc.isin(["legit_long", "legit_airport"]))
    if "archetype" in fr:
        out["night_rides_night_shift_passengers"] = sl(y, flag, (fr.archetype == "night_shift") & (fr.daypart == "night"))
        out["night_rides_day_oriented_passengers"] = sl(y, flag, fr.archetype.isin(DAY_ARCH) & (fr.daypart == "night"))
    return out


def crit(ok, support_ok=True, value_ok=True):
    if not value_ok:
        return "NOT EVALUABLE"
    if not support_ok:
        return "INCONCLUSIVE"
    return "PASS" if ok else "FAIL"


def main() -> None:
    CM.mkdir(parents=True, exist_ok=True)
    sel = json.loads((EVAL / "selection.json").read_text())
    bpath = ART / "passenger_fraud_v6_bundle.joblib"
    if sha(bpath) != sel["bundle_sha256"]:
        sys.exit("[eval] bundle differs from frozen selection.json")
    b = joblib.load(bpath); meta, model = b["metadata"], b["model"]
    thr, cols, policy = meta["decision_threshold"], meta["feature_names"], meta["policy"]["step_up_rules"]
    P3 = F3.Priors(**meta["priors"])
    frozen_ts = pd.Timestamp(sel["frozen_at_utc"]).timestamp()
    env = {"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"}
    if "--reuse-post-freeze" in sys.argv:
        for u in POST:
            man = json.loads((SYN / u / "dataset_manifest.json").read_text())
            assert (SYN / u / "events.csv").stat().st_mtime > frozen_ts, f"{u} predates the freeze"
            for fn, h in man["files"].items():
                assert sha(SYN / u / fn) == h, f"{u}/{fn} changed since generation"
    else:
        for u in POST:
            if (SYN / u).exists():
                sys.exit(f"[eval] {u} exists before this evaluation; post-freeze guarantee broken")
        subprocess.run([sys.executable, str(V6 / "data/build_datasets.py"), "--stage", "post_freeze"], check=True, env=env)
        subprocess.run([sys.executable, str(V6 / "training/score_references.py")], check=True, env=env)
    ref = joblib.load(CACHE / "reference_scores.joblib")
    thr4, thr5 = ref["thresholds"]["v4"], ref["thresholds"]["v5"]

    dev = pd.concat([pd.read_csv(SYN / "D6_dev/open_events.csv"), pd.read_csv(SYN / "D6_dev/sealed_events.csv")], ignore_index=True)
    specs = {"validation": (dev, dev.split.isin(["validation_temporal", "validation_unseen"])),
             "T1_temporal": (dev, dev.split.eq("test_temporal")), "T2_unseen": (dev, dev.split.eq("test_unseen"))}
    for u, name in zip(POST, ("T3_fresh", "T4_shift", "T5_scenario")):
        ev = pd.read_csv(SYN / u / "events.csv"); specs[name] = (ev, None)
    sets, s6 = {}, {}
    for name, (ev, mask) in specs.items():
        t0 = time.perf_counter()
        fr = build_matrix(ev, mask, P3)
        fr["_familiar"] = familiar(ev, fr.event_id.to_numpy())
        r = ref["sets"][name]
        pos = pd.Series(np.arange(len(r["event_id"])), index=r["event_id"]).loc[fr.event_id].to_numpy()
        fr["_s4"], fr["_s5"] = r["s4"][pos], r["s5"][pos]
        sets[name] = fr; s6[name] = model.predict_proba(X(fr, cols))[:, 1]
        print(f"  built {name}: {len(fr)} rows, {int(fr.fraud_label.sum())} fraud ({time.perf_counter() - t0:.0f}s)", flush=True)

    y_va, s_va = sets["validation"].fraud_label.to_numpy(), s6["validation"]
    thr_rows = []
    for p in FPR_POINTS:
        t = threshold_at_fpr(y_va, s_va, p)
        for name, fr in sets.items():
            y = fr.fraud_label.to_numpy(); m = binary_metrics(y, s6[name] >= t, s6[name], t)
            thr_rows.append({"set": name, "validation_fpr_cap": p, "threshold": t, "pre_registered": p == 0.02,
                             "fraud_detected": m["tp"], "fraud_missed": m["fn"], "legit_challenged": m["fp"],
                             "otp_challenges_per_10k_rides": 1e4 * m["flagged"] / m["n"],
                             **{k: m[k] for k in ("precision", "recall", "fpr", "f1")}})
    pd.DataFrame(thr_rows).to_csv(EVAL / "threshold_analysis.csv", index=False)

    res = {"selected": meta["selected_candidate"], "threshold": thr, "v4_threshold": thr4, "v5_threshold": thr5,
           "step_up_policy_rules": policy, "ap_implementation": AP_IMPL, "note": "ALL RESULTS ARE ON SYNTHETIC DATA", "sets": {}}
    comp = []
    for name, fr in sets.items():
        y, g = fr.fraud_label.to_numpy(), fr.passenger_id.to_numpy()
        f6, f4, f5 = s6[name] >= thr, fr._s4.to_numpy() >= thr4, fr._s5.to_numpy() >= thr5
        rapid = fr.is_within_10_minutes.to_numpy().astype(bool)
        pol = f6 | (rapid if "rapid_repeat_10min" in policy else False)
        r = {"rows": int(len(fr)), "fraud": int(y.sum()), "prevalence": float(y.mean()),
             "status": "selection data" if name == "validation" else "sealed (read after freeze)" if name.startswith(("T1", "T2"))
             else "generated after freeze",
             "v6": binary_metrics(y, f6, s6[name], thr), "v6_policy_model_or_10min": binary_metrics(y, pol),
             "v4": binary_metrics(y, f4, fr._s4.to_numpy(), thr4), "v5": binary_metrics(y, f5, fr._s5.to_numpy(), thr5)}
        if name != "validation":
            r["v6_cluster_bootstrap95"] = cluster_bootstrap(y, s6[name], thr, g, n_boot=500, seed=1)
            r["paired_ap_v6_minus_v4"] = paired_bootstrap_ap(y, s6[name], fr._s4.to_numpy(), g, n_boot=500, seed=2)
            r["paired_ap_v6_minus_v5"] = paired_bootstrap_ap(y, s6[name], fr._s5.to_numpy(), g, n_boot=500, seed=3)
        r["v6_recall_at_fpr"] = {p: recall_at_fpr(y, s6[name], p) for p in FPR_POINTS}
        r["v6_precision_at_alert_rate"] = [precision_at_alert_rate(y, s6[name], a) for a in (0.01, 0.02, 0.05)]
        r["subgroups"] = {"v6": subgroups(fr, f6), "v4": subgroups(fr, f4), "v5": subgroups(fr, f5)}
        rules = {"rapid_repeat_10min": rapid, "amount_anomalous": fr.is_amount_anomalous_v6.to_numpy().astype(bool),
                 "night_behaviour_anomalous": fr.is_night_behaviour_anomalous.to_numpy().astype(bool)}
        r["rules"] = {}
        for rk, rf in rules.items():
            comb = binary_metrics(y, f6 | rf); etp, efp = comb["tp"] - r["v6"]["tp"], comb["fp"] - r["v6"]["fp"]
            r["rules"][rk] = {"rule_alone": {k: binary_metrics(y, rf)[k] for k in ("tp", "fp", "precision", "recall", "fpr")},
                              "model_or_rule": {k: comb[k] for k in ("tp", "fp", "precision", "recall", "fpr")},
                              "extra_fraud_caught": etp, "extra_legit_challenged": efp,
                              "legit_challenges_per_extra_fraud": (efp / etp) if etp else None}
        res["sets"][name] = r
        for label, m in (("v6_selected", r["v6"]), ("v6_policy_model_or_10min", r["v6_policy_model_or_10min"]),
                         ("v4_frozen", r["v4"]), ("v5_frozen", r["v5"])):
            comp.append({"set": name, "model": label, **{k: m.get(k) for k in KEYS}})
        for label, m in (("v6", r["v6"]), ("v4", r["v4"]), ("v5", r["v5"])):
            pd.DataFrame([[m["tn"], m["fp"]], [m["fn"], m["tp"]]], index=["actual_legit", "actual_fraud"],
                         columns=["pred_legit", "pred_fraud"]).to_csv(CM / f"{name}__{label}.csv")
        line = f"  {name:12s} V6 AP {r['v6']['pr_auc']:.4f} P {r['v6']['precision']:.3f} R {r['v6']['recall']:.3f} FPR {r['v6']['fpr']:.4f}"
        line += f" | V4 AP {r['v4']['pr_auc']:.4f} R {r['v4']['recall']:.3f} | V5 AP {r['v5']['pr_auc']:.4f} R {r['v5']['recall']:.3f}"
        print(line, flush=True)

    # ── acceptance criteria (§9) ──
    gates = json.loads((EVAL / "gate_results.json").read_text())[meta["selected_candidate"]]
    probes = json.loads((EVAL / "reference_probes.json").read_text())
    t5, t3 = res["sets"]["T5_scenario"]["subgroups"], res["sets"]["T3_fresh"]
    fam_rows = lambda who: [t5[who][f"{s}_familiar"] for s in ("passenger_amount_anomaly", "driver_overcharge")]   # noqa: E731
    rec = {w: sum(x["tp"] for x in fam_rows(w)) / max(1, sum(x["fraud"] for x in fam_rows(w))) for w in ("v6", "v4", "v5")}
    n_fam = sum(x["fraud"] for x in fam_rows("v6"))
    fpr6, fpr4 = t3["v6"]["fpr"], t3["v4"]["fpr"]
    la = t3["subgroups"]["v6"]["by_scenario"].get("legit_airport", {}); oc = t3["subgroups"]["v6"]["by_scenario"].get("driver_overcharge", {})
    acc = {
        "AC-G_all_mandatory_gates (candidate stage; re-run on frozen bundle by tests)": {
            "value": {k: v["pass"] for k, v in gates.items()}, "status": crit(all(v["pass"] for v in gates.values()))},
        "AC-GPS": {"value": gates["G7"]["detail"], "status": crit(gates["G7"]["pass"])},
        "AC-FA1_deterministic_fare_anomaly_probes": {"v6_G1": gates["G1"]["pass"], "v4": probes["summary"]["v4"], "v5": probes["summary"]["v5"],
                                                     "status": crit(gates["G1"]["pass"])},
        "AC-FA2_familiar_driver_fare_anomaly_recall_T5": {"v6": rec["v6"], "v4": rec["v4"], "v5": rec["v5"], "support": n_fam,
                                                          "status": crit(rec["v6"] > rec["v4"] and rec["v6"] > rec["v5"], n_fam >= 100)},
        "AC-FP_T3_legit_FPR": {"v6": fpr6, "v4": fpr4, "limit": "<= 2.5% and <= V4 + 0.5pp",
                               "status": crit(fpr6 <= 0.025 and fpr6 <= fpr4 + 0.005)},
        "AC-REP / AC-PAR / AC-PROT": "evaluated by training/reproduce_check.py, training/benchmark_inference.py, tests and write_manifest.py"}
    hyp = {"H-AC1_validation_AP>=0.72": {"value": res["sets"]["validation"]["v6"]["pr_auc"],
                                         "status": crit(res["sets"]["validation"]["v6"]["pr_auc"] >= 0.72, res["sets"]["validation"]["fraud"] >= 300)},
           "H-AC2_T4_shift_AP>=0.55": {"value": res["sets"]["T4_shift"]["v6"]["pr_auc"],
                                       "status": crit(res["sets"]["T4_shift"]["v6"]["pr_auc"] >= 0.55, res["sets"]["T4_shift"]["fraud"] >= 300)},
           "H-AC3_T3_legit_airport_FPR<=10%": {"value": la.get("fpr"), "support": la.get("legit", 0),
                                              "status": crit((la.get("fpr") or 1) <= 0.10, la.get("legit", 0) >= 500, la.get("fpr") is not None)},
           "H-AC4_T3_overcharge_recall>=85%": {"value": oc.get("recall"), "support": oc.get("fraud", 0),
                                              "status": crit((oc.get("recall") or 0) >= 0.85, oc.get("fraud", 0) >= 100, oc.get("recall") is not None)}}
    f = res["sets"]["T3_fresh"]["v6"]
    res["acceptance_criteria"], res["hypotheses"] = acc, hyp
    res["failure_conditions"] = {"F1_no_eligible_candidate": False, "F2_T3_recall_lt_30pct_or_FPR_gt_3pct": bool(f["recall"] < 0.30 or f["fpr"] > 0.03)}
    pd.DataFrame(comp).to_csv(EVAL / "model_comparison.csv", index=False)
    (EVAL / "final_metrics.json").write_text(json.dumps(res, indent=1, default=float))
    summ = {k: {w: {m: res["sets"][k][w][m] for m in ("pr_auc", "roc_auc", "precision", "recall", "f1", "fpr", "flagged_pct", "tp", "fp", "fn", "tn")}
                for w in ("v6", "v4", "v5")} | {"v6_policy_model_or_10min": {m: res["sets"][k]["v6_policy_model_or_10min"][m] for m in ("precision", "recall", "fpr", "flagged_pct")}}
            for k in res["sets"]}
    (EVAL / "metrics_summary.json").write_text(json.dumps({"note": "SYNTHETIC", "threshold": thr, "sets": summ, "acceptance": acc, "hypotheses": hyp},
                                                         indent=1, default=float))
    keep = ["event_id", "passenger_id", "fraud_label", "scenario", "history_bucket", "daypart", "_familiar", "archetype",
            "driver_type", "trip_type", "anomaly_level", "is_within_10_minutes", "z_log", "log_ratio", "night_rarity",
            "driver_seen", "pair_fare_dev", "log1p_n_prior"]
    joblib.dump({k: {"frame": v[[c for c in keep if c in v]],
                     "s6": s6[k], "s4": v._s4.to_numpy(), "s5": v._s5.to_numpy()} for k, v in sets.items()}, CACHE / "final_scores.joblib")
    print(json.dumps(acc, indent=1, default=str)[:3000]); print(json.dumps(hyp, indent=1, default=str))


if __name__ == "__main__":
    main()
