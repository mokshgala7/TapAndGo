"""reports/REPRODUCIBILITY_MANIFEST.json: environment, seeds, key hashes, every V6 file hash (caches excluded) and the
final integrity check of the 404 protected files, the V1-V3 archive and both git repositories.
    PYTHONDONTWRITEBYTECODE=1 python3 training/write_manifest.py"""
import hashlib, json, platform, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent; ROOT = V6.parent.parent
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()
git = lambda a, c: subprocess.run(["git"] + a, cwd=c, capture_output=True, text=True).stdout.strip()
import joblib, numpy, pandas, sklearn, xgboost  # noqa: E401
prot = json.loads((V6 / "audit/protected_files_manifest.json").read_text())
changed = [p for p, v in prot["files"].items() if not (ROOT / p).exists() or sha(ROOT / p) != v["sha256"]]
now = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and p.relative_to(ROOT).parts[:2] != ("experiments", "passenger_fraud_v6")
       and not {"__pycache__", ".pytest_cache"} & set(p.parts) and p.name != ".DS_Store"}
be = Path.home() / "Desktop/Tap@Go Hosted"; zp = Path(prot["v1_v3_archive"]["path"])
files = {str(p.relative_to(V6)): sha(p) for p in sorted(V6.rglob("*")) if p.is_file() and "cache" not in p.parts
         and not {"__pycache__", ".pytest_cache"} & set(p.parts) and p.name not in (".DS_Store", "REPRODUCIBILITY_MANIFEST.json")}
meta = json.loads((V6 / "artifacts/model_metadata.json").read_text())
out = {"generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
       "environment": {"python": platform.python_version(), "platform": platform.platform(), "sklearn": sklearn.__version__,
                       "xgboost": xgboost.__version__, "numpy": numpy.__version__, "pandas": pandas.__version__, "joblib": joblib.__version__},
       "seeds": json.loads((V6 / "config/experiment_config.json").read_text())["seeds"],
       "selected_model": meta["selected_candidate"], "model_version": meta["model_version"], "feature_schema_version": meta["feature_schema_version"],
       "feature_names_in_order": meta["feature_names"], "hyperparameters": meta["hyperparameters"], "threshold": meta["decision_threshold"],
       "threshold_rule": meta["threshold_rule"], "policy": meta["policy"],
       "key_hashes": {k: files.get(k) for k in ("artifacts/passenger_fraud_v6_bundle.joblib", "audit/V6_EXPERIMENT_PREREGISTRATION.md",
                                                "evaluation/selection.json", "evaluation/final_metrics.json", "features/feature_builder.py",
                                                "features/v3_features.py", "training/gates.py", "integration/inference.py", "data/generator_v6.py")},
       "reproducibility": json.loads((V6 / "evaluation/reproducibility.json").read_text()),
       "inference_benchmark": json.loads((V6 / "evaluation/inference_benchmark.json").read_text()),
       "final_integrity_check": {"protected_files_checked": prot["file_count"], "protected_files_changed": changed,
                                 "files_added_under_TapGo-ML_outside_V6": sorted(now - set(prot["files"])),
                                 "v1_v3_archive_unchanged": zp.exists() and sha(zp) == prot["v1_v3_archive"]["sha256"],
                                 "ml_repo": {"head_unchanged": git(["rev-parse", "HEAD"], ROOT) == prot["ml_repo"]["head"],
                                             "status_short": git(["status", "--short"], ROOT).splitlines()},
                                 "backend_repo": {"head_unchanged": git(["rev-parse", "HEAD"], be) == prot["backend_repo"]["head"],
                                                  "status_short": git(["status", "--short"], be).splitlines()}},
       "v6_files": files}
(V6 / "reports/REPRODUCIBILITY_MANIFEST.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out["final_integrity_check"], indent=1)); print("v6 files hashed:", len(files))
