"""Build an app bundle from an accepted research workspace, read-only.

Every input is opened through the existing verified chain: the published primary
record, registered evaluation manifests with per-file SHA-256 checks, the
registry's pair manifests and verified Phase 6 experiment manifests. Nothing is
written into the workspace; final-test rows are refused.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Sequence
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from structural_break.app_bundle.analytics import (
    events_table,
    explain_models,
    feature_profile,
    model_curves,
)
from structural_break.app_bundle.contracts import (
    BUNDLE_SCHEMA_VERSION,
    EXPLAINED_VARIANTS,
    FAMILIES,
    AppBundle,
    BundleIdentity,
    HorizonData,
    PairSeries,
    Source,
)
from structural_break.app_bundle.strategy import ExperimentMismatchError, compact_experiment
from structural_break.backtest.historical_experiment import read_manifest
from structural_break.collaboration.queries import backtest_inputs
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.research.evaluation import ResearchModel
from structural_break.research.primary import (
    checked_file,
    checked_json,
    load_primary,
    registered_manifest,
)

STATE_COLUMNS = (
    "trading_date",
    "spread",
    "z_score",
    "abs_z",
    "pair_status",
    "beta",
    "econometric_eligible",
)
SNAPSHOT_COLUMNS = (
    "estimation_date",
    "effective_start",
    "effective_end",
    "pair_status",
    "status_reason",
    "n_obs",
    "alpha",
    "beta",
    "spread_mean",
    "spread_std",
    "relationship_age_months",
    "consecutive_invalid_snapshots",
    "eg_pvalue",
    "eg_tstat",
    "coint_pvalue",
    "half_life_days",
    "adf_level_p",
    "kpss_level_p",
)
CROSSING_COLUMNS = ("event_date", "direction", "z_entry", "baseline1_eligible", "pair_status")


def bundle_digest(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    return "app_bundle_" + hashlib.sha256(body).hexdigest()[:24]


def _check_dates(frame: pd.DataFrame, column: str, end: date) -> None:
    if column in frame and pd.to_datetime(frame[column]).dt.date.gt(end).any():
        raise ValueError("Presentation inputs must not include final-test rows")


def compact_pair_series(
    pair_id: str, frames: dict[str, pd.DataFrame], protocol: dict[str, Any]
) -> PairSeries:
    start = pd.Timestamp(protocol["fit_start"]).date()
    end = pd.Timestamp(protocol["development_end"]).date()
    state = frames["daily_pair_state"]
    state = state.loc[:, [name for name in STATE_COLUMNS if name in state]].copy()
    if "trading_date" in state:
        state["trading_date"] = pd.to_datetime(state["trading_date"]).dt.date
        _check_dates(state, "trading_date", end)
        state = state.loc[state["trading_date"].ge(start)]
    prices = frames["prices"]
    prices = prices.loc[:, [n for n in ("ticker", "trading_date", "adj_close") if n in prices]]
    prices = prices.copy()
    prices["trading_date"] = pd.to_datetime(prices["trading_date"]).dt.date
    _check_dates(prices, "trading_date", end)
    prices = prices.loc[prices["trading_date"].ge(start)]
    snapshots = frames["relationship_snapshots"]
    snapshots = snapshots.loc[:, [n for n in SNAPSHOT_COLUMNS if n in snapshots]].copy()
    if "status_reason" in snapshots:
        snapshots["status_reason"] = snapshots["status_reason"].map(
            lambda value: (
                ", ".join(map(str, value))
                if isinstance(value, (list, tuple)) or hasattr(value, "tolist")
                else ("" if value is None else str(value))
            )
        )
    crossings = frames["raw_crossings"]
    crossings = crossings.loc[:, [n for n in CROSSING_COLUMNS if n in crossings]].copy()
    for frame in (state, snapshots, crossings):
        frame.insert(0, "pair_id", pair_id)
    return PairSeries(
        pair_id,
        state.reset_index(drop=True),
        prices.reset_index(drop=True),
        snapshots.reset_index(drop=True),
        crossings.reset_index(drop=True),
    )


def load_pair_series(
    paths: ProjectPaths, pair_id: str, protocol: dict[str, Any], horizon: int
) -> PairSeries:
    return compact_pair_series(pair_id, backtest_inputs(paths, pair_id, horizon=horizon), protocol)


def _load_models(path: Path, manifest: dict[str, Any]) -> tuple[dict[str, ResearchModel], str]:
    for name, pinned in manifest["identity_inputs"]["computation"]["libraries"].items():
        if version(name) != pinned:
            return {}, f"UNAVAILABLE: installed {name} differs from the pinned {pinned}"
    models: dict[str, ResearchModel] = {}
    for family in FAMILIES:
        for variant in EXPLAINED_VARIANTS:
            name = f"{family}_{variant}"
            entries = [item for item in manifest["model_files"] if item["name"] == name]
            if len(entries) != 1:
                raise ValueError("Published model inventory differs")
            body = confined_path(path.parent, entries[0]["path"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != entries[0]["sha256"]:
                raise ValueError("Saved native model checksum differs")
            model: ResearchModel = joblib.load(io.BytesIO(body))
            if model.family != family or not model.columns:
                raise ValueError("Native model family or feature inventory differs")
            models[name] = model
    return models, "AVAILABLE"


def choose_showcase(
    predictions: pd.DataFrame,
    requested: int | Sequence[str] | None,
    required: Sequence[str] = (),
) -> tuple[str, ...]:
    known = set(predictions["pair_id"])
    missing = [name for name in required if name not in known]
    if missing:
        raise ValueError(f"Unknown pair identities: {', '.join(missing)}")
    if requested is None:
        return tuple(dict.fromkeys(required))
    if not isinstance(requested, int):
        return tuple(dict.fromkeys([*required, *requested]))
    assessed = predictions.loc[predictions["research_partition"].eq("assessment")]
    counts = (
        assessed.groupby("pair_id")
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["n", "pair_id"], ascending=[False, True])
    )
    preferred = [name for name in ("KO__PEP",) if name in known]
    ranked = tuple(dict.fromkeys([*required, *preferred, *counts["pair_id"].tolist()]))
    return ranked[: max(requested, len(required))]


def build_from_workspace(
    paths: ProjectPaths,
    *,
    primary_version: str | None = None,
    experiments: Sequence[Path] = (),
    showcase: int | Sequence[str] | None = None,
    required_pairs: Sequence[str] = (),
    lazy_pairs: bool = True,
    source: Source = "workspace",
    skip_unmatched_experiments: bool = False,
) -> AppBundle:
    primary = load_primary(paths, primary_version)
    inputs = primary["identity_inputs"]
    protocol: dict[str, Any] = inputs["protocol"]
    end = pd.Timestamp(protocol["development_end"]).date()
    evaluations = {
        int(horizon): item["research_version"] for horizon, item in inputs["evaluations"].items()
    }
    primary_horizon = int(protocol["primary_horizon"])
    loaded: dict[int, dict[str, Any]] = {}
    for horizon, evaluation in evaluations.items():
        path, manifest = registered_manifest(paths, evaluation, "evaluation")
        report = checked_json(path.parent / "report.json", manifest["report_sha256"])
        if report["protocol"] != protocol or report["final_test_read"] is not False:
            raise ValueError("Displayed report differs from the selected primary generation")
        predictions = pd.read_parquet(checked_file(path.parent, manifest, "predictions"))
        model_inputs = pd.read_parquet(checked_file(path.parent, manifest, "model_inputs"))
        _check_dates(predictions, "event_date", end)
        _check_dates(model_inputs, "event_date", end)
        models, status = _load_models(path, manifest)
        loaded[horizon] = {
            "report": report,
            "predictions": predictions,
            "model_inputs": model_inputs,
            "models": models,
            "status": status,
        }
    showcase_pairs = choose_showcase(
        loaded[primary_horizon]["predictions"], showcase, required_pairs
    )
    experiment_ids: dict[int, str] = {}
    strategies: dict[int, tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]] = {}
    for manifest_path in experiments:
        horizon = int(read_manifest(manifest_path).horizon_sessions)
        if horizon not in evaluations:
            if skip_unmatched_experiments:
                continue
            raise ValueError("Phase 6 experiment horizon is not a published horizon")
        try:
            _, summary, nav, trades = compact_experiment(
                manifest_path,
                primary_version=primary["primary_version"],
                evaluation_version=evaluations[horizon],
            )
        except ExperimentMismatchError:
            if skip_unmatched_experiments:
                continue
            raise
        experiment_ids[horizon] = summary["experiment_id"]
        strategies[horizon] = (summary, nav, trades)
    horizons: dict[int, HorizonData] = {}
    statuses = set()
    for horizon, item in loaded.items():
        predictions, model_inputs = item["predictions"], item["model_inputs"]
        statuses.add(item["status"])
        assessment = predictions.loc[predictions["research_partition"].eq("assessment"), "event_id"]
        showcase_ids = predictions.loc[predictions["pair_id"].isin(showcase_pairs), "event_id"]
        contributions, totals, importance = explain_models(
            model_inputs,
            item["models"],
            showcase_ids.tolist(),
            importance_ids=assessment.tolist(),
        )
        columns = item["report"]["models"].get("logistic", {}).get("B_both", {}).get(
            "feature_columns"
        ) or list(item["models"]["logistic_B_both"].columns if item["models"] else ())
        strategy = strategies.get(horizon)
        horizons[horizon] = HorizonData(
            report=item["report"],
            events=events_table(predictions, model_inputs),
            curves=model_curves(predictions),
            importance=importance,
            contributions=contributions,
            contribution_totals=totals,
            feature_profile=feature_profile(model_inputs, columns),
            strategy=strategy[0] if strategy else None,
            strategy_nav=strategy[1] if strategy else pd.DataFrame(),
            strategy_trades=strategy[2] if strategy else pd.DataFrame(),
        )
    pairs = pair_table(
        loaded[primary_horizon]["predictions"], showcase_pairs, all_available=lazy_pairs
    )
    series = [
        load_pair_series(paths, pair_id, protocol, primary_horizon) for pair_id in showcase_pairs
    ]
    identity_payload = {
        "schema": BUNDLE_SCHEMA_VERSION,
        "primary": primary["primary_version"],
        "evaluations": evaluations,
        "experiments": experiment_ids,
        "showcase": showcase_pairs,
    }
    identity = BundleIdentity(
        schema_version=BUNDLE_SCHEMA_VERSION,
        source=source,
        synthetic=False,
        primary_version=primary["primary_version"],
        registry_version=inputs["registry_version"],
        intelligence_version=inputs["intelligence_version"],
        evaluations=evaluations,
        experiments=experiment_ids,
        protocol=protocol,
        showcase_pairs=showcase_pairs,
        explanation_status=" / ".join(sorted(statuses)),
        bundle_id=bundle_digest(identity_payload),
    )

    def loader(pair_id: str) -> PairSeries:
        return load_pair_series(paths, pair_id, protocol, primary_horizon)

    return AppBundle(
        identity=identity,
        horizons=horizons,
        pairs=pairs,
        pair_state=_concat([item.state for item in series]),
        pair_prices=_concat([item.prices for item in series]).drop_duplicates(
            ["ticker", "trading_date"]
        )
        if series
        else pd.DataFrame(columns=["ticker", "trading_date", "adj_close"]),
        pair_snapshots=_concat([item.snapshots for item in series]),
        pair_crossings=_concat([item.crossings for item in series]),
        pair_loader=loader if lazy_pairs else None,
    )


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [frame for frame in frames if len(frame)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def pair_table(
    predictions: pd.DataFrame, showcase: Sequence[str], *, all_available: bool
) -> pd.DataFrame:
    """One row per pair with frozen labels and development event counts."""
    rows = predictions.assign(
        assessment=predictions["research_partition"].eq("assessment"),
    )
    table = (
        rows.groupby("pair_id")
        .agg(
            leg_a=("leg_a", "first"),
            leg_b=("leg_b", "first"),
            sector=("sector", "first") if "sector" in rows else ("leg_a", "first"),
            business_group=("business_group", "first"),
            events_n=("event_id", "size"),
            assessment_events_n=("assessment", "sum"),
            first_event=("event_date", "min"),
            last_event=("event_date", "max"),
        )
        .reset_index()
    )
    if "sector" not in rows:
        table["sector"] = "Unknown"
    table["series_available"] = True if all_available else table["pair_id"].isin(set(showcase))
    return table.sort_values("pair_id").reset_index(drop=True)
