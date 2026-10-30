"""
train_candidates.py  –  Build feature matrices, train the five pre-registered candidates (§6), compute each
candidate's validation threshold, and run Stage-A requirement gates on every candidate (§7).

Reads only D6_dev open rows, D6_valshift and D6_dr1/2. Never reads sealed_events.csv or post-freeze data.
    PYTHONDONTWRITEBYTECODE=1 python3 training/train_candidates.py
Writes artifacts/cache/*.pkl, artifacts/candidate_models/*.joblib, evaluation/{candidates.csv, gate_results.json,
validation_scores.pkl, hp_search.csv}
"""

import io
import json
import sys
import time
from itertools import product
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V6))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import ExtraTreesClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402

from data.universes import dr_configs  # noqa: E402
from features import v3_features as F3  # noqa: E402
from features.feature_builder import FEATURE_SETS, X, build_matrix, monotone_vector  # noqa: E402
from integration.inference import FraudScorerV6  # noqa: E402
from training.gates import gate_causality, gate_parity, run_model_gates  # noqa: E402
from training.metrics import binary_metrics, recall_at_fpr, threshold_at_fpr  # noqa: E402

SEED = 42
SYN, CACHE, CAND, EVAL = V6 / "data/synthetic", V6 / "artifacts/cache", V6 / "artifacts/candidate_models", V6 / "evaluation"
INNER_SPLIT = pd.Timestamp("2026-06-01T00:00:00+05:30")
CANDIDATES = {   # id: (family, feature set, grid)
    "C0_lr_transparent": ("logistic_regression", "C0_transparent", {"C": [0.1, 1.0]}),
    "C1_lr_P6": ("logistic_regression", "P6", {"C": [0.1, 1.0]}),
    "C2_et_P6": ("extra_trees", "P6", {"min_samples_leaf": [3, 10]}),
    "C3_xgb_mono_P6": ("xgboost_monotone", "P6", {"max_depth": [4, 6], "n_estimators": [300, 600]}),
    "C4_xgb_mono_P6_fam": ("xgboost_monotone", "P6_fam", {"max_depth": [4, 6], "n_estimators": [300, 600]}),
}
# Round 2 (amendment A3): retrain the gate-failing XGBoost and LR candidates with the defect fixed.
CANDIDATES_R2 = {
    "C5_lr_P6b": ("logistic_regression", "P6b", {"C": [0.1, 1.0]}),
    "C6_xgb_mono2_P6b": ("xgboost_monotone_v2", "P6b", {"max_depth": [4, 6], "n_estimators": [300, 600]}),
    "C7_xgb_mono2_P6b_fam": ("xgboost_monotone_v2", "P6b_fam", {"max_depth": [4, 6], "n_estimators": [300, 600]}),
}
# Round 3 (amendment A4): night-amount anomaly only on the expensive side; no separate variability input.
CANDIDATES_R3 = {
    "C8_xgb_mono2_P6c": ("xgboost_monotone_v2", "P6c", {"max_depth": [4, 6], "n_estimators": [300, 600]}),
    "C9_xgb_mono2_P6c_fam": ("xgboost_monotone_v2", "P6c_fam", {"max_depth": [4, 6], "n_estimators": [300, 600]}),
}


def make(family, p, cols):
    if family == "logistic_regression":
        return Pipeline([("scale", StandardScaler()), ("clf", LogisticRegression(C=p["C"], class_weight="balanced",
                                                                                   max_iter=4000, random_state=SEED))])
    if family == "extra_trees":
        return ExtraTreesClassifier(n_estimators=300, max_features="sqrt", class_weight="balanced_subsample",
                                    random_state=SEED, n_jobs=-1, **p)
    version = 2 if family == "xgboost_monotone_v2" else 1
    return XGBClassifier(learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, eval_metric="aucpr", tree_method="hist",
                         monotone_constraints=tuple(monotone_vector(cols, version)), random_state=SEED, n_jobs=8, **p)


