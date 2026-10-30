# Decisions

## D1: accept V6's R1 trade-off; V6 is the reference candidate (2026-10-26, decided by the project owner)

**Decision (user's words):** "Accept V6's trade-off: extra OTP challenges on legitimately expensive trips are
acceptable because OTP is cheap for genuine passengers. Keep V6 as the reference candidate."

**What is accepted.** On synthetic T3, V6 challenges 23.3% of legitimate long/airport trips (V4 9.4%, V5 6.9%) and 2.17%
of all legitimate rides, in exchange for:
- a passenger-specific fare anomaly that is always visible and never suppressed by a familiar driver (R1)
- no trip-context, driver-ledger or location data (R6/R7)

**What does not change:**
- The pre-registered results stand as recorded: AC-FA2 **FAIL**, AC-FP **FAIL**, all hypotheses **FAIL**,
  everything else PASS (`REQUIREMENTS_COMPLIANCE_REPORT.md`). The decision accepts these outcomes; it does not
  re-grade them.
- Model, threshold (0.063318) and step-up policy (model flag or 10-minute rule) are unchanged.
- V4 and V5 stay preserved as references only. V5 remains non-compliant with R1.

**Still open (not covered by D1):**
- The OTP policy for the 10-minute rule (175 legitimate challenges per extra fraud on T3).
- The backend integration and shadow-mode trial, which need separate authorisation.
- Real-outcome validation before any production use. V6 is **not production-ready**.

## D2: operational policy for the 10-minute rule. OPEN: requires an explicit product decision

Nothing was changed: the bundle's policy is still **model + rule** (`step_up_rules: ["rapid_repeat_10min"]`). The
backend implements neither option. Numbers are synthetic; source: `reports/final_freeze/VERIFIED_METRICS.json`.

| | A. Model-only risk scoring | B. Model + independent 10-minute rule (current bundle policy) |
|---|---|---|
| Step-up when | model flag | model flag **or** previous completed ride ≤ 600 s ago |
| T3 rides sent to OTP | 2.77% | 5.20% |
| T3 legitimate rides challenged (FPR) | 2.17% | 4.62% |
| T3 fraud recall | 49.1% | 50.2% |
| T3 precision of challenges | 22.6% | 12.3% |
| Marginal cost of the rule | — | 5,766 extra legitimate challenges for 33 extra frauds (**≈175 per extra fraud**); validation: 1,429 for 9 (≈159) |

- **A** keeps the OTP volume low. The `rapid_repeat_10min` flag is still returned in every response for the backend
  or analysts to see.
- **B** follows the original V1 design (a repeat within 10 minutes triggers verification). It roughly doubles OTP
  volume for about one extra percentage point of recall. Legitimate multi-leg journeys are the main source of the
  extra challenges.
- **Decision owner:** product/backend. Whichever is chosen must be implemented in the backend by separately
  authorised work; the ML model and threshold stay the same in both options.
