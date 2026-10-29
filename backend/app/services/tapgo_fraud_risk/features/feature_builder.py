"""
feature_builder.py  –  Final-experiment features: V6's passenger-only causal features + PERIOD-AWARE (day/night) fare
baselines (pre-registration §2). V6 header follows.

feature_builder.py  –  V6 passenger-only causal features, explicit fare-anomaly signal and rules.
See features/FEATURE_DICTIONARY.md and audit/V6_EXPERIMENT_PREREGISTRATION.md §3–§4.

Inputs: the transaction and THIS passenger's earlier ride payments (completed and failed). Nothing else: no
driver ledger, no aggregates, no location. History statistics use only rides COMPLETED strictly before the
current ride (nanosecond comparison). `v3_features.py` is a byte-identical copy of V3's verified builder.
The same functions serve batch building and single-transaction inference.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import v3_features as F3

K_PAIR = 3.0
MICRO_FARE = 30.0                     # ₹: micro_amount is 0 at or above this fare
ANOMALY_HIGH = (3.0, 1.8)             # (z, ratio) for level "high"
ANOMALY_ELEVATED = (2.0, 1.4)         # (z, ratio) for level "elevated"
LOCATION_TOKENS = ("gps", "lat", "lon", "latitude", "longitude", "geo", "location", "coord", "route", "distance",
                   "zone", "airport")

AMOUNT = ["z_log", "log_ratio", "abs_log_ratio", "high_dev", "low_dev", "below_prior_min", "above_prior_max",
          "veh_log_ratio", "fare_variability", "micro_amount"]
DAYNIGHT = ["is_night", "hour_sin", "hour_cos", "night_share_s", "night_rarity", "night_amount_log_ratio",
            "hourband_share_s", "is_weekend", "weekend_share_s"]
HISTORY = ["no_history", "history_insufficient", "profile_active", "log1p_n_prior", "history_uncertainty"]
VELOCITY = ["log_gap", "cnt_1h", "cnt_24h", "cnt_7d", "log1p_amt_1h", "log1p_amt_24h", "freq_ratio_7d",
            "log_prev_amount_ratio"]
VEHICLE = ["veh_auto_rickshaw", "veh_taxi", "veh_unknown", "vehicle_share_s"]
FAMILIARITY = ["driver_seen", "driver_share", "distinct_driver_ratio", "new_driver_rate_last10", "prev_same_driver",
               "pair_fare_dev"]
P6 = AMOUNT + DAYNIGHT + HISTORY + VELOCITY + VEHICLE
FEATURE_SETS = {
    "C0_transparent": ["z_log", "high_dev", "night_rarity", "history_uncertainty", "cnt_1h", "log_gap"],
    "P6": P6,
    "P6_fam": P6 + FAMILIARITY,
    # round 2 (amendment A3): cyclic hour terms removed; see MONOTONE_V2
    "P6b": [c for c in P6 if c not in ("hour_sin", "hour_cos")],
    "P6b_fam": [c for c in P6 if c not in ("hour_sin", "hour_cos")] + FAMILIARITY,
}
_R3_DROP = ("hour_sin", "hour_cos", "night_amount_log_ratio", "fare_variability")
_P7_REPLACE = {"z_log": "period_z", "log_ratio": "period_log_ratio", "abs_log_ratio": "period_abs_log_ratio",
               "high_dev": "period_high_dev", "low_dev": "period_low_dev", "pair_fare_dev": "pair_period_dev",
               "log_prev_amount_ratio": "prev_period_amount_ratio"}
FEATURE_SETS["P6c"] = [c for c in P6 if c not in _R3_DROP] + ["night_amount_high"]
FEATURE_SETS["P6c_fam"] = FEATURE_SETS["P6c"] + FAMILIARITY
# Every feature computable from the transaction + this passenger's earlier rides (gate G8 allowlist). Payment-method,
# rule, tier-B and driver-ledger features are deliberately absent.
FEATURE_SETS["P7_fam"] = [_P7_REPLACE.get(c, c) for c in FEATURE_SETS["P6c_fam"]
                          if c not in ("night_amount_high", "veh_log_ratio")] + ["period_history_n_log"]
FEATURE_SETS["P7"] = [c for c in FEATURE_SETS["P7_fam"] if c not in FAMILIARITY and c != "pair_period_dev"]
PERIOD_FEATURES = set(_P7_REPLACE.values()) | {"period_history_n_log"}
PASSENGER_HISTORY_FEATURES = set(P6) | set(FAMILIARITY) | {"night_amount_high"} | PERIOD_FEATURES
MONOTONE_INCREASING = {"z_log", "log_ratio", "abs_log_ratio", "high_dev", "above_prior_max", "veh_log_ratio",
                       "night_amount_log_ratio", "log_prev_amount_ratio", "pair_fare_dev"}
RULES = ["is_within_10_minutes", "is_amount_anomalous_v6", "is_night_behaviour_anomalous"]
SIGNALS = ["anomaly_z", "anomaly_ratio", "anomaly_level", "history_stage", "anomaly_basis"]
FORBIDDEN = {"event_id", "passenger_id", "driver_id", "fraud_label", "scenario", "episode_id", "confirm_timestamp",
             "split", "passenger_group", "archetype", "driver_is_ring", "driver_type", "trip_type", "fraud_account",
             "drift_active", "vehicle_true", "universe", "is_synthetic", "status", "timestamp", "amount", "log_amount"}


# Amendment A3 (round 2): an unusual night hour for this passenger, or less personal history, may not LOWER risk
MONOTONE_V2_INCREASING = MONOTONE_INCREASING | {"night_rarity", "is_night", "history_uncertainty", "history_insufficient",
                                                "no_history", "night_amount_high"}
MONOTONE_V2_DECREASING = {"hourband_share_s", "log1p_n_prior", "period_history_n_log"}
MONOTONE_V2_INCREASING = MONOTONE_V2_INCREASING | {"period_z", "period_log_ratio", "period_abs_log_ratio", "period_high_dev",
                                                  "pair_period_dev", "prev_period_amount_ratio"}


def monotone_vector(cols: list, version: int = 1) -> list:
    if version == 1:
        return [1 if c in MONOTONE_INCREASING else 0 for c in cols]
    return [1 if c in MONOTONE_V2_INCREASING else -1 if c in MONOTONE_V2_DECREASING else 0 for c in cols]


def prev_pair_stage(g: pd.DataFrame, targets: np.ndarray | None = None) -> pd.DataFrame:
    """ONE passenger's rows sorted by tn: previous completed fare/driver and pair median with this driver."""
    n = len(g)
    comp = g["status"].to_numpy() == "completed"
    ci = np.where(comp)[0]
    la = np.log(g["amount"].to_numpy(float))
    cla, cd = la[ci], g["driver_id"].to_numpy(object)[ci]
    drv = g["driver_id"].to_numpy(object)
    kb = np.searchsorted(ci, np.arange(n), side="left")
    idx = np.arange(n) if targets is None else np.where(targets)[0]
    rows = []
    for i in idx:
        k = int(kb[i])
        if k:
            m = cd[:k] == drv[i]
            rows.append({"pair_med_log": float(np.median(cla[:k][m])) if m.any() else np.nan,
                         "prev_same_driver": int(cd[k - 1] == drv[i]), "log_prev_amount_ratio": float(la[i] - cla[k - 1])})
        else:
            rows.append({"pair_med_log": np.nan, "prev_same_driver": 0, "log_prev_amount_ratio": 0.0})
    return pd.DataFrame(rows, index=g.index[idx])


