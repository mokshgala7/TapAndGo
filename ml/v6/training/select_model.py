"""
select_model.py  –  Requirements-first selection (pre-registration §7) on VALIDATION data only, the rule-policy
cost analysis (§4), and the freeze. Refuses to run if a bundle is already frozen.
    PYTHONDONTWRITEBYTECODE=1 python3 training/select_model.py
"""

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V6))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import sklearn  # noqa: E402
import xgboost  # noqa: E402

from features.feature_builder import FEATURE_SETS, X  # noqa: E402
from training.metrics import binary_metrics, recall_at_fpr  # noqa: E402

EVAL, ART, CACHE = V6 / "evaluation", V6 / "artifacts", V6 / "artifacts/cache"
BUNDLE = ART / "passenger_fraud_v6_bundle.joblib"
RULE_COST_LIMIT = 20.0


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def rule_costs(va, flag):
    """Validation: extra fraud caught and extra legitimate challenges when a rule is OR-ed with the model flag."""
    y = va.fraud_label.to_numpy()
    base = binary_metrics(y, flag)
    out = {}
    for name, col in (("rapid_repeat_10min", "is_within_10_minutes"), ("amount_anomalous", "is_amount_anomalous_v6"),
                      ("night_behaviour_anomalous", "is_night_behaviour_anomalous")):
        rf = va[col].to_numpy().astype(bool)
        comb = binary_metrics(y, flag | rf)
        etp, efp = comb["tp"] - base["tp"], comb["fp"] - base["fp"]
        cost = efp / etp if etp > 0 else None
        out[name] = {"rule_alone": {k: binary_metrics(y, rf)[k] for k in ("tp", "fp", "precision", "recall", "fpr")},
                     "extra_fraud_caught": etp, "extra_legit_challenged": efp, "legit_challenges_per_extra_fraud": cost,
                     "model_or_rule": {k: comb[k] for k in ("tp", "fp", "precision", "recall", "fpr")},
                     "within_cost_limit": cost is not None and cost <= RULE_COST_LIMIT}
    return out


def main() -> None:
    if BUNDLE.exists():
        sys.exit("[select] bundle already frozen; refusing to re-select")
    cand = pd.read_csv(EVAL / "candidates.csv")
    log = {"rule": "V6_EXPERIMENT_PREREGISTRATION.md §7", "stage_A": cand[["candidate", "eligible", "failed_gates"]].fillna("").to_dict("records")}
    el = cand[cand.eligible].copy()
    sel = {"post_freeze_data_generated": False, "sealed_read": False, "selection_log": log}
    if el.empty:
        sel["selected"] = None
        sel["outcome"] = "F1: no candidate passed the mandatory gates; nothing frozen"
        (EVAL / "selection.json").write_text(json.dumps(sel, indent=2, default=float))
        sys.exit("[select] F1: no eligible candidate")
    best = el.val_pr_auc.max()
    short = el[el.val_pr_auc >= best - 0.01]
    keep = short[short.valshift_pr_auc >= short.valshift_pr_auc.max() - 0.03]
    keep = keep.sort_values(["val_recall_at_fpr_0.02", "n_features", "latency_us"], ascending=[False, True, True])
    top = keep.iloc[0]
    tied = keep[keep["val_recall_at_fpr_0.02"] >= top["val_recall_at_fpr_0.02"] - 0.005].sort_values(["n_features", "latency_us"])
    chosen = tied.iloc[0]
    log["stage_B"] = {"best_val_ap": float(best), "shortlist": short[["candidate", "val_pr_auc", "valshift_pr_auc"]].to_dict("records"),
                      "after_valshift_veto": keep.candidate.tolist(),
                      "ranking": keep[["candidate", "val_recall_at_fpr_0.02", "n_features", "latency_us"]].to_dict("records"),
                      "chosen": chosen.candidate}
    model = joblib.load(ART / "candidate_models" / f"{chosen.candidate}.joblib")
    mat = pd.read_pickle(CACHE / "open_matrix.pkl"); va = mat[mat.split != "train"].copy()
    va["night_amount_high"] = np.maximum(0.0, va["night_amount_log_ratio"].to_numpy(float))
    cols = FEATURE_SETS[chosen.feature_set]
    s_va = model.predict_proba(X(va, cols))[:, 1]; thr = float(chosen.threshold_fpr2)
    costs = rule_costs(va, s_va >= thr)
    step_rules = ["rapid_repeat_10min"] + [r for r in ("amount_anomalous", "night_behaviour_anomalous") if costs[r]["within_cost_limit"]]
    log["rule_policy"] = {"costs_on_validation": costs, "step_up_rules": step_rules,
                          "note": "10-minute rule is in the policy by design (V1); the others only if cost <= 20 legit per extra fraud"}
    P3 = joblib.load(CACHE / "priors.joblib")
    meta = {"model_version": "passenger_fraud_v6.1.0.0", "feature_schema_version": "v6-features-1",
            "selected_candidate": chosen.candidate, "model_family": chosen.family, "feature_set": chosen.feature_set,
            "feature_names": cols, "n_features": len(cols), "hyperparameters": json.loads(chosen.params),
            "decision_threshold": thr, "threshold_version": "v6-thr-1",
            "threshold_rule": "highest-recall threshold with validation FPR <= 2%", "priors": P3.__dict__,
            "policy": {"step_up_rules": step_rules}, "trained_on": "D6_dev train split + D6_dr1 + D6_dr2 (synthetic)",
            "score_semantics": "uncalibrated model risk score in [0,1]; higher = riskier; NOT a fraud probability",
            "preregistration_sha256": sha(V6 / "audit/V6_EXPERIMENT_PREREGISTRATION.md"), "random_seed": 42,
            "library_versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "xgboost": xgboost.__version__,
                                 "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__,
                                 "platform": platform.platform()},
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    joblib.dump({"model": model, "metadata": meta}, BUNDLE)
    digest = sha(BUNDLE)
    (ART / (BUNDLE.name + ".sha256")).write_text(f"{digest}  {BUNDLE.name}\n")
    (ART / "model_metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    y = va.fraud_label.to_numpy()
    sel.update({"selected": chosen.candidate, "threshold": thr, "bundle_sha256": digest,
                "validation_metrics": binary_metrics(y, s_va >= thr, s_va, thr),
                "validation_recall_at_fpr": {p: recall_at_fpr(y, s_va, p) for p in (0.005, 0.01, 0.02, 0.05, 0.10)},
                "frozen_at_utc": meta["frozen_at_utc"]})
    (EVAL / "selection.json").write_text(json.dumps(sel, indent=2, default=float))
    print(json.dumps(log, indent=1, default=float)); print(f"[select] frozen {chosen.candidate} thr={thr:.6f} sha={digest[:12]}")


if __name__ == "__main__":
    main()
