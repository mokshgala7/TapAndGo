"""
generator_v6.py  –  Synthetic ride-payment universes for passenger_fraud_v6. Everything is fictional.

Derived from passenger_fraud_v4/data/generator_v4.py. V6 changes (pre-registration §5), removing the shortcuts the
V5 audit found:
  1. no "ring" drivers (driver types: local / hub / dishonest);
  2. fraud scenarios pick the passenger's FAMILIAR driver with a scenario-specific probability, otherwise a random
     non-hub driver (no concentration of fraud on special drivers); fraudulent new accounts pick random drivers;
  3. dishonest drivers overcharge 4% of their rides;
  4. IDs prefixed V6. Distances and zones stay internal; no location column is written.

V4 header follows.

Differences from V3 (see data/README.md):
* Route-based fares: base + per-km rate by vehicle × trip distance. Each passenger has a commute
  distance and a fare variability. Trip types: local/commute, long, airport (true context).
* Driver types: local, hub (airport/station queue; legitimate, many one-off passengers, high fares),
  ring (colluding; also legitimate regulars), dishonest (ordinary drivers who occasionally overcharge
  ANY passenger, including their regulars).
* Fraud: per-ride passenger episodes, a driver-side overcharge process, and fraudulent new accounts
  (first-ride fraud). The shift-only mechanism `collusive_regular_driver` is enabled by config.
* Unconfirmed episodes have an EMPTY confirmation timestamp (never the string "NaT").
Labels come only from these mechanisms, never from a feature value or rule threshold.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
HOURS = np.arange(24)
SURCHARGE_HOURS = {23, 0, 1, 2, 3, 4}
BASE = {"auto_rickshaw": 25.0, "taxi": 50.0}
PER_KM = {"auto_rickshaw": 14.0, "taxi": 20.0}


def _bump(c, sd):
    d = np.minimum(np.abs(HOURS - c), 24 - np.abs(HOURS - c))
    return np.exp(-0.5 * (d / sd) ** 2)


BASIS = {"morning": _bump(8.5, 1.2), "evening": _bump(18.5, 1.5),
         "day": np.clip(1 - np.abs(HOURS - 13) / 4.5, 0, None) + 0.02,
         "late": _bump(22.5, 1.4), "overnight": _bump(2.0, 2.2)}

#                  share, rides/wk, taxi Beta, commute km x, hour basis,                                            weekend x, NFC Beta
ARCHETYPES = {
    "commuter_auto":  (0.22, 6.0, (2, 8), 1.0, {"morning": .45, "evening": .45, "day": .08, "late": .02}, 0.45, (6, 3)),
    "commuter_taxi":  (0.11, 6.0, (7, 2), 1.3, {"morning": .45, "evening": .40, "day": .10, "late": .05}, 0.50, (4, 4)),
    "evening_social": (0.14, 3.0, (5, 3), 1.1, {"evening": .35, "late": .45, "day": .15, "overnight": .05}, 1.60, (3, 5)),
    "night_shift":    (0.08, 5.0, (4, 4), 1.1, {"overnight": .60, "late": .25, "morning": .15}, 0.90, (4, 4)),
    "occasional":     (0.23, 1.0, (3, 3), 1.0, {"day": .50, "evening": .30, "morning": .20}, 1.10, (4, 4)),
    "heavy_user":     (0.08, 14.0, (4, 3), 1.2, {"morning": .25, "day": .35, "evening": .30, "late": .10}, 0.90, (5, 4)),
    "student_budget": (0.14, 4.0, (1, 9), 0.8, {"morning": .35, "day": .30, "evening": .30, "late": .05}, 0.80, (3, 6)),
}
PASSENGER_SCENARIOS = ["passenger_amount_anomaly", "unfamiliar_driver_takeover", "velocity_spree", "card_testing",
                       "off_pattern_time", "quiet_compromised", "gradual_compromise", "indistinguishable",
                       "collusive_regular_driver"]
ALL_FRAUD_SCENARIOS = PASSENGER_SCENARIOS + ["driver_overcharge", "first_ride_fraud"]


@dataclass
class UniverseConfigV4:
    name: str
    seed: int
    n_passengers: int
    start: str = "2026-03-01"
    n_days: int = 184
    drivers_per_passenger: float = 0.25
    n_zones: int = 30
    driver_type_shares: dict = field(default_factory=lambda: {"local": .88, "hub": .07, "dishonest": .05})
    unknown_vehicle_frac: float = 0.08
    unknown_payment_frac: float = 0.01
    max_other_payment_share: float = 0.04
    fare_inflation: float = 1.0
    night_boost: float = 0.0
    hour_shift: int = 0
    archetype_shares: dict = field(default_factory=lambda: {k: v[0] for k, v in ARCHETYPES.items()})
    rate_scale: float = 0.6
    episode_rate: float = 0.0050          # passenger fraud episodes per legitimate ride
    scenario_weights: dict = field(default_factory=lambda: {
        "passenger_amount_anomaly": .18, "unfamiliar_driver_takeover": .12, "velocity_spree": .12,
        "card_testing": .10, "off_pattern_time": .13, "quiet_compromised": .14, "gradual_compromise": .09,
        "indistinguishable": .12, "collusive_regular_driver": 0.0})
    dishonest_overcharge_rate: float = 0.04   # per ride by a dishonest driver
    fraud_account_frac: float = 0.03          # share of late-joining passengers that are fraudulent accounts
    airport_trip_rate: float = 0.012
    long_trip_rate: float = 0.05
    drift_frac: float = 0.20
    join_at_start_frac: float = 0.60
    report_prob: float = 0.75


class _U:
    def __init__(self, cfg: UniverseConfigV4):
        self.c, self.r = cfg, np.random.default_rng(cfg.seed)
        self.t0 = datetime.fromisoformat(cfg.start).replace(tzinfo=IST)
        self.tag = cfg.name.split("_")[-1].upper()
        self._drivers()

    def _drivers(self):
        c, r = self.c, self.r
        n = max(200, int(c.n_passengers * c.drivers_per_passenger))
        types = list(c.driver_type_shares)
        p = np.array([c.driver_type_shares[t] for t in types]); p /= p.sum()
        dtype = np.array(types)[r.choice(len(types), n, p=p)]
        veh = np.where(dtype == "hub", np.where(r.random(n) < 0.8, "taxi", "auto_rickshaw"),
                       np.where(r.random(n) < 0.6, "auto_rickshaw", "taxi"))
        self.d = pd.DataFrame({"driver_id": [f"V6DRV-{self.tag}-{i:05d}" for i in range(n)], "driver_type": dtype,
                               "vehicle_true": veh, "zone": r.integers(0, c.n_zones, n)})
        self.d["vehicle_recorded"] = np.where(r.random(n) < c.unknown_vehicle_frac, None, self.d["vehicle_true"])
        d = self.d
        serve = d.driver_type != "hub"
        self.pool_vz = {k: g.index.to_numpy() for k, g in d[serve].groupby(["vehicle_true", "zone"])}
        self.pool_v = {k: g.index.to_numpy() for k, g in d[serve].groupby("vehicle_true")}
        self.hub_v = {k: g.index.to_numpy() for k, g in d[d.driver_type == "hub"].groupby("vehicle_true")}
        self.ring_v = {k: g.index.to_numpy() for k, g in d[d.driver_type == "ring"].groupby("vehicle_true")}
        self.dtype = d.driver_type.to_numpy()

    def _pick(self, pool):
        return int(self.r.choice(pool))

    def _hours(self, basis_w):
        c, r = self.c, self.r
        keys = list(BASIS)
        w = dict(zip(keys, r.dirichlet(np.array([basis_w.get(k, 0.0) for k in keys]) * 12 + 0.3)))
        w["late"] += c.night_boost / 2; w["overnight"] += c.night_boost / 2
        prof = sum(w[k] * BASIS[k] for k in keys) + 0.004
        prof = np.roll(prof, c.hour_shift)
        return prof / prof.sum()

    def _regulars(self, pax):
        r = self.r
        k = int(min(12, 1 + r.poisson(4)))
        regs = {}
        for v, share in (("taxi", pax["p_taxi"]), ("auto_rickshaw", 1 - pax["p_taxi"])):
            kv = max(1, int(round(k * share))) if share > 0.08 else 0
            pool = self.pool_vz.get((v, pax["zone"]), self.pool_v[v])
            regs[v] = list(r.choice(pool, size=min(kv, len(pool)), replace=False)) if kv else []
        return regs

    def _passenger(self, i):
        c, r = self.c, self.r
        names = list(c.archetype_shares)
        p = np.array([c.archetype_shares[k] for k in names]); p /= p.sum()
        arch = names[r.choice(len(names), p=p)]
        _, wk, taxi_b, km_x, basis_w, wkend, nfc_b = ARCHETYPES[arch]
        pax = {"id": f"V6PAX-{self.tag}-{i:05d}", "archetype": arch,
               "join_day": 0 if r.random() < c.join_at_start_frac else int(r.integers(1, c.n_days - 5)),
               "rate_day": float(np.clip(wk * c.rate_scale * math.exp(r.normal(0, 0.5)), 0.2, 20)) / 7,
               "p_taxi": float(r.beta(*taxi_b)),
               "km": float(np.clip(5.0 * km_x * math.exp(r.normal(0, 0.5)), 1.2, 20.0)),
               "sigma": float(r.uniform(0.08, 0.50)), "hours": self._hours(basis_w),
               "dow": np.array([1, 1, 1, 1, 1, wkend, wkend]) * np.exp(r.normal(0, 0.15, 7)),
               "nfc": float(r.beta(*nfc_b)), "other": float(r.uniform(0, c.max_other_payment_share)),
               "zone": int(r.integers(0, c.n_zones)), "p_regular": float(r.uniform(0.55, 0.92)),
               "chain_p": float(r.uniform(0.02, 0.15)), "fail_p": float(r.uniform(0.01, 0.06)), "drift_day": None}
        pax["regulars"] = self._regulars(pax)
        if r.random() < c.drift_frac and c.n_days - pax["join_day"] > 60:
            pax["drift_day"] = int(r.integers(pax["join_day"] + 20, c.n_days - 20))
        pax["fraud_account"] = pax["join_day"] > 0 and r.random() < c.fraud_account_frac
        return pax

    def _drift(self, pax):
        r = self.r
        pax["km"] = float(np.clip(pax["km"] * r.uniform(0.5, 2.0), 1.2, 25))
        if r.random() < 0.3:
            pax["p_taxi"] = 1 - pax["p_taxi"]
        if r.random() < 0.6:
            pax["zone"] = int(r.integers(0, self.c.n_zones)); pax["regulars"] = self._regulars(pax)
        if r.random() < 0.3:
            pax["hours"] = self._hours(ARCHETYPES[list(ARCHETYPES)[r.integers(len(ARCHETYPES))]][4])
        pax["rate_day"] *= float(r.uniform(0.6, 1.6))

    # primitives
    def _veh(self, pax):
        return "taxi" if self.r.random() < pax["p_taxi"] else "auto_rickshaw"

    def _fare(self, v, km, ts):
        f = (BASE[v] + PER_KM[v] * km) * self.c.fare_inflation
        return f * 1.25 if ts.hour in SURCHARGE_HOURS else f

    def _km(self, pax, trip):
        r = self.r
        if trip == "airport":
            return float(r.uniform(18, 35))
        if trip == "long":
            return float(r.uniform(12, 25))
        return float(max(0.8, pax["km"] * math.exp(r.normal(0, pax["sigma"]))))

    def _legit_driver(self, pax, v, trip):
        r = self.r
        if trip == "airport" and r.random() < 0.6 and len(self.hub_v.get(v, [])):
            return self._pick(self.hub_v[v])
        if trip == "long" and r.random() < 0.3 and len(self.hub_v.get(v, [])):
            return self._pick(self.hub_v[v])
        if trip == "local" and r.random() < 0.05 and len(self.hub_v.get(v, [])):
            return self._pick(self.hub_v[v])          # station pickups: hubs do some local rides too
        regs = pax["regulars"].get(v, [])
        if regs and r.random() < pax["p_regular"]:
            w = 1 / np.arange(1, len(regs) + 1); w /= w.sum()
            return int(regs[r.choice(len(regs), p=w)])
        pool = self.pool_vz.get((v, pax["zone"]), self.pool_v[v]) if r.random() < 0.7 else self.pool_v[v]
        return self._pick(pool)

    def _fraud_driver(self, v, pax, p_familiar):
        """V6: the passenger's familiar driver with probability p_familiar, else a random non-hub driver."""
        r = self.r
        if r.random() < p_familiar and pax["regulars"].get(v):
            return int(r.choice(pax["regulars"][v]))
        return self._pick(self.pool_v[v])

    def _method(self, pax, random_method=False):
        r = self.r
        if r.random() < self.c.unknown_payment_frac:
            return None
        if r.random() < (0.03 if random_method else pax["other"]):
            return "OTHER"
        return "NFC" if r.random() < (0.5 if random_method else pax["nfc"]) else "QR"

    def _time(self, day, hour):
        r = self.r
        return self.t0 + timedelta(days=int(day), hours=int(hour), minutes=int(r.integers(60)), seconds=int(r.integers(60)))

    def _off_hour(self, pax):
        inv = (1 / pax["hours"]) ** 0.7
        return int(self.r.choice(24, p=inv / inv.sum()))

    def _trip(self):
        u = self.r.random()
        return "airport" if u < self.c.airport_trip_rate else ("long" if u < self.c.airport_trip_rate + self.c.long_trip_rate else "local")

    # one passenger
    def passenger_events(self, i):
        c, r = self.c, self.r
        pax = self._passenger(i)
        ev = []

        def add(ts, v, drv, amt, method, status, label, scen, episode=None, trip="local"):
            ev.append({"passenger_id": pax["id"], "archetype": pax["archetype"], "ts": ts, "vehicle_true": v,
                       "driver_idx": drv, "amount": float(max(1, round(amt))), "payment_method": method,
                       "status": status, "fraud_label": label, "scenario": scen, "episode_id": episode,
                       "trip_type": trip, "fraud_account": int(pax["fraud_account"])})

        def legit_ride(ts, scen="legit_normal", trip=None, v=None, drv=None, amt_mult=1.0):
            trip = trip or self._trip()
            v = v or ("taxi" if trip == "airport" and r.random() < 0.85 else self._veh(pax))
            drv = self._legit_driver(pax, v, trip) if drv is None else drv
            amt = self._fare(v, self._km(pax, trip), ts) * amt_mult
            lab, sc, epi = 0, (scen if trip == "local" else f"legit_{trip}") if scen == "legit_normal" else scen, None
            if self.dtype[drv] == "dishonest" and r.random() < c.dishonest_overcharge_rate:
                amt *= r.uniform(1.4, 2.6); lab, sc, epi = 1, "driver_overcharge", f"{pax['id']}-OC{len(ev)}"
            failed = r.random() < pax["fail_p"]
            add(ts, v, drv, amt, self._method(pax), "failed" if failed else "completed", lab, sc, epi, trip)
            return failed, ts, v, drv, trip

        if pax["fraud_account"]:
            # Fraudulent new account: its first rides are fraud; usually abandoned afterwards
            day = pax["join_day"]; ep = f"{pax['id']}-FA"
            ts = self._time(day, int(r.integers(24)) if r.random() < 0.5 else r.choice(24, p=pax["hours"]))
            for _ in range(int(r.integers(1, 5))):
                v = "taxi" if r.random() < 0.6 else "auto_rickshaw"
                drv = self._pick(self.pool_v[v])          # V6: random driver (no ring/hub concentration)
                trip = "long" if r.random() < 0.3 else "local"
                add(ts, v, drv, self._fare(v, self._km(pax, trip), ts) * r.uniform(1.0, 3.0),
                    self._method(pax, True), "failed" if r.random() < 0.08 else "completed", 1, "first_ride_fraud", ep, trip)
                ts += timedelta(seconds=int(r.integers(600, 2 * 86400)))
        else:
            pre = None
            drifted = False
            for day in range(pax["join_day"], c.n_days):
                if pax["drift_day"] is not None and not drifted and day >= pax["drift_day"]:
                    pre = {k: (dict(pax[k]) if isinstance(pax[k], dict) else pax[k]) for k in ("km", "p_taxi", "zone", "regulars", "hours", "rate_day")}
                    self._drift(pax); drifted = True
                dow = (self.t0 + timedelta(days=day)).weekday()
                for _ in range(r.poisson(pax["rate_day"] * pax["dow"][dow] / pax["dow"].mean())):
                    u = r.random()
                    if u < 0.015:
                        failed, ts, v, drv, trip = legit_ride(self._time(day, self._off_hour(pax)), "legit_off_pattern", trip="local")
                    elif u < 0.035:
                        ts = self._time(day, r.choice(24, p=pax["hours"])); v = self._veh(pax)
                        add(ts, v, self._legit_driver(pax, v, "local"), BASE[v] * r.uniform(1.0, 1.3) * c.fare_inflation,
                            self._method(pax), "completed", 0, "legit_short_hop")
                        continue
                    else:
                        failed, ts, v, drv, trip = legit_ride(self._time(day, r.choice(24, p=pax["hours"])))
                    if failed and r.random() < 0.75:
                        last = ev[-1]          # a retry inherits the label/episode of the declined ride (e.g. overcharge)
                        add(ts + timedelta(seconds=int(r.integers(60, 480))), v, drv, last["amount"], last["payment_method"],
                            "completed" if r.random() < 0.9 else "failed", last["fraud_label"],
                            last["scenario"] if last["fraud_label"] else "legit_retry", last["episode_id"], trip)
                    elif not failed and r.random() < pax["chain_p"]:
                        ts2 = ts + timedelta(seconds=int(r.integers(120, 45 * 60)))
                        same = r.random() < 0.3
                        legit_ride(ts2, "legit_multi_leg", trip="local", v=v if same else None, drv=drv if same else None,
                                   amt_mult=r.uniform(0.4, 0.7) if r.random() < 0.2 else 1.0)

            # passenger fraud episodes: per-ride exposure hazard
            n_legit = sum(1 for e in ev if e["fraud_label"] == 0)
            names = list(c.scenario_weights)
            w = np.array([c.scenario_weights[k] for k in names]); w = w / w.sum()
            for e_i in range(r.poisson(c.episode_rate * n_legit)):
                scen = names[r.choice(len(names), p=w)]
                day = int(r.integers(pax["join_day"], c.n_days))
                st = {**pax, **pre} if (pre is not None and day < pax["drift_day"]) else pax
                ep = f"{pax['id']}-EP{e_i}"
                if scen == "passenger_amount_anomaly":
                    v = self._veh(st); trip = "airport" if r.random() < 0.08 else ("long" if r.random() < 0.3 else "local")
                    ts = self._time(day, r.choice(24, p=st["hours"]) if r.random() < 0.7 else int(r.integers(24)))
                    drv = self._fraud_driver(v, st, 0.5)
                    add(ts, v, drv, self._fare(v, self._km(st, trip), ts) * r.uniform(2.0, 5.0), self._method(st, True),
                        "completed", 1, scen, ep, trip)
                elif scen == "unfamiliar_driver_takeover":
                    ts = self._time(day, int(r.integers(24)))
                    for _ in range(int(r.integers(1, 3))):
                        v = self._veh(st)
                        add(ts, v, self._fraud_driver(v, st, 0.0), self._fare(v, self._km(st, "local"), ts) * r.uniform(1.0, 1.8),
                            self._method(st, True), "completed", 1, scen, ep)
                        ts += timedelta(seconds=int(r.integers(1800, 6 * 3600)))
                elif scen == "velocity_spree":
                    ts = self._time(day, int(r.integers(24)))
                    for _ in range(int(r.integers(2, 6))):
                        v = "taxi" if r.random() < 0.7 else "auto_rickshaw"
                        add(ts, v, self._fraud_driver(v, st, 0.2), self._fare(v, self._km(st, "local"), ts) * r.uniform(1.2, 3.0),
                            self._method(st, True), "failed" if r.random() < 0.1 else "completed", 1, scen, ep)
                        ts += timedelta(seconds=int(r.integers(120, 25 * 60)))
                elif scen == "card_testing":
                    ts = self._time(day, int(r.integers(24))); v = self._veh(st)
                    drv = self._fraud_driver(v, st, 0.2); m = self._method(st, True)
                    for _ in range(int(r.integers(3, 8))):
                        add(ts, v, drv, r.integers(1, 21), m, "failed" if r.random() < 0.65 else "completed", 1, scen, ep)
                        ts += timedelta(seconds=int(r.integers(20, 240)))
                    if r.random() < 0.5:
                        ts += timedelta(seconds=int(r.integers(120, 1800)))
                        add(ts, v, drv, self._fare(v, self._km(st, "local"), ts) * r.uniform(1.5, 3.0), m,
                            "completed" if r.random() < 0.8 else "failed", 1, scen, ep)
                elif scen == "off_pattern_time":
                    ts = self._time(day, self._off_hour(st))
                    for _ in range(int(r.integers(1, 3))):
                        v = self._veh(st)
                        add(ts, v, self._fraud_driver(v, st, 0.4), self._fare(v, self._km(st, "local"), ts) * r.uniform(1.0, 2.2),
                            self._method(st, True), "completed", 1, scen, ep)
                        ts += timedelta(seconds=int(r.integers(600, 3 * 3600)))
                elif scen == "quiet_compromised":
                    v = self._veh(st); ts = self._time(day, r.choice(24, p=st["hours"]))
                    add(ts, v, self._fraud_driver(v, st, 0.5), self._fare(v, self._km(st, "local"), ts), self._method(st), "completed", 1, scen, ep)
                elif scen == "gradual_compromise":
                    k = int(r.integers(3, 7)); top = r.uniform(1.6, 2.4); ts = self._time(day, r.choice(24, p=st["hours"]))
                    for j in range(k):
                        frac = j / max(1, k - 1)
                        hour = r.choice(24, p=(1 - frac) * st["hours"] + frac / 24)
                        ts = ts.replace(hour=int(hour))
                        v = self._veh(st)
                        add(ts, v, self._fraud_driver(v, st, 0.4), self._fare(v, self._km(st, "local"), ts) * (1 + (top - 1) * frac),
                            self._method(st, j > 0 and r.random() < 0.5), "completed", 1, scen, ep)
                        ts += timedelta(days=float(r.uniform(2, 6)))
                elif scen == "collusive_regular_driver":
                    v = self._veh(st); regs = st["regulars"].get(v) or st["regulars"].get("taxi") or st["regulars"].get("auto_rickshaw")
                    if not regs:
                        continue
                    drv = int(r.choice(regs)); ts = self._time(day, r.choice(24, p=st["hours"]))
                    for _ in range(int(r.integers(2, 5))):
                        add(ts, v, drv, self._fare(v, self._km(st, "local"), ts) * r.uniform(1.25, 1.8), self._method(st),
                            "completed", 1, scen, ep)
                        ts += timedelta(days=float(r.uniform(3, 12)))
                else:  # indistinguishable: generated exactly like a legitimate ride
                    v = self._veh(st); ts = self._time(day, r.choice(24, p=st["hours"]))
                    add(ts, v, self._legit_driver(st, v, "local"), self._fare(v, self._km(st, "local"), ts), self._method(st),
                        "completed", 1, scen, ep)

        ev.sort(key=lambda e: e["ts"])
        for a, b in zip(ev, ev[1:]):
            if b["ts"] <= a["ts"]:
                b["ts"] = a["ts"] + timedelta(seconds=1)
        end = self.t0 + timedelta(days=c.n_days)
        ev = [e for e in ev if e["ts"] < end]
        by_ep = {}
        for e in ev:
            if e["episode_id"]:
                by_ep.setdefault(e["episode_id"], []).append(e)
        for rows in by_ep.values():
            ct = max(x["ts"] for x in rows) + timedelta(days=float(r.uniform(2, 14))) if r.random() < c.report_prob else None
            for x in rows:
                x["confirm_ts"] = ct
        for e in ev:
            e.setdefault("confirm_ts", None)
            e["drift_active"] = int(pax["drift_day"] is not None and e["ts"] >= self.t0 + timedelta(days=pax["drift_day"]))
        return ev


