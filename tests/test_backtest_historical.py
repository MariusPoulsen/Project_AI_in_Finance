"""Generation-bound historical adapters on a tiny synthetic registered workspace."""

import hashlib
import json
import sys
from datetime import UTC, date, datetime
from math import exp, isclose
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from structural_break.backtest import cli
from structural_break.backtest.contracts import ExecutionConfig, canonical_sessions
from structural_break.backtest.experiment import run_ladder_experiment, verify_ladder_experiment
from structural_break.backtest.historical import (
    HistoricalSources,
    PriceBook,
    bind_accepted,
    bind_unaccepted,
    build_historical_events,
    default_spec,
    evaluate_historical_ladder,
    historical_labels,
    inventory_summary,
    select_inventory,
    trailing_adv20,
)
from structural_break.backtest.historical_contracts import HistoricalSpec
from structural_break.backtest.ladder import evaluate_ladder
from structural_break.backtest.ladder_contracts import LadderPolicy, RungSelection
from structural_break.backtest.ladder_fixtures import fixture_ladder
from structural_break.backtest.production_policy import (
    expand_policies,
    load_headline,
    load_sensitivities,
)
from structural_break.backtest.reporting import build_comparison_report
from structural_break.config.paths import ProjectPaths
from structural_break.research.primary import PrimaryNotReadyError
from tests.historical_workspace import DAYS, HORIZON, make_workspace, session_close


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, HistoricalSources]:
    root = tmp_path / "workspace"
    relative, sha = make_workspace(root)
    binding = bind_unaccepted(root, relative, sha)
    return root, HistoricalSources.open(root, binding)


def _inventory(sources: HistoricalSources) -> Any:
    spec = default_spec(sources)
    events, partitions, suppressed = build_historical_events(sources, spec)
    return spec, events, select_inventory(events, partitions, suppressed, spec)


def _accepted(spec: HistoricalSpec) -> HistoricalSpec:
    """Test-only stand-in for a published binding; real ones come from load_primary."""
    value = spec.model_dump(mode="json")
    value["binding"].update(acceptance="ACCEPTED", primary_version="research_primary_" + "e" * 24)
    value["ladder"]["status"] = "FROZEN"
    return HistoricalSpec.model_validate_json(json.dumps(value))


def _frozen_synthetic_config() -> ExecutionConfig:
    # Invented test parameters; they are not a proposed or frozen production policy.
    return ExecutionConfig.model_validate(
        {
            "version": "test-only-synthetic-frozen",
            "mode": "DEVELOPMENT",
            "status": "FROZEN",
            "horizon_sessions": HORIZON,
            "positive_beta_limit": 5.0,
            "entry_cost_bps": 5.0,
            "exit_cost_bps": 5.0,
            "annual_borrow_rate": 0.03,
        }
    )


