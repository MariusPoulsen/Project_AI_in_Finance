from __future__ import annotations

import numpy as np
import pandas as pd

from structural_break.experiments import p6_quant as pq
from structural_break.experiments import p6_quant_features as qf


def _state() -> pd.DataFrame:
    day = pd.Timestamp("2015-03-02")
    rows = [
        ("X__Y", 2.5),  # event pair: X rich vs Y
        ("X__Z", 2.2),  # X also rich vs Z
        ("W__X", -2.4),  # X rich vs W (X is leg B, negative z)
        ("Y__Z", 0.1),
    ]
    state = pd.DataFrame(
        {
            "pair_id": [r[0] for r in rows],
            "trading_date": day,
            "z_score": [r[1] for r in rows],
            "fresh_threshold_crossing": [True, False, False, False],
        }
    )
    legs = state["pair_id"].str.split("__", expand=True)
    state["leg_a"], state["leg_b"] = legs[0], legs[1]
    return state


def test_peer_features_measure_each_leg_against_its_other_peers() -> None:
    events = pd.DataFrame(
        {
            "pair_id": ["X__Y"],
            "event_date": ["2015-03-02"],
            "entry_z": [2.5],
            "leg_a": ["X"],
            "leg_b": ["Y"],
        }
    )
    out = qf.peer_features(events, _state())
    # X's other pairs: +2.2 (vs Z) and +2.4 (vs W): rich against everyone.
    assert np.isclose(out["peer_a_aligned_z"].iloc[0], 2.3)
    assert out["peer_a_share_diverged"].iloc[0] == 1.0
    # Y's other pair: Y vs Z at +0.1 means Y slightly rich; aligned for the cheap leg is -0.1.
    assert np.isclose(out["peer_b_aligned_z"].iloc[0], -0.1)
    assert out["market_share_diverged"].iloc[0] == 0.75


def test_track_record_uses_only_resolved_labels() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "pair_id": ["X__Y"] * 3,
            "leg_a": ["X"] * 3,
            "leg_b": ["Y"] * 3,
            "event_date": pd.to_datetime(["2015-01-02", "2015-01-20", "2015-01-21"]),
        }
    )
    targets = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "y_revert_success": [1.0, 0.0, 1.0],
            "outcome_type": ["CONVERGED", "STOPPED", "CONVERGED"],
            "resolution_date": ["2015-01-21", "2015-02-10", "2015-02-11"],
        }
    )
    out = qf.track_features(events, targets)
    # e1 resolved on 2015-01-21: not known on that same date, so e3 still sees no history.
    assert out["track_pair_n"].tolist() == [0, 0, 0]


def test_split_schemes() -> None:
    frame = pd.DataFrame(
        {
            "event_date": pd.to_datetime(["2008-06-01", "2009-06-01", "2010-03-01"]),
            "horizon_end_date": pd.to_datetime(["2008-07-01", "2009-07-01", "2010-04-01"]),
            "supervised_eligible": True,
            pq.TARGET: [0.0, 1.0, 0.0],
        }
    )
    d45, _, _ = pq.split(frame, 2010, "d45")
    recent, previous, test = pq.split(frame, 2010, "recent")
    assert len(d45) == 1 and len(recent) == 2
    assert len(previous) == 1 and len(test) == 1


def test_ou_simulation_behaves_sensibly() -> None:
    from structural_break.experiments import p6_quant_ou as ou

    shocks = np.random.default_rng(0).standard_normal((4000, ou.STEPS))
    z0 = np.array([2.0, 2.0, -2.0, 2.0])
    rho = np.array([0.80, 0.99, 0.80, 0.80])
    sigma = np.array([0.2, 0.2, 0.2, 1.0])
    out = ou.simulate(z0, rho, sigma, shocks)
    # Fast reversion beats slow reversion, and the sign of the divergence does not matter.
    assert out["ou_p_label"][0] > out["ou_p_label"][1]
    assert np.isclose(out["ou_p_label"][0], out["ou_p_label"][2])
    assert np.isclose(out["ou_zgain"][0], out["ou_zgain"][2])
    # A take profit at |z| 1.0 is reached at least as often as the 0.5 label.
    assert (out["ou_p_tp"] >= out["ou_p_label"]).all()
    assert out["ou_zgain"][0] > 0


def test_quant_param_variants_build_estimators() -> None:
    est = pq._estimator(pq.PARAMS["bag5"])
    assert isinstance(est, pq._Bag) and len(est.models) == 5
    assert set(pq.PARAMS) == {"base", "bag5"}


def test_feature_sets_keep_only_the_headline_models() -> None:
    from structural_break.experiments.p6_quant_ou import OU

    blocks = ("peer", "state", "earnings", "momentum", "track")
    available = ["b1", "a1", *(c for name in blocks for c in qf.BLOCKS[name]), *OU]
    sets = pq.feature_sets({"B": ("b1",), "A": ("a1",)}, available)
    assert list(sets) == ["B", "A", "B+rule+ou", "B+rule+ou+track"]
    assert set(sets["B+rule+ou+track"]) - set(sets["B+rule+ou"]) == set(qf.BLOCKS["track"])
