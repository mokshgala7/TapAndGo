"""
scorer.py  –  Fail-explicit risk scorer of the tapgo_fraud_risk package. Copied unchanged in logic from
experiments/passenger_fraud_final/integration/inference.py (verified there: gates, parity, reproducibility); only import
paths and the default bundle location differ.

Recommends risk only. It never authorises or rejects payments, touches wallets, sends OTPs, or opens a database
or network connection. Inputs are the transaction and THIS passenger's earlier ride payments; no driver ledger,
aggregates or location data. See integration/INTEGRATION_CONTRACT.md and ERROR_HANDLING.md.

    scorer = FraudScorerFinal.load()
    out = scorer.score(transaction, passenger_history)        # raises InferenceError subclasses
    out = scorer.score_safe(transaction, passenger_history)   # never raises; failures carry no score
"""

from __future__ import annotations

import hashlib
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .features import v3_features as F3
from .features.feature_builder import FEATURE_SETS, LOCATION_TOKENS, PERIOD_FEATURES, passenger_stage1, stage2

PACKAGE = Path(__file__).resolve().parent
DEFAULT_BUNDLE = PACKAGE / "models" / "tapgo_fraud_v6.joblib"      # V6: the selected model (see validation/)
PORTABLE_DEFAULT = PACKAGE / "models" / "tapgo_fraud_v6.xgb.json"  # the same V6 model, native XGBoost JSON (production)
SCHEMA_VERSION = "passenger_fraud_inference/final-1"
AMOUNT_MAX = 100_000.0
REQUIRED_META = {"model_version", "feature_schema_version", "feature_set", "feature_names", "decision_threshold",
                 "threshold_version", "priors", "library_versions", "model_family", "policy"}


class InferenceError(RuntimeError):
    status = "error"


class InvalidInputError(InferenceError):
    status = "invalid_input"


class DuplicateRequestError(InferenceError):
    status = "duplicate_request"


class SchemaMismatchError(InferenceError):
    status = "schema_mismatch"


class ModelUnavailableError(InferenceError):
    status = "model_unavailable"


class PredictionError(InferenceError):
    status = "prediction_error"


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _no_location(row: Mapping, where: str) -> None:
    bad = [k for k in row if any(t in str(k).lower() for t in LOCATION_TOKENS)]
    if bad:
        raise InvalidInputError(f"{where}: location data is not accepted (fields {bad}); V6 uses no location")


def _ts(v: Any, where: str) -> pd.Timestamp:
    if isinstance(v, datetime):
        if v.tzinfo is None or v.utcoffset() is None:
            raise InvalidInputError(f"{where}: timestamp has no timezone offset; refusing to assume UTC")
        return pd.Timestamp(v)
    if not isinstance(v, str) or not v.strip():
        raise InvalidInputError(f"{where}: timestamp must be an ISO-8601 string with offset or a tz-aware datetime")
    try:
        t = pd.Timestamp(v.strip())
    except (ValueError, TypeError) as e:
        raise InvalidInputError(f"{where}: unparseable timestamp {v!r}") from e
    if t.tzinfo is None:
        raise InvalidInputError(f"{where}: timestamp {v!r} has no timezone offset; refusing to assume UTC")
    return t


def _amount(v: Any, where: str) -> float:
    if isinstance(v, bool):
        raise InvalidInputError(f"{where}: amount must be numeric")
    try:
        a = float(v)
    except (TypeError, ValueError) as e:
        raise InvalidInputError(f"{where}: amount {v!r} is not numeric") from e
    if not math.isfinite(a) or a <= 0 or a > AMOUNT_MAX:
        raise InvalidInputError(f"{where}: amount must be finite, > 0 and <= {AMOUNT_MAX:.0f}; got {v!r}")
    return a


def _id(v: Any, where: str, field: str) -> str:
    if v is None or isinstance(v, bool) or not isinstance(v, (str, int)) or str(v) == "":
        raise InvalidInputError(f"{where}: {field} must be a non-empty string or integer")
    return str(v)


