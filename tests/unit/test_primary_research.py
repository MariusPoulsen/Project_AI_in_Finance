"""Publication/read-only safety fixtures; these are not scientific acceptance runs."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from structural_break.research import primary
from structural_break.research.protocol import canonical_bytes, identity, load_protocol
from structural_break.services.research_app import PrimaryResearchService
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import sha256_file, write_bytes
from structural_break.storage.registry import RunRegistry


@pytest.fixture
def release(paths, monkeypatch):
    """Real SQL/file registration with synthetic bytes and an explicit native stub."""
    protocol = load_protocol(paths.project_root / "configs/research_v2.yaml").model_dump(
        mode="json"
    )
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    registry_version = "research_registry_" + "1" * 24
    source = {"fixture": True}
    source_sha = "2" * 64
    revision = "3" * 40

    def json_file(path: Path, value: dict[str, Any]) -> Path:
        return write_bytes(path, canonical_bytes(value))

    def register(version: str, stage: str, manifest: dict[str, Any]) -> Path:
        directory = paths.artifacts / "research" / version
        run = "unit-fixture-" + version
        manifest.update(research_version=version, stage=stage, run_id=run, protocol=protocol)
        file = json_file(directory / "manifest.json", manifest)
        with factory.connect(read_only=False) as connection:
            connection.execute(
                "INSERT INTO ops.job_runs(run_id,job,started_at,finished_at,status,config_hash,"
                "config_snapshot,git_commit,dataset_version) "
                "VALUES (?, 'unit-fixture', now(), now(), 'SUCCESS', "
                "'fixture', '{}', 'fixture', ?)",
                [run, version],
            )
            connection.execute(
                "INSERT INTO analytics.research_versions VALUES (?,?,?,?,?,?)",
                [
                    version,
                    stage,
                    identity(protocol),
                    file.relative_to(paths.workspace_root).as_posix(),
                    sha256_file(file),
                    run,
                ],
            )
        return file

    registry_dir = paths.artifacts / "research" / registry_version
    freeze = json_file(
        registry_dir / "source_freeze.json", {"source": source, "final_test_locked": True}
    )
    registry = register(
        registry_version,
        "registry",
        {
            "source": source,
            "source_freeze_sha256": sha256_file(freeze),
            "inputs": [],
        },
    )
    sec = json_file(paths.workspace_root / "sec_metadata/fixture/manifest.json", {"fixture": True})
    intelligence = json_file(
        paths.workspace_root / "intelligence/fixture/manifest.json",
        {
            "intelligence_version": "fixture-intelligence",
            "all_events_retained": True,
            "final_test_outcomes_inspected": False,
            "event_count": 37421,
            "scheduled_event_count": 37421,
            "files": {},
            "inputs": {
                "event_registry_id": registry_version,
                "max_events": None,
                "sec_manifest_sha256": sha256_file(sec),
                "sentiment_policy": {"preprocessing_version": "sec-sentence-quality-wordpiece-v2"},
            },
        },
    )
    checks, generations, stages = {}, [], []
    for horizon in (20, 10, 30):
        version = "research_evaluation_" + str(horizon).zfill(24)
        directory = paths.artifacts / "research" / version
        directory.mkdir(parents=True)
        predictions = pd.DataFrame(
            {
                "event_id": ["fixture-event"],
                "event_date": [date(2022, 1, 3)],
                "pair_id": ["A__B"],
                "leg_a": ["A"],
                "leg_b": ["B"],
                "business_group": ["fixture"],
                "baseline1_eligible": [True],
                "research_partition": ["assessment"],
                "logistic_A_raw": [0.1],
                "logistic_A_calibrated": [0.1],
                "logistic_B_both_raw": [0.09],
                "logistic_B_both_calibrated": [0.09],
                "y_revert_success": ["outcome must never be decoded by presentation"],
            }
        )
        prediction_path = directory / "predictions.parquet"
        predictions.to_parquet(prediction_path, index=False)
        models = {}
        model_files = []
        for name in sorted(primary.MODEL_NAMES):
            file = write_bytes(directory / "models" / (name + ".joblib"), b"synthetic-unit-bytes")
            model_files.append(
                {
                    "name": name,
                    "path": file.relative_to(directory).as_posix(),
                    "sha256": sha256_file(file),
                }
            )
            family, variant = name.split("_", 1)
            metrics = {"n": 1, "positives": 0, "brier": 0.01, "log_loss": 0.1}
            models.setdefault(family, {})[variant] = {
                "calibrated_assessment": metrics,
                "calibrated_assessment_slices": {"ACTIVE": {"True": metrics}},
                "paired_assessment": {
                    "brier_delta_B_minus_A": -0.001,
                    "slices": {"ACTIVE": {"True": {"brier_delta_B_minus_A": -0.001}}},
                },
            }
        report = json_file(
            directory / "report.json",
            {
                "protocol": protocol,
                "final_test_read": False,
                "models": models,
            },
        )
        manifest = register(
            version,
            "evaluation",
            {
                "identity_inputs": {
                    "registry_version": registry_version,
                    "registry_manifest_sha256": sha256_file(registry),
                    "intelligence_manifest_sha256": sha256_file(intelligence),
                    "horizon": horizon,
                    "computation": {"source_sha256": source_sha},
                },
                "files": [
                    {
                        "name": "predictions",
                        "path": prediction_path.name,
                        "sha256": sha256_file(prediction_path),
                    }
                ],
                "model_files": model_files,
                "report_sha256": sha256_file(report),
                "final_test_read": False,
                "parents": [
                    {
                        "role": "intelligence",
                        "path": intelligence.relative_to(paths.workspace_root).as_posix(),
                        "sha256": sha256_file(intelligence),
                    }
                ],
            },
        )
        native = {
            "research_version": version,
            "final_test_read": False,
            "paired_comparison_reproduced": True,
            "native_max_errors": dict.fromkeys(primary.MODEL_NAMES, 0.0),
        }
        checks[version] = native
        generations.append(
            {
                "horizon": horizon,
                "research_version": version,
                "manifest_sha256": sha256_file(manifest),
                "native_verification": native,
            }
        )
        for command in ("train-models", "verify-models"):
            stages.append(
                {
                    "horizon": horizon,
                    "command": command,
                    "exit_code": 0,
                    "stdout_sha256": "4" * 64,
                    "stderr_sha256": "5" * 64,
                    "summary": {
                        "status": "SUCCESS",
                        "command": command,
                        "research_version": version,
                    },
                }
            )
    receipt = {
        "status": "ALL_THREE_HORIZONS_FITTED_AND_INDEPENDENTLY_VERIFIED",
        "final_test_unlocked": False,
        "horizons": [20, 10, 30],
        "registry_version": registry_version,
        "completed_generations": generations,
        "intelligence_manifest_sha256": sha256_file(intelligence),
        "stages": stages,
        "computational_source_sha256": source_sha,
        "source_revision": revision,
        "hosted_ci_gate_sha256": "6" * 64,
        "hosted_ci_gate": {
            "head_sha": revision,
            "computational_source_sha256": source_sha,
            "conclusion": "success",
            "runs": [
                {
                    "head_sha": revision,
                    "status": "completed",
                    "conclusion": "success",
                    "jobs": [{"status": "completed", "conclusion": "success"}],
                }
            ],
        },
    }
    calls = []
    monkeypatch.setattr(
        primary, "_native_verify", lambda paths, version: calls.append(version) or checks[version]
    )
    gate = json_file(paths.workspace_root / "fixture_ci_gate.json", receipt["hosted_ci_gate"])
    receipt["hosted_ci_gate_sha256"] = sha256_file(gate)
    file = json_file(paths.workspace_root / "fixture_pipeline.json", receipt)
    return paths, file, receipt, calls


def forbidden(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("Presentation must not write or run inference")


def promote(paths, file):
    return primary.promote_primary_research(
        paths, file, ci_gate=paths.workspace_root / "fixture_ci_gate.json"
    )


def test_publish_three_native_replays_idempotent_and_readonly(release, monkeypatch):
    paths, file, _, calls = release
    accepted = promote(paths, file)
    assert len(calls) == 3
    manifest = paths.artifacts / "research" / accepted["primary_version"] / "manifest.json"
    before = manifest.read_bytes()
    assert promote(paths, file) == accepted
    assert len(calls) == 6 and manifest.read_bytes() == before
    monkeypatch.setattr(primary, "_native_verify", forbidden)
    monkeypatch.setattr("structural_break.storage.database.migrate", forbidden)
    original = DuckDBConnectionFactory.connect

    def readonly(self, *, read_only=True):
        assert read_only is True
        return original(self, read_only=read_only)

    monkeypatch.setattr(DuckDBConnectionFactory, "connect", readonly)
    service = PrimaryResearchService(paths)
    view = service.view()
    assert service.versions() == (accepted["primary_version"],)
    assert len(service.comparison(view, 20)) == 10
    rows = service.predictions(view, 20, as_of=date(2023, 12, 31))
    assert rows.iloc[0].model_b_calibrated == 0.09
    assert "y_revert_success" not in rows
    with pytest.raises(ValueError, match="locked"):
        service.predictions(view, 20, as_of=date(2024, 1, 1))


def test_unready_database_is_never_created(paths):
    assert primary.primary_versions(paths) == ()
    with pytest.raises(primary.PrimaryNotReadyError):
        primary.load_primary(paths)
    assert not paths.database.exists()


def test_receipt_replacement_during_replay_binds_original_bytes(release, monkeypatch):
    paths, file, receipt, _ = release
    expected = sha256_file(file)
    checks = {
        row["research_version"]: row["native_verification"]
        for row in receipt["completed_generations"]
    }

    def replay(paths, version):
        file.write_bytes(b"replacement while verification was running")
        return checks[version]

    monkeypatch.setattr(primary, "_native_verify", replay)
    published = promote(paths, file)
    assert published["identity_inputs"]["pipeline_receipt_sha256"] == expected
    assert primary.load_primary(paths) == published


def test_ci_evidence_bytes_must_match_before_native_replay(release):
    paths, file, _, calls = release
    gate = paths.workspace_root / "fixture_ci_gate.json"
    gate.write_bytes(gate.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="CI evidence bytes"):
        promote(paths, file)
    assert calls == [] and primary.primary_versions(paths) == ()


def test_published_ci_evidence_cannot_be_replaced(release):
    paths, file, _, _ = release
    result = promote(paths, file)
    gate = paths.artifacts / "research" / result["primary_version"] / "hosted_ci_gate.json"
    gate.write_bytes(gate.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum"):
        primary.load_primary(paths)


@pytest.mark.parametrize("fault", ["pending", "ci", "stage", "source", "native", "final"])
def test_incomplete_release_never_publishes(release, fault, monkeypatch):
    paths, file, receipt, _ = release
    changed = deepcopy(receipt)
    if fault == "pending":
        changed["status"] = "WAITING_FOR_FULL_FEATURE_BATCH"
    elif fault == "ci":
        changed["hosted_ci_gate"]["runs"][0]["jobs"][0]["conclusion"] = "failure"
    elif fault == "stage":
        changed["stages"].pop()
    elif fault == "source":
        changed["computational_source_sha256"] = "a" * 64
    elif fault == "final":
        changed["final_test_unlocked"] = True
    else:
        monkeypatch.setattr(
            primary,
            "_native_verify",
            lambda *args: {
                **changed["completed_generations"][0]["native_verification"],
                "native_max_errors": {"logistic_A": float("nan")},
            },
        )
    altered = write_bytes(file.with_name("altered.json"), canonical_bytes(changed))
    with pytest.raises(ValueError):
        promote(paths, altered)
    assert primary.primary_versions(paths) == ()


@pytest.mark.parametrize(
    "target", ["report.json", "predictions.parquet", "models/logistic_A.joblib"]
)
def test_tampered_published_parent_fails_readonly(release, target):
    paths, file, receipt, _ = release
    promote(paths, file)
    directory = (
        paths.artifacts / "research" / receipt["completed_generations"][0]["research_version"]
    )
    path = directory / target
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        PrimaryResearchService(paths).view()


def test_failed_publication_retry_preserves_original_manifest(release, monkeypatch):
    paths, file, _, _ = release
    original = RunRegistry.finish
    fail = True

    def finish(self, *args, **kwargs):
        nonlocal fail
        if kwargs.get("status") == "SUCCESS" and fail:
            fail = False
            raise RuntimeError("unit-injected publication failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(RunRegistry, "finish", finish)
    with pytest.raises(RuntimeError):
        promote(paths, file)
    assert primary.primary_versions(paths) == ()
    directory = next(paths.artifacts.glob("research/research_primary_*"))
    original_bytes = (directory / "manifest.json").read_bytes()
    promote(paths, file)
    archived = list(directory.glob("unregistered_manifest_*.json"))
    assert len(archived) == 1 and archived[0].read_bytes() == original_bytes


def test_running_unregistered_publication_is_not_replaced(release, monkeypatch):
    paths, file, _, _ = release
    original = RunRegistry.finish

    def stopped(self, *args, **kwargs):
        if kwargs.get("status") == "FAILED":
            return None  # A simulated hard interruption leaves RUNNING.
        raise RuntimeError("unit-injected interruption")

    monkeypatch.setattr(RunRegistry, "finish", stopped)
    with pytest.raises(RuntimeError):
        promote(paths, file)
    directory = next(paths.artifacts.glob("research/research_primary_*"))
    before = (directory / "manifest.json").read_bytes()
    monkeypatch.setattr(RunRegistry, "finish", original)
    with pytest.raises(ValueError, match="confirmed failed"):
        promote(paths, file)
    assert (directory / "manifest.json").read_bytes() == before