K_PERIOD = 5.0                        # pseudo-rides of the passenger's overall baseline in the period baseline


def period_stage(g: pd.DataFrame, targets: np.ndarray | None = None) -> pd.DataFrame:
    """ONE passenger's rows sorted by tn: statistics of earlier COMPLETED rides in the SAME period (day 06:00-21:59 /
    night 22:00-05:59 local) as the target ride, overall and with the same driver, plus the previous same-period fare."""
    n = len(g)
    comp = g["status"].to_numpy() == "completed"
    ci = np.where(comp)[0]
    la = np.log(g["amount"].to_numpy(float))
    cla, cd = la[ci], g["driver_id"].to_numpy(object)[ci]
    night = g["is_night"].to_numpy(int)
    cn = night[ci]
    drv = g["driver_id"].to_numpy(object)
    kb = np.searchsorted(ci, np.arange(n), side="left")
    idx = np.arange(n) if targets is None else np.where(targets)[0]
    rows = []
    for i in idx:
        k = int(kb[i])
        m = cn[:k] == night[i]
        w = cla[:k][m]
        if len(w):
            med = float(np.median(w)); mad = float(np.median(np.abs(w - med)))
        else:
            med = mad = np.nan
        pm = m & (cd[:k] == drv[i])
        last = np.where(m)[0]
        rows.append({"period_n": int(m.sum()), "period_med_log": med, "period_mad_log": mad, "pair_period_n": int(pm.sum()),
                     "pair_period_med_log": float(np.median(cla[:k][pm])) if pm.any() else np.nan,
                     "prev_period_log": float(cla[:k][last[-1]]) if len(last) else np.nan})
    return pd.DataFrame(rows, index=g.index[idx])


