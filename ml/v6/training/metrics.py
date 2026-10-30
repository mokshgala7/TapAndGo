"""metrics.py  –  Metrics, thresholds, calibration and bootstrap utilities for V4 (copied unchanged into V6)."""

from __future__ import annotations

import math

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, confusion_matrix, roc_auc_score

AP_IMPL = "sklearn.metrics.average_precision_score (step-wise average precision, no interpolation)"


def _div(a, b):
    return None if b == 0 else a / b


def binary_metrics(y, flag, score=None, threshold=None) -> dict:
    y = np.asarray(y, dtype=int); flag = np.asarray(flag, dtype=bool)
    tn, fp, fn, tp = confusion_matrix(y, flag, labels=[0, 1]).ravel()
    prec, rec = _div(tp, tp + fp), _div(tp, tp + fn)
    f1 = None if prec is None or rec is None else (0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    n = len(y)
    out = {"n": int(n), "fraud_cases": int(y.sum()), "legit_cases": int(n - y.sum()),
           "prevalence": float(y.mean()) if n else None, "threshold": threshold,
           "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn), "flagged": int(tp + fp),
           "flagged_pct": float((tp + fp) / n) if n else None, "accuracy": float((tp + tn) / n) if n else None,
           "precision": prec, "recall": rec, "tpr": rec, "f1": f1, "fpr": _div(fp, fp + tn),
           "specificity": _div(tn, tn + fp), "roc_auc": None, "pr_auc": None, "brier": None}
    if score is not None and len(np.unique(y)) == 2:
        s = np.asarray(score, float)
        out["roc_auc"] = float(roc_auc_score(y, s)); out["pr_auc"] = float(average_precision_score(y, s))
        if np.all((s >= 0) & (s <= 1)):
            out["brier"] = float(brier_score_loss(y, s))
    return out


def threshold_at_fpr(y, score, max_fpr: float) -> float:
    """Highest-recall threshold with FPR <= max_fpr (flag if score >= threshold); midpoint between scores."""
    y = np.asarray(y, int); score = np.asarray(score, float)
    neg = np.sort(score[y == 0])
    allowed = int(math.floor(max_fpr * len(neg)))
    uniq = np.unique(score)[::-1]
    fp = len(neg) - np.searchsorted(neg, uniq, side="left")
    ok = np.where(fp <= allowed)[0]
    if len(ok) == 0:
        return float(uniq[0] + 1e-9)
    k = int(ok[-1])
    nxt = uniq[k + 1] if k + 1 < len(uniq) else uniq[k] - 1e-6
    return float((uniq[k] + nxt) / 2)


def recall_at_fpr(y, score, max_fpr: float) -> dict:
    t = threshold_at_fpr(y, score, max_fpr)
    m = binary_metrics(y, np.asarray(score) >= t, score, t)
    return {"max_fpr": max_fpr, "threshold": t, **{k: m[k] for k in ("recall", "precision", "fpr", "tp", "fp", "flagged")}}


def precision_at_alert_rate(y, score, rate: float) -> dict:
    y = np.asarray(y, int); s = np.asarray(score, float)
    k = max(1, int(round(rate * len(y))))
    top = np.argsort(-s, kind="mergesort")[:k]
    return {"alert_rate": rate, "alerts": k, "precision": float(y[top].mean()), "recall": float(y[top].sum() / max(1, y.sum()))}


def ece(y, p, bins: int = 10) -> float | None:
    p = np.asarray(p, float); y = np.asarray(y, int)
    if not np.all((p >= 0) & (p <= 1)):
        return None
    edges = np.linspace(0, 1, bins + 1); b = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return float(sum(abs(p[b == i].mean() - y[b == i].mean()) * (b == i).mean() for i in range(bins) if (b == i).any()))


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def _cluster_members(groups):
    uniq, inv = np.unique(np.asarray(groups), return_inverse=True)
    order = np.argsort(inv, kind="mergesort")
    bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
    return [order[bounds[g]:bounds[g + 1]] for g in range(len(uniq))]


def cluster_bootstrap(y, score, threshold, groups, n_boot=500, seed=0) -> dict:
    """95% CIs resampling passengers (rows of a passenger stay together)."""
    rng = np.random.default_rng(seed); y = np.asarray(y, int); s = np.asarray(score, float)
    mem = _cluster_members(groups); keys = ["precision", "recall", "f1", "fpr", "pr_auc", "roc_auc"]
    vals = {k: [] for k in keys}
    for _ in range(n_boot):
        idx = np.concatenate([mem[g] for g in rng.integers(0, len(mem), len(mem))])
        if y[idx].min() == y[idx].max():
            continue
        m = binary_metrics(y[idx], s[idx] >= threshold, s[idx], threshold)
        for k in keys:
            if m[k] is not None:
                vals[k].append(m[k])
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else None for k, v in vals.items()}


def paired_bootstrap_ap(y, s_a, s_b, groups, n_boot=500, seed=0) -> dict:
    """AP(a) - AP(b) on identical rows, passenger-cluster bootstrap."""
    rng = np.random.default_rng(seed); y = np.asarray(y, int)
    a, b = np.asarray(s_a, float), np.asarray(s_b, float)
    mem = _cluster_members(groups); diffs = []
    for _ in range(n_boot):
        idx = np.concatenate([mem[g] for g in rng.integers(0, len(mem), len(mem))])
        if y[idx].min() == y[idx].max():
            continue
        diffs.append(average_precision_score(y[idx], a[idx]) - average_precision_score(y[idx], b[idx]))
    d = average_precision_score(y, a) - average_precision_score(y, b)
    return {"ap_a": float(average_precision_score(y, a)), "ap_b": float(average_precision_score(y, b)),
            "diff": float(d), "ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
            "share_of_boot_diffs_gt_0": float(np.mean(np.array(diffs) > 0)), "n_boot": len(diffs)}
