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

import argparse
import hashlib
import io
import json
import math
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from structural_break.backtest.contracts import ExecutionConfig, PairTradeResult
from structural_break.backtest.historical import (
    HistoricalSources,
    bind_accepted,
    build_historical_events,
    default_spec,
)
from structural_break.backtest.historical_contracts import HistoricalSpec
from structural_break.backtest.production_policy import load_headline
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.config.paths import ProjectPaths
from structural_break.ml.model import fit_sigmoid
from structural_break.research.evaluation import ResearchModel, _estimator
from structural_break.storage.files import write_bytes

PLAN_VERSION = "p6-improvement-v1"
HORIZON = 20
DEVELOPMENT_END = date(2021, 12, 31)
ASSESSMENT = (date(2022, 1, 1), date(2023, 12, 31))
FIT_END_YEAR = 2019
EXIT_STOPS = (3.0, 3.5, 4.0, 1e6)
EXIT_BANDS = (0.5, 0.25)
FOLD_YEARS = (2016, 2017, 2018, 2019)
LOGISTIC_C = (0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0)
XGB_GRID = (
    {
        "learning_rate": 0.05,
        "max_depth": 2,
        "min_child_weight": 10,
        "n_estimators": 200,
        "reg_lambda": 10,
    },
    {
        "learning_rate": 0.05,
        "max_depth": 3,
        "min_child_weight": 20,
        "n_estimators": 100,
        "reg_lambda": 10,
    },
    {
        "learning_rate": 0.03,
        "max_depth": 2,
        "min_child_weight": 20,
        "n_estimators": 400,
        "reg_lambda": 10,
    },
    {
        "learning_rate": 0.05,
        "max_depth": 3,
        "min_child_weight": 20,
        "n_estimators": 200,
        "reg_lambda": 10,
    },
    {
        "learning_rate": 0.03,
        "max_depth": 4,
        "min_child_weight": 20,
        "n_estimators": 200,
        "reg_lambda": 10,
    },
    {
        "learning_rate": 0.03,
        "max_depth": 3,
        "min_child_weight": 20,
        "n_estimators": 400,
        "reg_lambda": 10,
    },
)
TOP_K = (0.10, 0.20, 0.33)
VETO = (0.20, 0.33)
HEADLINE_TOP_K = 0.20
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
CATALYST_DROPPED_PREFIXES = (
    "event_type_",
    "affected_leg_",
    "materiality_",
    "direction_",
    "relationship_relevance_",
)
CATALYST_DROPPED = ("source_count", "document_recency_days", "extraction_confidence")


def _checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


# --------------------------------------------------------------------------- #
# Execution: research exit variants and event simulation
# --------------------------------------------------------------------------- #


def exit_name(stop: float, band: float) -> str:
    return f"stop={'none' if stop >= 1e5 else f'{stop:g}'},band={band:g}"


def exit_configs(headline: ExecutionConfig) -> dict[str, ExecutionConfig]:
    """The frozen exit uses the frozen production policy; others are RESEARCH drafts."""
    result: dict[str, ExecutionConfig] = {}
    for stop in EXIT_STOPS:
        for band in EXIT_BANDS:
            name = exit_name(stop, band)
            if (stop, band) == (3.0, 0.5):
                result[name] = headline
                continue
            payload = headline.model_dump(mode="json") | {
                "version": f"{PLAN_VERSION}:research-exit:{name}",
                "mode": "RESEARCH",
                "status": "DRAFT",
                "adverse_boundary": stop,
                "convergence_band": band,
            }
            result[name] = ExecutionConfig.model_validate_json(json.dumps(payload))
    return result


def cost_variant(config: ExecutionConfig, bps: float) -> ExecutionConfig:
    """Same exit rule at a different per-side cost; never a frozen production policy."""
    payload = config.model_dump(mode="json") | {
        "version": f"{config.version}:cost={bps:g}bps",
        "mode": "RESEARCH",
        "status": "DRAFT",
        "entry_cost_bps": bps,
        "exit_cost_bps": bps,
    }
    return ExecutionConfig.model_validate_json(json.dumps(payload))


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
    if end > ASSESSMENT[1]:
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


def _order(value: float | None) -> float:
    """Explicit missing-mean ordering; 0.0 is a real value, never treated as missing."""
    return -math.inf if value is None else value


def complete_mean(frame: pd.DataFrame, name: str) -> tuple[float | None, int]:
    complete = frame.loc[frame[f"{name}|status"].eq("COMPLETE"), f"{name}|net"].astype(float)
    return (float(complete.mean()) if len(complete) else None, int(len(complete)))


