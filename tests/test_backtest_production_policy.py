"""The Decision 36 frozen execution policy and its deterministic sensitivity set."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from structural_break.backtest.production_policy import (
    expand_policies,
    load_analysis_policies,
    load_headline,
    load_sensitivities,
)
from structural_break.backtest.simulator import sha256

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
FIELDS = (
    "entry_cost_bps",
    "exit_cost_bps",
    "annual_borrow_rate",
    "positive_beta_limit",
    "min_leg_adv20_usd",
    "horizon_sessions",
)


def test_headline_and_sensitivities_expand_to_24_frozen_policies() -> None:
    headline = load_headline(CONFIGS)
    policies = expand_policies(headline, load_sensitivities(CONFIGS))
    assert policies[0] == headline and len(policies) == 24
    assert len({sha256(policy) for policy in policies}) == 24
    assert all(
        (policy.schema_version, policy.mode, policy.status)
        == ("pair-execution-policy-v2", "DEVELOPMENT", "FROZEN")
        for policy in policies
    )
    grid = {
        (policy.entry_cost_bps, policy.annual_borrow_rate)
        for policy in policies
        if all(
            getattr(policy, name) == getattr(headline, name)
            for name in ("positive_beta_limit", "min_leg_adv20_usd", "horizon_sessions")
        )
    }
    assert grid == {
        (cost, borrow) for cost in (2.5, 5.0, 10.0, 20.0) for borrow in (0.0, 0.01, 0.03, 0.1)
    }
    for policy in policies[16:]:
        changed = {name for name in FIELDS if getattr(policy, name) != getattr(headline, name)}
        assert len(changed) == 1
    assert {policy.positive_beta_limit for policy in policies} == {2.0, 3.0, 5.0, 100.0}
    assert {policy.min_leg_adv20_usd for policy in policies} == {0.0, 1e6, 5e6, 1e7}
    assert {policy.horizon_sessions for policy in policies} == {10, 20, 30}


def _copy(tmp_path: Path) -> Path:
    for name in ("phase6_execution.json", "phase6_execution_sensitivities.json"):
        shutil.copy(CONFIGS / name, tmp_path / name)
    return tmp_path


def _edit(path: Path, **updates: object) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(updates)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_loader_refuses_an_unfrozen_or_v1_headline(tmp_path: Path) -> None:
    configs = _copy(tmp_path)
    _edit(configs / "phase6_execution.json", status="DRAFT")
    with pytest.raises(ValueError, match="frozen v2 headline"):
        load_headline(configs)
    _edit(
        configs / "phase6_execution.json",
        status="FROZEN",
        schema_version="pair-execution-policy-v1",
    )
    with pytest.raises(ValidationError, match="schema v2"):
        load_headline(configs)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"headline_version": "other"}, "headline version"),
        ({"annual_borrow_rates": [0.0, 0.03, 0.1]}, "headline scenario"),
        ({"positive_beta_limits": [2.0, 3.0]}, "differ from the headline"),
        ({"headline_trading_threshold": 0.5}, "Decision 36"),
        ({"sensitivity_trading_thresholds": [0.2, 0.4]}, "Decision 36"),
    ],
)
def test_sensitivity_set_cannot_drift_from_the_frozen_declaration(
    tmp_path: Path, updates: dict[str, object], message: str
) -> None:
    configs = _copy(tmp_path)
    _edit(configs / "phase6_execution_sensitivities.json", **updates)
    with pytest.raises(ValueError, match=message):
        expand_policies(load_headline(configs), load_sensitivities(configs))


def test_sensitivity_values_must_be_unique(tmp_path: Path) -> None:
    configs = _copy(tmp_path)
    _edit(configs / "phase6_execution_sensitivities.json", cost_bps_per_side=[5.0, 5.0])
    with pytest.raises(ValidationError, match="unique"):
        load_sensitivities(configs)


def test_analysis_policies_are_frozen_by_decisions_35_and_38() -> None:
    analysis = load_analysis_policies(CONFIGS)
    assert (analysis.bootstrap.status, analysis.bootstrap.version) == (
        "FROZEN",
        "phase6-month-bootstrap-20261016",
    )
    assert (analysis.bootstrap.replicates, analysis.bootstrap.seed) == (2000, 5557)
    assert analysis.bootstrap.minimum_populated_months_for_interval == 12
    assert (analysis.portfolio.mode, analysis.portfolio.target_entry_fraction) == (
        "DEVELOPMENT",
        0.25,
    )
    robustness = analysis.robustness
    assert (robustness.status, robustness.version) == ("FROZEN", "phase6-robustness-20261016")
    assert (robustness.vix_elevated, robustness.vix_high) == (20.0, 30.0)
    assert (robustness.volatility_elevated, robustness.volatility_high) == (0.2, 0.4)
    assert robustness.tiny_population_threshold == 20
    assert robustness.context_policy_version == "phase6-feature-context-v1"


@pytest.mark.parametrize(
    ("section", "updates", "message"),
    [
        ("bootstrap", {"version": "phase6-fixture-month-bootstrap-v1"}, "bootstrap identity"),
        ("portfolio", {"mode": "FIXTURE"}, "portfolio identity"),
        (
            "robustness",
            {"status": "FIXTURE", "version": "phase6-fixture-robustness-v1"},
            "declared production slice policy",
        ),
    ],
)
def test_analysis_policies_refuse_fixture_identities(
    tmp_path: Path, section: str, updates: dict[str, object], message: str
) -> None:
    shutil.copy(CONFIGS / "phase6_analysis.json", tmp_path / "phase6_analysis.json")
    value = json.loads((tmp_path / "phase6_analysis.json").read_text(encoding="utf-8"))
    value[section].update(updates)
    (tmp_path / "phase6_analysis.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValidationError, match=message):
        load_analysis_policies(tmp_path)
