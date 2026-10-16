"""Generation-bound historical adapters on a tiny synthetic registered workspace.

Every file below is invented: four tickers, two pairs and four fresh crossings
in late 2023. The workspace mimics the registered manifest chain only so the
adapters' binding, reconciliation and refusal rules can be exercised offline.
"""

import hashlib
import json
import sys
from datetime import UTC, date, datetime
from math import exp, isclose, log
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
)
from structural_break.backtest.historical_contracts import HistoricalSpec
from structural_break.backtest.ladder import evaluate_ladder
from structural_break.backtest.ladder_contracts import LadderPolicy, RungSelection
from structural_break.backtest.ladder_fixtures import fixture_ladder
from structural_break.backtest.reporting import build_comparison_report
from structural_break.config.paths import ProjectPaths
from structural_break.research.primary import PrimaryNotReadyError

HORIZON = 10
SESSIONS = canonical_sessions(date(2023, 10, 2), date(2023, 12, 29))
DAYS = [row[0] for row in SESSIONS]
PROTOCOL = {
    "assessment_start": "2023-11-01",
    "assessment_end": "2023-12-31",
    "development_end": "2023-12-31",
    "candidate_threshold": 0.65,
    "final_test_locked": True,
    "entry_z": 2.0,
}
PAIRS: dict[str, dict[str, Any]] = {
    "AAA__BBB": {"beta": 0.8, "sector": "Technology", "base_b": 50.0, "drift": 0.001},
    "CCC__DDD": {"beta": 1.2, "sector": "Health Care", "base_b": 30.0, "drift": -0.0005},
}
ALPHA, MEAN, STD = 0.1, 0.0, 0.05
# z at selected closes; every other session sits at 0.3 inside no band.
Z_PATHS = {
    "AAA__BBB": {
        date(2023, 11, 3): 1.5,
        date(2023, 11, 6): 2.4,  # E1, ACTIVE, A 0.60 / B 0.70
        date(2023, 11, 7): 2.0,
        date(2023, 11, 8): 1.4,
        date(2023, 11, 9): 0.9,
        date(2023, 11, 10): 0.4,  # convergence close
        date(2023, 11, 17): 1.8,
        date(2023, 11, 20): 2.3,  # S1: fresh raw crossing omitted from h10 events
        date(2023, 11, 21): 1.0,
        date(2023, 12, 19): 1.2,
        **{day: 2.5 for day in DAYS if day >= date(2023, 12, 20)},  # E2, truncated path
    },
    "CCC__DDD": {
        date(2023, 11, 9): -1.0,
        date(2023, 11, 10): -2.2,  # E3, WATCH, entry session has a ZERO_VOLUME leg
    },
}
EVENTS = {
    "E1": ("AAA__BBB", date(2023, 11, 6), "ACTIVE", {"A": 0.60, "B": 0.70}, 1.0),
    "E2": ("AAA__BBB", date(2023, 12, 20), "ACTIVE", None, None),
    "E3": ("CCC__DDD", date(2023, 11, 10), "WATCH", {"A": 0.50, "B": 0.80}, 0.0),
}
SUPPRESSED = {"S1": ("AAA__BBB", date(2023, 11, 20), "ACTIVE")}


def _z(pair_id: str, day: date) -> float:
    return Z_PATHS[pair_id].get(day, 0.3)


def _close(day: date) -> datetime:
    return next(row[2] for row in SESSIONS if row[0] == day)


def _open(day: date) -> datetime:
    return next(row[1] for row in SESSIONS if row[0] == day)


def _json(path: Path, value: object) -> str:
    raw = json.dumps(value, sort_keys=True).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_z(pair_id: str, close_a: float, close_b: float) -> float:
    beta = PAIRS[pair_id]["beta"]
    return (log(close_a) - ALPHA - beta * log(close_b) - MEAN) / STD