def passenger_stage1(g: pd.DataFrame, targets: np.ndarray | None) -> pd.DataFrame:
    """All per-passenger history statistics (shared by batch building and single-transaction inference)."""
    return pd.concat([F3.stage1_passenger(g, targets, None, None), prev_pair_stage(g, targets), period_stage(g, targets)], axis=1)


def stage1(events: pd.DataFrame, target_mask: pd.Series | None) -> pd.DataFrame:
    """V3 stage 1 (no tier-B inputs) + previous/pair stage, for target rows. `events` must hold full histories."""
    pe = F3.prepare_events(events)
    parts = []
    for _, g in pe.groupby("passenger_id", sort=False):
        g = g.sort_values("tn")
        tm = None if target_mask is None else target_mask.loc[g.index].to_numpy()
        if tm is not None and not tm.any():
            continue
        parts.append(passenger_stage1(g, tm))
    want = events.index if target_mask is None else events.index[target_mask.to_numpy()]
    return pd.concat(parts).reindex(want)


def history_stage(n: np.ndarray) -> np.ndarray:
    return np.select([n == 0, n < F3.HISTORY_MIN, n < F3.PROFILE_ACTIVATION_MIN], ["none", "insufficient", "developing"],
                     default="personal")


def stage2(s1: pd.DataFrame, P3: F3.Priors) -> pd.DataFrame:
    """All model features, rules and explicit signals. Every numeric output is finite."""
    f = F3.stage2(s1, P3)
    n = s1["n_prior"].to_numpy(float)
    la = s1["log_amount"].to_numpy(float)
    k = F3.SHRINK_K
    mad_s = (n * np.nan_to_num(s1["mad_log"].to_numpy(float)) + k * P3.mad_log) / (n + k)
    med_s = (n * np.nan_to_num(s1["med_log"].to_numpy(float)) + k * P3.med_log["all"]) / (n + k)
    f["fare_variability"] = mad_s
    f["micro_amount"] = np.maximum(0.0, math.log(MICRO_FARE) - la)
    f["history_uncertainty"] = 1.0 / np.sqrt(n + 1.0)
    f["prev_same_driver"] = s1["prev_same_driver"].to_numpy(int)
    f["log_prev_amount_ratio"] = s1["log_prev_amount_ratio"].to_numpy(float)
    pn = s1["driver_n"].to_numpy(float)
    pair_med_s = (pn * np.nan_to_num(s1["pair_med_log"].to_numpy(float)) + K_PAIR * med_s) / (pn + K_PAIR)
    f["pair_fare_dev"] = la - pair_med_s
    # round 3 (amendment A4): only a MORE expensive than usual night fare is a night-amount anomaly
    f["night_amount_high"] = np.maximum(0.0, f["night_amount_log_ratio"].to_numpy(float))
    # explicit passenger fare-anomaly signal (independent of any model)
    z, ratio = f["z_log"].to_numpy(float), np.exp(f["log_ratio"].to_numpy(float))
    f["anomaly_z"], f["anomaly_ratio"] = z, ratio
    f["anomaly_level"] = np.select([(z >= ANOMALY_HIGH[0]) & (ratio >= ANOMALY_HIGH[1]),
                                    (z >= ANOMALY_ELEVATED[0]) & (ratio >= ANOMALY_ELEVATED[1])], ["high", "elevated"], "none")
    f["anomaly_basis"] = np.where(n == 0, "population_prior", "personal_shrunk")
    f["history_stage"] = history_stage(n)
    f["is_amount_anomalous_v6"] = (f["anomaly_level"] == "high").astype(int)
    # ── period-aware (day/night) baselines: period -> passenger overall -> population ──
    pn_ = s1["period_n"].to_numpy(float)
    mad_s_all = mad_s
    pm_s = (pn_ * np.nan_to_num(s1["period_med_log"].to_numpy(float)) + K_PERIOD * med_s) / (pn_ + K_PERIOD)
    pmad_s = (pn_ * np.nan_to_num(s1["period_mad_log"].to_numpy(float)) + K_PERIOD * mad_s_all) / (pn_ + K_PERIOD)
    plr = la - pm_s
    f["period_log_ratio"] = plr
    f["period_z"] = plr / np.maximum(F3.MAD_SIGMA * pmad_s, 0.15)
    f["period_abs_log_ratio"] = np.abs(plr)
    f["period_high_dev"] = np.maximum(0.0, plr)
    f["period_low_dev"] = np.maximum(0.0, -plr)
    ppn = s1["pair_period_n"].to_numpy(float)
    f["pair_period_dev"] = la - (ppn * np.nan_to_num(s1["pair_period_med_log"].to_numpy(float)) + K_PAIR * pm_s) / (ppn + K_PAIR)
    prev = s1["prev_period_log"].to_numpy(float)
    f["prev_period_amount_ratio"] = np.where(np.isnan(prev), 0.0, la - np.nan_to_num(prev))
    f["period_history_n_log"] = np.log1p(pn_)
    f["_period_typical"] = np.exp(pm_s)
    f["_period_n"] = pn_
    pz, pr = f["period_z"].to_numpy(float), np.exp(plr)
    f["period_anomaly_z"], f["period_anomaly_ratio"] = pz, pr
    f["period_anomaly_level"] = np.select([(pz >= ANOMALY_HIGH[0]) & (pr >= ANOMALY_HIGH[1]),
                                           (pz >= ANOMALY_ELEVATED[0]) & (pr >= ANOMALY_ELEVATED[1])], ["high", "elevated"], "none")
    f["is_amount_anomalous_period"] = (f["period_anomaly_level"] == "high").astype(int)
    return f