def latency_us(m, Xa, reps=200):
    ts = []
    for i in range(reps):
        r = Xa[i % len(Xa)][None, :]; t0 = time.perf_counter(); m.predict_proba(r); ts.append(time.perf_counter() - t0)
    return float(np.median(ts) * 1e6)


def matrices():
    CACHE.mkdir(parents=True, exist_ok=True)
    op = pd.read_csv(SYN / "D6_dev/open_events.csv")
    P3 = F3.Priors.fit(op[op.split == "train"])
    if (CACHE / "open_matrix.pkl").exists():
        return (pd.read_pickle(CACHE / "open_matrix.pkl"), pd.read_pickle(CACHE / "valshift_matrix.pkl"),
                pd.read_pickle(CACHE / "dr_matrix.pkl"), joblib.load(CACHE / "priors.joblib"), op)
    t0 = time.perf_counter()
    mat = build_matrix(op, None, P3)
    vs = pd.read_csv(SYN / "D6_valshift/events.csv"); vmat = build_matrix(vs, None, P3)
    dr = pd.concat([build_matrix(pd.read_csv(SYN / c.name / "events.csv"), None, P3).assign(universe=c.name)
                    for c in dr_configs()], ignore_index=True)
    mat.to_pickle(CACHE / "open_matrix.pkl"); vmat.to_pickle(CACHE / "valshift_matrix.pkl"); dr.to_pickle(CACHE / "dr_matrix.pkl")
    joblib.dump(P3, CACHE / "priors.joblib")
    print(f"[matrices] open {len(mat)} valshift {len(vmat)} dr {len(dr)} ({time.perf_counter() - t0:.0f}s)", flush=True)
    return mat, vmat, dr, P3, op


