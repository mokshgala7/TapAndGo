"""Builds ml/reports/evaluation_metrics.json and the small PNG charts from the V6 evaluation outputs in ml/v6/evaluation/.
Nothing here is computed or rounded by hand: every number is read from final_metrics.json / model_metadata.json.
ALL FIGURES ARE synthetic/demo-derived, not real-world performance.   Run:  python ml/reports/make_report_assets.py"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
V6 = HERE.parent / "v6"
LABEL = "synthetic/demo-derived, not real-world performance"
fm = json.loads((V6 / "evaluation" / "final_metrics.json").read_text())
meta = json.loads((V6 / "artifacts" / "model_metadata.json").read_text())
KEYS = ["n", "fraud_cases", "legit_cases", "prevalence", "threshold", "tp", "fp", "tn", "fn", "flagged", "flagged_pct",
        "precision", "recall", "f1", "fpr", "specificity", "roc_auc", "pr_auc"]


def pick(d):
    return {k: d[k] for k in KEYS if k in d}


def block(name):
    s = fm["sets"][name]
    out = {"rows": s.get("rows"), "fraud": s.get("fraud"), "prevalence": s.get("prevalence"),
           "v6": pick(s["v6"]), "v6_with_10_minute_rule": pick(s["v6_policy_model_or_10min"]),
           "v5_frozen": pick(s["v5"]), "v4_frozen": pick(s["v4"])}
    if "v6_recall_at_fpr" in s:
        out["v6_recall_at_fpr_cap"] = s["v6_recall_at_fpr"]
    if "v6_cluster_bootstrap95" in s:
        out["v6_cluster_bootstrap95"] = s["v6_cluster_bootstrap95"]
    return out


t3 = fm["sets"]["T3_fresh"]
sub = t3["subgroups"]["v6"]
daypart = {k: {"legit_rides": v["legit"], "legit_rides_that_get_an_otp": v["fp"], "legit_otp_share_fpr": v["fpr"],
               "fraud_recall": v["recall"]} for k, v in sub["by_daypart"].items()}
out = {
    "label": LABEL,
    "model": {"version": meta["model_version"], "family": meta["model_family"], "n_features": meta["n_features"],
              "feature_names": meta["feature_names"], "decision_threshold": meta["decision_threshold"],
              "threshold_rule": meta["threshold_rule"], "score_semantics": meta["score_semantics"],
              "trained_on": meta["trained_on"], "random_seed": meta["random_seed"], "library_versions": meta["library_versions"]},
    "held_out_final_evaluation_T3_fresh": {
        "description": "a universe generated AFTER the model was frozen (D6_fresh, seed 64001)", **block("T3_fresh"),
        "legit_rides_that_get_an_otp": {
            "overall_fpr": t3["v6"]["fpr"], "day": daypart["day"], "night": daypart["night"],
            "night_shift_passengers_at_night": {"fpr": sub["night_rides_night_shift_passengers"]["fpr"], "legit": sub["night_rides_night_shift_passengers"]["legit"]},
            "day_oriented_passengers_at_night": {"fpr": sub["night_rides_day_oriented_passengers"]["fpr"], "legit": sub["night_rides_day_oriented_passengers"]["legit"]},
            "legit_expensive_long_or_airport": {"fpr": sub["legit_expensive_long_or_airport"]["fpr"], "legit": sub["legit_expensive_long_or_airport"]["legit"]},
            "ordinary_legit_rides": {"fpr": sub["by_scenario"]["legit_normal"]["fpr"], "legit": sub["by_scenario"]["legit_normal"]["legit"]}},
        "recall_by_fraud_scenario": {k: {"fraud": v["fraud"], "recall": v["recall"]} for k, v in sub["by_scenario"].items() if v["fraud"]}},
    "validation_selection_data": block("validation"),
    "other_held_out_sets": {k: block(k) for k in ("T1_temporal", "T2_unseen", "T4_shift", "T5_scenario")},
    "comparison_with_earlier_versions": "see v4_frozen / v5_frozen in each block (scored on identical rows)",
}
(HERE / "evaluation_metrics.json").write_text(json.dumps(out, indent=1))

# ---- charts ----
v6, v5, v4 = t3["v6"], t3["v5"], t3["v4"]
fig, ax = plt.subplots(figsize=(4.6, 4))
cm = [[v6["tn"], v6["fp"]], [v6["fn"], v6["tp"]]]
ax.imshow(cm, cmap="Blues")
for i in range(2):
    for j in range(2):
        ax.text(j, i, f"{cm[i][j]:,}", ha="center", va="center", color="black", fontsize=12)
ax.set_xticks([0, 1], ["no OTP", "OTP"]); ax.set_yticks([0, 1], ["legitimate", "fraud"])
ax.set_xlabel("V6 decision (threshold %.4f)" % meta["decision_threshold"]); ax.set_title("V6 confusion matrix, held-out T3\n%s" % LABEL, fontsize=8)
fig.tight_layout(); fig.savefig(HERE / "v6_confusion_matrix_T3.png", dpi=110); plt.close(fig)

fig, ax = plt.subplots(figsize=(6, 3.6))
names = ["precision", "recall", "fpr"]; w = 0.25
for k, (lab, m) in enumerate((("V4", v4), ("V5", v5), ("V6", v6))):
    ax.bar([i + (k - 1) * w for i in range(3)], [m[n] for n in names], w, label=lab)
ax.set_xticks(range(3), ["precision", "recall", "false-positive rate"]); ax.legend(); ax.set_ylim(0, 0.6)
ax.set_title("V4 / V5 / V6 on identical held-out rides (T3)\n%s" % LABEL, fontsize=8); fig.tight_layout()
fig.savefig(HERE / "v4_v5_v6_comparison_T3.png", dpi=110); plt.close(fig)

rf = t3["v6_recall_at_fpr"]
xs = [float(k) for k in rf]; ys = [rf[k]["recall"] for k in rf]
fig, ax = plt.subplots(figsize=(5, 3.6)); ax.plot([x * 100 for x in xs], [y * 100 for y in ys], "o-")
ax.set_xlabel("allowed false-positive rate (%)"); ax.set_ylabel("recall (%)"); ax.grid(alpha=.3)
ax.set_title("V6 recall at a given FPR cap, held-out T3\n%s" % LABEL, fontsize=8); fig.tight_layout()
fig.savefig(HERE / "v6_recall_vs_fpr_T3.png", dpi=110); plt.close(fig)
print("ok")
