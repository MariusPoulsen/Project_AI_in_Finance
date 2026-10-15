"""Read accepted development data and reload existing models without training."""

from __future__ import annotations

import io
from importlib.metadata import version
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.research.evaluation import ResearchModel
from structural_break.research.primary import (
    MODEL_NAMES,
    checked_file,
    checked_json,
    load_primary,
    registered_manifest,
)
from structural_break.storage.files import sha256_file


def existing_predictions(
    paths: ProjectPaths,
    *,
    horizon: int = 20,
    pair_id: str | None = None,
    models: tuple[str, ...] = ("logistic_A", "logistic_B_both"),
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reload immutable fitted models and compare every returned probability."""
    primary = load_primary(paths)
    evaluations = primary["identity_inputs"]["evaluations"]
    if (
        str(horizon) not in evaluations
        or not models
        or not set(models).issubset(MODEL_NAMES)
        or len(models) != len(set(models))
    ):
        raise ValueError("Choose a published horizon and distinct predeclared model names")
    path, manifest = registered_manifest(
        paths, evaluations[str(horizon)]["research_version"], "evaluation"
    )
    for name, pinned in manifest["identity_inputs"]["computation"]["libraries"].items():
        if version(name) != pinned:
            raise ValueError(
                "Native inference requires the original locked numerical libraries; run team setup"
            )
    stored = pd.read_parquet(checked_file(path.parent, manifest, "predictions"))
    rows = pd.read_parquet(checked_file(path.parent, manifest, "model_inputs"))
    if stored["event_id"].duplicated().any() or rows["event_id"].duplicated().any():
        raise ValueError("Existing event identities must be unique")
    if pair_id is not None:
        stored = stored.loc[stored["pair_id"].eq(pair_id)].copy()
    if stored.empty:
        raise ValueError("No published development events match this selection")
    rows = rows.set_index("event_id").loc[stored["event_id"]].reset_index()
    dates = pd.to_datetime(stored["event_date"], errors="raise").dt.date
    if (
        dates.isna().any()
        or dates.gt(pd.Timestamp(manifest["protocol"]["development_end"]).date()).any()
    ):
        raise ValueError("Existing inference cannot open final-test events")
    columns = [
        name
        for name in (
            "event_id",
            "event_date",
            "pair_id",
            "leg_a",
            "leg_b",
            "research_partition",
            "baseline1_eligible",
        )
        if name in stored
    ]
    result = stored.loc[:, columns].reset_index(drop=True)
    errors = {}
    for name in models:
        entries = [item for item in manifest["model_files"] if item["name"] == name]
        if len(entries) != 1:
            raise ValueError("Published model inventory differs")
        item = entries[0]
        model_path = confined_path(path.parent, item["path"])
        body = model_path.read_bytes()
        import hashlib

        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("Saved native model checksum differs")
        model: ResearchModel = joblib.load(io.BytesIO(body))
        if model.family != name.split("_", 1)[0] or not model.columns:
            raise ValueError("Native model family or feature inventory differs")
        raw = np.asarray(
            model.estimator.predict_proba(rows.loc[:, model.columns].astype(float))[:, 1],
            dtype=float,
        )
        calibrated = np.asarray(model.predict(rows), dtype=float)
        error = max(
            float(np.max(np.abs(raw - stored[name + "_raw"].to_numpy(dtype=float)))),
            float(np.max(np.abs(calibrated - stored[name + "_calibrated"].to_numpy(dtype=float)))),
        )
        if (
            not np.isfinite(raw).all()
            or not np.isfinite(calibrated).all()
            or not np.isfinite(error)
            or error > 1e-12
        ):
            raise ValueError("Reloaded model predictions differ from the accepted publication")
        result[name + "_raw"] = raw
        result[name + "_calibrated"] = calibrated
        errors[name] = error
    return result, {
        "primary_version": primary["primary_version"],
        "horizon": horizon,
        "events": len(result),
        "native_max_errors": errors,
        "final_test_unlocked": False,
    }


def backtest_inputs(
    paths: ProjectPaths, pair_id: str, *, horizon: int = 20
) -> dict[str, pd.DataFrame]:
    """Return frozen prices, entry/relationship history and accepted predictions.

    These are simulator inputs, not a backtest result or an investability claim.
    Keep broad-registry episode construction and actual ACTIVE flags intact.
    """
    primary = load_primary(paths)
    if str(horizon) not in primary["identity_inputs"]["evaluations"]:
        raise ValueError("Choose a published predeclared horizon")
    registry_path, registry = registered_manifest(
        paths, primary["identity_inputs"]["registry_version"], "registry"
    )
    matches = [item for item in registry["pair_manifests"] if item["pair_id"] == pair_id]
    if len(matches) != 1:
        raise ValueError("Select one frozen pair identity")
    pair_path = confined_path(registry_path.parent / "pairs", pair_id + "/manifest.json")
    pair = checked_json(pair_path, matches[0]["sha256"])
    frames = {
        name: pd.read_parquet(checked_file(pair_path.parent, pair, name))
        for name in (
            "relationship_snapshots",
            "daily_pair_state",
            "raw_crossings",
            f"h{horizon}_events",
            f"h{horizon}_features",
            f"h{horizon}_targets",
            f"h{horizon}_partitions",
        )
    }
    market_item = next(item for item in registry["inputs"] if item["role"] == "market")
    market_path = confined_path(paths.workspace_root, market_item["path"])
    market = checked_json(market_path, market_item["sha256"])
    prices_path = confined_path(market_path.parent, "prices.parquet")
    if sha256_file(prices_path) != market["files"]["prices.parquet"]:
        raise ValueError("Backtest price checksum differs")
    roster_path = confined_path(market_path.parent, "pair_universe.parquet")
    if sha256_file(roster_path) != market["files"]["pair_universe.parquet"]:
        raise ValueError("Backtest pair roster checksum differs")
    roster = pd.read_parquet(roster_path)
    row = roster.loc[roster["pair_id"].eq(pair_id)]
    if len(row) != 1:
        raise ValueError("Market pair orientation differs")
    prices = pd.read_parquet(prices_path)
    prices = prices.loc[prices["ticker"].isin(row.iloc[0][["leg_a", "leg_b"]].tolist())].copy()
    cutoff = pd.Timestamp(primary["identity_inputs"]["protocol"]["development_end"]).date()
    if pd.to_datetime(prices["trading_date"]).dt.date.gt(cutoff).any():
        raise ValueError("Backtesting inputs cannot include final-test prices")
    frames["prices"] = prices
    evaluation_path, evaluation = registered_manifest(
        paths,
        primary["identity_inputs"]["evaluations"][str(horizon)]["research_version"],
        "evaluation",
    )
    predictions = pd.read_parquet(checked_file(evaluation_path.parent, evaluation, "predictions"))
    frames["predictions"] = predictions.loc[predictions["pair_id"].eq(pair_id)].copy()
    return frames


def write_frames(frames: dict[str, pd.DataFrame], directory: Path) -> dict[str, str]:
    if directory.exists():
        raise FileExistsError("Choose a new output directory")
    directory.mkdir(parents=True)
    output = {}
    for name, rows in frames.items():
        path = directory / (name + ".parquet")
        rows.to_parquet(path, index=False)
        output[name] = sha256_file(path)
    return output
