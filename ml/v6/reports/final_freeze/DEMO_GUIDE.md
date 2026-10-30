# V6 demonstration guide

**Purpose:** show how the frozen V6 reference candidate behaves on hand-made, **synthetic** rides.
**What it is not:** evidence of real-world fraud-detection performance (no real outcomes exist).
**No backend, database, network, real customer data or GPS is used.**

## Run

From `TapGo-ML/experiments/passenger_fraud_v6/`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 reports/final_freeze/run_demo.py
```

The script prints a table and writes `reports/final_freeze/demo_output.json` (full responses). The printed output of
the verified run is saved in `demo_output.txt`. Running it changes no model or artifact. It uses
`integration/inference.py` unchanged and loads `artifacts/passenger_fraud_v6_bundle.joblib`, hash-verified.

The fictional passenger has 80 earlier rides of about ₹100 by auto-rickshaw, mostly at 08–09 and 17–18 h.
Drivers DRV-A and DRV-B alternate, so DRV-A is **familiar** and DRV-NEW is not. The threshold is **0.063318**.
OTP step-up = model flag or the 10-minute rule.

## What to show, and what each case demonstrates (verified output)

| # | Case | Score | Flag | Fare anomaly | Rules | Action | Point |
|---|---|---|---|---|---|---|---|
| 1 | ₹100, familiar driver | 0.004 | no | none | – | none | ordinary ride, no friction |
| 2 | ₹500, unfamiliar driver | 0.485 | **yes** | **high** (≈4.8× typical) | amount | step-up | passenger-relative anomaly |
| 3 | ₹500, **familiar** driver | 0.351 | **yes** | **high** | amount | step-up | **a familiar driver cannot hide the anomaly** (V5's failure). The score is lower than with an unfamiliar driver (allowed context), but the explicit signal is identical and the ride is flagged |
| 3b/3c | familiar ₹200 / ₹300 | 0.336 / 0.351 | yes / yes | high / high | amount | step-up | score never falls as the fare rises (₹100 → 200 → 300 → 500: 0.004 → 0.336 → 0.351 → 0.351) |
| 4 | new passenger, ₹100 | 0.006 | no | none, stage `none` | – | none | explicit cold start: compared with all passengers (`basis = population_prior`), warning given |
| 4b | new passenger, ₹300 | 0.061 | no (just under 0.0633) | none | – | none | with no history, ₹300 is ordinary at population level. **Honest limit:** new-passenger fares are judged only against the population |
| 5 | day commuter at 02:07 | 0.004 | no | none | **night rule fires** | none | the personal night anomaly is reported. It is not in the OTP policy (validation cost 59 legitimate challenges per extra fraud) |
| 5b | habitual night traveller at 02:07 | 0.003 | no | none | night rule does not fire | none | night travellers are not penalised |
| 6/6b/6c | repeat after 599 / 600 / 601 s | 0.001 | no | none | 10-minute rule **T / T / F** | step-up / step-up / none | exact boundary; the reference is the previous **completed** ride |
| 7 | timestamp without timezone | – | – | – | – | `apply_fallback_policy` | `invalid_input`; never assumed UTC; **no score, never "low risk"** |
| 7b | negative amount | – | – | – | – | fallback | `invalid_input` |
| 7c | a `latitude` field supplied | – | – | – | – | fallback | location data is **refused** (no GPS) |
| 7d | same `idempotency_key` again | – | – | – | – | fallback | `duplicate_request`, no score |

## Talking points

- The model **recommends** (`recommended_action`); the backend would decide authorisation and OTP. V6 has no
  approve or reject capability and is **not integrated** with the backend.
- `risk_score` is an uncalibrated ranking score, **not a fraud probability**.
- Every metric in the reports is synthetic. V6 is a reference candidate, **not production-ready**.
