"""
build_datasets.py  –  Generate V6 universes (pre-registration §5).

    python data/build_datasets.py --stage dev          # D6_dev (split) + D6_valshift + D6_dr1/2, before training
    python data/build_datasets.py --stage post_freeze  # D6_fresh, D6_shift, D6_scenario; refuses unless frozen

Per universe (data/synthetic/<name>/): driver_ledger.csv (label-free, backend columns only), open_events.csv +
sealed_events.csv (D6_dev) or events.csv, drivers.csv, config.json, dataset_manifest.json.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(V6))
from data.generator_v6 import generate_universe  # noqa: E402
from data.universes import DEV, POST_FREEZE, VALSHIFT, dr_configs  # noqa: E402

OUT = V6 / "data" / "synthetic"
LEDGER_COLS = ["event_id", "passenger_id", "driver_id", "vehicle_type", "timestamp", "amount", "payment_method", "status"]
TRAIN_END, VAL_END = "2026-07-01T00:00:00+05:30", "2026-08-01T00:00:00+05:30"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_universe(cfg, ev, drivers, labelled: dict, extra: dict) -> None:
    out = OUT / cfg.name
    if out.exists() and any(out.iterdir()):
        sys.exit(f"[build] {out} exists; refusing to overwrite")
    out.mkdir(parents=True)
    ev[LEDGER_COLS].to_csv(out / "driver_ledger.csv", index=False)
    for fname, frame in labelled.items():
        frame.to_csv(out / fname, index=False)
    drivers.to_csv(out / "drivers.csv", index=False)
    (out / "config.json").write_text(json.dumps({**asdict(cfg), **extra}, indent=2))
    man = {"universe": cfg.name, "seed": cfg.seed, "rows": int(len(ev)), "passengers": int(ev.passenger_id.nunique()),
           "drivers": int(ev.driver_id.nunique()), **extra,
           "files": {f.name: sha(f) for f in sorted(out.iterdir()) if f.suffix == ".csv"}}
    if "open_events.csv" in labelled:          # never summarise sealed labels
        op = labelled["open_events.csv"]
        man["open_rows_by_split"] = op.split.value_counts().to_dict()
        man["open_fraud_by_split"] = op.groupby("split").fraud_label.sum().astype(int).to_dict()
        man["sealed_rows"] = int(len(labelled["sealed_events.csv"]))
    elif extra.get("stage") != "post_freeze":
        man["fraud"] = int(ev.fraud_label.sum()); man["fraud_rate"] = float(ev.fraud_label.mean())
    (out / "dataset_manifest.json").write_text(json.dumps(man, indent=2, default=int))
    print(json.dumps({k: v for k, v in man.items() if k != "files"}, default=int), flush=True)


def stage_dev() -> None:
    ev, drivers = generate_universe(DEV)
    pax = np.array(sorted(ev.passenger_id.unique()))
    perm = np.random.default_rng(DEV.seed + 1).permutation(pax)
    n10 = len(pax) // 10
    group = {p: "heldout_val" for p in perm[:n10]} | {p: "heldout_test" for p in perm[n10:2 * n10]} | \
            {p: "panel" for p in perm[2 * n10:]}
    ev["passenger_group"] = ev.passenger_id.map(group)
    ts = pd.to_datetime(ev.timestamp, format="ISO8601", utc=True)
    ev["split"] = np.select([ev.passenger_group.eq("heldout_test"), ev.passenger_group.eq("heldout_val"),
                             ts < pd.Timestamp(TRAIN_END), ts < pd.Timestamp(VAL_END)],
                            ["test_unseen", "validation_unseen", "train", "validation_temporal"], default="test_temporal")
    sealed = ev.split.isin(["test_temporal", "test_unseen"])
    write_universe(DEV, ev, drivers, {"open_events.csv": ev[~sealed], "sealed_events.csv": ev[sealed]},
                   {"train_end": TRAIN_END, "val_end": VAL_END, "group_seed": DEV.seed + 1, "stage": "dev"})
    for cfg, split in [(VALSHIFT, "validation_shift")] + [(c, "train_dr") for c in dr_configs()]:
        e, d = generate_universe(cfg)
        e["split"] = split; e["passenger_group"] = split
        write_universe(cfg, e, d, {"events.csv": e}, {"use": split, "stage": "dev"})


def stage_post_freeze() -> None:
    sel = V6 / "evaluation" / "selection.json"
    if not sel.exists() or json.loads(sel.read_text()).get("post_freeze_data_generated") is not False:
        sys.exit("[build] the model must be frozen (evaluation/selection.json) before post-freeze data exists")
    for cfg, split in POST_FREEZE:
        e, d = generate_universe(cfg)
        e["split"] = split; e["passenger_group"] = "post_freeze"
        write_universe(cfg, e, d, {"events.csv": e}, {"use": f"final evaluation {split} (generated after freeze)",
                                                    "stage": "post_freeze"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["dev", "post_freeze"], required=True)
    stage_dev() if ap.parse_args().stage == "dev" else stage_post_freeze()
