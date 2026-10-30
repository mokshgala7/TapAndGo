"""
verify_model.py  –  Final-freeze verification of the frozen V6 bundle (read-only; no retraining, no threshold change).

Checks loading (hash-verified), metadata vs the final report, schema, documented output, invalid-input handling, the
explicit fare-anomaly signal, absence of location inputs, and that scoring works with ALL network sockets blocked.
    cd experiments/passenger_fraud_v6 && PYTHONDONTWRITEBYTECODE=1 python3 reports/final_freeze/verify_model.py
Writes reports/final_freeze/verify_model.json
"""

import hashlib
import json
import socket
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V6 = HERE.parents[1]
sys.path.insert(0, str(V6))


class _NoNetwork(socket.socket):
    def __init__(self, *a, **k):
        raise RuntimeError("network access attempted during offline inference")


def main() -> None:
    real_socket = socket.socket
    socket.socket = _NoNetwork          # any network or database client would need a socket
    try:
        from features.feature_builder import FEATURE_SETS, LOCATION_TOKENS
        from integration.inference import DEFAULT_BUNDLE, SCHEMA_VERSION, FraudScorerV6
        from training.gates import profile, tx
        out = {}
        side = DEFAULT_BUNDLE.with_suffix(".joblib.sha256").read_text().split()[0]
        out["bundle_path"] = str(DEFAULT_BUNDLE.relative_to(V6.parent.parent))
        out["bundle_sha256_matches_sidecar"] = hashlib.sha256(DEFAULT_BUNDLE.read_bytes()).hexdigest() == side
        s = FraudScorerV6.load()
        m = s.meta
        out["metadata"] = {"model_version": m["model_version"], "feature_schema_version": m["feature_schema_version"],
                           "selected_candidate": m["selected_candidate"], "feature_set": m["feature_set"],
                           "n_features": len(s.feature_names), "threshold": s.threshold, "policy": m["policy"],
                           "schema_matches_code": s.feature_names == FEATURE_SETS[m["feature_set"]],
                           "output_schema": SCHEMA_VERSION}
        report = (V6 / "reports/FINAL_REPORT.md").read_text()
        out["metadata_matches_final_report"] = {"threshold_0.063318": "0.063318" in report and f"{s.threshold:.6f}" == "0.063318",
                                                "model_version": m["model_version"] in (V6 / "integration/INTEGRATION_CONTRACT.md").read_text()}
        h = profile()
        r = s.score(tx(100), h)
        out["documented_output_keys_present"] = sorted(r)
        out["normal_ride"] = {k: r[k] for k in ("scoring_status", "risk_score", "model_flag", "recommended_action")}
        a = s.score(tx(500, "D1"), h)
        out["fare_anomaly_exposed"] = a["passenger_fare_anomaly"]
        out["location_inputs_required"] = [c for c in s.feature_names if any(t in c.lower() for t in LOCATION_TOKENS)]
        out["location_field_refused"] = s.score_safe({**tx(100), "latitude": 19.07}, h)["scoring_status"] == "invalid_input"
        bad = {"naive_timestamp": {"timestamp": "2026-09-02 09:00:00", "amount": 100, "driver_id": "D1"},
               "negative_amount": {**tx(100), "amount": -5}, "missing_driver": {**tx(100), "driver_id": None},
               "garbage_timestamp": {**tx(100), "timestamp": "yesterday"}}
        out["invalid_inputs"] = {k: {kk: v[kk] for kk in ("scoring_status", "risk_score", "model_flag", "recommended_action")}
                                 for k, v in ((k, s.score_safe(t, h)) for k, t in bad.items())}
        out["invalid_inputs_never_low_risk"] = all(v["risk_score"] is None and v["model_flag"] is None
                                                   and v["recommended_action"] == "apply_fallback_policy" for v in out["invalid_inputs"].values())
        out["scored_with_network_blocked"] = True
        out["no_authorisation_methods"] = not [n for n in dir(s) if not n.startswith("_") and
                                               any(b in n.lower() for b in ("approve", "reject", "authori", "pay", "otp", "wallet"))]
    finally:
        socket.socket = real_socket
    out["all_checks_pass"] = bool(out["bundle_sha256_matches_sidecar"] and out["metadata"]["schema_matches_code"]
                                  and all(out["metadata_matches_final_report"].values()) and not out["location_inputs_required"]
                                  and out["location_field_refused"] and out["invalid_inputs_never_low_risk"]
                                  and out["no_authorisation_methods"] and out["fare_anomaly_exposed"]["level"] == "high")
    (HERE / "verify_model.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