def _opt_str(v: Any, where: str, field: str):
    if v is not None and not isinstance(v, str):
        raise InvalidInputError(f"{where}: {field} must be a string or null")
    return v


class _PortableBooster:
    """A native xgboost.Booster with the predict_proba contract of the training-time scikit-learn wrapper."""

    def __init__(self, booster):
        self.booster, self.n_features_in_ = booster, booster.num_features()

    def predict_proba(self, X):
        import xgboost
        p1 = np.asarray(self.booster.predict(xgboost.DMatrix(np.asarray(X, float))), float)
        return np.column_stack([1.0 - p1, p1])


class FraudScorerFinal:
    def __init__(self, bundle: Any, source: str = "<memory>"):
        if not isinstance(bundle, dict) or {"model", "metadata"} - set(bundle):
            raise ModelUnavailableError(f"bundle {source} is missing model/metadata")
        meta = bundle["metadata"]
        if not isinstance(meta, dict) or REQUIRED_META - set(meta):
            raise ModelUnavailableError("bundle metadata incomplete")
        fs = meta["feature_set"]
        if fs not in FEATURE_SETS or list(meta["feature_names"]) != FEATURE_SETS[fs]:
            raise SchemaMismatchError(f"bundle feature list does not match this code's feature set {fs!r}")
        model = bundle["model"]
        if getattr(model, "n_features_in_", len(meta["feature_names"])) != len(meta["feature_names"]) or not hasattr(model, "predict_proba"):
            raise SchemaMismatchError("model input width differs from the feature list")
        thr = meta["decision_threshold"]
        if isinstance(thr, bool) or not isinstance(thr, (int, float)) or not 0 < thr < 1:
            raise ModelUnavailableError(f"invalid threshold {thr!r}")
        try:
            self.P3 = F3.Priors(**meta["priors"])
        except TypeError as e:
            raise ModelUnavailableError(f"invalid priors: {e}") from e
        self.model, self.meta, self.feature_names = model, meta, list(meta["feature_names"])
        self.threshold, self.model_version = float(thr), meta["model_version"]
        self.policy = dict(meta["policy"])
        self.period_aware = bool(set(self.feature_names) & PERIOD_FEATURES)

    @classmethod
    def from_model(cls, model, feature_set: str, threshold: float, priors: F3.Priors, policy: dict | None = None,
                   name: str = "candidate") -> "FraudScorerFinal":
        """In-memory scorer for a candidate (used by the selection gates)."""
        import sklearn
        import xgboost
        meta = {"model_version": f"candidate:{name}", "feature_schema_version": "final-features-1", "feature_set": feature_set,
                "feature_names": FEATURE_SETS[feature_set], "decision_threshold": float(threshold),
                "threshold_version": "candidate", "priors": priors.__dict__, "model_family": name,
                "library_versions": {"sklearn": sklearn.__version__, "xgboost": xgboost.__version__},
                "policy": policy or {"step_up_rules": ["rapid_repeat_10min"]}}
        return cls({"model": model, "metadata": meta}, name)

    @classmethod
    def load(cls, path: Path | str = DEFAULT_BUNDLE, expected_sha256: str | None = None,
             strict_versions: bool = True) -> "FraudScorerFinal":
        path = Path(path)
        try:
            if not path.is_file():
                raise ModelUnavailableError(f"model bundle not found: {path}")
            if expected_sha256 is None:
                side = path.with_suffix(path.suffix + ".sha256")
                if not side.is_file():
                    raise ModelUnavailableError("no expected hash and no .sha256 sidecar")
                expected_sha256 = side.read_text().split()[0]
            if _sha(path) != expected_sha256:
                raise ModelUnavailableError("bundle hash mismatch; refusing to unpickle")
            import joblib
            bundle = joblib.load(path)
        except InferenceError:
            raise
        except Exception as e:
            raise ModelUnavailableError(f"could not load bundle: {type(e).__name__}: {e}") from e
        s = cls(bundle, str(path))
        if strict_versions:
            import sklearn
            import xgboost
            want = s.meta["library_versions"]
            bad = {k: (want.get(k), v) for k, v in (("sklearn", sklearn.__version__), ("xgboost", xgboost.__version__))
                   if want.get(k) != v}
            if bad:
                raise ModelUnavailableError(f"library versions differ from training (trained, installed): {bad}")
        return s

    @classmethod
    def load_portable(cls, path: Path | str = PORTABLE_DEFAULT) -> "FraudScorerFinal":
        """Load the native XGBoost JSON export (`<name>.xgb.json` + `<name>.meta.json`, both hash-verified against their
        .sha256 sidecars). Needs only numpy/pandas/xgboost: no scikit-learn, no pickle, so it is portable across Python
        and library versions. Scores are bit-identical to the .joblib bundle (verified at export and in the tests)."""
        path = Path(path)
        meta_path = path.with_name(path.name.replace(".xgb.json", ".meta.json"))
        try:
            for p in (path, meta_path):
                side = p.with_suffix(p.suffix + ".sha256")
                if not p.is_file() or not side.is_file():
                    raise ModelUnavailableError(f"model file or .sha256 sidecar not found: {p.name}")
                if _sha(p) != side.read_text().split()[0]:
                    raise ModelUnavailableError(f"hash mismatch for {p.name}")
            import json
            import xgboost
            meta = json.loads(meta_path.read_text())
            booster = xgboost.Booster()
            booster.load_model(str(path))
        except InferenceError:
            raise
        except Exception as e:
            raise ModelUnavailableError(f"could not load portable model: {type(e).__name__}: {e}") from e
        if booster.num_features() != len(meta.get("feature_names", ())):
            raise SchemaMismatchError("portable model input width differs from the feature list")
        model = _PortableBooster(booster)
        # Some xgboost versions (e.g. 2.x, 3.0.x) load this JSON without error but score it differently. Reproduce the
        # frozen bundle's scores on the stored rows, or refuse the model (fail-safe: model_unavailable, never a guess).
        chk = meta.get("self_check")
        if not chk:
            raise ModelUnavailableError("portable model metadata has no self_check rows")
        try:
            got = model.predict_proba(np.asarray(chk["X"], float))[:, 1]
            ok = got.shape == (len(chk["expected"]),) and bool(np.all(np.abs(got - np.asarray(chk["expected"])) <= chk["tolerance"]))
        except Exception as e:
            raise ModelUnavailableError(f"portable model self-check failed: {type(e).__name__}: {e}") from e
        if not ok:
            raise ModelUnavailableError(f"installed xgboost {xgboost.__version__} does not reproduce the frozen scores "
                                        "(self-check failed); use xgboost>=3.1,<4")
        meta = {k: v for k, v in meta.items() if k != "self_check"} | {"runtime_xgboost": xgboost.__version__}
        return cls({"model": model, "metadata": meta}, str(path))

    # ── features ────────────────────────────────────────────────────────────
    def features(self, transaction: Mapping, passenger_history) -> pd.DataFrame:
        if not isinstance(transaction, Mapping) or not transaction:
            raise InvalidInputError("transaction must be a non-empty mapping")
        if passenger_history is None or isinstance(passenger_history, (str, bytes, Mapping)) or not hasattr(passenger_history, "__iter__"):
            raise InvalidInputError("passenger_history must be a list (possibly empty)")
        _no_location(transaction, "transaction")
        t = _ts(transaction.get("timestamp"), "transaction")
        cur = {"timestamp": t, "amount": _amount(transaction.get("amount"), "transaction"),
               "driver_id": _id(transaction.get("driver_id"), "transaction", "driver_id"),
               "payment_method": _opt_str(transaction.get("payment_method"), "transaction", "payment_method"),
               "vehicle_type": _opt_str(transaction.get("vehicle_type"), "transaction", "vehicle_type"), "status": "pending"}
        key = transaction.get("idempotency_key")
        ph, seen_keys, dups_ignored = [], set(), 0
        for i, h in enumerate(passenger_history):
            w = f"passenger_history[{i}]"
            if not isinstance(h, Mapping) or h.get("status") is None:
                raise InvalidInputError(f"{w}: must be a mapping with status")
            _no_location(h, w)
            hk = h.get("idempotency_key")
            if hk is not None and hk in seen_keys:     # the same payment request recorded twice counts once
                dups_ignored += 1
                continue
            if hk is not None:
                seen_keys.add(hk)
            ph.append({"timestamp": _ts(h.get("timestamp"), w), "amount": _amount(h.get("amount"), w),
                       "driver_id": _id(h.get("driver_id"), w, "driver_id"),
                       "payment_method": _opt_str(h.get("payment_method"), w, "payment_method"),
                       "vehicle_type": _opt_str(h.get("vehicle_type"), w, "vehicle_type"),
                       "status": str(h["status"]).strip().lower(), "_key": h.get("idempotency_key")})
        if key is not None and any(r["_key"] == key for r in ph):
            raise DuplicateRequestError(f"idempotency_key {key!r} already present in the passenger's history")
        if any(r["timestamp"] == t and r["amount"] == cur["amount"] and r["driver_id"] == cur["driver_id"] for r in ph):
            raise DuplicateRequestError("identical (timestamp, amount, driver) ride already in the passenger's history")
        if any(r["timestamp"] >= t for r in ph):
            raise InvalidInputError("passenger_history contains rides at or after the transaction")
        rows = sorted(ph, key=lambda r: r["timestamp"]) + [cur]
        if any(b["timestamp"] <= a["timestamp"] for a, b in zip(rows, rows[1:])):
            raise InvalidInputError("passenger_history contains duplicate timestamps")
        df = pd.DataFrame([{k: v for k, v in r.items() if k != "_key"} | {"timestamp": r["timestamp"].isoformat()} for r in rows])
        pe = F3.prepare_events(df)
        target = np.zeros(len(pe), bool); target[-1] = True
        s1 = passenger_stage1(pe, target)
        f = stage2(s1, self.P3)
        n = s1["n_prior"].to_numpy(float)
        med_s = (n * np.nan_to_num(s1["med_log"].to_numpy(float)) + F3.SHRINK_K * self.P3.med_log["all"]) / (n + F3.SHRINK_K)
        f["_typical_fare"] = np.exp(med_s)
        f["_n_prior"], f["_gap"] = s1["n_prior"].to_numpy(), s1["secs_since_prev"].to_numpy()
        f["_pay"], f["_veh"] = s1["payment_cat"].to_numpy(), s1["vehicle_cat"].to_numpy()
        f["_dups_ignored"] = dups_ignored
        return f

    # ── scoring ─────────────────────────────────────────────────────────────
    def score(self, transaction, passenger_history) -> dict:
        t0 = time.perf_counter()
        try:
            f = self.features(transaction, list(passenger_history) if passenger_history is not None else None)
        except InferenceError:
            raise
        except TypeError as e:
            raise InvalidInputError(f"history must be iterable: {e}") from e
        except Exception as e:
            raise InvalidInputError(f"feature computation failed: {type(e).__name__}: {e}") from e
        missing = [c for c in self.feature_names if c not in f.columns]
        if missing:
            raise SchemaMismatchError(f"features missing from computation: {missing}")
        Xr = f[self.feature_names].to_numpy(float)
        if not np.isfinite(Xr).all():
            raise InvalidInputError("non-finite feature values")
        try:
            p = np.asarray(self.model.predict_proba(Xr))
        except Exception as e:
            raise PredictionError(f"model prediction failed: {type(e).__name__}: {e}") from e
        if p.shape != (1, 2) or not np.isfinite(p).all() or not 0 <= p[0, 1] <= 1:
            raise PredictionError(f"model returned an invalid output {p!r}")
        return self._result(f.iloc[0], float(p[0, 1]), (time.perf_counter() - t0) * 1000)

    def score_safe(self, transaction, passenger_history) -> dict:
        try:
            return self.score(transaction, passenger_history)
        except InferenceError as e:
            return self._failure(e.status, str(e))
        except Exception as e:
            return self._failure("prediction_error", f"{type(e).__name__}: {e}")

    def _failure(self, status, msg) -> dict:
        return {"schema_version": SCHEMA_VERSION, "scoring_status": status, "error": msg,
                "model_version": self.model_version, "feature_schema_version": self.meta["feature_schema_version"],
                "risk_score": None, "threshold": {"value": self.threshold, "version": self.meta["threshold_version"]},
                "model_flag": None, "passenger_fare_anomaly": None, "rules": None, "risk_tier": "unknown",
                "recommended_action": "apply_fallback_policy", "warnings": [],
                "policy_note": "No score was produced. Apply the backend's documented fallback (e.g. require step-up "
                               "verification); never treat this as approval."}

    def _result(self, f, score, ms) -> dict:
        n, gap = int(f["_n_prior"]), int(f["_gap"])
        lvl_col, z_col, r_col, amt_col = (("period_anomaly_level", "period_anomaly_z", "period_anomaly_ratio", "is_amount_anomalous_period")
                                          if self.period_aware else ("anomaly_level", "anomaly_z", "anomaly_ratio", "is_amount_anomalous_v6"))
        rules = {"rapid_repeat_10min": bool(f["is_within_10_minutes"]), "amount_anomalous": bool(f[amt_col]),
                 "night_behaviour_anomalous": bool(f["is_night_behaviour_anomalous"])}
        flag = score >= self.threshold
        step_rules = [r for r in self.policy.get("step_up_rules", []) if rules.get(r)]
        step_up = flag or bool(step_rules)
        warnings = []
        if n == 0:
            warnings.append("new_passenger_no_completed_history")
        elif n < F3.HISTORY_MIN:
            warnings.append("passenger_history_insufficient_lt20")
        if f["_veh"] == "unknown":
            warnings.append("vehicle_type_missing_or_unknown")
        if f["_pay"] == "UNKNOWN":
            warnings.append("payment_method_missing")
        if int(f["_dups_ignored"]):
            warnings.append("duplicate_history_rows_ignored")
        return {"schema_version": SCHEMA_VERSION, "scoring_status": "scored", "model_version": self.model_version,
                "feature_schema_version": self.meta["feature_schema_version"], "risk_score": round(score, 6),
                "score_semantics": "uncalibrated model risk score in [0,1]; higher = riskier; not a fraud probability",
                "threshold": {"value": self.threshold, "version": self.meta["threshold_version"]},
                "model_flag": bool(flag),
                "passenger_fare_anomaly": {"level": str(f[lvl_col]), "z": round(float(f[z_col]), 4),
                                           "ratio_to_typical": round(float(f[r_col]), 4),
                                           "typical_fare_inr": round(float(f["_typical_fare"]), 2),
                                           "basis": str(f["anomaly_basis"]), "history_stage": str(f["history_stage"]),
                                           "reference": "same period (day/night) of this passenger" if self.period_aware else "passenger overall",
                                           "period": "night" if int(f["is_night"]) else "day",
                                           "period_typical_fare_inr": round(float(f["_period_typical"]), 2),
                                           "period_history_rides": int(f["_period_n"])},
                "rules": {"rapid_repeat_10min": {"triggered": rules["rapid_repeat_10min"],
                                                 "elapsed_seconds": None if gap < 0 else gap,
                                                 "reference": "previous completed ride of this passenger",
                                                 "definition": "0 <= whole seconds <= 600"},
                          "amount_anomalous": rules["amount_anomalous"],
                          "night_behaviour_anomalous": rules["night_behaviour_anomalous"]},
                "risk_tier": "high" if (flag and step_rules) else ("elevated" if step_up else "low"),
                "recommended_action": "step_up_verification" if step_up else "no_additional_verification",
                "step_up_reasons": (["model_flag"] if flag else []) + step_rules,
                "history": {"prior_completed_rides": n},
                "warnings": warnings, "latency_ms": round(ms, 3),
                "policy_note": "Recommendation only; the backend decides authorisation and OTP. A flag is not confirmed fraud."}


