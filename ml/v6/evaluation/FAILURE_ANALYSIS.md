# Failure analysis (synthetic data)

Sources: `evaluation/final_metrics.json`, `candidates.csv`, `gate_results.json`, `round1/`, `round2/`.

## 1. Candidate failures (Stage A, validation fixtures; before any test data)

| Round | Candidate | Failed gates | Mechanism |
|---|---|---|---|
| 1 | C0 transparent LR | G1, G2, G4 | too few inputs: no flag at ×3 for some profiles |
| 1 | C1 LR (P6) | G3, G4 | linear terms let "night" and "short history" lower risk; LR has no monotonic constraint |
| 1 | C2 Extra Trees (P6) | G1, G3, G4 | **not monotonic in fare** (the same failure class as V5) |
| 1 | C3/C4 XGBoost monotone v1 | G3, G4 | cyclic hour terms made a commuter's 02:00 ride score below their 13:00 ride; history-length terms discounted a ₹500 anomaly after 5 rides |
| 2 | C5 LR, C6/C7 XGBoost monotone v2 | G3, G4 | `night_amount_log_ratio` made slightly cheaper night fares "safer" (−0.18 log-odds vs +0.04 for rarity); `fare_variability` plus shrunk habit shares turned small-sample uncertainty into "variable, so normal" |
| 3 | C8 XGBoost (P6c) | G3, G4 | without familiarity inputs the model mis-ordered the commuter/traveller night cases |
| 3 | **C9 XGBoost (P6c_fam)** | **none** | **selected** |

The lesson repeats the V5 audit: **any free population-level input can cancel a personal anomaly.** Requirements had
to be built into the model structure (monotone constraints), not left to the training data.

## 2. The structural trade-off measured on test data

With trip context out of scope (R6/R7), a legitimately expensive trip and an overcharge look the same from the
passenger's history. V6 is monotone in the passenger-relative fare (that is R1), so it challenges many legitimate
expensive trips:

| T3_fresh (238,790 rides) | V6 | V4 | V5 |
|---|---|---|---|
| Legit long/airport trips challenged (FPR) | **23.3%** | 9.4% | 6.9% |
| Legit normal rides challenged | **0.81%** | 1.02% | 1.02% |
| All legit rides challenged | 2.17% | 1.55% | 1.38% |
| Passenger amount anomaly recall, familiar driver | 43.8% | 51.0% | 44.8% |
| Driver overcharge recall, familiar driver | 9.0% | 16.4% | 18.0% |

V4 and V5 separate legitimate long and airport trips partly through **driver-ledger features**: for example a hub
driver's own price level, or a driver's history of expensive rides. Those same features let a familiar driver
suppress the passenger anomaly; V5 fails the deterministic probes outright, and V4 fails monotonicity. V6 gives them
up by design, and its legitimate-expensive-trip false positives use up the 2% budget. The result is lower recall on
subtle anomalies (overcharge ×1.4–2.6) and lower AP.

## 3. Where V6 misses fraud (T3)

| Scenario | V6 recall | Comment |
|---|---|---|
| card testing | 99.4% | micro-fare signal |
| velocity spree | 72.4% | velocity features |
| passenger amount anomaly (2–5×) | 61.1% | 76.6% unfamiliar / 43.8% familiar driver; the remaining misses sit among legitimate expensive trips |
| off-pattern time | 41.0% | |
| first-ride fraud | 38.4% | **best of the three models** (V4 32.6%, V5 36.0%) |
| unfamiliar takeover | 32.1% | |
| gradual compromise | 19.5% | early ramp rides look normal |
| driver overcharge | 15.2% | ×1.4–2.6 overlaps legitimate fare variation; without driver or trip information it is mostly undetectable |
| quiet compromised | 2.6% | normal fare, hour and habit |
| indistinguishable | 0% | generated like legitimate rides |

## 4. Rules (T3, on top of the model flag)

| Rule | Extra fraud | Extra legit challenges | Legit per extra fraud |
|---|---|---|---|
| 10-minute repeat (in the policy by V1 design) | 33 | 5,766 | **175** |
| amount anomaly (reported only) | 185 | 4,645 | 25 |
| night behaviour (reported only) | 154 | 10,395 | 68 |

With the 10-minute rule, step-up volume rises from 2.8% to 5.2% of rides (FPR 2.17% → 4.62%). It is a product
requirement, and its cost is documented for the backend to decide.