def build_matrix(events: pd.DataFrame, target_mask: pd.Series | None, P3: F3.Priors,
                 meta_cols: tuple = ("event_id", "passenger_id", "passenger_group", "archetype", "split", "scenario",
                                     "fraud_label", "status", "amount", "driver_type", "trip_type", "fraud_account",
                                     "episode_id", "drift_active")) -> pd.DataFrame:
    s1 = stage1(events, target_mask)
    f = stage2(s1, P3)
    meta = events.loc[s1.index, [c for c in meta_cols if c in events.columns]].copy()
    meta["n_prior"] = s1["n_prior"].to_numpy()
    meta["secs_since_prev"] = s1["secs_since_prev"].to_numpy()
    meta["history_bucket"] = pd.cut(meta["n_prior"], [-1, 0, 4, 19, 99, 10**9], labels=["0", "1-4", "5-19", "20-99", "100+"]).astype(str)
    meta["daypart"] = np.where(f["is_night"].to_numpy() == 1, "night", "day")
    return pd.concat([f, meta], axis=1)


def X(frame: pd.DataFrame, cols: list) -> np.ndarray:
    bad = FORBIDDEN & set(cols)
    if bad:
        raise ValueError(f"forbidden columns in feature set: {sorted(bad)}")
    loc = [c for c in cols if any(t in c.lower() for t in LOCATION_TOKENS)]
    if loc:
        raise ValueError(f"location-like columns are out of scope: {loc}")
    arr = frame[cols].to_numpy(float)
    if not np.isfinite(arr).all():
        raise ValueError("non-finite feature values")
    return arr
