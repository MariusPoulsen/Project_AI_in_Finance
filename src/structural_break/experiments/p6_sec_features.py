"""Pre-registered walk-forward test of new SEC feature blocks (DECISIONS 47).

Each block is added to v2's Model B (``B_both``) and compared with B itself, so
the contrast isolates the new information. Training and thresholds follow the
Decision 45 walk-forward exactly: for test year Y the models fit on label
windows that ended before Y-1, the top-20 % threshold comes from year Y-1
scores, and year Y is scored. 2010-2021 decide; 2022-2023 are reference rows.

Primary criterion (fixed before any run): logistic family, pooled 2010-2021
paired Brier difference (new minus B) on reversion success, month-block 95 %
interval entirely below zero, and the new block better in at least 8 of the
12 years. XGBoost and the frozen-exit top-20 % trading contrast are reported
as secondary evidence and do not change the verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.experiments.p6_improvement import (
    SEED,
    _sources,
    load_frame,
    paired_block_bootstrap,
)
from structural_break.experiments.p6_walkforward import (
    DECISION_YEARS,
    MINIMUM_POSITIVE_YEARS,
    REFERENCE_YEARS,
    TOP_SHARE,
    XGB_PARAMETERS,
    allocation,
    rolling_split,
)
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.timing import TIMING_FEATURE_COLUMNS
from structural_break.research.evaluation import _estimator
from structural_break.storage.files import write_bytes

PLAN_VERSION = "p6-sec-features-v1"
LOGISTIC_C = 0.01  # v2's tuned C for the h20 B_both logistic model
FAMILIES = {"logistic": {"C": LOGISTIC_C}, "xgboost": XGB_PARAMETERS}
PRIMARY_FAMILY = "logistic"
CATALYST_PREFIX = "full_"
TARGET = "y_revert_success"


def variants(b_columns: Sequence[str], available: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """New blocks as B additions or B replacements; absent blocks are skipped."""
    base = tuple(b_columns)
    result: dict[str, tuple[str, ...]] = {}
    if set(TIMING_FEATURE_COLUMNS).issubset(available):
        result["B_timing"] = (*base, *TIMING_FEATURE_COLUMNS)
    full = [CATALYST_PREFIX + name for name in EVENT_FEATURE_NAMES]
    if set(full).issubset(available):
        replaced = tuple(
            CATALYST_PREFIX + name if name in EVENT_FEATURE_NAMES else name for name in base
        )
        result["B_full_catalyst"] = replaced
        if "B_timing" in result:
            result["B_full_catalyst_timing"] = (*replaced, *TIMING_FEATURE_COLUMNS)
    return result


def _fit_predict(
    family: str, train: pd.DataFrame, columns: tuple[str, ...], rows: pd.DataFrame
) -> np.ndarray[Any, Any]:
    estimator = _estimator(family, FAMILIES[family], SEED)
    estimator.fit(train.loc[:, columns].astype(float), train[TARGET].astype(int))
    return np.asarray(estimator.predict_proba(rows.loc[:, columns].astype(float))[:, 1])


def _pooled(
    left: pd.Series, right: pd.Series, months: pd.Series, mask: pd.Series
) -> dict[str, Any]:
    known = mask & left.notna() & right.notna()
    result = paired_block_bootstrap(
        left[known].to_numpy(dtype=float),
        right[known].to_numpy(dtype=float),
        months[known].to_numpy(),
    )
    return {**result, "n": int(known.sum())}


def run(
    frame: pd.DataFrame,
    columns: dict[str, tuple[str, ...]],
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Walk-forward scores for B and every variant; verdicts per variant."""
    say = progress or (lambda message: None)
    signal_year = pd.to_datetime(frame["event_date"]).dt.year
    months = pd.to_datetime(frame["event_date"]).dt.strftime("%Y-%m")
    labelled = frame["supervised_eligible"].eq(True) & frame[TARGET].notna()
    decision = signal_year.isin(DECISION_YEARS)
    names = list(columns)
    result: dict[str, Any] = {"plan_version": PLAN_VERSION, "families": {}}
    for family in FAMILIES:
        brier = {name: pd.Series(np.nan, index=frame.index) for name in names}
        alloc = {name: pd.Series(np.nan, index=frame.index) for name in names}
        yearly: dict[str, dict[str, Any]] = {}
        for year in (*DECISION_YEARS, *REFERENCE_YEARS):
            say(f"{family}: year {year}")
            train, threshold_rows, test = rolling_split(frame, year)
            both = pd.concat([threshold_rows, test])
            row: dict[str, Any] = {"train_n": len(train), "test_n": len(test)}
            for name in names:
                scored = _fit_predict(family, train, columns[name], both)
                test_scores = pd.Series(scored[len(threshold_rows) :], index=test.index)
                y = test[TARGET]
                ok = labelled.loc[test.index]
                brier[name].loc[test.index[ok]] = (test_scores[ok] - y[ok].astype(float)) ** 2
                if "frozen|status" in test:
                    # As in Decision 45: only simulated candidates are thresholded and priced.
                    simulated = threshold_rows["frozen|status"].notna().to_numpy()
                    priced = test["frozen|status"].notna()
                    if simulated.any() and priced.any():
                        threshold_scores = scored[: len(threshold_rows)][simulated]
                        cut = float(np.quantile(threshold_scores, 1.0 - TOP_SHARE))
                        alloc[name].loc[test.index[priced]] = allocation(
                            test_scores[priced] >= cut,
                            test.loc[priced, "frozen|status"],
                            test.loc[priced, "frozen|net"],
                        )
                row[name] = {"brier": float(brier[name].loc[test.index].mean())}
            yearly[str(year)] = row
        family_result: dict[str, Any] = {"years": yearly, "variants": {}}
        for name in names:
            if name == "B":
                continue
            per_year = [
                yearly[str(y)][name]["brier"] - yearly[str(y)]["B"]["brier"] for y in DECISION_YEARS
            ]
            better = sum(value < 0 for value in per_year)
            pooled = _pooled(brier["B"], brier[name], months, decision)
            interval = pooled["interval_95"]
            economic = (
                _pooled(alloc["B"], alloc[name], months, decision)
                if alloc[name].notna().any()
                else None
            )
            reference = _pooled(brier["B"], brier[name], months, signal_year.isin(REFERENCE_YEARS))
            family_result["variants"][name] = {
                "brier_difference_vs_B": pooled,
                "years_better": better,
                "years_n": len(DECISION_YEARS),
                "passes": bool(
                    interval is not None and interval[1] < 0 and better >= MINIMUM_POSITIVE_YEARS
                ),
                "brier_difference_vs_B_reference_2022_2023": reference,
                "top20_allocation_difference_vs_B": economic,
            }
        result["families"][family] = family_result
    result["verdicts"] = {
        name: result["families"][PRIMARY_FAMILY]["variants"][name]["passes"]
        for name in names
        if name != "B"
    }
    return result


