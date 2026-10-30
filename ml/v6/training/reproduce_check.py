"""Independent reproducibility: regenerate D6_dr1 and D6_fresh (pinned seeds) and compare with the stored files; rebuild
the open matrix for a sample and compare with the cache; refit the selected candidate and compare validation scores.
    PYTHONDONTWRITEBYTECODE=1 python3 training/reproduce_check.py      -> evaluation/reproducibility.json"""
import io, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(V6))
import joblib, numpy as np, pandas as pd
from data.generator_v6 import generate_universe
from data.universes import FRESH, dr_configs
from features.feature_builder import X, build_matrix
from training.train_candidates import make

def same(cfg, stored):
    ev, _ = generate_universe(cfg); ref = pd.read_csv(stored)
    regen = pd.read_csv(io.StringIO(ev.to_csv(index=False)))
    cols = [c for c in regen.columns if c in ref.columns]
    return bool(regen[cols].equals(ref[cols]))
out = {"regenerate_D6_dr1_identical": same(dr_configs()[0], V6 / "data/synthetic/D6_dr1/events.csv"),
       "regenerate_D6_fresh_identical": same(FRESH, V6 / "data/synthetic/D6_fresh/events.csv")}
P3 = joblib.load(V6 / "artifacts/cache/priors.joblib")
op = pd.read_csv(V6 / "data/synthetic/D6_dev/open_events.csv")
sub = op[op.passenger_id.isin(op.passenger_id.drop_duplicates().sample(150, random_state=3))].reset_index(drop=True)
m = build_matrix(sub, None, P3); cache = pd.read_pickle(V6 / "artifacts/cache/open_matrix.pkl").set_index("event_id").loc[m.event_id]
meta = json.loads((V6 / "artifacts/model_metadata.json").read_text()); cols = meta["feature_names"]
cache["night_amount_high"] = cache["night_amount_log_ratio"].clip(lower=0)
out["matrix_max_abs_diff"] = float(np.abs(X(m, cols) - X(cache, cols)).max())
mat = pd.read_pickle(V6 / "artifacts/cache/open_matrix.pkl"); dr = pd.read_pickle(V6 / "artifacts/cache/dr_matrix.pkl")
for f_ in (mat, dr): f_["night_amount_high"] = f_["night_amount_log_ratio"].clip(lower=0)
tr = pd.concat([mat[mat.split == "train"], dr]); va = mat[mat.split != "train"]
model = make(meta["model_family"], meta["hyperparameters"], cols).fit(X(tr, cols), tr.fraud_label.to_numpy())
b = joblib.load(V6 / "artifacts/passenger_fraud_v6_bundle.joblib")
s_new, s_old = model.predict_proba(X(va, cols))[:, 1], b["model"].predict_proba(X(va, cols))[:, 1]
out["refit_bit_identical_validation_scores"] = bool(np.array_equal(s_new, s_old)); out["refit_max_abs_diff"] = float(np.abs(s_new - s_old).max())
(V6 / "evaluation/reproducibility.json").write_text(json.dumps(out, indent=1)); print(json.dumps(out))
