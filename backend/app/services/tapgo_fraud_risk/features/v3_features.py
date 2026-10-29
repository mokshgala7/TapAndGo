"""
features.py  –  Two-stage causal feature builder for passenger_fraud_v3.

Stage 1 (`stage1_passenger`): per-row statistics from the SAME passenger's prior COMPLETED ride
payments with a strictly earlier timestamp. No fitting. The current row's status and label are
never read. Tier-B inputs (declined attempts, confirmed fraud reports) are computed only if supplied.

Stage 2 (`stage2`): derived, model-ready features. Personal statistics are shrunk towards
population priors (`Priors`, fitted on training rows only) so that short histories fall back
smoothly to population behaviour instead of producing noisy or undefined values.

Batch building (training/evaluation) and single-transaction inference call the SAME two
functions, so the features cannot drift between them (parity is also tested).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TZ = "Asia/Kolkata"
NIGHT_HOURS = (22, 23, 0, 1, 2, 3, 4, 5)          # 22:00–05:59 local
TEN_MINUTES_S = 600
HISTORY_MIN = 20                                   # history_insufficient: < 20 prior completed rides
PROFILE_ACTIVATION_MIN = 100                       # profile_active: >= 100 prior completed rides
SHRINK_K = 5.0                                     # pseudo-rides of population prior in shrinkage
NO_GAP_SECONDS = 365 * 86400                       # sentinel gap when there is no prior completed ride
AMOUNT_MAX = 100_000.0                             # inference sanity cap (₹)

PAYMENT_CATS = ("NFC", "QR", "OTHER", "UNKNOWN")
VEHICLE_CATS = ("auto_rickshaw", "taxi", "unknown")

# v1 rule constants (unchanged definitions)
AMT_HIGH, AMT_LOW, AMT_MAD_K, MAD_SIGMA = 3.0, 0.3, 4.0, 1.4826
NIGHT_SHARE_T, NIGHT_AMT_RATIO, NIGHT_MIN_PRIOR = 0.15, 2.0, 3


def epoch_ns(ts: pd.Series) -> np.ndarray:
    """Epoch nanoseconds regardless of the datetime resolution pandas inferred (pandas 3 may use 's')."""
    return ts.dt.tz_convert("UTC").dt.as_unit("ns").astype("int64").to_numpy(np.int64)


def norm_payment(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "UNKNOWN"
    s = str(v).strip().upper()
    if s == "":
        return "UNKNOWN"
    if s == "NFC":
        return "NFC"
    if s in ("QR", "QR_WALLET"):
        return "QR"
    return "OTHER"


def norm_vehicle(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "unknown"
    s = str(v).strip().lower()
    if "auto" in s:
        return "auto_rickshaw"
    if s in ("taxi", "cab", "car"):
        return "taxi"
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
STAGE1_COLS = [
    "amount", "log_amount", "hour", "is_night", "is_weekend", "payment_cat", "vehicle_cat",
    "n_prior", "med_log", "mad_log", "min_log", "max_log", "med_lin", "mad_lin",
    "veh_n", "veh_med_log", "night_n", "night_med_log", "night_med_lin", "hourband_n", "weekend_n",
    "method_n", "vehicle_n", "driver_n", "distinct_drivers", "new_driver_rate_last10",
    "secs_since_prev", "days_since_first", "cnt_1h", "cnt_24h", "cnt_7d", "amt_1h", "amt_24h",
    "rate_per_day",
    # tier B (NaN when the input was not supplied)
    "failed_1h", "failed_24h", "driver_reports_prior", "pax_reports_prior",
]


def stage1_passenger(g: pd.DataFrame, targets: np.ndarray | None = None,
                     driver_reports: dict | None = None, pax_reports: np.ndarray | None = None) -> pd.DataFrame:
    """
    g: ONE passenger's events sorted by strictly increasing `tn` (epoch ns) with columns
       t (epoch s), tn, hour, is_night, is_weekend, amount, status, driver_id, payment_cat, vehicle_cat.
    targets: boolean mask of rows to compute (default all).
    driver_reports: {driver_id: sorted np.array of confirmation epoch seconds} (tier B, optional).
    pax_reports: sorted np.array of this passenger's confirmation epoch seconds (tier B, optional).
    """
    n = len(g)
    t = g["t"].to_numpy(np.int64)
    tn = g["tn"].to_numpy(np.int64)                       # nanoseconds, for the exact 10-minute gap
    if n > 1 and not np.all(np.diff(tn) > 0):
        raise ValueError("events must have strictly increasing timestamps")
    amt = g["amount"].to_numpy(float)
    comp = (g["status"].to_numpy() == "completed")
    failed_t = t[~comp]
    hour, night, wkend = g["hour"].to_numpy(int), g["is_night"].to_numpy(int), g["is_weekend"].to_numpy(int)
    drv, pay, veh = g["driver_id"].to_numpy(object), g["payment_cat"].to_numpy(object), g["vehicle_cat"].to_numpy(object)

    # completed-only arrays in time order, and k[i] = number of completed rows strictly before row i
    ci = np.where(comp)[0]
    ct, ctn, ca, cla = t[ci], tn[ci], amt[ci], np.log(amt[ci])
    ch, cn, cw = hour[ci], night[ci], wkend[ci]
    cd, cp, cv = drv[ci], pay[ci], veh[ci]
    k_before = np.searchsorted(ci, np.arange(n), side="left")
    cum_amt = np.concatenate([[0.0], np.cumsum(ca)])
    seen, first_flag, distinct = set(), np.zeros(len(ci)), np.zeros(len(ci) + 1, dtype=int)
    for j, d in enumerate(cd):
        first_flag[j] = d not in seen
        seen.add(d)
        distinct[j + 1] = len(seen)

    rows = []
    idx = np.arange(n) if targets is None else np.where(targets)[0]
    for i in idx:
        k = int(k_before[i])
        a, la, ti = amt[i], math.log(amt[i]), t[i]
        r = {"amount": a, "log_amount": la, "hour": int(hour[i]), "is_night": int(night[i]),
             "is_weekend": int(wkend[i]), "payment_cat": pay[i], "vehicle_cat": veh[i], "n_prior": k}
        if k:
            L, A = cla[:k], ca[:k]
            med = float(np.median(L)); medl = float(np.median(A))
            vm = cv[:k] == veh[i]
            nm = cn[:k] == 1
            hd = np.abs(ch[:k] - hour[i]) % 24
            r.update(med_log=med, mad_log=float(np.median(np.abs(L - med))), min_log=float(L.min()),
                     max_log=float(L.max()), med_lin=medl, mad_lin=float(np.median(np.abs(A - medl))),
                     veh_n=int(vm.sum()), veh_med_log=float(np.median(L[vm])) if vm.any() else np.nan,
                     night_n=int(nm.sum()), night_med_log=float(np.median(L[nm])) if nm.any() else np.nan,
                     night_med_lin=float(np.median(A[nm])) if nm.any() else np.nan,
                     hourband_n=int((np.minimum(hd, 24 - hd) <= 1).sum()), weekend_n=int(cw[:k].sum()),
                     method_n=int((cp[:k] == pay[i]).sum()), vehicle_n=int(vm.sum()),
                     driver_n=int((cd[:k] == drv[i]).sum()), distinct_drivers=int(distinct[k]),
                     new_driver_rate_last10=float(first_flag[max(0, k - 10):k].mean()),
                     secs_since_prev=int((tn[i] - ctn[k - 1]) // 10**9), days_since_first=(ti - ct[0]) / 86400.0)
            lo1, lo24, lo7 = (np.searchsorted(ct[:k], ti - w, side="right") for w in (3600, 86400, 7 * 86400))
            r.update(cnt_1h=k - lo1, cnt_24h=k - lo24, cnt_7d=k - lo7,
                     amt_1h=float(cum_amt[k] - cum_amt[lo1]), amt_24h=float(cum_amt[k] - cum_amt[lo24]),
                     rate_per_day=k / max(1.0, (ti - ct[0]) / 86400.0))
        else:
            r.update(med_log=np.nan, mad_log=np.nan, min_log=np.nan, max_log=np.nan, med_lin=np.nan,
                     mad_lin=np.nan, veh_n=0, veh_med_log=np.nan, night_n=0, night_med_log=np.nan,
                     night_med_lin=np.nan, hourband_n=0, weekend_n=0, method_n=0, vehicle_n=0, driver_n=0,
                     distinct_drivers=0, new_driver_rate_last10=0.0, secs_since_prev=-1,
                     days_since_first=0.0, cnt_1h=0, cnt_24h=0, cnt_7d=0, amt_1h=0.0, amt_24h=0.0,
                     rate_per_day=0.0)
        # tier B
        prior_failed = failed_t[failed_t < ti]
        r["failed_1h"] = int((prior_failed > ti - 3600).sum())
        r["failed_24h"] = int((prior_failed > ti - 86400).sum())
        if driver_reports is not None:
            arr = driver_reports.get(drv[i])
            r["driver_reports_prior"] = int(np.searchsorted(arr, ti, side="left")) if arr is not None else 0
        else:
            r["driver_reports_prior"] = np.nan
        r["pax_reports_prior"] = (int(np.searchsorted(pax_reports, ti, side="left"))
                                  if pax_reports is not None else np.nan)
        rows.append(r)
    out = pd.DataFrame(rows, index=g.index[idx], columns=STAGE1_COLS)
    return out


def prepare_events(ev: pd.DataFrame) -> pd.DataFrame:
    """Add t / hour / is_night / is_weekend / normalised categoricals. Raises on bad timestamps."""
    ts = pd.to_datetime(ev["timestamp"], format="ISO8601", utc=True, errors="raise")
    loc = ts.dt.tz_convert(TZ)
    out = ev.copy()
    out["tn"] = epoch_ns(ts)
    out["t"] = (out["tn"] // 10**9).astype(np.int64)
    out["hour"] = loc.dt.hour.astype(int)
    out["is_night"] = out["hour"].isin(NIGHT_HOURS).astype(int)
    out["is_weekend"] = (loc.dt.weekday >= 5).astype(int)
    out["payment_cat"] = ev["payment_method"].map(norm_payment)
    out["vehicle_cat"] = ev["vehicle_type"].map(norm_vehicle)
    return out


def report_index(ev: pd.DataFrame) -> tuple[dict, dict]:
    """Confirmed fraud reports by driver and by passenger: {id: sorted confirmation epoch seconds}."""
    rep = ev[ev["fraud_label"].eq(1)]
    # Unconfirmed episodes are stored as empty or the string "NaT"; both mean "never confirmed".
    # (Bug fixed 2026-10-26: "NaT" used to parse to the minimum integer, i.e. "confirmed at -inf".)
    parsed = pd.to_datetime(rep["confirm_timestamp"].replace("NaT", None), format="ISO8601", utc=True, errors="coerce")
    rep = rep[parsed.notna()]
    ct = epoch_ns(parsed[parsed.notna()]) // 10**9
    rep = rep.assign(ct=ct)
    # One report per fraud episode (per driver involved), not one per fraudulent row
    rd = rep.drop_duplicates(["episode_id", "driver_id"])
    rp = rep.drop_duplicates("episode_id")
    by_d = {d: np.sort(g["ct"].to_numpy()) for d, g in rd.groupby("driver_id")}
    by_p = {p: np.sort(g["ct"].to_numpy()) for p, g in rp.groupby("passenger_id")}
    return by_d, by_p


def stage1_frame(ev: pd.DataFrame, target_mask: pd.Series | None = None, with_tier_b: bool = True,
                 report_source: pd.DataFrame | None = None) -> pd.DataFrame:
    """Stage-1 statistics for (target) rows of many passengers. `ev` must hold full histories."""
    pe = prepare_events(ev)
    by_d, by_p = report_index(report_source if report_source is not None else ev) if with_tier_b else (None, None)
    parts = []
    for pid, g in pe.groupby("passenger_id", sort=False):
        g = g.sort_values("tn")
        tm = None if target_mask is None else target_mask.loc[g.index].to_numpy()
        if tm is not None and not tm.any():
            continue
        parts.append(stage1_passenger(g, tm, by_d, by_p.get(pid, np.array([], dtype=np.int64)) if by_p is not None else None))
    want = ev.index if target_mask is None else ev.index[target_mask.to_numpy()]
    return pd.concat(parts).reindex(want)


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Priors:
    """Population statistics fitted on TRAINING completed rides only (label-free)."""
    med_log: dict = field(default_factory=dict)      # by vehicle_cat, plus "all"
    mad_log: float = 0.3
    night_share: float = 0.1
    hour_share: list = field(default_factory=list)   # share of rides within ±1 h of each hour
    weekend_share: float = 0.25
    method_share: dict = field(default_factory=dict)
    vehicle_share: dict = field(default_factory=dict)
    fitted_rows: int = 0

    @classmethod
    def fit(cls, ev_train: pd.DataFrame) -> "Priors":
        pe = prepare_events(ev_train)
        c = pe[pe["status"] == "completed"]
        la = np.log(c["amount"].to_numpy(float))
        med_all = float(np.median(la))
        med = {"all": med_all}
        for v in VEHICLE_CATS:
            m = c["vehicle_cat"].to_numpy() == v
            med[v] = float(np.median(la[m])) if m.sum() >= 50 else med_all
        hours = c["hour"].to_numpy()
        hshare = []
        for h in range(24):
            d = np.abs(hours - h) % 24
            hshare.append(float((np.minimum(d, 24 - d) <= 1).mean()))
        return cls(med_log=med, mad_log=float(np.median(np.abs(la - med_all))),
                   night_share=float(c["is_night"].mean()), hour_share=hshare,
                   weekend_share=float(c["is_weekend"].mean()),
                   method_share={m: float((c["payment_cat"] == m).mean()) for m in PAYMENT_CATS},
                   vehicle_share={v: float((c["vehicle_cat"] == v).mean()) for v in VEHICLE_CATS},
                   fitted_rows=int(len(c)))


TIER_A = [
    "log_amount", "hour_sin", "hour_cos", "is_night", "is_weekend",
    "no_history", "history_insufficient", "profile_active", "log1p_n_prior",
    "z_log", "log_ratio", "abs_log_ratio", "low_dev", "high_dev", "veh_log_ratio",
    "below_prior_min", "above_prior_max", "night_amount_log_ratio",
    "night_share_s", "night_rarity", "hourband_share_s", "weekend_share_s",
    "method_share_s", "vehicle_share_s", "driver_seen", "driver_share", "distinct_driver_ratio",
    "new_driver_rate_last10", "log_gap", "cnt_1h", "cnt_24h", "cnt_7d",
    "log1p_amt_1h", "log1p_amt_24h", "freq_ratio_7d",
    "pay_NFC", "pay_QR", "pay_OTHER", "pay_UNKNOWN", "veh_auto_rickshaw", "veh_taxi", "veh_unknown",
]
RULES = ["is_within_10_minutes", "is_amount_anomalous", "is_night_behaviour_anomalous"]
TIER_B = ["failed_1h", "failed_24h", "log1p_driver_reports", "pax_reports_prior"]
FEATURE_SETS = {"A": TIER_A, "A_rules": TIER_A + RULES, "B_research": TIER_A + RULES + TIER_B}
ELIGIBLE_SETS = ("A", "A_rules")


def rule_flags(s1: pd.DataFrame) -> pd.DataFrame:
    """The deterministic v1 rules, from stage-1 statistics (no fitting)."""
    gap = s1["secs_since_prev"].to_numpy()
    enough = s1["n_prior"].to_numpy() >= HISTORY_MIN
    a, med, mad = s1["amount"].to_numpy(), s1["med_lin"].to_numpy(), s1["mad_lin"].to_numpy()
    with np.errstate(invalid="ignore"):
        amount = enough & ((a > AMT_HIGH * med) | (a > med + AMT_MAD_K * MAD_SIGMA * mad) | (a < AMT_LOW * med))
        night_ref = np.where(s1["night_n"].to_numpy() >= NIGHT_MIN_PRIOR, s1["night_med_lin"].to_numpy(), med)
        share = np.where(s1["n_prior"] > 0, s1["night_n"] / s1["n_prior"].clip(lower=1), 0.0)
        night = (s1["is_night"].to_numpy() == 1) & enough & ((share < NIGHT_SHARE_T) | (a > NIGHT_AMT_RATIO * night_ref))
    return pd.DataFrame({"is_within_10_minutes": ((gap >= 0) & (gap <= TEN_MINUTES_S)).astype(int),
                         "is_amount_anomalous": amount.astype(int),
                         "is_night_behaviour_anomalous": night.astype(int)}, index=s1.index)


def stage2(s1: pd.DataFrame, P: Priors) -> pd.DataFrame:
    """Model-ready features. Every output is finite; missing history uses documented fallbacks."""
    k, n = SHRINK_K, s1["n_prior"].to_numpy(float)
    la = s1["log_amount"].to_numpy()
    vc = s1["vehicle_cat"].to_numpy()
    pop_med_v = np.array([P.med_log.get(v, P.med_log["all"]) for v in vc])
    has = n > 0

    def shrink(x, nn, prior):
        x = np.where(np.isnan(x), 0.0, x)
        return (nn * x + k * prior) / (nn + k)

    med_s = shrink(s1["med_log"].to_numpy(), n, P.med_log["all"])
    mad_s = shrink(s1["mad_log"].to_numpy(), n, P.mad_log)
    log_ratio = la - med_s
    veh_n = s1["veh_n"].to_numpy(float)
    veh_med_s = shrink(s1["veh_med_log"].to_numpy(), veh_n, pop_med_v)
    night_n = s1["night_n"].to_numpy(float)
    night_ref = np.where(night_n >= NIGHT_MIN_PRIOR, s1["night_med_log"].to_numpy(), med_s)
    night_share_s = (night_n + k * P.night_share) / (n + k)
    hour = s1["hour"].to_numpy()
    hour_prior = np.array(P.hour_share)[hour]
    gap = s1["secs_since_prev"].to_numpy(float)
    rate = s1["rate_per_day"].to_numpy(float)
    f = pd.DataFrame(index=s1.index)
    f["log_amount"] = la
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    f["is_night"], f["is_weekend"] = s1["is_night"].to_numpy(), s1["is_weekend"].to_numpy()
    f["no_history"] = (~has).astype(int)
    f["history_insufficient"] = (n < HISTORY_MIN).astype(int)
    f["profile_active"] = (n >= PROFILE_ACTIVATION_MIN).astype(int)
    f["log1p_n_prior"] = np.log1p(n)
    f["z_log"] = log_ratio / np.maximum(MAD_SIGMA * mad_s, 0.15)
    f["log_ratio"] = log_ratio
    f["abs_log_ratio"] = np.abs(log_ratio)
    f["low_dev"] = np.maximum(0, -log_ratio)
    f["high_dev"] = np.maximum(0, log_ratio)
    f["veh_log_ratio"] = la - veh_med_s
    f["below_prior_min"] = np.where(has, np.minimum(0, la - np.nan_to_num(s1["min_log"].to_numpy())), 0.0)
    f["above_prior_max"] = np.where(has, np.maximum(0, la - np.nan_to_num(s1["max_log"].to_numpy())), 0.0)
    f["night_amount_log_ratio"] = np.where(f["is_night"] == 1, la - np.nan_to_num(night_ref, nan=0.0), 0.0)
    f["night_share_s"] = night_share_s
    f["night_rarity"] = f["is_night"] * (1 - night_share_s)
    f["hourband_share_s"] = (s1["hourband_n"].to_numpy() + k * hour_prior) / (n + k)
    f["weekend_share_s"] = (s1["weekend_n"].to_numpy() + k * P.weekend_share) / (n + k)
    pc = s1["payment_cat"].to_numpy()
    f["method_share_s"] = (s1["method_n"].to_numpy() + k * np.array([P.method_share.get(m, 0.0) for m in pc])) / (n + k)
    f["vehicle_share_s"] = (s1["vehicle_n"].to_numpy() + k * np.array([P.vehicle_share.get(v, 0.0) for v in vc])) / (n + k)
    f["driver_seen"] = (s1["driver_n"].to_numpy() > 0).astype(int)
    f["driver_share"] = np.where(has, s1["driver_n"].to_numpy() / np.maximum(n, 1), 0.0)
    f["distinct_driver_ratio"] = np.where(has, s1["distinct_drivers"].to_numpy() / np.maximum(n, 1), 0.0)
    f["new_driver_rate_last10"] = s1["new_driver_rate_last10"].to_numpy(float)
    f["log_gap"] = np.log1p(np.where(gap >= 0, gap, NO_GAP_SECONDS))
    f["log_days_since_first"] = np.log1p(s1["days_since_first"].to_numpy(float))
    for c in ("cnt_1h", "cnt_24h", "cnt_7d"):
        f[c] = s1[c].to_numpy(float)
    f["log1p_amt_1h"], f["log1p_amt_24h"] = np.log1p(s1["amt_1h"].to_numpy(float)), np.log1p(s1["amt_24h"].to_numpy(float))
    f["freq_ratio_7d"] = (f["cnt_7d"] + 1) / (rate * 7 + 1)
    for m in PAYMENT_CATS:
        f[f"pay_{m}"] = (pc == m).astype(int)
    for v in VEHICLE_CATS:
        f[f"veh_{v}"] = (vc == v).astype(int)
    f = pd.concat([f, rule_flags(s1)], axis=1)
    f["failed_1h"], f["failed_24h"] = s1["failed_1h"].to_numpy(float), s1["failed_24h"].to_numpy(float)
    f["log1p_driver_reports"] = np.log1p(s1["driver_reports_prior"].to_numpy(float))
    f["pax_reports_prior"] = s1["pax_reports_prior"].to_numpy(float)
    return f
