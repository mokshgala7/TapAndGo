"""Data isolation, feature scope, generator de-biasing and integrity."""
import hashlib
import json
import re

import pandas as pd

from conftest import V6
from data.universes import POST_FREEZE, dr_configs
from features.feature_builder import FEATURE_SETS, FORBIDDEN, LOCATION_TOKENS

ROOT = V6.parent.parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_protected_files_unchanged():
    man = json.loads((V6 / "audit/protected_files_manifest.json").read_text())
    bad = [p for p, v in man["files"].items() if not (ROOT / p).exists() or sha(ROOT / p) != v["sha256"]]
    assert not bad and man["file_count"] == len(man["files"]) == 404


def test_preregistration_unchanged():
    assert sha(V6 / "audit/V6_EXPERIMENT_PREREGISTRATION.md") == (V6 / "logs/preregistration_hash.txt").read_text().split()[1]


def test_v3_feature_code_is_byte_identical_copy():
    assert sha(V6 / "features/v3_features.py") == sha(V6.parent / "passenger_fraud_v4/features/v3_features.py")


def test_feature_sets_have_no_forbidden_or_location_columns():
    for name, cols in FEATURE_SETS.items():
        assert not (FORBIDDEN & set(cols)), name
        assert not [c for c in cols if any(t in c.lower() for t in LOCATION_TOKENS)], name
        assert not [c for c in cols if c.startswith(("pay_", "drv_", "driver_n", "driver_fare", "mkt_"))], name


def test_no_location_columns_in_any_generated_file():
    for f in (V6 / "data/synthetic").glob("*/*.csv"):
        cols = pd.read_csv(f, nrows=1).columns
        assert not [c for c in cols if any(t in c.lower() for t in LOCATION_TOKENS)], f


def test_ledger_is_label_free_and_manifests_match():
    for d in (V6 / "data/synthetic").iterdir():
        man = json.loads((d / "dataset_manifest.json").read_text())
        for fn, h in man["files"].items():
            assert sha(d / fn) == h, (d.name, fn)
        assert not ({"fraud_label", "scenario", "episode_id", "driver_type"} & set(pd.read_csv(d / "driver_ledger.csv", nrows=1).columns))


def test_generator_shortcut_gate_passes_on_dev():
    diag = json.loads((V6 / "evaluation/data_diagnostics.json").read_text())
    assert not diag["D6_dev_open"]["shortcut_gate"]["violates_(>40% fraud and <10% legit)"]
    assert "ring" not in diag["D6_dev_open"]["fraud_share_by_driver_type"]


def test_splits_disjoint_and_chronological():
    op = pd.read_csv(V6 / "data/synthetic/D6_dev/open_events.csv", usecols=["passenger_id", "split", "timestamp"])
    se = pd.read_csv(V6 / "data/synthetic/D6_dev/sealed_events.csv", usecols=["passenger_id", "split", "timestamp"])
    g = pd.concat([op, se]).groupby("split").passenger_id.apply(set)
    assert not (g["test_unseen"] & (g["train"] | g["validation_temporal"] | g["validation_unseen"]))
    assert not (g["validation_unseen"] & g["train"])
    ts = lambda s: pd.to_datetime(pd.concat([op, se]).query("split == @s").timestamp, format="ISO8601", utc=True)  # noqa: E731
    assert ts("train").max() < ts("validation_temporal").min() and ts("validation_temporal").max() < ts("test_temporal").min()


def test_training_and_selection_never_read_test_data():
    pat = re.compile(r"read_(csv|pickle)\([^)]*(sealed_events|D6_fresh|D6_shift|D6_scenario)")
    for f in ("training/train_candidates.py", "training/select_model.py", "training/data_diagnostics.py"):
        assert not pat.search((V6 / f).read_text()), f


def test_frozen_before_post_freeze_data():
    sel = json.loads((V6 / "evaluation/selection.json").read_text())
    assert sel["post_freeze_data_generated"] is False and sel["sealed_read"] is False
    assert sha(V6 / "artifacts/passenger_fraud_v6_bundle.joblib") == sel["bundle_sha256"]
    frozen = pd.Timestamp(sel["frozen_at_utc"]).timestamp()
    for cfg, _ in POST_FREEZE:
        assert (V6 / "data/synthetic" / cfg.name / "events.csv").stat().st_mtime > frozen


def test_dr_worlds_never_contain_the_unseen_mechanism():
    for c in dr_configs():
        assert c.scenario_weights["collusive_regular_driver"] == 0.0
        ev = pd.read_csv(V6 / "data/synthetic" / c.name / "events.csv", usecols=["scenario"])
        assert not (ev.scenario == "collusive_regular_driver").any()


def test_every_candidate_has_a_recorded_gate_outcome_and_only_eligible_selected():
    cand = pd.read_csv(V6 / "evaluation/candidates.csv")
    gates = json.loads((V6 / "evaluation/gate_results.json").read_text())
    assert set(cand.candidate) <= set(gates)
    sel = json.loads((V6 / "evaluation/selection.json").read_text())
    assert bool(cand.set_index("candidate").loc[sel["selected"], "eligible"]) is True
    for r in cand.itertuples():
        assert r.eligible == all(v["pass"] for v in gates[r.candidate].values())