def choose_exit(simulated: pd.DataFrame, names: Sequence[str]) -> dict[str, Any]:
    """Argmax fit-period (2006-2019) mean net; keep frozen unless 2020-2021 agrees."""
    years = pd.to_datetime(simulated["event_date"]).dt.year
    fit, calibration = simulated.loc[years.le(FIT_END_YEAR)], simulated.loc[years.ge(2020)]
    table = {}
    for name in names:
        fit_mean, fit_n = complete_mean(fit, name)
        cal_mean, cal_n = complete_mean(calibration, name)
        table[name] = {"fit_mean": fit_mean, "fit_n": fit_n, "cal_mean": cal_mean, "cal_n": cal_n}
    frozen = exit_name(3.0, 0.5)
    best = max(names, key=lambda name: _order(table[name]["fit_mean"]))
    guard = _order(table[best]["cal_mean"]) > _order(table[frozen]["cal_mean"])
    chosen = best if best == frozen or guard else frozen
    return {
        "table": table,
        "fit_best": best,
        "calibration_guard_passed": bool(guard),
        "chosen": chosen,
    }


def choose_gate(simulated: pd.DataFrame, exit_rule: str) -> dict[str, Any]:
    """Baseline 0 (all fresh) versus Baseline 1 (ACTIVE) over 2006-2021 economics."""
    all_mean, all_n = complete_mean(simulated, exit_rule)
    active_mean, active_n = complete_mean(simulated.loc[simulated["active"]], exit_rule)
    chosen = "B1" if _order(active_mean) > _order(all_mean) else "B0"
    return {
        "B0": {"mean": all_mean, "n": all_n},
        "B1": {"mean": active_mean, "n": active_n},
        "chosen": chosen,
    }


# --------------------------------------------------------------------------- #
# Modelling
# --------------------------------------------------------------------------- #


def feature_sets(a_columns: Sequence[str], b_columns: Sequence[str]) -> dict[str, tuple[str, ...]]:
    extra = [column for column in b_columns if column not in a_columns]
    lean = [
        column
        for column in extra
        if not column.startswith(CATALYST_DROPPED_PREFIXES) and column not in CATALYST_DROPPED
    ]
    return {
        "A": tuple(a_columns),
        "B_both": tuple(b_columns),
        "B_lean": (*a_columns, *lean),
        "B_plus": (*a_columns, *lean, *INTERACTIONS),
    }


def add_interactions(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for name, (left, right) in INTERACTIONS.items():
        result[name] = result[left].astype(float) * result[right].astype(float)
    return result


def candidates(family: str) -> list[dict[str, Any]]:
    if family == "logistic":
        return [{"C": c} for c in LOGISTIC_C]
    return [dict(parameters) for parameters in XGB_GRID]


def _brier(y: np.ndarray[Any, Any], p: np.ndarray[Any, Any]) -> float:
    return float(np.mean((p - y) ** 2))


def forward_folds(fit: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame, int]]:
    """Fit on windows ending before the fold year; validate on in-year completed windows."""
    end = pd.to_datetime(fit["horizon_end_date"]).dt.date
    year = pd.to_datetime(fit["event_date"]).dt.year
    folds = []
    for fold in FOLD_YEARS:
        train = fit.loc[end.lt(date(fold, 1, 1))]
        validation = fit.loc[year.eq(fold) & end.le(date(fold, 12, 31))]
        folds.append((train, validation, fold))
    return folds


def tune(fit: pd.DataFrame, target: str, sets: dict[str, tuple[str, ...]]) -> list[dict[str, Any]]:
    """Mean forward-fold Brier for every feature set x family x parameter."""
    folds = forward_folds(fit)
    scores = []
    for set_name, columns in sets.items():
        for family in ("logistic", "xgboost"):
            for parameters in candidates(family):
                briers = []
                for train, validation, _fold in folds:
                    y_train = train[target].astype(int)
                    if y_train.nunique() < 2 or validation.empty:
                        continue
                    estimator = _estimator(family, parameters, SEED)
                    estimator.fit(train.loc[:, columns].astype(float), y_train)
                    probability = estimator.predict_proba(validation.loc[:, columns].astype(float))[
                        :, 1
                    ]
                    briers.append(_brier(validation[target].to_numpy(dtype=float), probability))
                scores.append(
                    {
                        "feature_set": set_name,
                        "family": family,
                        "parameters": parameters,
                        "folds_used": len(briers),
                        "mean_brier": float(np.mean(briers)) if briers else None,
                    }
                )
    return scores


