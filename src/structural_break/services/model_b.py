"""Offline Model B fitting and verified inference on the unchanged Model A cohort."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from structural_break.common.logging import configure_logging, new_run_id
from structural_break.config.loader import config_hash
from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.snapshots import content_identity, json_bytes
from structural_break.ml.model import predictive_metrics, validate_features
from structural_break.services.foundation import git_revision
from structural_break.services.model_a import (
    ModelARepository,
    UnpublishedVersionError,
    _archive_unregistered,
    _freeze_frames,
    _read_frames,
    merge_event_rows,
    ml_computation_identity,
    validate_event_frames,
)
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import segment, sha256_file, write_bytes
from structural_break.storage.model_b import publish_model_b
from structural_break.storage.registry import Registration, RunRegistry


def _read_verified_frames(
    paths: ProjectPaths,
    manifest: dict[str, Any],
    *,
    datasets: frozenset[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Read the same bytes that match a previously verified manifest's hashes."""
    frames = {}
    for item in manifest["files"]:
        if not item["path"].endswith(".parquet") or (
            datasets is not None and item["dataset"] not in datasets
        ):
            continue
        raw = confined_path(paths.workspace_root, item["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Verified artifact checksum changed during the operation")
        frames[item["dataset"]] = pd.read_parquet(io.BytesIO(raw))
    return frames


def _verify_manifest_files(paths: ProjectPaths, manifest: dict[str, Any]) -> None:
    for item in manifest["files"]:
        if sha256_file(confined_path(paths.workspace_root, item["path"])) != item["sha256"]:
            raise ValueError("Verified artifact checksum changed during the operation")


@dataclass(frozen=True)
class _VerifiedModelBInputs:
    """Request-local lineage; never retained by a repository or reused by public reads."""

    model: dict[str, Any]
    evidence: dict[str, Any]
    dataset: dict[str, Any]
    model_a: dict[str, Any]
    references: tuple[tuple[str, str], ...]

    def verify_files(self, paths: ProjectPaths) -> None:
        for path, expected in self.references:
            if sha256_file(confined_path(paths.workspace_root, path)) != expected:
                raise ValueError("Verified parent manifest checksum changed during the operation")
        for manifest in (self.model, self.evidence, self.dataset, self.model_a):
            _verify_manifest_files(paths, manifest)


def model_b_feature_schema(
    model_a_schema: dict[str, Any], *, version: str | None = None
) -> dict[str, Any]:
    """Append the fixed event block; preserve every quantitative definition/order."""
    from structural_break.intelligence.event_features import event_schema_columns

    columns = copy.deepcopy(model_a_schema["columns"]) + event_schema_columns()
    names = [column["name"] for column in columns]
    if len(names) != len(set(names)):
        raise ValueError("Model B feature families have overlapping names")
    identity = {"model_a_schema": model_a_schema, "columns": columns}
    return {
        "version": version or "model-b-" + content_identity(identity)[:24],
        "model_a_feature_schema_version": model_a_schema["version"],
        "feature_columns": names,
        "columns": columns,
    }


def merge_model_b_rows(
    parent_frames: dict[str, pd.DataFrame],
    model_b_features: pd.DataFrame,
    schema: dict[str, Any],
) -> pd.DataFrame:
    """Reject cohort/quantitative changes rather than making an easier evidence subset."""
    validate_event_frames(parent_frames)
    parent_rows = merge_event_rows(parent_frames)
    original = parent_rows.set_index("event_id")
    if model_b_features["event_id"].duplicated().any() or set(model_b_features["event_id"]) != set(
        original.index
    ):
        raise ValueError("Model B must retain exactly one feature row for every Model A event")
    features = model_b_features.set_index("event_id").reindex(original.index)
    if "event_available_at" not in features:
        raise ValueError("Model B lacks structured event availability timestamp")
    quantitative = [item["name"] for item in schema["columns"] if item.get("family") != "event"]
    for name in (
        *quantitative,
        "event_timestamp",
        "feature_cutoff_timestamp",
        "data_snapshot_id",
        "relationship_version",
        "dataset_version",
    ):
        if name not in features or name not in original:
            raise ValueError(f"Model B lacks original feature/lineage field: {name}")
        try:
            pd.testing.assert_series_equal(
                features[name],
                original[name],
                check_dtype=False,
                check_names=False,
                check_exact=True,
            )
        except AssertionError as error:
            raise ValueError(
                f"Model B changed original quantitative values/lineage: {name}"
            ) from error
    for name in (
        "feature_cutoff_timestamp",
        "event_feature_cutoff_timestamp",
        "evidence_max_timestamp",
        "event_available_at",
    ):
        if name in features:
            observed = pd.to_datetime(features[name], utc=True)
            cutoffs = pd.to_datetime(features["event_timestamp"], utc=True)
            if observed.gt(cutoffs).any():
                raise ValueError("Structured event evidence exceeds event cutoff")
            if name == "event_available_at" and observed.isna().any():
                raise ValueError("Structured event availability cannot be unknown")
    rows = parent_rows.copy()
    additions = [name for name in model_b_features if name not in rows and name != "event_id"]
    rows = rows.merge(
        model_b_features[["event_id", *additions]], on="event_id", validate="one_to_one"
    )
    rows["feature_schema_version"] = schema["version"]
    # Optional missing event values remain NaN; explicit UNKNOWN indicators stay finite.
    validate_features(rows.loc[rows["model_ready"], schema["feature_columns"]], schema)
    return rows


def compare_model_a_b(
    rows: pd.DataFrame,
    model_a_predictions: pd.DataFrame,
    model_b_predictions: pd.DataFrame,
    *,
    threshold: float,
) -> dict[str, Any]:
    """Paired validation comparison and coverage slices, without final outcomes."""
    final = rows["partition"].isin(["final_test", "test"])
    if rows.loc[final, "y_revert_success"].notna().any():
        raise ValueError("Final-test outcomes cannot enter the Model A/B comparison")
    eligible = rows.loc[rows["partition"].eq("validation") & rows["supervised_eligible"]].copy()
    eligible = eligible.sort_values(["event_timestamp", "event_id"]).reset_index(drop=True)
    ids = eligible["event_id"].tolist()
    aligned: dict[str, pd.DataFrame] = {}
    for label, predictions in (("A", model_a_predictions), ("B", model_b_predictions)):
        if predictions["event_id"].duplicated().any() or not set(ids).issubset(
            predictions["event_id"]
        ):
            raise ValueError(
                "Model comparison requires predictions for every eligible validation event"
            )
        aligned[label] = predictions.set_index("event_id").loc[ids].reset_index()
    y = eligible["y_revert_success"].astype(int)

    def metrics(mask: pd.Series) -> dict[str, Any]:
        return {
            label: {
                "raw": predictive_metrics(
                    y[mask], predictions.loc[mask, "raw_probability"], threshold
                ),
                "calibrated": predictive_metrics(
                    y[mask], predictions.loc[mask, "calibrated_probability"], threshold
                ),
            }
            for label, predictions in aligned.items()
        }

    all_events = pd.Series(True, index=eligible.index)
    groups = {
        "all_eligible_validation": all_events,
        "evidence_available": eligible["evidence_available"].eq(1),
        "UNKNOWN": eligible["event_type_UNKNOWN"].eq(1),
        "NONE": eligible["event_type_NONE"].eq(1),
        "supported_catalyst": eligible["event_type_UNKNOWN"].eq(0)
        & eligible["event_type_NONE"].eq(0),
    }
    paired = {
        name: {"event_ids": eligible.loc[mask, "event_id"].tolist(), **metrics(mask)}
        for name, mask in groups.items()
    }
    overall = paired["all_eligible_validation"]
    deltas: dict[str, Any] = {}
    for role in ("raw", "calibrated"):
        deltas[role] = {
            name: None
            if overall["A"][role][name] is None or overall["B"][role][name] is None
            else overall["B"][role][name] - overall["A"][role][name]
            for name in ("roc_auc", "pr_auc", "brier", "coverage")
        }
    validation = rows.loc[rows["partition"].eq("validation")]
    return {
        "comparison_policy": (
            "Same frozen P3 eligible validation events for both models; no evidence-based filtering"
        ),
        "raw_metric_role": "RAW_VALIDATION_HOLDOUT",
        "calibrated_metric_role": "CALIBRATION_FIT_DESCRIPTIVE",
        "validation_total_events": len(validation),
        "validation_supervised_eligible": len(eligible),
        "validation_excluded_by_original_A_policy": len(validation) - len(eligible),
        "validation_positives": int(y.sum()),
        "validation_class_identifiable": y.nunique() == 2,
        "paired_subsets": paired,
        "B_minus_A": deltas,
        "threshold": threshold,
        "final_test": {"status": "LOCKED", "outcomes_inspected": False},
        "interpretation": (
            "Raw probabilities are holdout comparisons. Calibrated probabilities are fitted "
            "on these validation outcomes. Coverage subsets are descriptive paired slices "
            "and cannot replace the full-cohort comparison. A single class makes ROC-AUC "
            "and PR-AUC undefined; a constant smoothed calibrator does not establish "
            "predictive usefulness."
        ),
    }


def _matching_model_a(paths: ProjectPaths, dataset_version: str) -> dict[str, Any]:
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        row = connection.execute(
            "SELECT v.model_version FROM analytics.model_versions v "
            "JOIN ops.job_runs r ON v.run_id=r.run_id "
            "WHERE v.dataset_version=? AND r.status='SUCCESS' "
            "ORDER BY r.finished_at DESC,v.model_version LIMIT 1",
            [dataset_version],
        ).fetchone()
    if row is None:
        raise UnpublishedVersionError(
            "Model B requires a fitted Model A on its unchanged parent dataset"
        )
    return ModelARepository(paths).manifest(str(row[0]))


def train_model_b(
    paths: ProjectPaths,
    config: ProjectConfig,
    *,
    event_feature_version: str | None = None,
    model_version: str | None = None,
) -> dict[str, Any]:
    """Train only from stored, verified structured features; never call an LLM."""
    from structural_break.ml.model import train_chronological_model
    from structural_break.services.intelligence import EvidenceRepository

    paths.create_directories()
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    evidence_repository = EvidenceRepository(paths)
    evidence = evidence_repository.manifest(event_feature_version)
    dataset = ModelARepository(paths).dataset_manifest(evidence["dataset_version"])
    current_config = config.model_dump(mode="json")
    for section in ("data", "universe", "econometrics", "ml"):
        if dataset["config_snapshot"][section] != current_config[section]:
            raise ValueError(
                "Parent event scientific settings differ from Model B training settings"
            )
    schema = evidence["feature_schema"]
    expected = model_b_feature_schema(dataset["feature_schema"], version=schema["version"])
    if schema != expected:
        raise ValueError("Model B schema differs from frozen Model A plus structured event block")
    frames = evidence_repository._frames_from_verified_manifest(evidence)
    rows = merge_model_b_rows(_read_frames(paths, dataset), frames["model_b_features"], schema)
    model_a = _matching_model_a(paths, dataset["dataset_version"])
    parent_evidence = _registered_evidence_path(paths, evidence["event_feature_version"])
    parent_references = (
        (parent_evidence["path"], parent_evidence["sha256"]),
        (
            f"artifacts/events/{dataset['dataset_version']}/manifest.json",
            sha256_file(paths.artifacts / "events" / dataset["dataset_version"] / "manifest.json"),
        ),
        (
            f"artifacts/models/{model_a['model_version']}/manifest.json",
            sha256_file(paths.artifacts / "models" / model_a["model_version"] / "manifest.json"),
        ),
    )
    identity = {
        "dataset_version": dataset["dataset_version"],
        "event_feature_version": evidence["event_feature_version"],
        "model_a_version": model_a["model_version"],
        "config_hash": config_hash(config),
        "computation_identity": ml_computation_identity(),
    }
    model_id = segment(model_version or "model_b_" + content_identity(identity)[:24])
    with factory.connect() as connection:
        registered = connection.execute(
            "SELECT count(*) FROM analytics.model_b_versions WHERE model_version=?", [model_id]
        ).fetchone()
    repository = ModelBRepository(paths)
    if registered and registered[0]:
        previous = repository.manifest(model_id)
        if any(previous.get(key) != value for key, value in identity.items()):
            raise ValueError("Model B identity already has different inputs/settings/computation")
        return previous
    run_id = new_run_id()
    destination = paths.artifacts / "models" / model_id
    _archive_unregistered(paths, destination, run_id)
    registry = RunRegistry(factory, paths.workspace_root)
    revision = git_revision(paths.project_root)
    registry.start(run_id, "train-model-b", config, revision, dataset["dataset_version"])
    logger = configure_logging()
    logger.info("Model B training started", extra={"run_id": run_id, "model_version": model_id})
    try:
        result = train_chronological_model(
            rows,
            schema,
            config.ml,
            destination,
            model_version=model_id,
            dataset_version=dataset["dataset_version"],
            tracking_directory=paths.artifacts / "mlflow",
            label_policy=dataset["label_policy"],
            expected_feature_schema_version=schema["version"],
            model_variant="B",
        )
        ready = rows.loc[rows["model_ready"]].reset_index(drop=True)
        predictions = pd.concat(
            [
                ready[["event_id", "pair_id", "event_timestamp", "partition"]],
                result.bundle.predict(ready[schema["feature_columns"]]),
            ],
            axis=1,
        )
        predictions["dataset_version"] = dataset["dataset_version"]
        predictions["relationship_version"] = dataset["relationship_version"]
        predictions["event_feature_version"] = evidence["event_feature_version"]
        predictions["prediction_timestamp"] = datetime.now(UTC)
        predictions["code_revision"] = revision
        predictions["evaluation_role"] = predictions["partition"].map(
            {
                "train": "TRAINING_RESUBSTITUTION",
                "validation": "CALIBRATION_FIT_DESCRIPTIVE",
                "final_test": "LOCKED_FEATURE_ONLY_INFERENCE",
                "outside": "EXCLUDED",
            }
        )
        excluded = ready["partition"].isin(["train", "validation"]) & ~ready["supervised_eligible"]
        predictions.loc[excluded, "evaluation_role"] = "EXCLUDED_FROM_SUPERVISION"
        prediction_files = _freeze_frames(paths, destination, {"model_b_predictions": predictions})
        comparison = compare_model_a_b(
            rows,
            _read_frames(paths, model_a)["model_predictions"],
            predictions,
            threshold=float(config.ml.candidate_threshold),
        )
        comparison.update(
            {
                "model_a_version": model_a["model_version"],
                "model_b_version": model_id,
                "dataset_version": dataset["dataset_version"],
                "event_feature_version": evidence["event_feature_version"],
            }
        )
        write_bytes(destination / "model_a_b_comparison.json", json_bytes(comparison))
        native_files = [
            {
                "dataset": path.stem,
                "path": path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in sorted(destination.iterdir())
            if path.is_file() and path.name not in {"manifest.json", "model_b_predictions.parquet"}
        ]
        # Detect changes during fitting without repeating the SEC scientific audit.
        for path, expected_sha256 in parent_references:
            if sha256_file(confined_path(paths.workspace_root, path)) != expected_sha256:
                raise ValueError("Verified parent manifest checksum changed during the operation")
        for upstream in (evidence, dataset, model_a):
            _verify_manifest_files(paths, upstream)
        manifest = {
            **identity,
            "model_version": model_id,
            "data_snapshot_id": dataset["data_snapshot_id"],
            "relationship_version": dataset["relationship_version"],
            "synthetic": dataset["synthetic"],
            "run_id": run_id,
            "code_revision": revision,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "config_snapshot": current_config,
            "files": native_files + prediction_files,
            "model_manifest": result.manifest,
            "feature_schema": schema,
            "metrics": result.metrics,
            "comparison": comparison,
            "counts": {"predictions": len(predictions)},
            "upstream_event_manifest_sha256": parent_references[1][1],
            "parent_evidence_manifest": parent_evidence,
            "upstream_model_a_manifest_sha256": parent_references[2][1],
            "final_test_outcomes_computed": False,
        }
        manifest_path = write_bytes(destination / "manifest.json", json_bytes(manifest))
        registry.finish(
            run_id,
            status="SUCCESS",
            record_count=len(predictions),
            artifacts=(Registration("model-b", model_id, manifest_path),),
            publish=lambda connection: publish_model_b(
                connection, paths, manifest, predictions, run_id
            ),
        )
        logger.info("Model B published", extra={"run_id": run_id, "status": "SUCCESS"})
        return manifest
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        write_bytes(
            destination / "failures" / f"{run_id}.json",
            json_bytes(
                {"run_id": run_id, "model_version": model_id, "error_type": type(error).__name__}
            ),
        )
        raise


def _registered_evidence_path(paths: ProjectPaths, identity: str) -> dict[str, str]:
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        row = connection.execute(
            "SELECT manifest_path,checksum FROM analytics.event_intelligence_versions "
            "WHERE event_feature_version=?",
            [identity],
        ).fetchone()
    if row is None:
        raise UnpublishedVersionError("Structured event generation is not registered")
    return {"path": str(row[0]), "sha256": str(row[1])}


class ModelBRepository:
    """Read immutable model/SHAP caches, with their original evidence and Model A parents."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.factory = DuckDBConnectionFactory(paths.database)

    def manifest(self, model_version: str | None = None) -> dict[str, Any]:
        return self._verified_inputs(model_version).model

    def _verified_inputs(self, model_version: str | None = None) -> _VerifiedModelBInputs:
        from structural_break.services.intelligence import EvidenceRepository

        try:
            with self.factory.connect() as connection:
                if model_version is None:
                    row = connection.execute(
                        "SELECT v.manifest_path,v.checksum,v.model_version "
                        "FROM ops.active_model_b a "
                        "JOIN analytics.model_b_versions v ON a.model_version=v.model_version "
                        "WHERE singleton"
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT manifest_path,checksum,model_version "
                        "FROM analytics.model_b_versions "
                        "WHERE model_version=?",
                        [model_version],
                    ).fetchone()
        except duckdb.CatalogException as error:
            raise UnpublishedVersionError("No published Model B") from error
        if row is None:
            raise UnpublishedVersionError("No published Model B")
        path = confined_path(self.paths.workspace_root, row[0])
        if sha256_file(path) != row[1]:
            raise ValueError("Model B manifest checksum mismatch")
        manifest: dict[str, Any] = json.loads(path.read_bytes())
        if (
            manifest["model_version"] != row[2]
            or manifest.get("final_test_outcomes_computed") is not False
        ):
            raise ValueError("Model B identity or final-test lock differs")
        for item in manifest["files"]:
            if (
                sha256_file(confined_path(self.paths.workspace_root, item["path"]))
                != item["sha256"]
            ):
                raise ValueError("Model B artifact checksum mismatch")
        parent = manifest["parent_evidence_manifest"]
        if (
            sha256_file(confined_path(self.paths.workspace_root, parent["path"]))
            != parent["sha256"]
        ):
            raise ValueError("Model B evidence parent checksum mismatch")
        evidence = EvidenceRepository(self.paths).manifest(manifest["event_feature_version"])
        dataset = ModelARepository(self.paths).dataset_manifest(manifest["dataset_version"])
        model_a = ModelARepository(self.paths).manifest(manifest["model_a_version"])
        for upstream in (evidence, dataset, model_a):
            for name in (
                "dataset_version",
                "data_snapshot_id",
                "relationship_version",
                "synthetic",
            ):
                if upstream[name] != manifest[name]:
                    raise ValueError("Model B upstream source identity differs")
        for kind, key, identity in (
            ("events", "upstream_event_manifest_sha256", manifest["dataset_version"]),
            ("models", "upstream_model_a_manifest_sha256", manifest["model_a_version"]),
        ):
            if (
                sha256_file(self.paths.artifacts / kind / identity / "manifest.json")
                != manifest[key]
            ):
                raise ValueError("Model B upstream manifest mismatch")
        nested = manifest["model_manifest"]
        if (
            nested["model_version"] != manifest["model_version"]
            or nested["dataset_version"] != manifest["dataset_version"]
            or nested["feature_schema_version"] != manifest["feature_schema"]["version"]
            or evidence["feature_schema"] != manifest["feature_schema"]
            or nested.get("final_test_locked") is not True
            or model_a["dataset_version"] != manifest["dataset_version"]
        ):
            raise ValueError("Model B bundle schema or parent cohort differs")
        return _VerifiedModelBInputs(
            manifest,
            evidence,
            dataset,
            model_a,
            (
                (str(row[0]), str(row[1])),
                (parent["path"], parent["sha256"]),
                (
                    f"artifacts/events/{manifest['dataset_version']}/manifest.json",
                    manifest["upstream_event_manifest_sha256"],
                ),
                (
                    f"artifacts/models/{manifest['model_a_version']}/manifest.json",
                    manifest["upstream_model_a_manifest_sha256"],
                ),
            ),
        )

    def active_manifest(self) -> dict[str, Any]:
        return self.manifest()

    def features(self, event_ids: list[str] | None = None) -> pd.DataFrame:
        from structural_break.services.intelligence import EvidenceRepository

        inputs = self._verified_inputs()
        frame = EvidenceRepository(self.paths)._frames_from_verified_manifest(inputs.evidence)[
            "model_b_features"
        ]
        return frame if event_ids is None else frame.loc[frame["event_id"].isin(event_ids)].copy()

    def predictions(
        self, pair_id: str | None = None, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        manifest = self.active_manifest()
        return ModelARepository._filter(
            _read_frames(self.paths, manifest)["model_b_predictions"], pair_id, start, end
        )

    def events(
        self, pair_id: str | None = None, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        manifest = self.active_manifest()
        frames = ModelARepository(self.paths).dataset_frames(manifest["dataset_version"])
        return ModelARepository._filter(frames["divergence_events"], pair_id, start, end)

    def comparison(self) -> dict[str, Any]:
        manifest = self.active_manifest()
        return dict(manifest["comparison"])

    def load_bundle(self) -> Any:
        from structural_break.ml.model import load_bundle

        manifest = self.active_manifest()
        return load_bundle(self.paths.artifacts / "models" / manifest["model_version"])


def verify_model_b(paths: ProjectPaths) -> dict[str, Any]:
    """Replay persisted probabilities and SHAP; final rows are features-only inference."""
    repository = ModelBRepository(paths)
    inputs = repository._verified_inputs()
    manifest = inputs.model
    stored = _read_verified_frames(paths, manifest)["model_b_predictions"]
    from structural_break.ml.model import load_bundle
    from structural_break.services.intelligence import EvidenceRepository

    evidence_frames = EvidenceRepository(paths)._frames_from_verified_manifest(inputs.evidence)
    features = evidence_frames["model_b_features"].set_index("event_id").loc[stored["event_id"]]
    # Re-anchor executable/native files after the potentially long SEC audit.
    _verify_manifest_files(paths, manifest)
    fresh = load_bundle(paths.artifacts / "models" / manifest["model_version"]).predict(
        features[manifest["feature_schema"]["feature_columns"]]
    )
    errors = {
        name: float(np.max(np.abs(stored[name].to_numpy() - fresh[name].to_numpy())))
        for name in ("raw_probability", "calibrated_probability", "logistic_probability")
    }
    if any(value > 1e-12 for value in errors.values()):
        raise ValueError("Reloaded Model B probabilities differ from frozen predictions")
    contributions = np.asarray(fresh["shap_values"].tolist())
    shap_error = float(
        np.max(np.abs(contributions.sum(axis=1) + fresh["shap_base_value"] - fresh["raw_margin"]))
    )
    if not np.isfinite(shap_error) or shap_error > 1e-5:
        raise ValueError("Model B SHAP contributions exceed the raw-margin acceptance tolerance")
    rows = merge_model_b_rows(
        _read_verified_frames(paths, inputs.dataset),
        evidence_frames["model_b_features"],
        manifest["feature_schema"],
    )
    comparison = compare_model_a_b(
        rows,
        _read_verified_frames(paths, inputs.model_a)["model_predictions"],
        stored,
        threshold=float(manifest["comparison"]["threshold"]),
    )
    comparison.update(
        {
            "model_a_version": manifest["model_a_version"],
            "model_b_version": manifest["model_version"],
            "dataset_version": manifest["dataset_version"],
            "event_feature_version": manifest["event_feature_version"],
        }
    )
    if comparison != manifest["comparison"]:
        raise ValueError("Cached Model A/B comparison cannot be reproduced from its frozen inputs")
    inputs.verify_files(paths)
    return {
        "model_version": manifest["model_version"],
        "synthetic": manifest["synthetic"],
        "event_feature_version": manifest["event_feature_version"],
        "prediction_count": len(stored),
        "reload_max_errors": errors,
        "shap_raw_margin_max_error": shap_error,
        "paired_comparison_reproduced": True,
        "final_test_outcomes_inspected": False,
        "comparison": manifest["comparison"],
    }
