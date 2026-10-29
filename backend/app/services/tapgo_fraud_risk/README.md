# tapgo_fraud_risk (vendored)

Read-only copy of `TapGo-ML/deployment/tapgo_fraud_risk/` (package 1.1.0), V6 model only, in the portable native
XGBoost JSON format (no scikit-learn, no pickle). `MANIFEST.json` lists the SHA-256 of every vendored file;
`tests/test_fraud_risk_shadow.py` checks it. Do not edit these files here: change the source package, re-run its tests,
and copy it again.

The backend calls it only through `app/services/fraud_risk_shadow.py` (shadow mode: log only).