def main() -> None:
    CAND.mkdir(parents=True, exist_ok=True); EVAL.mkdir(exist_ok=True)
    mat, vmat, dr, P3, op = matrices()
    for m_ in (mat, vmat, dr):           # round-3 feature on cached matrices (same definition as stage2)
        if "night_amount_high" not in m_:
            m_["night_amount_high"] = np.maximum(0.0, m_["night_amount_log_ratio"].to_numpy(float))
    tsmap = dict(zip(op.event_id, pd.to_datetime(op.timestamp, format="ISO8601", utc=True)))
    tr, va = mat[mat.split == "train"], mat[mat.split != "train"]
    itr = tr[tr.event_id.map(tsmap) < INNER_SPLIT]; iva = tr[tr.event_id.map(tsmap) >= INNER_SPLIT]
    y_va, y_vs = va.fraud_label.to_numpy(), vmat.fraud_label.to_numpy()
    print(f"[train] train {len(tr)} ({tr.fraud_label.sum()}) + DR {len(dr)} ({dr.fraud_label.sum()}) | inner {len(itr)}/{len(iva)} "
          f"| validation {len(va)} ({y_va.sum()}) | valshift {len(vmat)} ({y_vs.sum()})", flush=True)
    g9 = gate_causality(op, P3)
    print(f"[G9 causality] {g9['pass']} {g9['detail']}", flush=True)
    rows, hp, gates, vscores = [], [], {"G9_shared_builder": g9}, {}
    plan = dict(CANDIDATES)
    rnd = 3 if "--round3" in sys.argv else 2 if "--round2" in sys.argv else 1
    if rnd > 1:                          # keep earlier rounds' results on record; add the fixed candidates
        prev = EVAL / f"round{rnd - 1}"
        rows = pd.read_csv(prev / "candidates.csv").to_dict("records")
        hp = pd.read_csv(prev / "hp_search.csv").to_dict("records")
        gates.update({k: v for k, v in json.loads((prev / "gate_results.json").read_text()).items() if k != "G9_shared_builder"})
        vscores = joblib.load(prev / "validation_scores.pkl")["scores"]
        plan = CANDIDATES_R2 if rnd == 2 else CANDIDATES_R3
    for cid, (fam, fs, grid) in plan.items():
        cols = FEATURE_SETS[fs]
        fit_inner = pd.concat([itr, dr]); fit_full = pd.concat([tr, dr])
        best = None
        for vals in product(*grid.values()):
            p = dict(zip(grid, vals)); t0 = time.perf_counter()
            m = make(fam, p, cols).fit(X(fit_inner, cols), fit_inner.fraud_label.to_numpy())
            ap = float(average_precision_score(iva.fraud_label, m.predict_proba(X(iva, cols))[:, 1]))
            hp.append({"candidate": cid, "params": json.dumps(p), "inner_ap": ap, "seconds": round(time.perf_counter() - t0, 1)})
            if best is None or ap > best[0]:
                best = (ap, p)
        t0 = time.perf_counter()
        model = make(fam, best[1], cols).fit(X(fit_full, cols), fit_full.fraud_label.to_numpy())
        train_s = time.perf_counter() - t0
        s_va, s_vs = model.predict_proba(X(va, cols))[:, 1], model.predict_proba(X(vmat, cols))[:, 1]
        thr = threshold_at_fpr(y_va, s_va, 0.02)
        m_va, m_vs = binary_metrics(y_va, s_va >= thr, s_va, thr), binary_metrics(y_vs, s_vs >= thr, s_vs, thr)
        joblib.dump(model, CAND / f"{cid}.joblib"); vscores[cid] = s_va
        scorer = FraudScorerV6.from_model(model, fs, thr, P3, name=cid)
        g = run_model_gates(scorer); g["G10"] = gate_parity(scorer, op, mat)
        failed = [k for k, v in g.items() if not v["pass"]]
        gates[cid] = g
        row = {"candidate": cid, "round": rnd, "family": fam, "feature_set": fs, "n_features": len(cols), "params": json.dumps(best[1]),
               "inner_ap": best[0], "threshold_fpr2": thr, "eligible": not failed and g9["pass"], "failed_gates": ";".join(failed),
               "train_seconds": round(train_s, 1), "latency_us": round(latency_us(model, X(va, cols)), 1),
               **{f"val_{k}": m_va[k] for k in ("pr_auc", "roc_auc", "precision", "recall", "f1", "fpr", "tp", "fp", "fn", "tn", "flagged")},
               "valshift_pr_auc": m_vs["pr_auc"], "valshift_fpr_at_thr": m_vs["fpr"],
               "val_recall_at_fpr_0.01": recall_at_fpr(y_va, s_va, 0.01)["recall"],
               "val_recall_at_fpr_0.02": recall_at_fpr(y_va, s_va, 0.02)["recall"],
               "val_recall_at_fpr_0.05": recall_at_fpr(y_va, s_va, 0.05)["recall"]}
        for part in ("validation_temporal", "validation_unseen"):
            msk = (va.split == part).to_numpy()
            row[f"{part}_pr_auc"] = binary_metrics(y_va[msk], s_va[msk] >= thr, s_va[msk])["pr_auc"]
        for sc in ("passenger_amount_anomaly", "driver_overcharge", "first_ride_fraud", "off_pattern_time", "legit_long", "legit_airport", "legit_multi_leg"):
            msk = (va.scenario == sc).to_numpy()
            row[f"val_flag_rate_{sc}"] = float((s_va[msk] >= thr).mean()) if msk.any() else None
        rows.append(row)
        print(f"  {cid:22s} valAP={m_va['pr_auc']:.4f} rec@2%={row['val_recall_at_fpr_0.02']:.3f} vsAP={m_vs['pr_auc']:.4f} "
              f"eligible={row['eligible']} failed={failed or '-'} ({train_s:.0f}s)", flush=True)
        pd.DataFrame(rows).to_csv(EVAL / "candidates.csv", index=False)
        (EVAL / "gate_results.json").write_text(json.dumps(gates, indent=1, default=str))
    pd.DataFrame(hp).to_csv(EVAL / "hp_search.csv", index=False)
    joblib.dump({"event_id": va.event_id.to_numpy(), "y": y_va, "scores": vscores}, EVAL / "validation_scores.pkl")


if __name__ == "__main__":
    main()