def load_experiment_frame(
    workspace: Path, features: Sequence[Path], simulation: Path | None
) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]]]:
    frame, report = load_frame(workspace, _sources(workspace).binding.evaluation.version)
    for path in features:
        block = pd.read_parquet(path)
        clash = (set(block.columns) - {"event_id"}) & set(frame.columns)
        if clash:
            raise ValueError(f"Feature block repeats existing columns: {sorted(clash)[:5]}")
        frame = frame.merge(block, on="event_id", how="left", validate="one_to_one")
    if simulation is not None:
        simulated = pd.read_parquet(simulation, columns=["event_id", "frozen|status", "frozen|net"])
        frame = frame.merge(simulated, on="event_id", how="left", validate="one_to_one")
    b_columns = tuple(report["models"]["logistic"]["B_both"]["feature_columns"])
    columns = {"B": b_columns, **variants(b_columns, list(frame.columns))}
    if len(columns) == 1:
        raise ValueError("No new SEC feature block was supplied")
    return frame, columns


def build_timing_block(workspace: Path, sec_metadata: Path, output: Path) -> Path:
    """Timing features for every event of the accepted h20 model table."""
    from structural_break.intelligence.timing import filing_timing_features, session_closes
    from structural_break.research.intelligence import _coverage_bounds

    version = _sources(workspace).binding.evaluation.version
    inputs = pd.read_parquet(workspace / "artifacts/research" / version / "model_inputs.parquet")
    pairs = pd.read_parquet(workspace / "universe/source_v1/pair_universe.parquet")
    events = inputs.loc[
        :,
        ["event_id", "pair_id", "event_timestamp", "abnormal_return_A_1d", "abnormal_return_B_1d"],
    ].merge(
        pairs.loc[:, ["pair_id", "leg_a_security_id", "leg_b_security_id"]],
        on="pair_id",
        validate="many_to_one",
    )
    filings = pd.read_parquet(sec_metadata / "filings.parquet")
    coverage = _coverage_bounds(json.loads((sec_metadata / "coverage.json").read_bytes()), filings)
    stamps = pd.to_datetime(events["event_timestamp"], utc=True)
    closes = session_closes(
        stamps.min().date().replace(day=1) - pd.Timedelta(days=31), stamps.max().date()
    )
    block = filing_timing_features(events, filings, coverage, closes)
    output.parent.mkdir(parents=True, exist_ok=True)
    block.to_parquet(output, index=False)
    return output


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    timing = sub.add_parser("timing", help="build the timing feature block")
    timing.add_argument("--workspace-root", type=Path, required=True)
    timing.add_argument("--sec-metadata", type=Path, required=True)
    timing.add_argument("--output", type=Path, required=True)
    evaluate = sub.add_parser("evaluate", help="run the pre-registered walk-forward")
    evaluate.add_argument("--workspace-root", type=Path, required=True)
    evaluate.add_argument("--features", type=Path, action="append", required=True)
    evaluate.add_argument("--simulation", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    if args.command == "timing":
        path = build_timing_block(args.workspace_root, args.sec_metadata, args.output)
        print(json.dumps({"output": str(path)}))
        return
    frame, columns = load_experiment_frame(args.workspace_root, args.features, args.simulation)
    result = run(frame, columns, progress=lambda m: print(m, file=sys.stderr, flush=True))
    result["inputs"] = {
        "features": [str(path) for path in args.features],
        "simulation": str(args.simulation) if args.simulation else None,
        "columns": {name: list(value) for name, value in columns.items()},
        "decision_years": list(DECISION_YEARS),
        "reference_years": list(REFERENCE_YEARS),
        "run_date": date.today().isoformat(),
    }
    write_bytes(args.output, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({"output": str(args.output), "verdicts": result["verdicts"]}))


if __name__ == "__main__":
    main()
