# Distribution shift and generalisation (synthetic)

All V6 test universes were generated **after** the freeze. T1/T2 were sealed until then. V4/V5 are their frozen
models scored on the same rows. ΔAP is a paired passenger-cluster bootstrap, 500 reps.

| Set | Rows / fraud | V6 AP [95% CI] | V6 recall / FPR | V4 AP | V5 AP | ΔAP V6−V4 [CI] | ΔAP V6−V5 [CI] |
|---|---|---|---|---|---|---|---|
| T1 temporal (Aug, panel) | 38,165 / 551 | 0.493 [0.405, 0.567] | 52.5% / 2.19% | 0.509 | 0.552 | −0.017 [−0.043, +0.010] | −0.060 [−0.086, −0.038] |
| T2 unseen passengers | 23,895 / 297 | 0.389 [0.275, 0.496] | 45.1% / 2.28% | 0.432 | 0.470 | −0.043 [−0.078, −0.006] | −0.081 [−0.117, −0.052] |
| T3 fresh universe | 238,790 / 3,040 | 0.440 [0.408, 0.472] | 49.1% / 2.17% | 0.474 | 0.501 | −0.034 [−0.045, −0.022] | −0.061 [−0.070, −0.051] |
| T4 shifted universe (fare ×1.2, schedules +2 h, more missing metadata, half the prevalence, unseen collusive-driver fraud) | 188,941 / 1,415 | 0.199 [0.151, 0.240] | 33.3% / **3.25%** | 0.220 | 0.257 | −0.022 [−0.036, −0.007] | −0.058 [−0.072, −0.047] |
| T5 scenario-focused | 187,186 / 5,331 | 0.389 [0.364, 0.411] | 40.8% / 2.94% | 0.470 | 0.498 | −0.080 [−0.089, −0.070] | −0.109 [−0.118, −0.099] |

Observations:

- **V6 generalises consistently but at a lower level than V4/V5 on every synthetic set.** Only T1 vs V4 is not
  significant.
- **Under shift, V6's FPR rises to 3.25%** (V4 1.85%, V5 1.95%). Fare inflation pushes legitimate fares above
  passengers' historical medians, and a monotone model must react. The shift set's unseen
  `collusive_regular_driver` fraud is caught at 2.3% (4/175).
- **Cold start** (T3 recall by history: 0 / 1–4 / 5–19 / 20–99 / 100+):
  - V6: 40.0 / 48.8 / 47.7 / 48.0 / 52.2%
  - V4: 27.3 / 44.0 / 51.3 / 54.3 / 54.5%
  - V5: 29.1 / 45.2 / 51.7 / 54.6 / 55.7%

  **V6 is best for new passengers (0–4 rides).**
- **Day/night** (T3 night-ride FPR, night-shift vs day-oriented passengers): V6 2.4% / 5.8%, V4 1.8% / 3.8%, V5
  1.2% / 2.6%. V6 penalises unusual night rides for day-oriented passengers more than for habitual night travellers.
  That is the intended direction, with higher absolute false positives.
- The Previous numerical targets (hypotheses) all FAIL on D6:

  | Hypothesis | Target | V6 result |
  |---|---|---|
  | H-AC1 validation AP | ≥ 0.72 | 0.393 |
  | H-AC2 shift AP | ≥ 0.55 | 0.199 |
  | H-AC3 legit-airport FPR | ≤ 10% | 33.0% |
  | H-AC4 overcharge recall | ≥ 85% | 15.2% |

  D6 removes the ring-driver shortcut, so these numbers are not comparable with V4/V5's numbers on D4/D5.
