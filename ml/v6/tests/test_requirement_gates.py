"""Mandatory requirement gates G1–G10 (audit/REQUIREMENT_TEST_SPECIFICATION.md) re-run on the FROZEN bundle."""
import joblib
import pandas as pd
import pytest

from conftest import V6
from training import gates as G


@pytest.mark.parametrize("gate", ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"])
def test_model_gate(scorer, gate):
    fn = {"G1": G.gate_g1, "G2": G.gate_g2, "G3": G.gate_g3, "G4": G.gate_g4, "G5": G.gate_g5, "G6": G.gate_g6,
          "G7": G.gate_g7, "G8": G.gate_g8}[gate]
    r = fn(scorer)
    assert r["pass"], r["detail"]


def test_g1_familiar_driver_cannot_suppress_fare_anomaly(scorer):
    h = G.profile(median=100.0)
    fam = [scorer.score(G.tx(f, "D1"), h) for f in (100, 200, 300, 500)]
    assert [r["passenger_fare_anomaly"]["level"] for r in fam] == ["none", "high", "high", "high"]
    assert all(a["risk_score"] <= b["risk_score"] for a, b in zip(fam, fam[1:]))
    assert fam[2]["model_flag"] and fam[3]["model_flag"] and not fam[0]["model_flag"]
    assert fam[3]["rules"]["amount_anomalous"] is True


def test_g9_no_future_leakage():
    P3 = joblib.load(V6 / "artifacts/cache/priors.joblib")
    op = pd.read_csv(V6 / "data/synthetic/D6_dev/open_events.csv")
    r = G.gate_causality(op, P3)
    assert r["pass"], r["detail"]


def test_g10_interface_batch_parity(scorer):
    op = pd.read_csv(V6 / "data/synthetic/D6_dev/open_events.csv")
    mat = pd.read_pickle(V6 / "artifacts/cache/open_matrix.pkl")
    if "night_amount_high" not in mat:
        mat["night_amount_high"] = mat["night_amount_log_ratio"].clip(lower=0)
    r = G.gate_parity(scorer, op, mat)
    assert r["pass"], r["detail"]
