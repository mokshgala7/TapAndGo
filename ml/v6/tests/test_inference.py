"""V6 inference interface: schema, contract, artifacts, failure modes, serialization."""
import hashlib
import json
import shutil

import joblib
import numpy as np
import pandas as pd
import pytest

from conftest import V6
from features.feature_builder import FEATURE_SETS, X
from integration.inference import (DEFAULT_BUNDLE, DuplicateRequestError, FraudScorerV6, InferenceError, InvalidInputError,
                                   ModelUnavailableError, PredictionError, SchemaMismatchError)
from training.gates import profile, tx

H = profile()
KEYS = {"schema_version", "scoring_status", "model_version", "feature_schema_version", "risk_score", "score_semantics",
        "threshold", "model_flag", "passenger_fare_anomaly", "rules", "risk_tier", "recommended_action", "step_up_reasons",
        "history", "warnings", "latency_ms", "policy_note"}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _b():
    return joblib.load(DEFAULT_BUNDLE)


def test_output_schema(scorer):
    r = scorer.score(tx(100), H)
    assert set(r) == KEYS and r["scoring_status"] == "scored" and 0 <= r["risk_score"] <= 1
    assert r["model_version"] == "passenger_fraud_v6.1.0.0" and r["schema_version"] == "passenger_fraud_inference/6"
    assert set(r["passenger_fare_anomaly"]) == {"level", "z", "ratio_to_typical", "typical_fare_inr", "basis", "history_stage"}
    assert set(r["rules"]) == {"rapid_repeat_10min", "amount_anomalous", "night_behaviour_anomalous"}
    json.dumps(r)


def test_contract_document_matches_code(scorer):
    doc = (V6 / "integration/INTEGRATION_CONTRACT.md").read_text()
    assert scorer.model_version in doc and "passenger_fraud_inference/6" in doc and f"{scorer.threshold:.6f}" in doc
    for k in KEYS:
        assert f"`{k}`" in doc, k
    for c in scorer.feature_names:
        assert f"`{c}`" in doc, c


def test_no_side_effect_methods(scorer):
    bad = ("write", "insert", "commit", "send", "otp", "wallet", "approve", "reject", "pay", "charge")
    assert not [m for m in dir(scorer) if not m.startswith("_") and any(b in m.lower() for b in bad)]


def test_never_approves_or_rejects(scorer):
    for f in (8, 100, 500, 5000):
        assert scorer.score(tx(f), H)["recommended_action"] in {"step_up_verification", "no_additional_verification"}


def test_deterministic(scorer):
    assert len({scorer.score(tx(137), H)["risk_score"] for _ in range(5)}) == 1


def test_duplicate_request_has_no_score(scorer):
    last = H[-1]
    with pytest.raises(DuplicateRequestError):          # identical (timestamp, amount, driver) to a history ride
        scorer.score({k: last[k] for k in ("timestamp", "amount", "driver_id")}, H)
    keyed = H + [{**last, "timestamp": "2026-08-31T10:00:00+05:30", "idempotency_key": "X"}]
    out = scorer.score_safe(tx(100, idempotency_key="X"), keyed)
    assert out["scoring_status"] == "duplicate_request" and out["risk_score"] is None
    assert out["recommended_action"] == "apply_fallback_policy"


def test_missing_corrupt_mismatched_bundle(tmp_path):
    with pytest.raises(ModelUnavailableError):
        FraudScorerV6.load(tmp_path / "none.joblib")
    p = tmp_path / "b.joblib"; shutil.copy(DEFAULT_BUNDLE, p)
    with pytest.raises(ModelUnavailableError, match="sidecar"):
        FraudScorerV6.load(p)
    with pytest.raises(ModelUnavailableError, match="mismatch"):
        FraudScorerV6.load(p, expected_sha256="0" * 64)
    p.write_bytes(b"garbage")
    with pytest.raises(ModelUnavailableError):
        FraudScorerV6.load(p, expected_sha256=sha(p))


def test_schema_mismatch_and_bad_threshold(tmp_path):
    b = _b(); b["metadata"] = {**b["metadata"], "feature_names": b["metadata"]["feature_names"][:-1]}
    with pytest.raises(SchemaMismatchError):
        FraudScorerV6(b)
    b = _b(); b["metadata"] = {**b["metadata"], "decision_threshold": 1.5}
    with pytest.raises(ModelUnavailableError):
        FraudScorerV6(b)
    b = _b(); b["metadata"]["library_versions"] = {**b["metadata"]["library_versions"], "xgboost": "0.0"}
    p = tmp_path / "v.joblib"; joblib.dump(b, p)
    with pytest.raises(ModelUnavailableError, match="versions"):
        FraudScorerV6.load(p, expected_sha256=sha(p))


def test_error_hierarchy():
    for e in (InvalidInputError, DuplicateRequestError, SchemaMismatchError, ModelUnavailableError, PredictionError):
        assert issubclass(e, InferenceError)


def test_bundle_reload_equals_candidate_model():
    b = _b(); name = b["metadata"]["selected_candidate"]
    cand = joblib.load(V6 / "artifacts/candidate_models" / f"{name}.joblib")
    mat = pd.read_pickle(V6 / "artifacts/cache/open_matrix.pkl").sample(2000, random_state=0)
    mat["night_amount_high"] = mat["night_amount_log_ratio"].clip(lower=0)
    Xa = X(mat, b["metadata"]["feature_names"])
    assert np.array_equal(b["model"].predict_proba(Xa), cand.predict_proba(Xa))
    assert b["metadata"]["feature_names"] == FEATURE_SETS[b["metadata"]["feature_set"]]


def test_unknown_categoricals_and_missing_fields(scorer):
    t = tx(100); t["payment_method"] = None; t["vehicle_type"] = "bike"
    r = scorer.score(t, H)
    assert "vehicle_type_missing_or_unknown" in r["warnings"] and "payment_method_missing" in r["warnings"]