def test_unaccepted_binding_follows_the_checksum_chain(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    relative, sha = make_workspace(root)
    binding = bind_unaccepted(root, relative, sha)
    assert binding.acceptance == "UNACCEPTED_ENGINEERING"
    assert binding.primary_version is None
    assert binding.horizon_sessions == HORIZON
    assert binding.registry.version == "research_registry_" + "1" * 24
    assert binding.market.version == "market_fixture0000000000"
    assert (binding.assessment_start, binding.candidate_threshold) == (date(2023, 11, 1), 0.65)
    with pytest.raises(ValueError, match="checksum"):
        bind_unaccepted(root, relative, "0" * 64)
    registry = root / binding.registry.path
    registry.write_bytes(registry.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum"):
        bind_unaccepted(root, relative, sha)


def test_binding_refuses_traversal_and_unlocked_generations(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    relative, _ = make_workspace(root)
    with pytest.raises(ValueError, match="relative path|escapes"):
        bind_unaccepted(root, "../" + relative, "0" * 64)
    manifest = root / relative
    value = json.loads(manifest.read_bytes())
    value["final_test_read"] = True
    raw = json.dumps(value).encode()
    manifest.write_bytes(raw)
    with pytest.raises(ValueError, match="development-only"):
        bind_unaccepted(root, relative, hashlib.sha256(raw).hexdigest())


def test_acceptance_comes_only_from_the_primary_publication(
    workspace: tuple[Path, HistoricalSources], tmp_path: Path, project_root: Path
) -> None:
    root, sources = workspace
    forged = sources.binding.model_copy(
        update={"acceptance": "ACCEPTED", "primary_version": "research_primary_" + "f" * 24}
    )
    with pytest.raises(ValueError, match="project workspace paths"):
        HistoricalSources.open(root, forged)
    paths = ProjectPaths.resolve(project_root, root)
    with pytest.raises(PrimaryNotReadyError):
        HistoricalSources.open(root, forged, paths=paths)
    with pytest.raises(PrimaryNotReadyError):
        bind_accepted(paths, HORIZON)
    changed = sources.binding.model_copy(update={"prices_sha256": "0" * 64})
    with pytest.raises(ValueError, match="does not reproduce"):
        HistoricalSources.open(root, changed)
    with pytest.raises(ValidationError, match="primary readiness"):
        sources.binding.model_validate_json(
            json.dumps({**sources.binding.model_dump(mode="json"), "acceptance": "ACCEPTED"})
        )


def test_price_book_uses_same_row_adjustment_and_quality_rules(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    spec = default_spec(sources)
    frame = pd.DataFrame(
        [
            ("AAA", date(2023, 11, 1), 10.2, 10.0, 9.0, "OK"),
            ("BBB", date(2023, 11, 1), 20.0, 20.0, 19.0, "ZERO_VOLUME"),
            ("CCC", date(2023, 11, 1), 5.0, 5.0, 5.0, "STALE"),
            ("DDD", date(2023, 11, 1), 5.0, 0.0, 5.0, "OK"),
        ],
        columns=["ticker", "trading_date", "open", "close", "adj_close", "quality_flag"],
    )
    book = PriceBook.build(frame, spec)
    opening, close = book.bars[("AAA", date(2023, 11, 1))]
    assert close == 9.0 and opening is not None and isclose(opening, 10.2 * 9.0 / 10.0)
    assert book.bars[("BBB", date(2023, 11, 1))] == (None, 19.0)
    assert book.bars[("CCC", date(2023, 11, 1))] == (None, None)
    assert book.bars[("DDD", date(2023, 11, 1))] == (None, None)
    assert book.lineage.adjustment_policy == "yahoo-retrospective-adjclose-ratio-v1"
    assert book.lineage.source_sha256 == sources.binding.prices_sha256
    with pytest.raises(ValueError, match="one row"):
        PriceBook.build(pd.concat([frame, frame.iloc[:1]]), spec)


def test_inventory_selects_without_prices_or_labels(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    root, sources = workspace
    # Selection must not touch labels: corrupting them leaves the inventory intact.
    targets = root / sources.binding.registry.path.replace("manifest.json", "h10_targets.parquet")
    targets.write_bytes(b"corrupted")
    spec, events, inventory = _inventory(sources)
    assert spec.ladder.status == "DRAFT" and spec.ladder.full_system == "NOT_RUN"
    assert [row.event_id for row in inventory.rows] == ["E1", "E3", "E2"]
    assert [row.crossing_id for row in inventory.suppressed] == ["cross_S1"]
    assert (inventory.simulated, inventory.labels_read, inventory.final_test_read) == (
        False,
        False,
        False,
    )
    rows = {row.event_id: row for row in inventory.rows}
    expected = {
        "E1": ("SELECTED", "SELECTED", "WITHHELD", "SELECTED", "NOT_RUN"),  # A 0.25, B 0.70
        "E2": ("SELECTED", "SELECTED", "UNAVAILABLE", "UNAVAILABLE", "NOT_RUN"),
        "E3": ("SELECTED", "WITHHELD", "WITHHELD", "WITHHELD", "NOT_RUN"),
    }
    for event_id, dispositions in expected.items():
        assert tuple(item.disposition for item in rows[event_id].selections) == dispositions
    assert rows["E2"].selections[2].reason_codes == ("MISSING_MODEL_A",)
    assert rows["E3"].selections[1].reason_codes == ("PAIR_NOT_ACTIVE",)
    assert {row.partition for row in inventory.rows} == {"assessment", None}
    summary = inventory_summary(inventory)
    assert summary["economic_results"] is None and summary["simulated"] is False
    assert summary["rungs"]["FULL_SYSTEM"]["disposition_counts"] == {"NOT_RUN": 3}
    assert summary["suppressed_raw_crossings_n"] == 1
    with pytest.raises(ValueError, match="checksum"):
        historical_labels(sources, spec, events)


def test_events_bind_frozen_snapshot_and_truncate_before_the_lock(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    _, events, _ = _inventory(sources)
    by_id = {event.state.event_id: event for event in events}
    request = by_id["E1"].request
    assert request.data_kind == "DEVELOPMENT_CAPTURE"
    assert request.snapshot.formation_end == date(2023, 10, 31)
    assert request.signal_at == session_close(date(2023, 11, 6))
    assert len(request.sessions) == HORIZON + 2
    assert by_id["E1"].state.previous is not None
    assert isclose(by_id["E1"].state.previous.z, 1.5, abs_tol=1e-9)
    assert by_id["E3"].state.sector == "Health Care"
    late = by_id["E2"].request
    assert late.sessions[-1].session_date == date(2023, 12, 29)
    assert len(late.sessions) < HORIZON + 2
    assert all(session.session_date.year == 2023 for session in late.sessions)
    bars = {bar.session_date: bar for bar in by_id["E3"].request.prices}
    assert bars[date(2023, 11, 13)].open_b is None
    assert bars[date(2023, 11, 13)].close_b is not None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"previous_z_shift": 0.01}, "Previous z does not reconcile"),
        (
            {"extra_event_fields": {"E1": {"beta": 0.81}}},
            "relationship parameters differ",
        ),
        (
            {
                "extra_event_fields": {
                    "E1": {"event_timestamp": pd.Timestamp(datetime(2023, 11, 6, 22, tzinfo=UTC))}
                }
            },
            "exact XNYS signal close",
        ),
    ],
)
def test_reconciliation_failures_stop_the_build(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    root = tmp_path / "workspace"
    relative, sha = make_workspace(root, **overrides)
    sources = HistoricalSources.open(root, bind_unaccepted(root, relative, sha))
    with pytest.raises(ValueError, match=message):
        build_historical_events(sources, default_spec(sources))


def test_spec_refuses_fixture_run_retuned_or_unaccepted_frozen_policies(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    value = default_spec(sources).model_dump(mode="json")
    cases = [
        (("ladder", "status"), "FIXTURE", "synthetic fixture"),
        (("ladder", "full_system"), "RUN", "not run"),
        (("ladder", "candidate_threshold"), 0.5, "approved Decision 36"),
        (("ladder", "status"), "FROZEN", "Unaccepted"),
        (("window_start",), "2023-06-01", "assessment window"),
        (("ladder", "horizon_sessions"), 20, "horizon"),
    ]
    for keys, replacement, message in cases:
        changed = json.loads(json.dumps(value))
        target = changed
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = replacement
        with pytest.raises(ValidationError, match=message):
            HistoricalSpec.model_validate_json(json.dumps(changed))


def test_draft_or_unaccepted_inputs_cannot_produce_returns(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    spec, events, _ = _inventory(sources)
    frozen = _frozen_synthetic_config()
    with pytest.raises(ValueError, match="accepted generation"):
        evaluate_historical_ladder(events, spec, frozen)
    accepted = _accepted(spec)
    draft_ladder = accepted.model_dump(mode="json")
    draft_ladder["ladder"]["status"] = "DRAFT"
    with pytest.raises(ValueError, match="frozen ladder"):
        evaluate_historical_ladder(
            events, HistoricalSpec.model_validate_json(json.dumps(draft_ladder)), frozen
        )
    draft = frozen.model_dump(mode="json") | {"status": "DRAFT"}
    with pytest.raises(ValueError, match="frozen production"):
        evaluate_historical_ladder(
            events, accepted, ExecutionConfig.model_validate_json(json.dumps(draft))
        )


def test_frozen_production_policy_runs_with_signal_time_leg_liquidity(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    spec, events, _ = _inventory(sources)
    configs = Path(__file__).resolve().parents[1] / "configs"
    policies = {
        policy.version.split(":")[-1]: policy
        for policy in expand_policies(load_headline(configs), load_sensitivities(configs))
    }
    # The fixture registry is a 10-session horizon: use the frozen 10-session variant.
    ten = policies["horizon=10"]
    assert (ten.status, ten.min_leg_adv20_usd, ten.positive_beta_limit) == (
        "FROZEN",
        5_000_000.0,
        3.0,
    )
    rows = {row.event_id: row for row in evaluate_historical_ladder(events, _accepted(spec), ten)}
    first = rows["E1"].execution
    assert first is not None and (first.status, first.reason) == ("COMPLETE", "CONVERGENCE")
    assert first.execution_config_version == "phase6-execution-v2-20261016:horizon=10"
    strict = ten.model_dump(mode="json") | {"min_leg_adv20_usd": 1e12}
    illiquid = evaluate_historical_ladder(
        events, _accepted(spec), ExecutionConfig.model_validate_json(json.dumps(strict))
    )
    assert {row.execution.reason for row in illiquid if row.execution} == {"ILLIQUID_LEG"}


def test_frozen_accepted_path_runs_the_shared_engine_once_per_event(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    spec, events, _ = _inventory(sources)
    rows = {
        row.event_id: row
        for row in evaluate_historical_ladder(events, _accepted(spec), _frozen_synthetic_config())
    }
    assert set(rows) == {"E1", "E2", "E3"}
    assert all(row.selections[4].disposition == "NOT_RUN" for row in rows.values())
    first, late, zero = rows["E1"].execution, rows["E2"].execution, rows["E3"].execution
    assert first is not None and late is not None and zero is not None
    assert (first.status, first.reason) == ("COMPLETE", "CONVERGENCE")
    assert first.exit is not None and first.exit.session_date == date(2023, 11, 13)
    assert (late.status, late.reason) == ("UNPRICED", "INCOMPLETE_SESSION_PATH")
    assert late.net_return is None
    assert (zero.status, zero.reason) == ("NOT_ENTERED", "MISSING_ENTRY_OPEN")


def test_labels_are_a_separate_complete_window_input(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    spec, events, _ = _inventory(sources)
    labels, missing = historical_labels(sources, spec, events)
    assert {label.event_id: label.label_success for label in labels} == {"E1": 1, "E3": 0}
    assert missing == {"LABEL_NOT_ELIGIBLE": 1}
    assert {label.label_policy_version for label in labels} == {"label-fixture-v1"}


def test_not_run_full_system_reports_status_without_metrics(tmp_path: Path) -> None:
    events, policy, config, labels = fixture_ladder()
    value = policy.model_dump(mode="json")
    value["full_system"] = "NOT_RUN"
    not_run = LadderPolicy.model_validate_json(json.dumps(value))
    rows = evaluate_ladder(events, not_run, config)
    assert {row.selections[4].disposition for row in rows} == {"NOT_RUN"}
    report = build_comparison_report(events, rows, not_run, labels=labels)
    assert report["natural_rungs"]["FULL_SYSTEM"]["status"] == "NOT_RUN"
    assert report["natural_rungs"]["FULL_SYSTEM"]["metrics"] is None
    assert report["adjacent_comparisons"]["MODEL_B__FULL_SYSTEM"]["status"] == "NOT_RUN"
    assert report["agent_controller"]["status"] == "NOT_RUN"
    assert "selected_n" in report["natural_rungs"]["MODEL_B"]
    manifest = run_ladder_experiment(events, not_run, config, tmp_path / "out", labels=labels)
    assert "| FULL_SYSTEM | 14 | not run |" in (manifest.parent / "summary.md").read_text()
    assert verify_ladder_experiment(manifest)["status"] == "VERIFIED_SYNTHETIC_REPLAY"


@pytest.mark.parametrize(
    ("rung", "disposition", "reason"),
    [
        ("MODEL_B", "NOT_RUN", "CONTROLLER_GENERATION_NOT_ACCEPTED"),
        ("FULL_SYSTEM", "NOT_RUN", "MISSING_CONTROLLER"),
        ("FULL_SYSTEM", "WITHHELD", "CONTROLLER_GENERATION_NOT_ACCEPTED"),
    ],
)
def test_not_run_is_reserved_for_an_unaccepted_controller(
    rung: str, disposition: str, reason: str
) -> None:
    with pytest.raises(ValidationError, match="unaccepted controller"):
        RungSelection.model_validate_json(
            json.dumps({"rung": rung, "disposition": disposition, "reason_codes": [reason]})
        )


def test_inventory_cli_is_content_addressed_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "workspace"
    relative, sha = make_workspace(root)
    arguments = [
        "structural-break-backtest",
        "historical-inventory",
        "--workspace-root",
        str(root),
        "--evaluation-manifest",
        relative,
        "--evaluation-sha256",
        sha,
        "--horizon",
        str(HORIZON),
        "--output-dir",
        str(tmp_path / "out"),
    ]
    outputs = []
    for _ in range(2):
        monkeypatch.setattr(sys, "argv", arguments)
        cli.main()
        outputs.append(json.loads(capsys.readouterr().out))
    assert outputs[0] == outputs[1]
    assert outputs[0]["acceptance"] == "UNACCEPTED_ENGINEERING"
    assert outputs[0]["events_n"] == 3 and outputs[0]["economic_results"] is None
    directory = Path(outputs[0]["directory"])
    assert sorted(path.name for path in directory.iterdir()) == [
        "inventory.json",
        "spec.json",
        "summary.json",
    ]
    monkeypatch.setattr(sys, "argv", [*arguments[:-2], "--horizon", "20", *arguments[-2:]])
    with pytest.raises(SystemExit):
        cli.main()


def test_signal_time_liquidity_uses_exact_sessions(
    workspace: tuple[Path, HistoricalSources],
) -> None:
    _, sources = workspace
    _, events, _ = _inventory(sources)
    request = next(event.request for event in events if event.state.event_id == "E1")
    signal = DAYS.index(date(2023, 11, 6))
    # Fixture leg B: adjusted close 50 * exp(0.001 i), raw = 1.01 x adjusted, shares 1e6 + 1e3 i.
    expected = (
        sum(
            50.0 * exp(0.001 * index) * 1.01 * (1_000_000.0 + 1000.0 * index)
            for index in range(signal - 19, signal + 1)
        )
        / 20
    )
    assert request.signal_adv20_usd_b is not None
    assert isclose(request.signal_adv20_usd_b, expected, rel_tol=1e-12)
    sessions = canonical_sessions(date(2023, 10, 1), date(2023, 11, 6))[-20:]
    volumes = {("XYZ", day): 1.0 for day, _, _ in sessions}
    assert trailing_adv20(volumes, "XYZ", date(2023, 11, 6)) == 1.0
    del volumes[("XYZ", sessions[3][0])]
    assert trailing_adv20(volumes, "XYZ", date(2023, 11, 6)) is None
    assert trailing_adv20(volumes, "XYZ", date(2023, 11, 4)) is None  # not a session


@pytest.mark.parametrize("threshold", [0.2, 0.3, 0.4, 0.65])
def test_spec_admits_only_decision_35_thresholds(
    workspace: tuple[Path, HistoricalSources], threshold: float
) -> None:
    _, sources = workspace
    assert default_spec(sources, threshold=threshold).ladder.candidate_threshold == threshold
