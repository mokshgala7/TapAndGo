# V6 requirements compliance report

**Status:** reference candidate (D1). 6 of 8 acceptance criteria PASS and **2 FAIL** (AC-FA2, AC-FP). All evidence is
synthetic. No real-world fraud validation exists. Not production-ready, not integrated with the backend.

All results are synthetic. "Gate" means the automated check in `training/gates.py`, re-run on the frozen bundle by
`tests/test_requirement_gates.py` (all passed).

| Req | Requirement | V6 status | Evidence | V4 / V5 on the same checks |
|---|---|---|---|---|
| R1 | Passenger-specific fare anomaly, including with a familiar driver | **PASS (functional)** | G1: for passengers at ₹60/₹100/₹250 the score is monotone ×1→×5; ×3 and ×5 are flagged with familiar **and** unfamiliar drivers; the explicit anomaly signal is identical for both. Example ₹100 passenger, familiar driver: scores 0.004 / 0.336 / 0.351 / 0.351 (corrected 2026-10-27; earlier figures were round-1 candidate C4's), levels none / high / high / high. G2: the variable passenger is not flagged at ₹160 | V4 **FAIL** (non-monotone: ₹200 > ₹300). V5 **FAIL** (familiar ₹300/₹500 unflagged). `evaluation/reference_probes.json` |
| R1 (cost) | "A higher fare must not automatically be fraud" | **PARTIAL** | Legitimate long/airport trips are challenged at 23.3% on T3 (V4 9.4%, V5 6.9%). Without trip context the model cannot tell them from overcharges | — |
| R2 | Day/night behaviour | **PASS (functional)** | G3: the night rule fires for the day commuter at 02:00 and not for the night traveller; model score commuter ≥ traveller and 02:00 ≥ 13:00; the traveller is not flagged at 13:00; boundaries 05:59 / 06:00 / 21:59 / 22:00 are correct in IST and UTC input; naive timestamps are refused. Sparse history (5 rides): scored, night rule inactive (needs ≥ 20), warning given | V4 passes only via its rule output; V5 dropped the rule output |
| R3 | 10-minute rule | **PASS (ML experiment)** | G5: 599/600 trigger, 601 does not; a failed ride does not replace the reference (780 s, not triggered); duplicate requests (`idempotency_key` or identical ride) return `duplicate_request` with no score; missing timestamp → `invalid_input`. A legitimate multi-leg ride triggers the rule by design: cost 175 legitimate challenges per extra fraud on T3 | **Backend: NOT IMPLEMENTED** (`qr.py:368-382`); unchanged by V6 |
| R4 | Cold start | **PASS** | G4: n = 0 scored with population basis; ₹500 flagged and ₹100 not, at n = 1, 5, 19, 50 and 150; stages none / insufficient / developing / personal at 0 / 1–19 / 20–99 / ≥ 100. T3 recall at 0 rides is 40.0% vs V4 27.3% and V5 29.1% | V4 passes G4b; V5 fails |
| R5 | Risk scoring only; errors never low risk | **PASS** | G6: every invalid input, prediction exception or NaN returns no score and `apply_fallback_policy`; no approve/reject/OTP methods (test) | — |
| R6 | No GPS / location | **PASS** | G7: no location-like feature or column anywhere; location fields refused at inference; generator writes none | — |
| R7 | Available data only | **PASS** | G8: scorer takes `(transaction, passenger_history)` only; no driver ledger, aggregates, tier B or payment-method features | V5 needs new stored columns and a nightly job |
| — | No future leakage | **PASS** | G9: 0 changed columns over 7,113 rows | — |
| — | Training/inference parity | **PASS** | G10 max diff 0.0 (25 rows); scores identical on 300 T3 rides | — |

## Pre-registered acceptance criteria

| ID | Result | Value |
|---|---|---|
| AC-G all mandatory gates | **PASS** | G1–G10 pass (candidate stage and frozen-bundle tests) |
| AC-GPS | **PASS** | — |
| AC-FA1 deterministic fare-anomaly probes | **PASS** | V6 passes; V4 and V5 fail G1 |
| AC-FA2 familiar-driver fare-anomaly recall on T5 (amount anomaly + overcharge, 1,012 cases) | **FAIL** | V6 13.4% vs V4 19.5% vs V5 25.5% |
| AC-FP T3 legitimate FPR ≤ 2.5% and ≤ V4 + 0.5 pp | **FAIL** | V6 2.17% (≤ 2.5% ✓) but V4 1.55% + 0.5 = 2.05% ✗ |
| AC-REP reproducibility | **PASS** | regeneration identical; refit bit-identical (`evaluation/reproducibility.json`) |
| AC-PAR parity | **PASS** | 0 mismatches / 300; features max diff 0.0 |
| AC-PROT protected files | **PASS for V6** (exception noted) | 404 TapGo-ML files unchanged. The backend status clause is **not met**: backend HEAD unchanged; **the backend working tree changed during this session** (`backend/app/routes/wallet.py` modified 19:49 IST, `backend/tests/test_wallet_security.py` 19:53 IST, +571/−2 lines). V6 issued no backend command (its only backend access was read-only inspection during the earlier audit), so this was another session or person; V6 did not touch or revert it |

Hypotheses (previous targets): H-AC1 0.393, H-AC2 0.199, H-AC3 33.0% and H-AC4 15.2% all **FAIL**, as predicted in
the pre-registration.

## Why AC-FA2 and AC-FP fail, honestly

- **AC-FA2.** 850 of the 1,012 cases are familiar-driver *overcharges* (×1.4–2.6). V4/V5 catch more of them through
  driver-ledger information, which is outside V6's scope. Within passenger-amount anomalies (2–5×) with a familiar
  driver, V6 reaches 45.1%, against 58.6% for V4 and 57.4% for V5.
- **AC-FP.** V6's false positives concentrate on legitimate long and airport trips.
- **Common cause.** Both failures follow from enforcing R1 strictly (monotone, never suppressed) while R6/R7 forbid
  the trip context or driver data that would separate expensive legitimate trips from overcharges.
- **The criteria were not changed after the results.**
