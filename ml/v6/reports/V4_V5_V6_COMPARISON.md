# V4 vs V5 vs V6 (identical inputs; synthetic)

All three frozen models scored the same V6 rows: V4 and V5 with their own code and thresholds, V5's driver
annotations and market inputs rebuilt from each V6 ledger. V4/V5 were trained on D4/D5 data; V6 on D6.

## Requirement probes (deterministic, `evaluation/reference_probes.json`, `gate_results.json`)

| Probe | V4 | V5 | V6 |
|---|---|---|---|
| G1 fare anomaly (monotone; ×3/×5 flagged, familiar and unfamiliar; ×1 not) | FAIL | FAIL | **PASS** |
| ₹100 passenger, familiar driver, ₹300 / ₹500 | flagged / flagged (but ₹200 0.174 > ₹300 0.132) | **not flagged** (0.008 / 0.070) | flagged / flagged (0.351 / 0.351; corrected from C4's 0.618) |
| G4b cold start (₹500 flagged, ₹100 not, n = 1–150) | PASS | FAIL | **PASS** |
| Rule outputs returned | 10-min, amount, night | 10-min only | 10-min, amount (V6 definition, any history), night |
| Inputs required | passenger + driver history | + per-ride annotations + nightly market median | **passenger history only** |

## Synthetic test performance (frozen thresholds)

| Set | Metric | V4 | V5 | V6 |
|---|---|---|---|---|
| T3 fresh | AP | 0.474 | **0.501** | 0.440 |
| | recall / FPR | 52.8% / 1.55% | 53.5% / 1.38% | 49.1% / 2.17% |
| | precision | 30.5% | 33.4% | 22.6% |
| T4 shift | AP | 0.220 | **0.257** | 0.199 |
| T5 scenario | AP | 0.470 | **0.498** | 0.389 |
| T1 / T2 | AP | 0.509 / 0.432 | **0.552 / 0.470** | 0.493 / 0.389 |
| T3 first rides (0 history) | recall | 27.3% | 29.1% | **40.0%** |
| T3 legit long/airport | FPR | 9.4% | 6.9% | 23.3% |
| T3 legit normal rides | FPR | 1.02% | 1.02% | **0.81%** |

## Reading

- **On synthetic AP, V5 > V4 > V6 everywhere**, and V6 − V5 is significantly negative on every set.
- **V6 is the only model that satisfies the functional requirements**, above all the familiar-driver fare anomaly
  and monotonicity.
- **Most of the AP gap comes from legitimate expensive trips.** V4/V5 use driver-ledger signals to recognise them.
  Those same signals let familiarity override the passenger anomaly.
- **V6 is better for brand-new passengers** and has fewer false alarms on ordinary rides.
- **The decision between them is a product choice,** not a modelling one. Either:
  - accept more OTP challenges on legitimately expensive trips (V6, requirement-compliant), or
  - allow driver data to discount fare jumps (V4/V5, not compliant with R1).
- **Decided (D1, `DECISIONS.md`): the first option.** V6 is the reference candidate. It is not production-ready and has
  no real-world validation.