def fit_model(
    fit: pd.DataFrame,
    calibration: pd.DataFrame,
    target: str,
    columns: tuple[str, ...],
    family: str,
    parameters: dict[str, Any],
) -> ResearchModel:
    estimator = _estimator(family, parameters, SEED)
    estimator.fit(fit.loc[:, columns].astype(float), fit[target].astype(int))
    temporary = ResearchModel(columns, estimator, None, family)
    calibrator = fit_sigmoid(temporary.margins(calibration), calibration[target].astype(int))
    return ResearchModel(columns, estimator, calibrator, family)


def thresholds(scores: pd.Series) -> dict[str, float]:
    """Calibration-period quantiles: top-k selection and bottom-v veto cut-offs."""
    values = scores.dropna().to_numpy(dtype=float)
    if not len(values):
        raise ValueError("Thresholds need calibration-period scores")
    result = {f"top_{k:g}": float(np.quantile(values, 1.0 - k)) for k in TOP_K}
    result |= {f"veto_{v:g}": float(np.quantile(values, v)) for v in VETO}
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


def _model_bytes(model: ResearchModel) -> bytes:
    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    return buffer.getvalue()


def develop(
    sources: HistoricalSources,
    workspace: Path,
    configs: Path,
    output: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Every pre-registered choice from 2006-2021 only; writes frozen_choices.json."""
    say = progress or (lambda message: None)
    if sources.binding.horizon_sessions != HORIZON or sources.binding.acceptance != "ACCEPTED":
        raise ValueError("Development needs the accepted h20 generation")
    headline = load_headline(configs)
    exits = exit_configs(headline)
    say("simulating 2006-2021 events under eight exit variants")
    simulated = simulate_events(sources, exits, date(2006, 1, 1), DEVELOPMENT_END, progress=say)
    if pd.to_datetime(simulated["event_date"]).dt.date.gt(DEVELOPMENT_END).any():
        raise ValueError("Development stage read an assessment-period event")
    exit_choice = choose_exit(simulated, list(exits))
    chosen_exit = exit_choice["chosen"]
    gate_choice = choose_gate(simulated, chosen_exit)
    outcomes = simulated.loc[:, ["event_id", f"{chosen_exit}|status", f"{chosen_exit}|net"]]
    outcomes.columns = ["event_id", "econ_status", "econ_net"]
    frame, report = load_frame(workspace, sources.binding.evaluation.version)
    frame = frame.merge(outcomes, on="event_id", how="left")
    frame["econ"] = np.where(
        frame["econ_status"].eq("COMPLETE"),
        (frame["econ_net"].astype(float) > 0).astype(float),
        np.nan,
    )
    frame["revert"] = frame["y_revert_success"].astype(float)
    models_info = report["models"]["logistic"]
    sets = feature_sets(
        models_info["A"]["feature_columns"], models_info["B_both"]["feature_columns"]
    )
    fit_rows = frame.loc[frame["research_partition"].eq("fit")]
    calibration_rows = frame.loc[frame["research_partition"].eq("calibration")]
    if pd.to_datetime(calibration_rows["event_date"]).dt.date.gt(DEVELOPMENT_END).any():
        raise ValueError("Calibration rows must precede the assessment window")
    directory = output / "models"
    choices: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "decision": "DECISIONS 43",
        "binding": sources.binding.model_dump(mode="json"),
        "exit": exit_choice,
        "exit_config": exits[chosen_exit].model_dump(mode="json"),
        "gate": gate_choice,
        "feature_sets": {name: list(columns) for name, columns in sets.items()},
        "models": {},
    }
    for target in TARGETS:
        fit_known = fit_rows.loc[fit_rows[target].notna()]
        calibration_known = calibration_rows.loc[calibration_rows[target].notna()]
        for information, allowed in (("A", ("A",)), ("B", ("B_both", "B_lean", "B_plus"))):
            say(f"tuning {target} {information}")
            scores = tune(fit_known, target, {name: sets[name] for name in allowed})
            usable = [score for score in scores if score["mean_brier"] is not None]
            selections = {f"{information}_selected": min(usable, key=lambda s: s["mean_brier"])}
            if information == "B":
                fixed = [score for score in usable if score["feature_set"] == "B_both"]
                selections["B_both_fixed"] = min(fixed, key=lambda s: s["mean_brier"])
            for label, chosen in selections.items():
                model = fit_model(
                    fit_known,
                    calibration_known,
                    target,
                    sets[chosen["feature_set"]],
                    chosen["family"],
                    chosen["parameters"],
                )
                body = _model_bytes(model)
                key = f"{target}|{label}"
                path = write_bytes(directory / f"{target}_{label}.joblib", body)
                calibrated = pd.Series(
                    model.predict(calibration_rows), index=calibration_rows.index
                )
                gate_thresholds = {
                    "B0": thresholds(calibrated),
                    "B1": thresholds(
                        calibrated.loc[calibration_rows["baseline1_eligible"].eq(True)]
                    ),
                }
                choices["models"][key] = {
                    "target": target,
                    "information": information,
                    "label": label,
                    "feature_set": chosen["feature_set"],
                    "family": chosen["family"],
                    "parameters": chosen["parameters"],
                    "fold_mean_brier": chosen["mean_brier"],
                    "fit_n": len(fit_known),
                    "calibration_n": len(calibration_known),
                    "model_path": path.name,
                    "model_sha256": _checksum(body),
                    "thresholds": gate_thresholds,
                }
            choices.setdefault("tuning", {})[f"{target}|{information}"] = scores
    choices["development_simulation"] = {
        "events_n": len(simulated),
        "first_event": str(min(simulated["event_date"])),
        "last_event": str(max(simulated["event_date"])),
    }
    return write_bytes(output / "frozen_choices.json", _json_bytes(choices))


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


def _predictive(y: np.ndarray[Any, Any], p: np.ndarray[Any, Any]) -> dict[str, Any]:
    if len(y) == 0 or len(set(y.tolist())) < 2:
        return {"n": int(len(y)), "roc_auc": None, "pr_auc": None, "brier": None}
    return {
        "n": int(len(y)),
        "positives": int(y.sum()),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "brier": _brier(y, p),
    }


def _rule_mask(scores: pd.Series, cut: float) -> pd.Series:
    """Top-k selects scores at or above its cut; a veto keeps scores at or above its cut."""
    return scores.ge(cut)


def _economics(net: pd.Series, status: pd.Series, selected: pd.Series) -> dict[str, Any]:
    chosen = selected.astype("boolean").fillna(False).astype(bool)
    complete = chosen & status.eq("COMPLETE")
    values = net.loc[complete].astype(float)
    return {
        "selected_n": int(chosen.sum()),
        "priced_n": int(complete.sum()),
        "unknown_n": int((chosen & ~status.eq("COMPLETE")).sum()),
        "mean_net_bps": float(values.mean() * 1e4) if len(values) else None,
        "median_net_bps": float(values.median() * 1e4) if len(values) else None,
        "hit_rate": float((values > 0).mean()) if len(values) else None,
    }


def _allocation(net: pd.Series, status: pd.Series, selected: pd.Series) -> pd.Series:
    """Selected COMPLETE -> net; withheld -> 0; selected unknown or unscored -> NaN."""
    result = pd.Series(0.0, index=net.index)
    result[selected.isna()] = np.nan
    chosen = selected.astype("boolean").fillna(False).astype(bool)
    result[chosen & status.eq("COMPLETE")] = net[chosen & status.eq("COMPLETE")].astype(float)
    result[chosen & ~status.eq("COMPLETE")] = np.nan
    return result


def evaluate(
    sources: HistoricalSources,
    workspace: Path,
    output: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> Path:
    say = progress or (lambda message: None)
    raw = (output / "frozen_choices.json").read_bytes()
    choices = json.loads(raw)
    if choices["binding"] != sources.binding.model_dump(mode="json"):
        raise ValueError("Evaluation sources differ from the frozen development binding")
    models: dict[str, ResearchModel] = {}
    for key, info in choices["models"].items():
        body = (output / "models" / info["model_path"]).read_bytes()
        if _checksum(body) != info["model_sha256"]:
            raise ValueError("Frozen model checksum differs")
        models[key] = joblib.load(io.BytesIO(body))
    exit_config = ExecutionConfig.model_validate_json(json.dumps(choices["exit_config"]))
    configs = {"headline": exit_config, "stress10": cost_variant(exit_config, 10.0)}
    say("simulating 2022-2023 events under the chosen exit")
    simulated = simulate_events(sources, configs, *ASSESSMENT, progress=say)
    frame, _ = load_frame(workspace, sources.binding.evaluation.version)
    frame = simulated.merge(
        frame.drop(columns=["pair_id", "event_date"]), on="event_id", how="left"
    )
    frame["econ"] = np.where(
        frame["headline|status"].eq("COMPLETE"),
        (frame["headline|net"].astype(float) > 0).astype(float),
        np.nan,
    )
    frame["revert"] = frame["y_revert_success"].astype(float)
    month = pd.to_datetime(frame["event_date"]).dt.strftime("%Y-%m").to_numpy()
    quarter = (
        pd.to_datetime(frame["event_date"]).dt.year.astype(str)
        + "Q"
        + pd.to_datetime(frame["event_date"]).dt.quarter.astype(str)
    ).to_numpy()
    scored = frame["research_partition"].eq("assessment")
    scores: dict[str, pd.Series] = {}
    for key, model in models.items():
        values = pd.Series(np.nan, index=frame.index)
        if scored.any():
            values[scored] = model.predict(frame.loc[scored])
        scores[key] = values
    result: dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "frozen_choices_sha256": _checksum(raw),
        "post_hoc_exploratory": True,
        "final_test_read": False,
        "assessment_events_n": int(len(frame)),
        "scored_events_n": int(scored.sum()),
        "exit": choices["exit"]["chosen"],
        "headline_gate": choices["gate"]["chosen"],
        "predictive": {},
        "paired_brier_quarter_bootstrap": {},
        "economics": {},
        "paired_allocation_month_bootstrap": {},
    }
    for key, values in scores.items():
        target = choices["models"][key]["target"]
        known = values.notna() & frame[target].notna()
        result["predictive"][key] = _predictive(
            frame.loc[known, target].to_numpy(dtype=float), values[known].to_numpy(dtype=float)
        )
    for target in TARGETS:
        for b_label in ("B_selected", "B_both_fixed"):
            a, b = scores[f"{target}|A_selected"], scores[f"{target}|{b_label}"]
            known = a.notna() & b.notna() & frame[target].notna()
            y = frame.loc[known, target].to_numpy(dtype=float)
            left = (a[known].to_numpy(dtype=float) - y) ** 2
            right = (b[known].to_numpy(dtype=float) - y) ** 2
            result["paired_brier_quarter_bootstrap"][f"{target}|{b_label}-A"] = (
                paired_block_bootstrap(
                    left, right, quarter[known.to_numpy()], seed=SEED, minimum_blocks=1
                )
            )
    gates = {"B0": pd.Series(True, index=frame.index), "B1": frame["active"].astype(bool)}
    for cost in ("headline", "stress10"):
        net, status = frame[f"{cost}|net"], frame[f"{cost}|status"]
        for gate_name, gate in gates.items():
            population = gate
            prefix = f"{cost}|{gate_name}"
            result["economics"][f"{prefix}|trade_all"] = _economics(
                net[population], status[population], pd.Series(True, index=frame.index)[population]
            )
            for key, values in scores.items():
                info = choices["models"][key]
                cuts = info["thresholds"][gate_name]
                for rule, cut in cuts.items():
                    selected = _rule_mask(values, cut).astype(object)
                    selected[values.isna()] = np.nan
                    result["economics"][f"{prefix}|{key}|{rule}"] = _economics(
                        net[population], status[population], selected[population]
                    )
            for target in TARGETS:
                for b_label in ("B_selected", "B_both_fixed"):
                    for rule in choices["models"][f"{target}|A_selected"]["thresholds"][gate_name]:
                        sides = []
                        for label in ("A_selected", b_label):
                            key = f"{target}|{label}"
                            cut = choices["models"][key]["thresholds"][gate_name][rule]
                            selected = _rule_mask(scores[key], cut).astype(object)
                            selected[scores[key].isna()] = np.nan
                            sides.append(_allocation(net, status, selected))
                        known = sides[0].notna() & sides[1].notna() & population
                        result["paired_allocation_month_bootstrap"][
                            f"{prefix}|{target}|{b_label}-A|{rule}"
                        ] = {
                            "common_candidates_n": int(known.sum()),
                            **paired_block_bootstrap(
                                sides[0][known].to_numpy(dtype=float),
                                sides[1][known].to_numpy(dtype=float),
                                month[known.to_numpy()],
                            ),
                        }
    return write_bytes(output / "evaluation.json", _json_bytes(result))


def _sources(workspace: Path) -> HistoricalSources:
    paths = ProjectPaths.resolve(Path.cwd(), workspace)
    binding = bind_accepted(paths, HORIZON)
    return HistoricalSources.open(workspace.resolve(), binding, paths=paths)


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("develop", "evaluate"))
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--configs-dir", type=Path, default=Path("configs"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    sources = _sources(args.workspace_root)

    def say(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    if args.stage == "develop":
        path = develop(
            sources, args.workspace_root, args.configs_dir, args.output_dir, progress=say
        )
    else:
        path = evaluate(sources, args.workspace_root, args.output_dir, progress=say)
    print(json.dumps({"stage": args.stage, "output": str(path)}))


if __name__ == "__main__":
    main()


__all__ = [
    "choose_exit",
    "choose_gate",
    "develop",
    "evaluate",
    "exit_configs",
    "feature_sets",
    "forward_folds",
    "paired_block_bootstrap",
    "thresholds",
]