def make_workspace(
    root: Path, *, previous_z_shift: float = 0.0, extra_event_fields: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Write the registered chain; return the evaluation manifest path and checksum."""
    closes: dict[tuple[str, date], float] = {}
    price_rows = []
    for pair_id, spec in PAIRS.items():
        leg_a, leg_b = pair_id.split("__")
        for index, day in enumerate(DAYS):
            close_b = spec["base_b"] * exp(spec["drift"] * index)
            close_a = exp(ALPHA + spec["beta"] * log(close_b) + MEAN + STD * _z(pair_id, day))
            closes[(leg_a, day)], closes[(leg_b, day)] = close_a, close_b
            for ticker, adjusted in ((leg_a, close_a), (leg_b, close_b)):
                # Raw prices differ by a dividend factor; adjusted open = open * adj/close.
                zero = ticker == "DDD" and day == date(2023, 11, 13)
                price_rows.append(
                    {
                        "ticker": ticker,
                        "trading_date": day,
                        "open": adjusted * 0.999 * 1.01,
                        "close": adjusted * 1.01,
                        "adj_close": adjusted,
                        "quality_flag": "ZERO_VOLUME" if zero else "OK",
                    }
                )
    market = root / "market/source_v1"
    market_files = {
        "prices.parquet": _parquet(market / "prices.parquet", pd.DataFrame(price_rows)),
        "pair_universe.parquet": _parquet(
            market / "pair_universe.parquet",
            pd.DataFrame(
                [
                    {
                        "pair_id": pair_id,
                        "leg_a": pair_id.split("__")[0],
                        "leg_b": pair_id.split("__")[1],
                        "sector": spec["sector"],
                        "active_to": None,
                    }
                    for pair_id, spec in PAIRS.items()
                ]
            ),
        ),
    }
    market_sha = _json(
        market / "manifest.json",
        {
            "data_snapshot_id": "market_fixture0000000000",
            "final_test_prices_collected": False,
            "files": market_files,
        },
    )
    registry_version = "research_registry_" + "1" * 24
    registry = root / "artifacts/research" / registry_version
    pair_manifests = []
    for pair_id, spec in PAIRS.items():
        leg_a, leg_b = pair_id.split("__")
        crossings = []
        for crossing_id, (owner, day, status, *_rest) in {**EVENTS, **SUPPRESSED}.items():
            if owner != pair_id:
                continue
            previous = DAYS[DAYS.index(day) - 1]
            crossings.append(
                {
                    "pair_id": pair_id,
                    "crossing_id": "cross_" + crossing_id,
                    "event_date": day,
                    "relationship_snapshot_id": "snap_" + pair_id,
                    "pair_status": status,
                    "previous_z_score": _snapshot_z(
                        pair_id, closes[(leg_a, previous)], closes[(leg_b, previous)]
                    )
                    + previous_z_shift,
                    "z_entry": _snapshot_z(pair_id, closes[(leg_a, day)], closes[(leg_b, day)]),
                }
            )
        snapshot = pd.DataFrame(
            [
                {
                    "relationship_snapshot_id": "snap_" + pair_id,
                    "pair_id": pair_id,
                    "alpha": ALPHA,
                    "beta": spec["beta"],
                    "spread_mean": MEAN,
                    "spread_std": STD,
                    "window_end": date(2023, 10, 31),
                    "effective_start_at": pd.Timestamp(_open(date(2023, 11, 1))),
                }
            ]
        )
        directory = registry / "pairs" / pair_id
        files = [
            {
                "name": "raw_crossings",
                "path": "raw_crossings.parquet",
                "sha256": _parquet(directory / "raw_crossings.parquet", pd.DataFrame(crossings)),
            },
            {
                "name": "relationship_snapshots",
                "path": "relationship_snapshots.parquet",
                "sha256": _parquet(directory / "relationship_snapshots.parquet", snapshot),
            },
        ]
        pair_manifests.append(
            {
                "pair_id": pair_id,
                "sha256": _json(directory / "manifest.json", {"pair_id": pair_id, "files": files}),
            }
        )
    events, targets, predictions = [], [], []
    for event_id, (pair_id, day, _status, scores, label) in EVENTS.items():
        leg_a, leg_b = pair_id.split("__")
        events.append(
            {
                "event_id": event_id,
                "pair_id": pair_id,
                "event_date": day,
                "event_timestamp": pd.Timestamp(_close(day)),
                "feature_cutoff_timestamp": pd.Timestamp(_close(day)),
                "relationship_snapshot_id": "snap_" + pair_id,
                "alpha": ALPHA,
                "beta": PAIRS[pair_id]["beta"],
                "spread_mean": MEAN,
                "spread_std": STD,
                "entry_z": _snapshot_z(pair_id, closes[(leg_a, day)], closes[(leg_b, day)]),
                "label_policy_version": "label-fixture-v1",
                **(extra_event_fields or {}).get(event_id, {}),
            }
        )
        window = canonical_sessions(day, date(2023, 12, 29))
        complete = len(window) > HORIZON
        targets.append(
            {
                "event_id": event_id,
                "label_policy_version": "label-fixture-v1",
                "y_revert_success": label if complete else float("nan"),
                "label_eligible": complete and label is not None,
                "horizon_end_date": window[HORIZON][0] if complete else None,
            }
        )
        if scores is not None:
            predictions.append(
                {
                    "event_id": event_id,
                    "research_partition": "assessment",
                    "logistic_A_calibrated": scores["A"],
                    "logistic_B_both_calibrated": scores["B"],
                }
            )
    registry_files = [
        {
            "name": f"h{HORIZON}_events",
            "path": f"h{HORIZON}_events.parquet",
            "sha256": _parquet(registry / f"h{HORIZON}_events.parquet", pd.DataFrame(events)),
        },
        {
            "name": f"h{HORIZON}_targets",
            "path": f"h{HORIZON}_targets.parquet",
            "sha256": _parquet(registry / f"h{HORIZON}_targets.parquet", pd.DataFrame(targets)),
        },
    ]
    registry_sha = _json(
        registry / "manifest.json",
        {
            "stage": "registry",
            "research_version": registry_version,
            "final_test_read": False,
            "protocol": PROTOCOL,
            "protocol_hash": "a" * 64,
            "inputs": [
                {"role": "market", "path": "market/source_v1/manifest.json", "sha256": market_sha}
            ],
            "files": registry_files,
            "pair_manifests": pair_manifests,
        },
    )
    evaluation_version = "research_evaluation_" + "2" * 24
    evaluation = root / "artifacts/research" / evaluation_version
    model_files = []
    for name in ("logistic_A", "logistic_B_both"):
        path = evaluation / "models" / f"{name}.joblib"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic bundle {name}".encode())
        model_files.append(
            {
                "name": name,
                "path": f"models/{name}.joblib",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    relative = f"artifacts/research/{evaluation_version}/manifest.json"
    sha = _json(
        root / relative,
        {
            "stage": "evaluation",
            "research_version": evaluation_version,
            "final_test_read": False,
            "protocol": PROTOCOL,
            "protocol_hash": "a" * 64,
            "identity_inputs": {
                "horizon": HORIZON,
                "registry_version": registry_version,
                "registry_manifest_sha256": registry_sha,
            },
            "parents": [
                {
                    "role": "registry",
                    "path": f"artifacts/research/{registry_version}/manifest.json",
                    "sha256": registry_sha,
                }
            ],
            "files": [
                {
                    "name": "predictions",
                    "path": "predictions.parquet",
                    "sha256": _parquet(
                        evaluation / "predictions.parquet", pd.DataFrame(predictions)
                    ),
                }
            ],
            "model_files": model_files,
        },
    )
    return relative, sha


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
        "E1": ("SELECTED", "SELECTED", "WITHHELD", "SELECTED", "NOT_RUN"),
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
    assert request.signal_at == _close(date(2023, 11, 6))
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
        (("ladder", "candidate_threshold"), 0.6, "matched v2 threshold"),
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
    production = ExecutionConfig.model_validate_json(
        (Path(__file__).resolve().parents[1] / "configs/phase6_execution.json").read_text()
    )
    with pytest.raises(ValueError, match="frozen production"):
        evaluate_historical_ladder(events, accepted, production)


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
