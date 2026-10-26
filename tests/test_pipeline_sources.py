"""Pre-registered P6 improvement experiment: decision rules on small deterministic data."""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from structural_break.backtest.contracts import ExecutionConfig
from structural_break.backtest.production_policy import load_headline
from structural_break.pipeline.sources import (
    INTERACTIONS,
    add_interactions,
    choose_exit,
    choose_gate,
    cost_variant,
    exit_configs,
    exit_name,
    feature_sets,
    forward_folds,
    paired_block_bootstrap,
    thresholds,
)

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def test_exit_variants_keep_the_frozen_rule_and_mark_the_rest_research() -> None:
    headline = load_headline(CONFIGS)
    variants = exit_configs(headline)
    assert len(variants) == 8 and variants[exit_name(3.0, 0.5)] is headline
    research = [config for config in variants.values() if config is not headline]
    assert {(config.mode, config.status) for config in research} == {("RESEARCH", "DRAFT")}
    assert {config.adverse_boundary for config in research} >= {3.5, 4.0, 1e6}
    stressed = cost_variant(headline, 10.0)
    assert (stressed.mode, stressed.entry_cost_bps, stressed.exit_cost_bps) == (
        "RESEARCH",
        10.0,
        10.0,
    )


def test_production_modes_cannot_change_the_exit_or_freeze_research() -> None:
    base = load_headline(CONFIGS).model_dump(mode="json")
    with pytest.raises(ValidationError, match="Only research exit variants"):
        ExecutionConfig.model_validate_json(json.dumps(base | {"adverse_boundary": 4.0}))
    with pytest.raises(ValidationError, match="cannot be frozen"):
        ExecutionConfig.model_validate_json(
            json.dumps(base | {"mode": "RESEARCH", "convergence_band": 0.25})
        )


def _simulated(rows: list[tuple[int, bool, dict[str, float]]]) -> pd.DataFrame:
    records = []
    for index, (year, active, nets) in enumerate(rows):
        record: dict[str, object] = {
            "event_id": f"E{index}",
            "event_date": date(year, 6, 1),
            "active": active,
        }
        for name, net in nets.items():
            record[f"{name}|status"] = "COMPLETE"
            record[f"{name}|net"] = net
        records.append(record)
    return pd.DataFrame(records)


def test_exit_choice_uses_fit_period_and_keeps_frozen_without_calibration_support() -> None:
    frozen, wide = exit_name(3.0, 0.5), exit_name(4.0, 0.5)
    supported = _simulated(
        [(2010, True, {frozen: 0.0, wide: 0.01}), (2020, False, {frozen: 0.0, wide: 0.002})]
    )
    choice = choose_exit(supported, [frozen, wide])
    assert (choice["fit_best"], choice["chosen"], choice["calibration_guard_passed"]) == (
        wide,
        wide,
        True,
    )
    unsupported = _simulated(
        [(2010, True, {frozen: 0.0, wide: 0.01}), (2021, False, {frozen: 0.0, wide: -0.01})]
    )
    assert choose_exit(unsupported, [frozen, wide])["chosen"] == frozen


def test_gate_choice_compares_all_fresh_with_active_economics() -> None:
    rule = exit_name(3.0, 0.5)
    frame = _simulated([(2010, True, {rule: 0.02}), (2011, False, {rule: -0.04})])
    assert choose_gate(frame, rule)["chosen"] == "B1"
    frame = _simulated([(2010, True, {rule: -0.02}), (2011, False, {rule: 0.04})])
    assert choose_gate(frame, rule)["chosen"] == "B0"


def test_feature_sets_drop_sparse_catalyst_columns_and_add_interactions() -> None:
    a = ["abs_z", "divergence_sign", "aligned_relative_return_5d"]
    b = [
        *a,
        "event_type_UNKNOWN",
        "materiality_HIGH",
        "source_count",
        "evidence_available",
        "tone_aligned_contrast",
        "sec_one_sided_recent_8k",
    ]
    sets = feature_sets(a, b)
    assert sets["A"] == tuple(a) and sets["B_both"] == tuple(b)
    assert "event_type_UNKNOWN" not in sets["B_lean"] and "source_count" not in sets["B_lean"]
    assert "evidence_available" in sets["B_lean"] and "tone_aligned_contrast" in sets["B_lean"]
    assert sets["B_plus"][-len(INTERACTIONS) :] == tuple(INTERACTIONS)
    frame = pd.DataFrame(
        {name: [2.0] for left, right in INTERACTIONS.values() for name in (left, right)}
    )
    assert add_interactions(frame)["ix_absz_tone"].iloc[0] == 4.0


def test_forward_folds_purge_label_windows_across_the_fold_boundary() -> None:
    fit = pd.DataFrame(
        {
            "event_date": [
                date(2015, 3, 1),
                date(2015, 12, 20),
                date(2016, 5, 1),
                date(2016, 12, 15),
            ],
            "horizon_end_date": [
                date(2015, 4, 1),
                date(2016, 1, 20),
                date(2016, 6, 1),
                date(2017, 1, 15),
            ],
        }
    )
    train, validation, year = forward_folds(fit)[0]
    assert year == 2016
    assert list(train["event_date"]) == [date(2015, 3, 1)]
    assert list(validation["event_date"]) == [date(2016, 5, 1)]


def test_thresholds_are_calibration_quantiles() -> None:
    cuts = thresholds(pd.Series(np.linspace(0.0, 1.0, 101)))
    assert cuts["top_0.2"] == pytest.approx(0.8)
    assert cuts["veto_0.2"] == pytest.approx(0.2)
    with pytest.raises(ValueError, match="calibration-period scores"):
        thresholds(pd.Series([np.nan]))


def test_paired_block_bootstrap_is_deterministic_and_needs_twelve_blocks() -> None:
    blocks = np.repeat([f"2022-{month:02d}" for month in range(1, 13)], 3)
    left = np.zeros(len(blocks))
    right = np.linspace(-0.01, 0.02, len(blocks))
    first = paired_block_bootstrap(left, right, blocks)
    assert first == paired_block_bootstrap(left, right, blocks)
    assert first["blocks_n"] == 12 and first["interval_95"] is not None
    assert first["estimate"] == pytest.approx(right.mean())
    few = paired_block_bootstrap(left[:6], right[:6], blocks[:6])
    assert few["interval_95"] is None
