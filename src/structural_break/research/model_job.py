"""Immutable matched A/B model jobs using cached target-free research evidence."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from structural_break.config.loader import load_config
from structural_break.config.models import Pair, UniverseConfig
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.sentiment import SENTIMENT_FEATURE_COLUMNS
from structural_break.ml.features import FEATURE_COLUMNS
from structural_break.ml.model import fit_sigmoid, predictive_metrics
from structural_break.research.evaluation import (
    ResearchModel,
    evaluate_matched_models,
    paired_assessment,
)
from structural_break.research.protocol import canonical_bytes, experiment_config, identity
from structural_break.research.runner import (
    _registered_manifest,
    computational_identity,
    publish_research,
)
from structural_break.storage.files import sha256_file, write_bytes


def _read_named(directory: Path, manifest: dict[str, Any], name: str) -> pd.DataFrame:
    item = next(item for item in manifest["files"] if item["name"] == name)
    path = confined_path(directory, item["path"])
    body = path.read_bytes()
    import hashlib

    if hashlib.sha256(body).hexdigest() != item["sha256"]:
        raise ValueError("Research input bytes changed before decoding")
    return pd.read_parquet(io.BytesIO(body))


def train_research_models(
    paths: ProjectPaths,
    registry_version: str,
    intelligence_directory: Path,
    *,
    horizon: int = 20,
) -> dict[str, Any]:
    from structural_break.research.intelligence import (
        METADATA_FEATURE_COLUMNS,
        verify_event_intelligence,
    )
    from structural_break.research.protocol import ResearchProtocol

    parent = _registered_manifest(paths, registry_version)
    if parent is None or parent["stage"] != "registry":
        raise ValueError("Research registry must be successfully registered")
    protocol = ResearchProtocol.model_validate(parent["protocol"])
    if horizon not in (protocol.primary_horizon, *protocol.sensitivity_horizons):
        raise ValueError("Unregistered research horizon")
    registry_directory = paths.artifacts / "research" / registry_version
    # The intelligence verifier reads no outcome fields and never contacts a
    # provider. It rechecks packs, exact quotes and stored sentiment aggregations.
    frames = {
        name: _read_named(registry_directory, parent, f"h{horizon}_{name}")
        for name in ("events", "features", "targets", "partitions")
    }
    universe_input = next(i for i in parent["inputs"] if i["role"] == "universe")
    universe_directory = confined_path(paths.workspace_root, universe_input["path"]).parent
    sec_directory = paths.workspace_root / "sec_metadata" / "source_v1"
    verify_event_intelligence(
        intelligence_directory,
        universe_directory,
        sec_directory,
        cache_workspace=paths.workspace_root / "cache",
    )
    features_path = intelligence_directory / "features.parquet"
    event_features = pd.read_parquet(features_path)
    if event_features["event_id"].duplicated().any():
        raise ValueError("Duplicate text feature identities")
    pairs = pd.read_parquet(universe_directory / "pair_universe.parquet")
    rows = frames["events"].merge(
        frames["features"], on="event_id", validate="one_to_one", suffixes=("", "_feature")
    )
    rows = rows.merge(
        frames["targets"][["event_id", "y_revert_success"]], on="event_id", validate="one_to_one"
    )
    rows = rows.merge(
        frames["partitions"][["event_id", "supervised_eligible"]],
        on="event_id",
        validate="one_to_one",
    )
    rows = rows.merge(pairs[["pair_id", "leg_a", "leg_b"]], on="pair_id", validate="many_to_one")
    # A target-independent evidence registry shares a pair/time source pack
    # across horizon sensitivities, avoiding repeated text/API computation.
    mappings = pd.read_parquet(intelligence_directory / "event_mapping.parquet")
    key_columns = ["pair_id", "event_timestamp"]
    mappings["event_timestamp"] = pd.to_datetime(mappings["event_timestamp"], utc=True)
    if mappings.duplicated(key_columns).any():
        raise ValueError("Text evidence registry has duplicate pair/time observations")
    rows["event_timestamp"] = pd.to_datetime(rows["event_timestamp"], utc=True)
    mappings = mappings.rename(columns={"event_id": "evidence_event_id"})
    rows = rows.merge(
        mappings[key_columns + ["evidence_event_id"]],
        on=key_columns,
        how="left",
        validate="many_to_one",
    )
    if rows["evidence_event_id"].isna().any():
        raise ValueError("Every quantitative event requires an explicit text/UNKNOWN row")
    event_features = event_features.rename(columns={"event_id": "evidence_event_id"})
    text_columns = (*EVENT_FEATURE_NAMES, *SENTIMENT_FEATURE_COLUMNS, *METADATA_FEATURE_COLUMNS)
    rows = rows.merge(
        event_features[["evidence_event_id", *text_columns]],
        on="evidence_event_id",
        how="left",
        validate="many_to_one",
    )
    if len(rows) != len(frames["events"]):
        raise ValueError("Matched quantitative cohort changed during evidence join")
    rows["tone_aligned_contrast"] = rows["divergence_sign"] * rows["sentiment_net_contrast"]
    tone_columns = (*SENTIMENT_FEATURE_COLUMNS, "tone_aligned_contrast")
    blocks = {
        "metadata": METADATA_FEATURE_COLUMNS,
        "tone": tone_columns,
        "catalyst": EVENT_FEATURE_NAMES,
        "both": (*EVENT_FEATURE_NAMES, *tone_columns, *METADATA_FEATURE_COLUMNS),
    }
    computation = computational_identity(paths.project_root)
    inputs = {
        "registry_version": registry_version,
        "registry_manifest_sha256": sha256_file(registry_directory / "manifest.json"),
        "intelligence_manifest_sha256": sha256_file(intelligence_directory / "manifest.json"),
        "horizon": horizon,
        "computation": computation,
    }
    generation = "research_evaluation_" + identity(inputs)[:24]
    existing = _registered_manifest(paths, generation)
    if existing is not None:
        return existing
    result = evaluate_matched_models(rows, FEATURE_COLUMNS, blocks, protocol)
    if computational_identity(paths.project_root) != computation:
        raise ValueError("Source changed during matched fitting")
    directory = paths.artifacts / "research" / generation
    native_files = []
    for name, content in result.models.items():
        native = write_bytes(directory / "models" / f"{name}.joblib", content)
        native_files.append(
            {
                "name": name,
                "path": native.relative_to(directory).as_posix(),
                "sha256": sha256_file(native),
            }
        )
    report = write_bytes(directory / "report.json", canonical_bytes(result.report))
    config = experiment_config(
        load_config(paths.project_root / "configs"),
        protocol,
        UniverseConfig(
            version="research-v2-survivor-peers",
            orientation="leg_a_is_y",
            pairs=tuple(
                Pair(leg_a=r["leg_a"], leg_b=r["leg_b"], peer_group=r["peer_group"])
                for r in pairs.to_dict("records")
            ),
        ),
        horizon,
    )
    manifest = {
        "identity_inputs": inputs,
        "model_files": native_files,
        "report_sha256": sha256_file(report),
        "final_test_read": False,
        "parents": [
            {
                "role": role,
                "path": path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(path),
            }
            for role, path in (
                ("registry", registry_directory / "manifest.json"),
                ("intelligence", intelligence_directory / "manifest.json"),
            )
        ],
    }
    manifest = publish_research(
        paths,
        config,
        protocol,
        "evaluation",
        generation,
        directory,
        manifest,
        {"predictions": result.predictions, "model_inputs": rows},
    )
    verify_research_models(paths, generation)
    return manifest


def verify_research_models(paths: ProjectPaths, research_version: str) -> dict[str, Any]:
    from structural_break.research.intelligence import verify_event_intelligence
    from structural_break.research.protocol import ResearchProtocol

    manifest = _registered_manifest(paths, research_version)
    if manifest is None or manifest["stage"] != "evaluation":
        raise ValueError("Research evaluation must be registered")
    directory = paths.artifacts / "research" / research_version
    report = json.loads((directory / "report.json").read_bytes())
    if sha256_file(directory / "report.json") != manifest["report_sha256"]:
        raise ValueError("Research model report changed")
    for parent in manifest["parents"]:
        path = confined_path(paths.workspace_root, parent["path"])
        if sha256_file(path) != parent["sha256"]:
            raise ValueError("Research evaluation parent changed")
    registry_parent = _registered_manifest(paths, manifest["identity_inputs"]["registry_version"])
    if registry_parent is None:
        raise ValueError("Research evaluation registry parent is not registered")
    universe_input = next(i for i in registry_parent["inputs"] if i["role"] == "universe")
    universe_directory = confined_path(paths.workspace_root, universe_input["path"]).parent
    intelligence_parent = next(p for p in manifest["parents"] if p["role"] == "intelligence")
    verify_event_intelligence(
        confined_path(paths.workspace_root, intelligence_parent["path"]).parent,
        universe_directory,
        paths.workspace_root / "sec_metadata" / "source_v1",
        cache_workspace=paths.workspace_root / "cache",
    )
    rows = _read_named(directory, manifest, "model_inputs")
    stored = _read_named(directory, manifest, "predictions")
    rows = rows.set_index("event_id").loc[stored["event_id"]].reset_index()
    errors: dict[str, float] = {}
    assessment = stored["research_partition"].eq("assessment")
    protocol = ResearchProtocol.model_validate(manifest["protocol"])
    for item in manifest["model_files"]:
        path = confined_path(directory, item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ValueError("Research native model checksum mismatch")
        model: ResearchModel = joblib.load(io.BytesIO(path.read_bytes()))
        probabilities = model.predict(rows)
        raw_probabilities = model.estimator.predict_proba(rows.loc[:, model.columns].astype(float))[
            :, 1
        ]
        raw_error = float(
            np.max(np.abs(raw_probabilities - stored[f"{item['name']}_raw"].to_numpy()))
        )
        error = float(
            np.max(np.abs(probabilities - stored[f"{item['name']}_calibrated"].to_numpy()))
        )
        if error > 1e-12 or raw_error > 1e-12:
            raise ValueError("Research native probabilities do not replay")
        errors[item["name"]] = max(error, raw_error)
        family, name = item["name"].split("_", 1)
        calibration_mask = stored["research_partition"].eq("calibration")
        recalibrated = fit_sigmoid(
            model.margins(rows.loc[calibration_mask.to_numpy()]),
            stored.loc[calibration_mask, "y_revert_success"].to_numpy(),
        )
        if vars(recalibrated) != vars(model.calibrator):
            raise ValueError(
                "Research calibrator does not reproduce on the independent calibration tail"
            )
        expected_metrics = predictive_metrics(
            stored.loc[assessment, "y_revert_success"].to_numpy(),
            probabilities[assessment.to_numpy()],
            protocol.candidate_threshold,
        )
        if expected_metrics != report["models"][family][name]["calibrated_assessment"]:
            raise ValueError("Stored research assessment metrics do not reproduce")
        raw_metrics = predictive_metrics(
            stored.loc[assessment, "y_revert_success"].to_numpy(),
            raw_probabilities[assessment.to_numpy()],
            protocol.candidate_threshold,
        )
        if raw_metrics != report["models"][family][name]["raw_assessment"]:
            raise ValueError("Stored raw research assessment metrics do not reproduce")
        if name != "A":
            paired = paired_assessment(
                stored.loc[assessment],
                stored.loc[assessment, f"{family}_A_calibrated"].to_numpy(),
                probabilities[assessment.to_numpy()],
                protocol,
            )
            if paired != report["models"][family][name]["paired_assessment"]:
                raise ValueError("Stored paired research comparison does not reproduce")
    return {
        "research_version": research_version,
        "native_max_errors": errors,
        "paired_comparison_reproduced": True,
        "final_test_read": False,
    }