def generate_universe(cfg: UniverseConfigV4) -> tuple[pd.DataFrame, pd.DataFrame]:
    u = _U(cfg)
    rows = []
    for i in range(cfg.n_passengers):
        rows.extend(u.passenger_events(i))
    ev = pd.DataFrame(rows)
    d = u.d
    idx = ev.pop("driver_idx").to_numpy()
    ev["driver_id"] = d.driver_id.to_numpy()[idx]
    ev["vehicle_type"] = d.vehicle_recorded.to_numpy()[idx]
    ev["driver_type"] = d.driver_type.to_numpy()[idx]
    ev["driver_is_ring"] = (ev["driver_type"] == "ring").astype(int)
    ev = ev.sort_values(["ts", "passenger_id"], kind="mergesort").reset_index(drop=True)
    ev.insert(0, "event_id", [f"V6EV-{u.tag}-{k:07d}" for k in range(len(ev))])
    ev["timestamp"] = [t.isoformat() for t in ev["ts"]]
    # pd.NaT is an instance of datetime, so test for missingness explicitly (V3's "NaT" bug must not recur)
    ev["confirm_timestamp"] = [None if (t is None or pd.isna(t)) else t.isoformat() for t in ev["confirm_ts"]]
    ev["universe"] = cfg.name
    ev["is_synthetic"] = 1
    cols = ["event_id", "universe", "passenger_id", "archetype", "driver_id", "vehicle_type", "vehicle_true",
            "timestamp", "amount", "payment_method", "status", "fraud_label", "scenario", "episode_id",
            "confirm_timestamp", "driver_is_ring", "driver_type", "trip_type", "fraud_account",
            "drift_active", "is_synthetic"]
    return ev[cols], d.drop(columns=["zone"])          # V6: no zone column leaves the generator


def config_dict(cfg: UniverseConfigV4) -> dict:
    return asdict(cfg)
