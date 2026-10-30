"""
universes.py  –  V6 universe configurations (pre-registration §5).
"""

from __future__ import annotations

import numpy as np

from .generator_v6 import UniverseConfigV4 as Cfg

_D = Cfg("default", 0, 1)

DEV = Cfg("D6_dev", 61001, 3000)
VALSHIFT = Cfg("D6_valshift", 61501, 1200, fare_inflation=1.10, night_boost=0.15, unknown_vehicle_frac=0.12,
               unknown_payment_frac=0.02)

DR_MASTER_SEED, DR_SEEDS = 62000, (62001, 62002)
DR_STARTS = ("2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01")


def _dirichlet(rng, base: dict, conc: float, zero=()) -> dict:
    keys = [k for k in base if k not in zero and base[k] > 0]
    w = rng.dirichlet(np.array([base[k] for k in keys]) * conc)
    out = {k: 0.0 for k in base}
    out.update({k: float(v) for k, v in zip(keys, w)})
    return out


def dr_configs() -> list:
    """Extra training worlds; parameter ranges as pre-registered for V5 §3 (collusive mechanism never enabled)."""
    rng = np.random.default_rng(DR_MASTER_SEED)
    out = []
    for i, seed in enumerate(DR_SEEDS, 1):
        out.append(Cfg(
            f"D6_dr{i}", seed, 1000, start=str(rng.choice(DR_STARTS)),
            fare_inflation=float(rng.uniform(0.85, 1.35)), night_boost=float(rng.uniform(0, 0.30)),
            hour_shift=int(rng.integers(-1, 4)), unknown_vehicle_frac=float(rng.uniform(0.04, 0.25)),
            unknown_payment_frac=float(rng.uniform(0.005, 0.06)), max_other_payment_share=float(rng.uniform(0.02, 0.12)),
            episode_rate=float(rng.uniform(0.002, 0.008)), dishonest_overcharge_rate=float(rng.uniform(0.02, 0.08)),
            fraud_account_frac=float(rng.uniform(0.01, 0.05)), airport_trip_rate=float(rng.uniform(0.008, 0.03)),
            long_trip_rate=float(rng.uniform(0.03, 0.08)),
            archetype_shares=_dirichlet(rng, _D.archetype_shares, 50),
            scenario_weights=_dirichlet(rng, _D.scenario_weights, 30, zero=("collusive_regular_driver",)),
            driver_type_shares=_dirichlet(rng, _D.driver_type_shares, 100)))
    return out


FRESH = Cfg("D6_fresh", 64001, 3000)
SHIFT = Cfg(   # V4's SHIFT parameters (V6 driver types), including the unseen collusive mechanism
    "D6_shift", 65001, 2500, start="2026-05-01", fare_inflation=1.20, night_boost=0.25, hour_shift=2,
    unknown_vehicle_frac=0.20, unknown_payment_frac=0.05, max_other_payment_share=0.10, episode_rate=0.0025,
    fraud_account_frac=0.015, dishonest_overcharge_rate=0.03,
    archetype_shares={"commuter_auto": .15, "commuter_taxi": .10, "evening_social": .22, "night_shift": .15,
                      "occasional": .18, "heavy_user": .08, "student_budget": .12},
    scenario_weights={"passenger_amount_anomaly": .10, "unfamiliar_driver_takeover": .10, "velocity_spree": .08,
                      "card_testing": .06, "off_pattern_time": .16, "quiet_compromised": .16,
                      "gradual_compromise": .10, "indistinguishable": .09, "collusive_regular_driver": .15})
SCENARIO = Cfg(   # boosted coverage for the dedicated subsets (fare anomaly, overcharge, first ride, night, repeats)
    "D6_scenario", 66001, 2500, episode_rate=0.0100, dishonest_overcharge_rate=0.08, fraud_account_frac=0.08,
    airport_trip_rate=0.03, long_trip_rate=0.07, driver_type_shares={"local": .83, "hub": .09, "dishonest": .08},
    scenario_weights={"passenger_amount_anomaly": .22, "unfamiliar_driver_takeover": .08, "velocity_spree": .14,
                      "card_testing": .06, "off_pattern_time": .16, "quiet_compromised": .10,
                      "gradual_compromise": .16, "indistinguishable": .08, "collusive_regular_driver": 0.0})
POST_FREEZE = ((FRESH, "T3_fresh"), (SHIFT, "T4_shift"), (SCENARIO, "T5_scenario"))
