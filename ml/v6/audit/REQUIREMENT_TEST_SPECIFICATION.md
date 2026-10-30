# Requirement test specification (mandatory gates)

Written before any V6 code, data or model existed. The gates are implemented in `training/gates.py` and run:
- on **every candidate**, at the candidate's own validation threshold, before selection (Stage A)
- again on the **frozen bundle** by `tests/test_requirement_gates.py`

A candidate failing any gate is **ineligible**. Gates are never edited to accommodate a model.

Fixtures are deterministic and built in memory (`training/gates.py: profile()`), independent of every training
dataset:
- "stable ₹M passenger": 80 completed rides over 90 days, fares M·exp(N(0, 0.12)), seed 0
- auto-rickshaw, payment `QR`, day hours {8, 9, 17, 18} unless stated
- drivers alternate D1/D2, so D1 is **familiar**; NEW is unfamiliar
- the transaction is 1 day after the last ride at 12:07 Asia/Kolkata unless stated

## G1: passenger fare anomaly with familiar and unfamiliar drivers (R1)

For each M ∈ {₹60, ₹100, ₹250} and driver ∈ {D1 familiar, NEW unfamiliar}, score fares M × {1, 2, 3, 5}.

| ID | Check | Pass condition |
|---|---|---|
| G1a | Monotonic risk score | score(×1) ≤ score(×2) ≤ score(×3) ≤ score(×5) (tolerance 1e-12) |
| G1b | Explicit passenger anomaly signal (independent of the model) | level `none` at ×1; at least `elevated` at ×2; `high` at ×3 and ×5; z non-decreasing. Identical for familiar and unfamiliar drivers |
| G1c | Recognition | model flag at ×3 and ×5 for **both** drivers (cases C, D) |
| G1d | Ordinary fare | ×1 not flagged for either driver (cases A, E) |
| G1e | Familiarity cannot erase the anomaly | the familiar-driver signal equals the unfamiliar one; familiar ×3 and ×5 are flagged |

## G2: naturally variable passenger (R1, case F)

A variable ₹100 passenger (σ = 0.45, seed 4) against a stable ₹100 passenger, both charged ₹160 (inside the variable
passenger's usual range).

**Pass:**
- variable explicit level ≠ `high`
- variable score ≤ stable score
- variable not flagged

## G3: day/night (R2)

| ID | Setup | Pass condition |
|---|---|---|
| G3a | day commuter (hours 8/9/17/18) vs night traveller (22/23/1/2), ₹100 at 02:07 | night-behaviour rule True for the commuter and False for the traveller; traveller not flagged; score(commuter) ≥ score(traveller) |
| G3b | commuter ₹100 at 02:07 vs 13:07 | score(02:07) ≥ score(13:07) |
| G3c | night traveller ₹100 at 13:07 | not flagged (night travellers are not penalised for day rides) |
| G3d | sparse (5-ride) commuter at 02:07 | scored. The night rule does not fire (it needs ≥ 20 rides, documented). Warning `passenger_history_insufficient_lt20` |
| G3e | boundaries | 05:59 → night, 06:00 → day, 21:59 → day, 22:00 → night (Asia/Kolkata; also given in UTC as +00:00) |
| G3f | naive timestamp (no offset) | `invalid_input`, no score: never assumed UTC |

## G4: cold start (R4)

| ID | Setup | Pass condition |
|---|---|---|
| G4a | n = 0, ₹100 and ₹300 | scored; `history_stage = none`; anomaly `basis = population_prior`; ₹100 not flagged; warning `new_passenger_no_completed_history` |
| G4b | stable ₹100 history with n ∈ {1, 5, 19, 50, 150}, fares ₹100 and ₹500 | ₹500 flagged; ₹100 not flagged; score(₹500) ≥ score(₹100) |
| G4c | stage labels | n = 0 → none; 1–19 → insufficient; 20–99 → developing; ≥ 100 → personal |

## G5: 10-minute rule and request handling (R3)

| ID | Setup | Pass condition |
|---|---|---|
| G5a | previous completed ride, new ride at +599 / +600 / +601 s | triggered True / True / False; `elapsed_seconds` exact |
| G5b | completed ride at 0, failed ride at +8 min, new ride at +13 min | elapsed 780 s, not triggered |
| G5c | transaction `idempotency_key` equal to one in the history | `scoring_status = duplicate_request`, no score, action `apply_fallback_policy` |
| G5d | transaction identical (timestamp, amount, driver) to the last history ride | `duplicate_request` |
| G5e | legitimate multi-leg ride (same driver, +5 min) | rule triggers by design; reported as a false-positive cost, not a failure |
| G5f | missing timestamp | `invalid_input` |

## G6: inference error handling (R5)

Pass condition for every case: never a score, never "low risk", always `apply_fallback_policy`.
- invalid amount, driver or timestamp
- non-list history
- future history
- missing, corrupt or hash-mismatched bundle
- schema mismatch
- prediction raises an exception or returns NaN

## G7: no GPS / location (R6)

**Pass:**
- no feature name or input field matches `gps|lat|lon|latitude|longitude|geo|location|coord|route|distance|zone|airport`
- a transaction or history row containing any such key is refused (`invalid_input`, "location data is not accepted")
- the generator writes no such column

## G8: feature availability (R7)

**Pass:**
- every feature is computable from the transaction and this passenger's earlier ride payments only
- the scorer takes no driver ledger, annotation, market aggregate or tier-B input
- payment-method features are excluded (constant `"QR"` in production)

## G9: no future leakage

Mutating every ride after a cut (amount × 9, driver renamed, labels flipped) leaves every earlier row's features
unchanged.

## G10: training/inference parity

Interface features equal the batch-matrix features on 25 random validation rides (max abs diff ≤ 1e-9); scores
also equal on 300 test rides.

## Reported, not gating

- legitimate multi-leg FPR and rule costs
- subgroup metrics
- latency
