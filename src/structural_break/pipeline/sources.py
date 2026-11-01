"""Pre-registered P6 model and trading improvements (DECISIONS 43; exploratory).

Two strictly separated stages:

* ``develop`` reads only events with signals in 2006-2021. It chooses the exit
  rule, builds the economic target, tunes matched A/B models on four forward
  folds, calibrates them on 2020-2021 and derives every rank/veto threshold from
  calibration-period scores. It writes ``frozen_choices.json`` plus the models,
  and it never simulates, scores or reads a 2022-2023 outcome.
* ``evaluate`` loads those frozen choices, checks their checksums and evaluates
  every pre-registered variant once on 2022-2023. Every variant is reported.

Results are post-hoc development evidence, never final-test results. The frozen
Decision 36 production policy and the accepted Decision 42 experiments are not
modified. Exit variants run in the explicit RESEARCH execution mode.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break import periods
from structural_break.backtest.contracts import ExecutionConfig, PairTradeResult
from structural_break.backtest.historical import (
    HistoricalSources,
    bind_accepted,
    build_historical_events,
    default_spec,
)
from structural_break.backtest.historical_contracts import HistoricalSpec
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.config.paths import ProjectPaths

PLAN_VERSION = "p6-improvement-v1"
HORIZON = 20
DEVELOPMENT_END = date(2021, 12, 31)
ASSESSMENT = (date(2022, 1, 1), date(2023, 12, 31))
LOGISTIC_C = (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0)
SEED = 42
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 5557
TARGETS = ("econ", "revert")
INTERACTIONS = {
    "ix_absz_sentiment_asymmetry": ("abs_z", "sentiment_net_asymmetry"),
    "ix_absz_one_sided_8k": ("abs_z", "sec_one_sided_recent_8k"),
    "ix_sign_8k_asymmetry": ("divergence_sign", "sec_recent_8k_count_asymmetry"),
    "ix_aligned_return_tone": ("aligned_relative_return_5d", "tone_aligned_contrast"),
    "ix_absz_tone": ("abs_z", "tone_aligned_contrast"),
    "ix_known_tone": ("sentiment_both_known", "tone_aligned_contrast"),
}


# --------------------------------------------------------------------------- #
# Execution: research exit variants and event simulation
# --------------------------------------------------------------------------- #


def _spec(sources: HistoricalSources, start: date, end: date) -> HistoricalSpec:
    base = default_spec(sources)
    return HistoricalSpec(
        binding=base.binding,
        ladder=base.ladder,
        window_start=start,
        window_end=end,
        admitted_partitions=("fit", "calibration", "assessment"),
    )


def _chunks(start: date, end: date, years: int = 3) -> list[tuple[date, date]]:
    result = []
    year = start.year
    while year <= end.year:
        last = min(year + years - 1, end.year)
        result.append((max(start, date(year, 1, 1)), min(end, date(last, 12, 31))))
        year = last + 1
    return result


def simulate_events(
    sources: HistoricalSources,
    configs: dict[str, ExecutionConfig],
    start: date,
    end: date,
    *,
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """One row per fresh h20 episode event; each config is simulated once per event."""
    if end > max(ASSESSMENT[1], periods.data_end()):
        raise ValueError("Simulation cannot extend past the development period")
    rows: list[dict[str, Any]] = []
    for chunk_start, chunk_end in _chunks(start, end):
        spec = _spec(sources, chunk_start, chunk_end)
        events, partitions, _ = build_historical_events(sources, spec)
        if progress is not None:
            progress(f"simulating {len(events)} events {chunk_start}..{chunk_end}")
        for event, partition in zip(events, partitions, strict=True):
            row: dict[str, Any] = {
                "event_id": event.state.event_id,
                "pair_id": event.state.pair_id,
                "event_date": event.request.sessions[0].session_date,
                "active": event.state.pair_status == "ACTIVE",
                "stored_partition": partition,
            }
            for name, config in configs.items():
                result: PairTradeResult = simulate_pair_trade(event.request, config)
                row[f"{name}|status"] = result.status
                row[f"{name}|net"] = result.net_return
            rows.append(row)
        del events
    frame = pd.DataFrame(rows)
    if frame.empty or frame["event_id"].duplicated().any():
        raise ValueError("Simulated event inventory must be nonempty and unique")
    return frame


# --------------------------------------------------------------------------- #
# Modelling
# --------------------------------------------------------------------------- #


def add_interactions(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for name, (left, right) in INTERACTIONS.items():
        result[name] = result[left].astype(float) * result[right].astype(float)
    return result


def load_frame(workspace: Path, evaluation_version: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    directory = workspace / "artifacts/research" / evaluation_version
    report = json.loads((directory / "report.json").read_bytes())
    inputs = pd.read_parquet(directory / "model_inputs.parquet")
    partitions = pd.read_parquet(
        directory / "predictions.parquet", columns=["event_id", "research_partition"]
    )
    frame = inputs.merge(partitions, on="event_id", how="left")
    return add_interactions(frame), report


# --------------------------------------------------------------------------- #
# Assessment evaluation (run once, after the frozen choices are recorded)
# --------------------------------------------------------------------------- #


def paired_block_bootstrap(
    left: np.ndarray[Any, Any],
    right: np.ndarray[Any, Any],
    blocks: np.ndarray[Any, Any],
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
    minimum_blocks: int = 12,
) -> dict[str, Any]:
    """Mean of (right - left) with identical sampled blocks for both sides.

    The economic month bootstrap needs 12 blocks (Decision 38). The forecast
    quarter bootstrap follows v2: all assessment quarters, seed 42, no minimum.
    """
    labels = sorted(set(blocks.tolist()))
    if not labels:
        return {"estimate": None, "interval_95": None, "blocks_n": 0}
    index = {label: position for position, label in enumerate(labels)}
    block_index = np.array([index[value] for value in blocks.tolist()])
    difference = right - left
    sums = np.bincount(block_index, weights=difference, minlength=len(labels))
    counts = np.bincount(block_index, minlength=len(labels)).astype(float)
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(labels), (draws, len(labels)))
    totals, sizes = sums[sampled].sum(axis=1), counts[sampled].sum(axis=1)
    means = totals[sizes > 0] / sizes[sizes > 0]
    interval = (
        [float(value) for value in np.quantile(means, [0.025, 0.975])]
        if len(labels) >= minimum_blocks and len(means)
        else None
    )
    return {
        "estimate": float(difference.mean()) if len(difference) else None,
        "interval_95": interval,
        "blocks_n": len(labels),
        "draws": draws,
        "seed": seed,
    }


def _sources(workspace: Path) -> HistoricalSources:
    """The accepted binding, or a final-test workspace's evaluation (Decision 118)."""
    paths = ProjectPaths.resolve(Path.cwd(), workspace)
    marker = workspace / "final_test_binding.json"
    if marker.exists():
        from structural_break.backtest.historical import bind_unaccepted

        record = json.loads(marker.read_bytes())
        binding = bind_unaccepted(
            workspace.resolve(), record["evaluation_manifest"], record["evaluation_sha256"]
        )
        if binding.horizon_sessions != HORIZON:
            raise ValueError("The final-test binding is for another horizon")
        return HistoricalSources.open(workspace.resolve(), binding, paths=paths)
    binding = bind_accepted(paths, HORIZON)
    return HistoricalSources.open(workspace.resolve(), binding, paths=paths)


__all__ = ["paired_block_bootstrap"]


def registry_dir(workspace: Path) -> Path:
    """The event registry behind the bound evaluation (its recorded ``registry`` parent)."""
    version = _sources(workspace).binding.evaluation.version
    manifest = json.loads(
        (workspace / "artifacts/research" / version / "manifest.json").read_text(encoding="utf-8")
    )
    parent = next(p for p in manifest["parents"] if p["role"] == "registry")
    return (workspace / str(parent["path"])).parent


def registry_targets(workspace: Path, horizon: int = 20) -> pd.DataFrame:
    """The registry's targets, with the final-test labels (Decision 120b) once they exist."""
    targets = pd.read_parquet(registry_dir(workspace) / f"h{horizon}_targets.parquet")
    labels = workspace / "final_test_labels.parquet"
    if not periods.final_years_open() or not labels.exists():
        return targets
    final = pd.read_parquet(labels).set_index("event_id")
    rows = targets["event_id"].isin(final.index)
    for column in final.columns:
        if column in targets.columns:
            targets.loc[rows, column] = targets.loc[rows, "event_id"].map(final[column]).to_numpy()
    return targets
