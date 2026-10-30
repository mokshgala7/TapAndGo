# Tap&Go Machine Learning Pipeline (TapGo-ML)

This repository contains the Machine Learning risk-scoring pipeline for the **Tap&Go** NFC/QR cashless fare payment platform. It handles data ingestion, feature engineering, model training, hyperparameter tuning, and threshold selection to detect fraudulent transactions in real-time.

## 🎯 Core Philosophy: OTP Step-Up

Tap&Go does **not** hard-block suspicious transactions. Instead, transactions flagged as high-risk trigger an **OTP (One-Time Password) challenge**. 

Because of this UX design, our models are tuned to maximize **Recall** (catching as much fraud as possible) while maintaining a strict minimum **Precision** (≥ 30%). This ensures the platform is secure, but legitimate passengers aren't overly burdened with constant OTP friction.

---

## 🗂️ Project Structure

```text
TapGo-ML/
├── data/                      # Train/Val/Test CSV splits
├── models/                    # Saved trained models (.pkl) and scalers
├── notebooks/                 # Exploratory Data Analysis (EDA) Jupyter notebooks
├── reports/                   # Evaluation metrics, ROC/PR curves, and thresholds
├── scripts/
│   └── run_pipeline.py        # Master CLI script to run the end-to-end ML pipeline
├── src/
│   ├── models/                # Wrappers (XGBoost, Random Forest, Logistic Reg., Isolation Forest)
│   ├── config.py              # Centralized configuration (paths, hyperparams, target columns)
│   ├── data_loader.py         # CSV ingestion and cyclic datetime encoding
│   ├── feature_engineering.py # Derived feature logic (velocity spikes, auth pressure)
│   ├── preprocessing.py       # Robust scaling for distance-based models
│   ├── train.py               # Base training loop
│   ├── tune.py                # Hyperparameter tuning via RandomizedSearchCV
│   ├── validate.py            # OTP threshold selection on validation data
│   ├── evaluate.py            # Final unbiased test set evaluation
│   ├── report.py              # Matplotlib visualization generator
│   └── predict.py             # Inference API wrapper for backend integration
├── DATASET_DOCUMENTATION.md   # Detailed notes on synthetic dataset methodology
└── requirements.txt           # Python dependencies
```

---

## ⚙️ Installation

1. Ensure you have Python installed (3.9+ recommended).
2. Install the required data science libraries:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🚀 Usage

### 1. Run the Full Pipeline
To train the models, select optimal OTP thresholds, evaluate on the test set, and generate visual reports, simply run:
```bash
python scripts/run_pipeline.py
```

### 2. Hyperparameter Tuning
To thoroughly search for the best model parameters using 5-fold Cross Validation (optimizing for PR-AUC), use the `--tune` flag. This will automatically overwrite the saved models with the best estimators found:
```bash
python scripts/run_pipeline.py --tune
```

### 3. Backend Inference (Scoring)
To score a live transaction from your backend application, use `src/predict.py`. You can call it from the CLI:
```bash
python -m src.predict --json '{"transaction_amount": 450, "payment_method": "NFC", "transaction_hour": 23, "transaction_day_of_week": 5, "transactions_last_1hour": 4}'
```
Or import it directly into a Python microservice:
```python
from src.predict import load_inference_pipeline, predict_transaction

# Load model into memory once at startup
pipeline = load_inference_pipeline("xgboost")

# Predict on a live transaction
result = predict_transaction(pipeline, transaction_data_dict)

if result["trigger_otp"]:
    print("Action: Challenge User with OTP")
```

---

## 📊 Model Performance

Our recommended production model is **XGBoost**, natively tuned to handle the ~3.16% fraud class imbalance.

* **Test ROC-AUC:** `0.960`
* **Test PR-AUC:** `0.704`
* **Recall:** `~73%` of all fraud attempts are caught.
* **Precision:** `~29%` (Approximately 1 in 3 OTP challenges sent to users is a confirmed fraud attempt).

Visual reports (ROC curves, Precision-Recall curves, Confusion Matrices, and Feature Importance bar charts) are generated automatically and saved to the `reports/` directory after running the pipeline.
