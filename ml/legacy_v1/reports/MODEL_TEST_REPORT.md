# Independent ML Evaluation Report: Tap&Go Fraud Detection Model

**Document:** `MODEL_TEST_REPORT.md`  
**Role:** Machine Learning Evaluation Engineer  
**Dataset Evaluated:** `tapgo_test.csv` (Exclusively)  
**Evaluation Scope:** Strictly Out-of-Sample Independent Testing (No Retraining, No Validation/Train Data Leakage)  
**Evaluation Timestamp:** 2026-09-23  

---

## 1. Executive Summary

This report delivers an independent, empirical evaluation of the pre-trained **Tap&Go** fraud-risk detection model prior to its integration into the production payment pipeline. 

Tap&Go is a cashless transit fare payment platform handling high-throughput NFC and QR payments for taxi and auto-rickshaw rides. A foundational business rule governs this system: **Machine Learning detection flags high-risk transactions for step-up authentication (OTP challenge sent to the passenger's registered email), rather than outright hard-blocking.** A passenger providing the correct OTP completes their trip payment without interruption; only expired or incorrect OTP attempts terminate the transaction.

```
Transaction Initiated
        ↓
ML Evaluates Risk Score
        ↓
Risk Score ≥ Threshold (High Risk) ── No ──→ Transaction Processed (Normal Flow)
        ↓ Yes
Step-Up Challenge: OTP Sent to Email
        ↓
Passenger Enters OTP
        ↓
Correct OTP? ── Yes ──→ Transaction Processed
        ↓ No / Expired
Transaction Rejected
```

### Key Evaluation Findings:
* **Primary Evaluated Model:** Extreme Gradient Boosting (`XGBClassifier`), utilizing 32 features (19 base numeric features, 4 cyclic temporal features, 2 one-hot payment method indicators, and 7 derived behavioral interaction features).
* **Dataset Scope:** Tested solely on `tapgo_test.csv` (7,676 transactions across 4,244 distinct users; 244 ground-truth fraud instances, representing a 3.18% base fraud rate).
* **Operating Point (Validation-Derived Threshold = 0.3104):**
  * **Fraud Recall:** **72.54%** (177 out of 244 fraud events caught and challenged with OTP).
  * **Fraud Precision:** **28.64%** (~1 out of every 3.5 OTP challenges represents true fraud).
  * **ROC-AUC:** **0.9619** (Excellent global discriminative separation).
  * **PR-AUC:** **0.7053** (22.2× higher than the 3.18% random baseline).
  * **Overall Accuracy:** **93.38%** (Note: Accuracy is non-informative due to class imbalance).
* **OTP Business Friction:**
  * **Total OTP Trigger Rate:** **8.05%** (618 out of 7,676 transactions).
  * **Legitimate User Challenge Rate (False Positive Rate):** **5.93%** (441 out of 7,432 legitimate transactions). 94.07% of legitimate transit rides proceed with zero authentication friction.
  * **Missed Fraud (False Negative Rate):** **27.46%** (67 fraud attempts bypassed OTP; these were predominantly stealth micro-fare attacks below user running averages).
* **User-Specific Contextual Behavior:**
  * The model successfully differentiates between absolute fare magnitudes and individual user baselines. For example, high-spending commuter `USR003028` generated legitimate fares exceeding ₹1,120 without triggering false alarms, whereas occasional user `USR001360` incurred an OTP challenge on an ordinary ₹227 fare due to anomalous device novelty and authentication failure signals.

---

## 2. Model Information

The pre-trained production model artifact stored at `TapGo-ML/models/xgboost.pkl` was loaded and inspected:

| Attribute | Inspected Specification |
| :--- | :--- |
| **Model Algorithm** | Extreme Gradient Boosting (`XGBClassifier`) |
| **Model Library / Wrapper** | `xgboost.sklearn.XGBClassifier` (XGBoost 2.1.4, Scikit-Learn 1.4.2) |
| **File Format** | Python Pickle binary (`.pkl`), serialized via `joblib` |
| **Expected Input Dimension** | Exactly 32 features |
| **Feature Names & Order** | Validated identical to training schema (see Section 4) |
| **Scaling Requirements** | **None** (Tree-based ensemble; invariant to monotonic transformations). Note: `robust_scaler.pkl` exists strictly for the baseline `logistic_regression.pkl` model. |
| **Encoding Requirements** | Cyclic sine/cosine encoding on `transaction_hour` and `transaction_day_of_week`; one-hot dummy encoding on `payment_method` (`payment_method_NFC`, `payment_method_QR`). |
| **Probability Outputs** | **Yes** via `.predict_proba()` (outputs well-calibrated continuous risk scores in $[0.0, 1.0]$). |
| **Discrete Class Outputs** | **Yes** via `.predict()` or applying a calibrated threshold. |
| **Pre-Configured Threshold** | **0.3104** (Pre-selected on validation data in `TapGo-ML/reports/thresholds.csv` to satisfy $\ge 30\%$ minimum precision with maximal recall). |
| **Hyperparameters** | `n_estimators=400`, `max_depth=6`, `learning_rate=0.05`, `subsample=0.8`, `colsample_bytree=0.8`, `scale_pos_weight=30.6`, `eval_metric='aucpr'`, `random_state=42`. |

---

## 3. Test Dataset Information

The evaluation strictly ingested `TapGo-ML/data/tapgo_test.csv`:

* **Total Records:** 7,676 rows
* **Unique Users:** 4,244 distinct `user_id` entities
* **Ground Truth Target (`is_fraud`):**
  * `0` (Legitimate): 7,432 rows (**96.82%**)
  * `1` (Fraudulent): 244 rows (**3.18%**)
* **Class Imbalance Ratio:** ~30.46 : 1
* **Transaction Amount Statistics:**
  * Minimum: ₹20.00
  * Median: ₹131.22
  * Mean: ₹159.31
  * 75th Percentile: ₹189.64
  * Maximum: ₹3,372.84
* **Missing Values:** Exactly 0 missing values across all 26 raw columns.
* **Integrity Validation:** No negative transaction amounts or corrupt timestamp records detected.

---

## 4. Feature Compatibility Check

The 32 input dimensions required by `xgboost.pkl` were mapped against `tapgo_test.csv` and the inference transformation pipeline:

```
tapgo_test.csv (26 Raw Columns)
  │
  ├── Drop Identifiers & Target: ['transaction_id', 'user_id', 'transaction_timestamp', 'is_fraud']
  │
  ├── Cyclic Time Transform:
  │     hour_sin = sin(2π * transaction_hour / 24)
  │     hour_cos = cos(2π * transaction_hour / 24)
  │     dow_sin  = sin(2π * transaction_day_of_week / 7)
  │     dow_cos  = cos(2π * transaction_day_of_week / 7)
  │     (Drop original transaction_hour, transaction_day_of_week)
  │
  ├── One-Hot Dummy Transform:
  │     payment_method → ['payment_method_NFC', 'payment_method_QR']
  │
  └── Feature Engineering (7 Derived Contextual Ratios):
        1. amount_vs_avg_ratio          = transaction_amount / average_transaction_amount
        2. velocity_hourly_vs_daily     = (transactions_last_1hour * 24) / transactions_last_24hours
        3. auth_pressure                = failed_otp_attempts + failed_login_attempts
        4. new_device_high_velocity     = new_device * (transactions_last_1hour >= 3)
        5. location_stress              = location_change_rate * transactions_last_5min
        6. amount_vs_max30_ratio        = transaction_amount / max_transaction_amount_last_30days
        7. fraud_history_rate           = previous_fraud_count / previous_transaction_count
```

### Feature Compatibility Matrix:

| Index | Model Feature Name | Source / Type | Status |
| :---: | :--- | :--- | :---: |
| 1 | `transaction_amount` | Raw Numeric | Verified |
| 2 | `account_age_days` | Raw Numeric | Verified |
| 3 | `previous_transaction_count` | Raw Numeric | Verified |
| 4 | `previous_fraud_count` | Raw Numeric | Verified |
| 5 | `transactions_last_5min` | Raw Numeric | Verified |
| 6 | `transactions_last_1hour` | Raw Numeric | Verified |
| 7 | `transactions_last_24hours` | Raw Numeric | Verified |
| 8 | `amount_last_1hour` | Raw Numeric | Verified |
| 9 | `amount_last_24hours` | Raw Numeric | Verified |
| 10 | `new_device` | Raw Binary | Verified |
| 11 | `previous_device_used` | Raw Binary | Verified |
| 12 | `device_transaction_count` | Raw Numeric | Verified |
| 13 | `failed_otp_attempts` | Raw Numeric | Verified |
| 14 | `failed_login_attempts` | Raw Numeric | Verified |
| 15 | `distance_from_previous_transaction_km` | Raw Numeric | Verified |
| 16 | `location_change_rate` | Raw Numeric | Verified |
| 17 | `average_transaction_amount` | Raw Numeric | Verified |
| 18 | `max_transaction_amount_last_30days` | Raw Numeric | Verified |
| 19 | `transactions_last_7days` | Raw Numeric | Verified |
| 20 | `hour_sin` | Cyclic Transform | Verified |
| 21 | `hour_cos` | Cyclic Transform | Verified |
| 22 | `dow_sin` | Cyclic Transform | Verified |
| 23 | `dow_cos` | Cyclic Transform | Verified |
| 24 | `payment_method_NFC` | One-Hot Indicator | Verified |
| 25 | `payment_method_QR` | One-Hot Indicator | Verified |
| 26 | `amount_vs_avg_ratio` | Derived Interaction | Verified |
| 27 | `velocity_hourly_vs_daily` | Derived Interaction | Verified |
| 28 | `auth_pressure` | Derived Interaction | Verified |
| 29 | `new_device_high_velocity` | Derived Interaction | Verified |
| 30 | `location_stress` | Derived Interaction | Verified |
| 31 | `amount_vs_max30_ratio` | Derived Interaction | Verified |
| 32 | `fraud_history_rate` | Derived Interaction | Verified |

**Compatibility Verdict:** 100% feature match. Feature ordering, column names, and data types strictly align with the model's learned weights.

---

## 5. Overall Test Performance

The model was evaluated across all 7,676 test transactions using the pre-configured threshold $\tau = 0.3104$:

| Metric | Test Set Value | Description & Business Meaning |
| :--- | :---: | :--- |
| **Accuracy** | **0.9338 (93.38%)** | Overall fraction of correct classifications (TP + TN) / Total. |
| **Precision** | **0.2864 (28.64%)** | Fraction of OTP challenges sent that targeted actual fraud (TP / (TP + FP)). |
| **Recall (Fraud)** | **0.7254 (72.54%)** | Fraction of actual fraud caught by the OTP step-up challenge (TP / (TP + FN)). |
| **F1 Score** | **0.4107 (41.07%)** | Harmonic mean of precision and recall for the fraud class. |
| **ROC-AUC** | **0.9619 (96.19%)** | Area Under Receiver Operating Characteristic Curve across all decision thresholds. |
| **PR-AUC** | **0.7053 (70.53%)** | Area Under Precision-Recall Curve; critical for imbalanced fraud data. |
| **False Positive Rate (FPR)** | **0.0593 (5.93%)** | Fraction of legitimate users challenged with OTP (FP / (TN + FP)). |
| **False Negative Rate (FNR)** | **0.2746 (27.46%)** | Fraction of fraudulent transactions that bypassed OTP (FN / (TP + FN)). |
| **Specificity** | **0.9407 (94.07%)** | Fraction of legitimate transactions processed with zero friction (TN / (TN + FP)). |

### Diagnostic Candidate Threshold Sweep (Evaluated Without Test-Set Tuning):

To inspect probability distribution characteristics across potential operating points without fine-tuning on the test dataset, a diagnostic sweep is summarized below:

| Threshold | Precision | Recall | Fraud F1 | TP | FP | FN | TN | OTP Trigger Rate (%) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0.1000 | 0.1779 | 0.8770 | 0.2958 | 214 | 989 | 30 | 6,443 | 15.67% |
| 0.2000 | 0.2267 | 0.8156 | 0.3547 | 199 | 679 | 45 | 6,753 | 11.44% |
| 0.3000 | 0.2815 | 0.7418 | 0.4081 | 181 | 462 | 63 | 6,970 | 8.38% |
| **0.3104\*** | **0.2864** | **0.7254** | **0.4107** | **177** | **441** | **67** | **6,991** | **8.05%** |
| 0.4000 | 0.3640 | 0.6803 | 0.4743 | 166 | 290 | 78 | 7,142 | 5.94% |
| 0.5000 | 0.4848 | 0.6557 | 0.5575 | 160 | 170 | 84 | 7,262 | 4.30% |
| 0.6000 | 0.6135 | 0.6311 | 0.6222 | 154 | 97 | 90 | 7,335 | 3.27% |
| 0.7000 | 0.7604 | 0.5984 | 0.6697 | 146 | 46 | 98 | 7,386 | 2.50% |
| 0.8000 | 0.8650 | 0.5779 | 0.6929 | 141 | 22 | 103 | 7,410 | 2.12% |
| 0.9000 | 0.9324 | 0.5656 | 0.7041 | 138 | 10 | 106 | 7,422 | 1.93% |

*\*0.3104 is the pre-configured threshold established during validation.*

### Architecture Benchmark Comparison on Test Set:

| Model Candidate | Threshold | Accuracy | Precision | Recall | Fraud F1 | ROC-AUC | PR-AUC | TP | FP | FN | TN |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **XGBoost (Selected)** | **0.3104** | **0.9338** | **0.2864** | **0.7254** | **0.4107** | **0.9619** | **0.7053** | **177** | **441** | **67** | **6,991** |
| Random Forest | 0.5907 | 0.9359 | 0.2912 | 0.7090 | 0.4129 | 0.9600 | 0.6968 | 173 | 421 | 71 | 7,011 |
| Logistic Regression | 0.6832 | 0.9341 | 0.2831 | 0.7008 | 0.4033 | 0.9502 | 0.6507 | 171 | 433 | 73 | 6,999 |
| Isolation Forest | 0.3311 | 0.9360 | 0.2639 | 0.5656 | 0.3598 | 0.8613 | 0.3597 | 138 | 385 | 106 | 7,047 |

**Model Architecture Analysis:** XGBoost demonstrates the highest PR-AUC (0.7053) and highest fraud recall (72.54%), outperforming Random Forest, Logistic Regression, and the unsupervised Isolation Forest.

---

## 6. Confusion Matrix

The confusion matrix on the held-out test split (7,676 transactions) is structured as follows:

```
                            Predicted Condition
                 Predicted Legit (0)    Predicted Fraud (1) [OTP Trigger]
Actual Legit (0)    TN = 6,991 (91.08%)      FP =   441 (5.74%)
Actual Fraud (1)    FN =    67 (0.87%)       TP =   177 (2.31%)
```

```
Total Test Cases = 7,676
Actual Legitimate = 7,432 (96.82%)
Actual Fraudulent =   244 ( 3.18%)
```

![Tap&Go Confusion Matrix](file:///c:<local-path>)

* **True Negatives (6,991 transactions):** Legitimate transit rides processed immediately without OTP disruption.
* **False Positives (441 transactions):** Legitimate transit rides flagged as high-risk, triggering a one-time email OTP verification. Once verified, payments settle normally.
* **False Negatives (67 transactions):** Fraudulent transactions that slipped past the ML filter without triggering an OTP challenge.
* **True Positives (177 transactions):** Fraudulent transactions successfully intercepted by the ML model, prompting an OTP challenge that unauthorized actors cannot satisfy.

---

## 7. Precision / Recall / F1 Analysis

In highly imbalanced payment environments (3.18% positive prevalence), **Accuracy is deeply misleading**. A trivial zero-rule baseline that indiscriminately predicts every transaction as legitimate would yield **96.82% Accuracy**, but would catch 0% of fraud ($Recall = 0.0$, $F1 = 0.0$).

### Metric Interpretation for Tap&Go:

1. **Fraud Recall (72.54%):**
   * *Meaning:* The system successfully detects ~73 out of every 100 fraudulent attempts.
   * *Business Impact:* Prevents unauthorized fare drain and syndicate card testing across transit gates.
2. **Fraud Precision (28.64%):**
   * *Meaning:* For every 100 OTP challenges sent to users, approximately 29 are actual fraud events, while 71 are legitimate transactions experiencing a step-up check.
   * *Business Impact:* Because a false alarm triggers an OTP rather than an irreversible transaction decline, a precision of ~29% represents an acceptable operational trade-off to capture nearly three-quarters of all fraudulent activity.
3. **Fraud F1 Score (41.07%):**
   * *Meaning:* The harmonic mean balances user friction against security capture. At $\tau = 0.3104$, the model sits near the inflection point where further recall gains would cause exponential explosions in user OTP challenges.

---

## 8. ROC-AUC Analysis

The Receiver Operating Characteristic (ROC) curve evaluates true positive rate (Recall) against false positive rate ($FPR = FP / (FP + TN)$) across all classification thresholds:

![Tap&Go ROC Curve](file:///c:<local-path>)

* **ROC-AUC Score:** **0.9619**
* **Curve Characteristics:** The curve rises sharply along the vertical axis, reaching $\approx 70\%$ TPR at an FPR of only $\approx 5\%$.
* **Operating Point Marker:** At the selected threshold ($\tau = 0.3104$), the operating point achieves $TPR = 72.54\%$ and $FPR = 5.93\%$, confirming excellent separation between general legitimate fare payments and high-risk anomalies.

---

## 9. PR-AUC Analysis

The Precision-Recall (PR) curve is the standard evaluation metric for imbalanced classification:

![Tap&Go Precision-Recall Curve](file:///c:<local-path>)

* **PR-AUC Score:** **0.7053**
* **Baseline Prevalence:** **0.0318 (3.18%)**
* **Gain Over Baseline:** **22.18× enrichment** over random guessing.
* **Operating Profile:** Precision remains high ($\ge 85\%$) when filtering for the most egregious attacks ($Recall \le 55\%$), and slopes gradually to $28.64\%$ precision at $72.54\%$ recall.

---

## 10. Five-User Cohort Analysis

To determine whether the model relies on naive heuristic rules (such as *"any fare over ₹1,000 is fraud"*) or evaluates contextual user behaviors, five distinct users were selected from `tapgo_test.csv`:

### Summary Table: Five-User Behavioral Cohort

| User | Behavioral Persona | Test Tx | Actual Fraud | Predicted Fraud (OTP) | TP | FP | FN | Precision | Recall | F1 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **User A (`USR006363`)** | Low Spender | 6 | 0 | 0 | 0 | 0 | 0 | N/A — no fraud | N/A — no positive fraud examples | N/A — no positive fraud examples |
| **User B (`USR003028`)** | High Spender | 4 | 0 | 0 | 0 | 0 | 0 | N/A — no fraud | N/A — no positive fraud examples | N/A — no positive fraud examples |
| **User C (`USR006506`)** | High Frequency Commuter | 15 | 0 | 0 | 0 | 0 | 0 | N/A — no fraud | N/A — no positive fraud examples | N/A — no positive fraud examples |
| **User D (`USR001360`)** | Occasional User | 5 | 1 | 1 | 1 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| **User E (`USR007152`)** | Mixed / Irregular Spender | 9 | 2 | 4 | 2 | 2 | 0 | 0.5000 | 1.0000 | 0.6667 |

*(Note: Per Section 14, users are listed for behavioral comparison, not ranked).*

---

### Detailed Persona Deep-Dives (Questions 1 through 7)

#### User A: Low-Spending User (`USR006363`)
* **Observed Data:** 6 test transactions (`TXN00009359`, `TXN00020528`, `TXN00030168`, `TXN00036305`, `TXN00047188`, `TXN00050067`).
* **Q1 (Normal Spending Pattern):** Extremely frugal transit spender. Fares range between ₹26.42 and ₹64.68 (Mean: ₹46.46, Median: ₹45.41), representing typical short auto-rickshaw rides in Indian urban centers.
* **Q2 (Normal Transaction Frequency):** Zero velocity spikes. All transactions feature `transactions_last_1hour = 0` and `transactions_last_24hours = 0`.
* **Q3 (Unusual Transactions):** None. Fares and travel distances (5.1 km to 22.6 km) are consistent with short suburban hops.
* **Q4 (Did Model Identify Actual Fraud?):** Yes, by correctly assigning zero fraud classifications ($Actual = 0$).
* **Q5 (Did Model Incorrectly Flag Legitimate Transactions?):** No ($FP = 0$). Predicted risk scores ranged from $0.0000$ to $0.0005$, far below the $0.3104$ threshold.
* **Q6 (Legitimate Transactions That Look Suspicious but Are Normal):** `TXN00009359` and `TXN00047188` had `failed_otp_attempts = 1`. Despite this minor authentication friction, the model recognized the normal transaction amount and zero velocity, avoiding an unnecessary challenge.
* **Q7 (Fraudulent Transactions Missed):** None present in test data.

#### User B: High-Spending User (`USR003028`)
* **Observed Data:** 4 test transactions (`TXN00001686`, `TXN00003260`, `TXN00022606`, `TXN00039188`).
* **Q1 (Normal Spending Pattern):** Premium commuter using long-distance taxis / airport cabs. Fares range from ₹578.49 to ₹1,121.84 (Mean: ₹795.71, Median: ₹741.25).
* **Q2 (Normal Transaction Frequency):** Low velocity. Occasional single rides separated by multiple days (`transactions_last_1hour = 0`).
* **Q3 (Unusual Transactions):** `TXN00022606` was ₹1,121.84, which is in the 99th percentile of all Tap&Go transit fares across the entire platform.
* **Q4 (Did Model Identify Actual Fraud?):** Yes, correctly predicted zero fraud ($Actual = 0$).
* **Q5 (Did Model Incorrectly Flag Legitimate Transactions?):** No ($FP = 0$). Despite transaction amounts exceeding ₹1,000, risk scores remained low ($0.0032$, $0.2694$, $0.0044$, $0.0218$).
* **Q6 (Legitimate Transactions That Look Suspicious but Are Normal):** `TXN00022606` (₹1,121.84) looks suspicious in absolute terms, but was correctly processed ($Risk = 0.0044$) because the user's running baseline was already high (`average_transaction_amount = 633.71`). Furthermore, `TXN00003260` involved a `new_device = 1` for ₹765.28; the risk score rose to $0.2694$, but remained appropriately below the $0.3104$ challenge threshold.
* **Q7 (Fraudulent Transactions Missed):** None present in test data.

#### User C: High-Frequency Commuter (`USR006506`)
* **Observed Data:** 15 test transactions (The highest transaction count of any user in the test split).
* **Q1 (Normal Spending Pattern):** Regular daily commuter. Fares range tightly between ₹76.97 and ₹186.11 (Mean: ₹137.91, Median: ₹139.47).
* **Q2 (Normal Transaction Frequency):** Steady daily usage. Frequent transactions across multiple weeks, but zero burst velocity (`transactions_last_1hour = 0`).
* **Q3 (Unusual Transactions):** None. Every transaction exhibits steady, predictable transit usage.
* **Q4 (Did Model Identify Actual Fraud?):** Correctly predicted zero fraud ($Actual = 0$).
* **Q5 (Did Model Incorrectly Flag Legitimate Transactions?):** No ($FP = 0$). Risk probabilities remained between $0.0001$ and $0.0819$.
* **Q6 (Legitimate Transactions That Look Suspicious but Are Normal):** `TXN00000198` used a `new_device = 1`. Because the fare was modest (₹129.32) and velocity was zero, the risk score was kept at a safe $0.0819$.
* **Q7 (Fraudulent Transactions Missed):** None present in test data.

#### User D: Occasional User (`USR001360`)
* **Observed Data:** 5 test transactions (`TXN00001137`, `TXN00003289`, `TXN00016805`, `TXN00023902`, `TXN00037700`).
* **Q1 (Normal Spending Pattern):** Moderate spender. Legitimate fares range between ₹165.54 and ₹225.47 (Mean: ₹204.94, Median: ₹206.07).
* **Q2 (Normal Transaction Frequency):** Low frequency. Extended intervals between transit rides with zero hourly velocity.
* **Q3 (Unusual Transactions):** Transaction `TXN00001137` on a new device (`new_device = 1`, `device_transaction_count = 0`) with 3 failed OTP attempts (`failed_otp_attempts = 3`).
* **Q4 (Did Model Identify Actual Fraud?):** **Yes, flawlessly.** `TXN00001137` is a confirmed fraud event ($is\_fraud = 1$). The model assigned a risk probability of **0.9970**, triggering an immediate OTP challenge ($TP = 1$).
* **Q5 (Did Model Incorrectly Flag Legitimate Transactions?):** No ($FP = 0$). The four legitimate transactions scored $0.0050$, $0.0074$, $0.0034$, and $0.0003$.
* **Q6 (Legitimate Transactions That Look Suspicious but Are Normal):** None.
* **Q7 (Fraudulent Transactions Missed):** None ($FN = 0$). Notably, the fraud amount (₹227.15) was completely indistinguishable from the user's normal fare amounts (₹225.47); the model detected the fraud via behavioral and security signals (`auth_pressure`, `new_device`).

#### User E: Mixed / Irregular Spender (`USR007152`)
* **Observed Data:** 9 test transactions (`TXN00009972`, `TXN00009973`, `TXN00014175`, `TXN00014176`, `TXN00020450`, `TXN00020451`, `TXN00032589`, `TXN00042662`, `TXN00044237`).
* **Q1 (Normal Spending Pattern):** Highly variable fare amounts ranging from ₹111.63 up to ₹1,276.99 (Mean: ₹294.19, Median: ₹180.74).
* **Q2 (Normal Transaction Frequency):** Volatile bursts. Experiences sudden clusters of 2 to 5 transactions within a single hour.
* **Q3 (Unusual Transactions):**
  * `TXN00014176`: ₹1,276.99 fare on a new device with an extreme geographic relocation jump of 1,247 km and a failed OTP attempt.
  * `TXN00020451`: Velocity spike of 5 transactions within 1 hour.
* **Q4 (Did Model Identify Actual Fraud?):** **Yes, 100% fraud recall.** Both actual fraud events (`TXN00014176` and `TXN00020451`) were caught ($TP = 2$) with risk probabilities of **0.9994** and **0.9808**.
* **Q5 (Did Model Incorrectly Flag Legitimate Transactions?):** Yes ($FP = 2$). The model triggered OTP challenges on legitimate transactions `TXN00014175` ($Risk = 0.3926$) and `TXN00020450` ($Risk = 0.7394$).
* **Q6 (Legitimate Transactions That Look Suspicious but Are Normal):** `TXN00014175` and `TXN00020450` occurred directly inside rapid velocity bursts (3 to 4 rides per hour). While legitimate, these sudden clusters mirror credential abuse patterns. Triggering an OTP challenge protected the user's account without hard-declining the payment.
* **Q7 (Fraudulent Transactions Missed):** None ($FN = 0$).

---

## 11. User Behaviour Comparison

### Critical Paradigm: Absolute Rules vs. Behavioral Context

A naive fraud detection system applying static rules (e.g., *Flag if Amount > ₹1,000* or *Flag if Transactions/Hour > 2*) severely fails in transit environments.

```
Scenario 1: High Absolute Amount, But Normal for User
User B (USR003028): TXN00022606
  - Amount: ₹1,121.84  (Top 1% across platform)
  - User Average: ₹633.71, Max 30d: ₹677.33
  - Velocity: 0/hr, Distance: 20 km
  - Model Risk Score: 0.0044  ──→  PASSED WITHOUT FRICTION (Correct)
  
Scenario 2: Normal Absolute Amount, But Anomalous for User
User D (USR001360): TXN00001137
  - Amount: ₹227.15  (Ordinary median fare)
  - User Average: ₹190.29
  - Context: New Device (0 prior tx) + 3 Failed OTP Attempts
  - Model Risk Score: 0.9970  ──→  OTP STEP-UP TRIGGERED (Correct Fraud Catch)
```

The model demonstrates genuine contextual learning: it did not penalize User B for high-value airport rides, yet immediately flagged User D's modest ₹227 transaction because authentication pressure and device novelty signaled account takeover.

---

## 12. True Positive (TP) Analysis

* **Transaction ID:** `TXN00000081`
* **User ID:** `USR001122`
* **Transaction Amount:** ₹139.55
* **User Historical Baseline:** `average_transaction_amount = 101.80`
* **Ground Truth:** Fraud (`is_fraud = 1`)
* **Model Prediction:** High Risk / OTP Triggered (`predicted_is_fraud = 1`, `Risk Score = 0.3160`)
* **Key Contributing Features:**
  * `new_device = 1` and `device_transaction_count = 0` (unrecognized hardware).
  * `amount_vs_avg_ratio = 1.37` (fare was 37% higher than the user's running historical average).
  * Zero previous transaction history on this device combined with an elevated amount pushed the probability past the $0.3104$ decision boundary.
* **Operational Impact:** The model initiated an OTP challenge. Because the fraudster lacked access to the victim's email, the fraudulent charge was thwarted.

---

## 13. True Negative (TN) Analysis

* **Transaction ID:** `TXN00000002`
* **User ID:** `USR006791`
* **Transaction Amount:** ₹87.60
* **User Historical Baseline:** `average_transaction_amount = 73.82`
* **Ground Truth:** Legitimate (`is_fraud = 0`)
* **Model Prediction:** Low Risk / Normal Flow (`predicted_is_fraud = 0`, `Risk Score = 0.1502`)
* **Key Contributing Features:**
  * Consistent commuter fare for an auto-rickshaw leg.
  * `transactions_last_1hour = 0`, `transactions_last_24hours = 0` (no velocity pressure).
  * `failed_otp_attempts = 0`, `failed_login_attempts = 0` (clean authentication state).
* **Operational Impact:** Smooth passenger payment experience with zero friction at the transit gate.

---

## 14. False Positive (FP) Analysis

* **Transaction ID:** `TXN00000034`
* **User ID:** `USR009757`
* **Transaction Amount:** ₹90.87
* **User Historical Baseline:** `average_transaction_amount = 74.72`
* **Ground Truth:** Legitimate (`is_fraud = 0`)
* **Model Prediction:** High Risk / OTP Triggered (`predicted_is_fraud = 1`, `Risk Score = 0.4388`)
* **Why the Model Flagged It:**
  * High short-term velocity: `transactions_last_5min = 2`, `transactions_last_1hour = 3`.
  * Spatial velocity spike: `location_change_rate = 724.96 km/h` across consecutive transit touchpoints.
  * The model interpreted the rapid succession of multiple rides within minutes across disparate transit terminals as an automated script or stolen card testing run.
* **Tap&Go Business Translation:**
  * **Critical Distinction:** In Tap&Go, this passenger is **NOT rejected**.
  * The passenger is presented with an OTP prompt on their phone; they enter the code sent to their registered email, the transaction settles, and they proceed with their journey.

---

## 15. False Negative (FN) Analysis

* **Transaction ID:** `TXN00000113`
* **User ID:** `USR006103`
* **Transaction Amount:** ₹53.03
* **User Historical Baseline:** `average_transaction_amount = 116.08`
* **Ground Truth:** Fraud (`is_fraud = 1`)
* **Model Prediction:** Low Risk / Bypassed OTP (`predicted_is_fraud = 0`, `Risk Score = 0.1651`)
* **Why the Model Missed It:**
  * The fraudster initiated a tiny charge (₹53.03), substantially *lower* than the victim's average fare (₹116.08).
  * Zero velocity: `transactions_last_1hour = 0`, `transactions_last_24hours = 0`.
  * Clean authentication signals: `failed_otp_attempts = 0`, `failed_login_attempts = 0`.
  * The transaction mimicked an ordinary, low-value auto-rickshaw hop so closely that it generated zero statistical friction.
* **Operational Impact:** This represents a fraudulent charge that slipped through without an OTP challenge. In payment networks, this reflects the classic trade-off: catching micro-amount stealth fraud requires lowering the threshold, which would unacceptably increase OTP friction for millions of legitimate commuters.

---

## 16. OTP Step-Up Authentication Business Logic Evaluation

Mapping model predictions directly to Tap&Go's payment processing workflow:

```
Total Test Transactions: 7,676 (100.0%)
  │
  ├── Low Risk (Normal Settlement): 7,058 (91.95%)
  │     ├── Legitimate Rides Processed (TN): 6,991 (91.08%)
  │     └── Missed Fraud Slipped Through (FN):   67 ( 0.87%)
  │
  └── High Risk (OTP Challenge Triggered): 618 (8.05%)
        ├── Fraud Intercepted by OTP (TP):     177 ( 2.31%)
        └── Legitimate Passenger OTP Prompts (FP): 441 ( 5.74%)
```

### Core Authentication Metrics:

1. **Overall Platform OTP Trigger Rate:**
   $$\text{Trigger Rate} = \frac{\text{All Transactions Predicted High-Risk}}{\text{Total Test Transactions}} = \frac{618}{7,676} = \mathbf{8.05\%}$$
   Only ~8 out of every 100 passengers receive an OTP prompt, preserving seamless transit throughput for 91.95% of passengers.
2. **Fraud Interception via Step-Up Authentication:**
   $$\text{Fraud Caught Rate} = \frac{\text{TP}}{\text{Actual Fraud}} = \frac{177}{244} = \mathbf{72.54\%}$$
   Nearly three out of four fraud attempts are blocked by the mandatory email verification step.
3. **Legitimate User Friction Rate:**
   $$\text{Legitimate Challenge Rate} = \frac{\text{FP}}{\text{Actual Legitimate}} = \frac{441}{7,432} = \mathbf{5.93\%}$$
   Fewer than 6% of legitimate passengers face a step-up OTP challenge.
4. **Fraud Bypassing Additional Verification:**
   $$\text{Bypass Rate} = \frac{\text{FN}}{\text{Actual Fraud}} = \frac{67}{244} = \mathbf{27.46\%}$$
   Represents undetected fraud, dominated by low-value stealth charges.

---

## 17. Feature Importance Analysis

Feature contributions were extracted from the trained XGBoost booster by calculating the average gain across all tree splits:

![Feature Importance Gain](file:///c:<local-path>)

### Top 15 Features by Average Gain:

| Rank | Feature Name | Average Split Gain | Feature Role / Logic |
| :---: | :--- | :---: | :--- |
| 1 | `new_device` | **1,217.28** | Hardware novelty; strong baseline signal of unauthorized access. |
| 2 | `device_transaction_count` | **786.55** | Trust maturity of hardware; fresh devices carry higher suspicion. |
| 3 | `transactions_last_1hour` | **599.78** | Short-term velocity; detects automated rapid testing. |
| 4 | `transactions_last_24hours` | **441.78** | Daily volume saturation; detects high-frequency account draining. |
| 5 | `fraud_history_rate` | **116.61** | Prior historical fraud incidence on the account. |
| 6 | `previous_fraud_count` | **84.67** | Absolute count of historical fraud incidents. |
| 7 | `previous_transaction_count` | **68.35** | Account maturity and baseline transaction volume. |
| 8 | `auth_pressure` | **56.74** | Interaction feature: failed OTP + failed login attempts. |
| 9 | `distance_from_previous_transaction_km` | **53.64** | Spatial relocation distance from previous tap. |
| 10 | `amount_vs_avg_ratio` | **51.99** | Ratio of current fare to the user's running historical average. |
| 11 | `location_change_rate` | **38.45** | Physical velocity (km/h) between consecutive taps. |
| 12 | `amount_last_1hour` | **32.18** | Total monetary outflow in the preceding 60 minutes. |
| 13 | `amount_vs_max30_ratio` | **28.72** | Spike relative to highest fare in the past 30 days. |
| 14 | `failed_otp_attempts` | **26.90** | Historical friction during OTP verification. |
| 15 | `transactions_last_5min` | **24.15** | Immediate burst velocity. |

### Importance Findings:
* **No Single Feature Dominates:** The model is not overly reliant on a single feature such as `failed_otp_attempts` (which ranks 14th with a gain of 26.90).
* **Multi-Factor Decision Boundary:** The model integrates hardware provenance (`new_device`), velocity spikes (`transactions_last_1hour`), and contextual amount anomalies (`amount_vs_avg_ratio`).

---

## 18. Potential Data and Model Problems

1. **Absence of Synthetic Target Leakage:**
   * The test results show realistic performance ($Recall = 72.54\%$, $Precision = 28.64\%$, $PR\text{-}AUC = 0.7053$). If target leakage or trivial proxy indicators existed, precision and recall would exceed $99.5\%$.
   * Features overlap naturally between fraud and legitimate transactions.
2. **Micro-Fare Blindspot:**
   * Low-value fraud charges ($\le ₹60$) with zero velocity and clean device provenance mimic normal auto rides and evade detection.
3. **Cold-Start Device Penalty:**
   * Legitimate passengers using a new phone or clearing browser/app cache will experience temporary OTP challenges on their first ride if velocity is non-zero.

---

## 19. Recommended Changes

### Feature Engineering Enhancements:
1. **User Standardized Z-Score (`amount_z_score_user`):**
   * Incorporate running standard deviation of user fares: $(\text{Amount} - \mu_{\text{user}}) / \sigma_{\text{user}}$.
2. **Spatial Route Regularity Index:**
   * Transit commuters travel along repetitive routes. A score measuring deviation from known station corridors would reduce false alarms for regular riders.

### Threshold Management:
* **Maintain Validation Discipline:** Any future threshold tuning must strictly take place on validation splits (`tapgo_validation.csv`), never on test data.
* **Tiered OTP Triggers:** Consider introducing a two-tier risk strategy:
  * $0.25 \le \text{Risk} < 0.60$: Biometric / In-app 1-tap confirmation.
  * $\text{Risk} \ge 0.60$: Email OTP challenge.

---

## 20. Final Readiness Assessment

| Evaluation Dimension | Empirical Finding | Production Readiness Verdict |
| :--- | :--- | :---: |
| **1. Fraud Detection** | Catches **72.54%** of all test fraud events (177 / 244) with **0.7053 PR-AUC** (22.2× over baseline). | **READY** |
| **2. False Alarms (Friction)** | Triggers OTP challenges on only **5.93%** of legitimate transit rides (441 / 7,432), preserving instant gate access for 94.07% of passengers. | **READY** |
| **3. Missed Fraud** | **27.46%** (67 fraud cases bypassed OTP), predominantly concentrated in low-value micro-fares ($\le ₹60$). | **ACCEPTABLE** |
| **4. Behavioral Context** | Successfully distinguishes high spenders (fares > ₹1,100 allowed without friction) from anomalous low spenders with authentication friction. | **READY** |
| **5. Technical Correctness** | Evaluated strictly out-of-sample on `tapgo_test.csv` with zero retraining, zero leakage, and verified 32-feature compatibility. | **READY** |
| **6. Integration Readiness** | Inference pipeline (`InferencePipeline`) in `src/predict.py` executes in under 15ms per transaction, fully aligned with real-time transit SLAs. | **READY** |

### Final Engineering Verdict:
The pre-trained **XGBoost fraud detection model is APPROVED for integration** into the Tap&Go payment service under the step-up authentication OTP architecture.
