# Data for the V6 fraud model

**Everything here is synthetic.** No real passenger, driver, card, email or ledger row was used. Identifiers look like
`V6PAX-DEV-02617` / `V6DRV-DEV-00324`; every row carries `is_synthetic = 1`. Results computed from this data are
**synthetic/demo-derived, not real-world performance**.

## What is in git

| File | What |
|---|---|
| `sample_transactions.csv` | 1,000 rows drawn from the V6 development data (192 KB), see below |

**The full dataset is NOT stored in git** (the development universe alone is about 70 MB of CSV) to keep the repository small. It is regenerated
deterministically from the seeds below, and you can check you have the same one with the SHA-256 values at the end.

## The sample (`sample_transactions.csv`)

* 1,000 rows from `open_events.csv` of the development universe (train / validation splits only; the sealed test
  labels are never sampled). Sorted by time.
* **100 fraud + 900 legitimate**, i.e. **10% fraud**. The real class ratio is 1.26% (2,177 of 172,364 open rows), so fraud is
  **deliberately over-sampled about 8x** to be visible. Do not compute rates from this sample.
* Stratified by `scenario` (17 scenarios: 7 legitimate kinds and 10 fraud kinds, including `indistinguishable`), fixed seed 20261030.
* Split mix in the sample: train 678, validation_temporal 193, validation_unseen 129.
* All 23 columns of the source file are kept. Checked: all are synthetic (ids, flags, timestamps, amounts), none can be real, so no column was dropped.

## Column dictionary

| Column | Meaning |
|---|---|
| `event_id` | synthetic ride id (`V6EV-DEV-...`) |
| `universe` | which generated universe (`D6_dev`) |
| `passenger_id`, `driver_id` | synthetic ids (`V6PAX-...`, `V6DRV-...`) |
| `archetype` | the synthetic passenger's habit type (for example `night_shift`, `student_budget`) |
| `vehicle_type` | vehicle type as the backend would record it (can be empty: some drivers have none) |
| `vehicle_true` | the generator's true vehicle type (not available to a real backend; not a model input) |
| `timestamp` | ride time, ISO 8601 with the +05:30 offset |
| `amount` | fare in rupees |
| `payment_method` | `NFC`, `QR` or `OTHER` |
| `status` | `completed` or `failed` |
| `fraud_label` | **label**: 1 = fraud, 0 = legitimate |
| `scenario` | the generator scenario that produced the row (`legit_normal`, `card_testing`, `driver_overcharge`, ...) |
| `episode_id`, `confirm_timestamp` | grouping / confirmation time for multi-step scenarios (often empty) |
| `driver_is_ring`, `driver_type`, `trip_type` | generator internals about the driver and trip (`local`, `airport`, ...) |
| `fraud_account`, `drift_active` | generator flags (compromised account; distribution drift active) |
| `is_synthetic` | always 1 |
| `passenger_group`, `split` | which passenger group / data split the row belongs to |

The model itself uses only the backend-available columns (`passenger_id`, `driver_id`, `vehicle_type`, `timestamp`, `amount`,
`payment_method`, `status`, history); the rest are for generation, labelling and analysis (see `ml/v6/features/FEATURE_DICTIONARY.md`).

## The full dataset

Development universe `D6_dev` (generator seed **61001**, passenger-group seed 61002): **234,424 rows**,
2,988 passengers, 750 drivers, **3,025 fraud rows (1.29%)**.

| Part | Rows | Fraud | Use |
|---|---|---|---|
| `open_events.csv`: `train` | 113,852 | 1,418 | training (before 2026-07-01) |
| `open_events.csv`: `validation_temporal` | 36,431 | 474 | validation (July) |
| `open_events.csv`: `validation_unseen` | 22,081 | 285 | validation (passengers never seen in training) |
| `sealed_events.csv`: `test_temporal` | 38,165 | 551 | held out (T1, August), sealed until the model was frozen |
| `sealed_events.csv`: `test_unseen` | 23,895 | 297 | held out (T2, unseen passengers), sealed |

Training also used two extra universes `D6_dr1` / `D6_dr2` (seeds 62001 / 62002). **The final held-out evaluation (T3) uses a
universe generated after the model was frozen:** `D6_fresh` (seed 64001), **238,790 rides, 3,040 fraud (1.27%)**. T4 (shift, seed 65001)
and T5 (scenario set, seed 66001) are generated the same way. Class balance is therefore about 1.2 to 1.3% fraud in every split.

**Regenerate:** `python ml/v6/data/build_datasets.py --stage dev`, then `--stage post_freeze` (seeds are in
`ml/v6/config/experiment_config.json`). The generator is `ml/v6/data/generator_v6.py`. Output goes to `ml/v6/data/synthetic/`
(git-ignored).

## Check you have the same data (SHA-256 of the files in `D6_dev/` and `D6_fresh/`)

| File | Bytes | SHA-256 |
|---|---|---|
| `D6_dev/open_events.csv` | 32,521,485 | `b8a1940e6f2fe9da69130975dbdfba6eff47f5008e1c6f6d928968b365ffe332` |
| `D6_dev/sealed_events.csv` | 12,010,067 | `69d4489f397abb41adb9d3fa162819af5f044453187ccb073a171618ffc36e49` |
| `D6_dev/driver_ledger.csv` | 24,227,319 | `3e60c5775d9c1f6f29e86b37694e54760ab6d083640c17c1ffa5a6550e6b3fbd` |
| `D6_dev/drivers.csv` | 31,372 | `b8b4cfcc5c3e0421b79cdf22d75bc8ecfc3bf5bcd01982c69237ac1d8e8c97ee` |
| `D6_fresh/events.csv` | 47,832,646 | `07a23c7e18ec81027d32ca135dd5f25c599c8f009b844e1d948999d6b57c850b` |

These values were computed from the files on the author's machine and match `dataset_manifest.json` of each universe.
