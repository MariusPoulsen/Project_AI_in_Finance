"""Explicit readiness publication and read-only access to immutable v2 generations.

Promotion is a batch operation: it independently replays the three evaluations.
Presentation access never migrates, loads a native model, predicts or contacts a
provider. It checks the registered proof and the published bytes it consumes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.research.protocol import ResearchProtocol, canonical_bytes, identity
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file, write_bytes

PRIMARY_SCHEMA = "research-primary-v2.1"
_VERSION = re.compile(r"research_(registry|evaluation|primary)_[0-9a-f]{24}")
MODEL_NAMES = frozenset(
    f"{family}_{variant}"
    for family in ("logistic", "xgboost")
    for variant in ("A", "B_metadata", "B_tone", "B_catalyst", "B_both")
)


class PrimaryNotReadyError(FileNotFoundError):
    """No explicitly published primary readiness generation exists."""


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Research publication JSON must contain one object")
    return value


def checked_json(path: Path, digest: str) -> dict[str, Any]:
    """Check the exact bytes decoded, including a concurrent file replacement."""
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("Research JSON checksum differs")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("Research publication JSON must contain one object")
    return value


def registered_manifest(
    paths: ProjectPaths, version: str, stage: str, *, coordinated: bool = False
) -> tuple[Path, dict[str, Any]]:
    """Read a successful SQL registration without any writer/migration call."""
    if _VERSION.fullmatch(version) is None:
        raise ValueError("Invalid explicit research generation")
    factory = DuckDBConnectionFactory(paths.database, coordinated=coordinated)
    try:
        with factory.connect(read_only=True) as connection:
            row = connection.execute(
                """SELECT r.manifest_path,r.checksum,r.stage,r.run_id,r.protocol_hash
                FROM analytics.research_versions r JOIN ops.job_runs j USING(run_id)
                WHERE r.research_version=? AND j.status='SUCCESS'""",
                [version],
            ).fetchone()
    except (FileNotFoundError, duckdb.CatalogException):
        raise PrimaryNotReadyError("No registered primary research generation") from None
    if row is None:
        raise PrimaryNotReadyError("The requested research generation is not registered")
    path = confined_path(paths.workspace_root, row[0])
    manifest = checked_json(path, row[1])
    if (
        row[2] != stage
        or manifest.get("stage") != stage
        or manifest.get("research_version") != version
        or manifest.get("run_id") != row[3]
        or identity(manifest.get("protocol", manifest.get("identity_inputs", {}).get("protocol")))
        != row[4]
    ):
        raise ValueError("Registered research identity or stage differs")
    return path, manifest


def primary_versions(paths: ProjectPaths) -> tuple[str, ...]:
    try:
        with DuckDBConnectionFactory(paths.database).connect(read_only=True) as connection:
            rows = connection.execute(
                """SELECT r.research_version FROM analytics.research_versions r
                JOIN ops.job_runs j USING(run_id)
                WHERE r.stage='primary' AND j.status='SUCCESS' ORDER BY r.research_version"""
            ).fetchall()
    except (FileNotFoundError, duckdb.CatalogException):
        return ()
    return tuple(str(row[0]) for row in rows)


def _active_version(paths: ProjectPaths) -> str:
    try:
        with DuckDBConnectionFactory(paths.database).connect(read_only=True) as connection:
            row = connection.execute(
                "SELECT primary_version FROM ops.active_primary_research WHERE singleton"
            ).fetchone()
    except (FileNotFoundError, duckdb.CatalogException):
        raise PrimaryNotReadyError("Primary v2 outputs have not been published") from None
    if row is None:
        raise PrimaryNotReadyError("Primary v2 outputs have not been published")
    return str(row[0])


def checked_file(directory: Path, manifest: dict[str, Any], name: str) -> Path:
    entries = [row for row in manifest["files"] if row["name"] == name]
    if len(entries) != 1:
        raise ValueError("Research output requires one explicit named artifact")
    path = confined_path(directory, entries[0]["path"])
    if sha256_file(path) != entries[0]["sha256"]:
        raise ValueError("Research artifact checksum differs")
    return path


def _native_check(result: dict[str, Any], version: str) -> None:
    errors = result.get("native_max_errors")
    if (
        result.get("research_version") != version
        or result.get("paired_comparison_reproduced") is not True
        or result.get("final_test_read") is not False
        or not isinstance(errors, dict)
        or set(errors) != MODEL_NAMES
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1e-12
            for value in errors.values()
        )
    ):
        raise ValueError(
            "All ten native models must independently verify with the final test locked"
        )


def _native_verify(
    paths: ProjectPaths,
    version: str,
    *,
    parsing_workers: int = 0,
    progress: Callable[[dict[str, Any]], None] | None = None,
    source_proof: Path | None = None,
    source_proof_sha256: str | None = None,
) -> dict[str, Any]:
    # Intentionally imported only by the explicit batch promotion function.
    from structural_break.research.model_job import verify_research_models

    return verify_research_models(
        paths,
        version,
        parsing_workers=parsing_workers,
        progress=progress,
        source_proof=source_proof,
        source_proof_sha256=source_proof_sha256,
        publication=source_proof is not None,
    )


def _binding(paths: ProjectPaths, bindings: dict[str, str], path: Path, digest: str) -> None:
    relative = path.resolve().relative_to(paths.workspace_root.resolve()).as_posix()
    if sha256_file(path) != digest:
        raise ValueError("Primary research source or artifact checksum differs")
    if relative in bindings and bindings[relative] != digest:
        raise ValueError("Primary research source has conflicting identities")
    bindings[relative] = digest


def _pipeline_check(receipt: dict[str, Any]) -> None:
    gate = receipt.get("hosted_ci_gate", {})
    source = receipt.get("computational_source_sha256")
    revision = receipt.get("source_revision")
    if (
        not isinstance(source, str)
        or re.fullmatch(r"[0-9a-f]{64}", source) is None
        or not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or gate.get("conclusion") != "success"
        or gate.get("head_sha") != revision
        or gate.get("computational_source_sha256") != source
        or re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("hosted_ci_gate_sha256", ""))) is None
        or not gate.get("runs")
        or any(
            run.get("head_sha") != revision
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or not run.get("jobs")
            or any(
                job.get("status") != "completed" or job.get("conclusion") != "success"
                for job in run["jobs"]
            )
            for run in gate["runs"]
        )
    ):
        raise ValueError("The completed pipeline must bind its successful hosted CI gate")
    stages = receipt.get("stages")
    if not isinstance(stages, list) or len(stages) != 6:
        raise ValueError("All three production fits and separate verifications must finish")
    for row, (horizon, command) in zip(
        stages,
        ((h, c) for h in (20, 10, 30) for c in ("train-models", "verify-models")),
        strict=True,
    ):
        if (
            row.get("horizon") != horizon
            or row.get("command") != command
            or row.get("exit_code") != 0
            or row.get("summary", {}).get("status") != "SUCCESS"
            or row.get("summary", {}).get("command") != command
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(row.get(name, ""))) is None
                for name in ("stdout_sha256", "stderr_sha256")
            )
        ):
            raise ValueError("The pipeline contains an incomplete production stage")
    if receipt.get("verification_strategy") == "shared-source-two-full-replays-v1":
        sources = receipt.get("source_stages")
        if not isinstance(sources, list) or len(sources) != 2:
            raise ValueError("Two actual complete source reconstruction stages are required")
        for row, purpose in zip(sources, ("fitting_input", "independent_publication"), strict=True):
            summary = row.get("summary", {})
            if (
                row.get("command") != "verify-source-inputs"
                or row.get("exit_code") != 0
                or summary.get("status") != "SUCCESS"
                or summary.get("command") != "verify-source-inputs"
                or summary.get("source_proof_purpose") != purpose
                or summary.get("complete_raw_reconstruction") is not True
                or summary.get("final_test_read") is not False
                or type(summary.get("event_count")) is not int
                or summary["event_count"] < 1
                or summary["event_count"] != sources[0].get("summary", {}).get("event_count")
                or receipt.get("checkpoint_count", summary["event_count"]) != summary["event_count"]
                or any(
                    re.fullmatch(r"[0-9a-f]{64}", str(row.get(key, ""))) is None
                    for key in ("stdout_sha256", "stderr_sha256")
                )
                or re.fullmatch(r"[0-9a-f]{64}", str(summary.get("source_proof_sha256", "")))
                is None
            ):
                raise ValueError("Complete source reconstruction exit, purpose or lineage differs")

        def stamp(row: dict[str, Any], field: str) -> datetime:
            value = datetime.fromisoformat(row[field])
            if value.tzinfo is None:
                raise ValueError("Source-stage chronology must be timezone aware")
            return value.astimezone(UTC)

        if stamp(sources[0], "completed_at_utc") > min(
            stamp(row, "started_at_utc") for row in stages
        ) or stamp(sources[1], "started_at_utc") < max(
            stamp(row, "completed_at_utc") for row in stages
        ):
            raise ValueError("Independent source reconstruction must bracket all model stages")


def _inputs(
    paths: ProjectPaths,
    receipt: dict[str, Any],
    *,
    replay_native: bool,
    parsing_workers: int = 0,
    progress: Callable[[dict[str, Any]], None] | None = None,
    source_proof: Path | None = None,
    source_proof_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    if (
        receipt.get("status") != "ALL_THREE_HORIZONS_FITTED_AND_INDEPENDENTLY_VERIFIED"
        or receipt.get("final_test_unlocked") is not False
    ):
        raise ValueError("The complete verified pipeline must finish before primary promotion")
    _pipeline_check(receipt)
    registry_version = receipt["registry_version"]
    registry_path, registry = registered_manifest(paths, registry_version, "registry")
    protocol = ResearchProtocol.model_validate(registry["protocol"])
    horizons = (protocol.primary_horizon, *protocol.sensitivity_horizons)
    if horizons != (20, 10, 30) or receipt.get("horizons") != list(horizons):
        raise ValueError("Primary readiness requires the predeclared 20/10/30 horizons")
    generations = receipt.get("completed_generations")
    if not isinstance(generations, list) or len(generations) != len(horizons):
        raise ValueError("Primary readiness requires all three completed evaluations")
    by_horizon = {row["horizon"]: row for row in generations}
    if set(by_horizon) != set(horizons):
        raise ValueError("Primary readiness horizons are duplicated or incomplete")
    bindings: dict[str, str] = {}
    _binding(paths, bindings, registry_path, sha256_file(registry_path))
    freeze_path = registry_path.parent / "source_freeze.json"
    _binding(paths, bindings, freeze_path, registry["source_freeze_sha256"])
    freeze = read_json(freeze_path)
    if freeze.get("final_test_locked") is not True or freeze.get("source") != registry["source"]:
        raise ValueError("Research source freeze differs or final test is unlocked")
    source_receipts: list[dict[str, Any]] = []
    if receipt.get("verification_strategy") == "shared-source-two-full-replays-v1":
        for stage in receipt["source_stages"]:
            summary = stage["summary"]
            version = summary["source_verification_version"]
            if re.fullmatch(r"research_source_verification_[0-9a-f]{24}", version) is None:
                raise ValueError("Invalid explicit complete source proof version")
            proof_path = confined_path(
                paths.artifacts, f"source_verification/{version}/manifest.json"
            )
            digest = summary["source_proof_sha256"]
            _binding(paths, bindings, proof_path, digest)
            source_receipts.append(checked_json(proof_path, digest))
        initial, final = source_receipts
        if (
            initial.get("purpose") != "fitting_input"
            or final.get("purpose") != "independent_publication"
            or initial.get("identity_inputs") != final.get("identity_inputs")
            or final.get("complete_raw_reconstruction") is not True
            or final.get("final_test_read") is not False
            or final["identity_inputs"]["registry_version"] != registry_version
            or final["identity_inputs"]["verifier_computation"]["source_sha256"]
            != receipt["computational_source_sha256"]
        ):
            raise ValueError(
                "The two independent source receipts must verify identical fitting inputs"
            )
        if replay_native:
            from structural_break.research.source_proof import validate_source_proof

            if (
                source_proof is None
                or source_proof_sha256
                != receipt["source_stages"][1]["summary"]["source_proof_sha256"]
                or source_proof.resolve() != proof_path
            ):
                raise ValueError(
                    "Publication requires its explicit second independent source proof"
                )
            validate_source_proof(
                paths,
                registry_version,
                confined_path(
                    paths.workspace_root, final["identity_inputs"]["intelligence_directory"]
                ),
                proof_path,
                digest,
                purpose="independent_publication",
                progress=progress,
            )
    elif source_proof is not None or source_proof_sha256 is not None:
        raise ValueError("Shared source proof requires the explicit two-reconstruction pipeline")
    for item in registry["inputs"]:
        _binding(paths, bindings, confined_path(paths.workspace_root, item["path"]), item["sha256"])
    evaluations: dict[str, Any] = {}
    checks: dict[str, Any] = {}
    intelligence_path: Path | None = None
    for horizon in horizons:
        row = by_horizon[horizon]
        version = row["research_version"]
        for stage in receipt["stages"]:
            if stage["horizon"] == horizon and stage["summary"].get("research_version") != version:
                raise ValueError("Completed generations differ from production-stage identities")
        path, manifest = registered_manifest(paths, version, "evaluation")
        _binding(paths, bindings, path, row["manifest_sha256"])
        inputs = manifest["identity_inputs"]
        if (
            inputs["registry_version"] != registry_version
            or inputs["registry_manifest_sha256"] != sha256_file(registry_path)
            or inputs["horizon"] != horizon
            or inputs["computation"]["source_sha256"] != receipt["computational_source_sha256"]
            or manifest.get("final_test_read") is not False
            or manifest["protocol"] != registry["protocol"]
        ):
            raise ValueError("Primary evaluations must share the same frozen registry and protocol")
        if source_receipts and (
            inputs.get("verification_strategy") != "shared-source-two-full-replays-v1"
            or inputs.get("fitting_source_proof_sha256")
            != receipt["source_stages"][0]["summary"]["source_proof_sha256"]
            or inputs.get("source_verification_inputs_sha256")
            != identity(source_receipts[0]["identity_inputs"])
        ):
            raise ValueError("Every primary model must bind the same complete fitting source proof")
        parents = {item["role"]: item for item in manifest["parents"]}
        parent = parents["intelligence"]
        current_intelligence = confined_path(paths.workspace_root, parent["path"])
        if intelligence_path is not None and current_intelligence != intelligence_path:
            raise ValueError("Primary evaluations cannot mix intelligence batches")
        intelligence_path = current_intelligence
        _binding(paths, bindings, current_intelligence, parent["sha256"])
        if inputs["intelligence_manifest_sha256"] != parent["sha256"]:
            raise ValueError("Evaluation intelligence parent differs")
        for item in manifest["files"] + manifest["model_files"]:
            _binding(paths, bindings, confined_path(path.parent, item["path"]), item["sha256"])
        if {item["name"] for item in manifest["model_files"]} != MODEL_NAMES:
            raise ValueError("Primary evaluation native-model inventory is incomplete")
        report_path = path.parent / "report.json"
        _binding(paths, bindings, report_path, manifest["report_sha256"])
        report = checked_json(report_path, manifest["report_sha256"])
        if report.get("final_test_read") is not False or report["protocol"] != registry["protocol"]:
            raise ValueError("Evaluation report differs from the locked research protocol")
        if replay_native:
            if progress is not None:
                progress(
                    {
                        "status": "RUNNING",
                        "stage": "PUBLICATION_NATIVE_REPLAY",
                        "horizon": horizon,
                        "publication_horizons_verified": len(checks),
                        "publication_horizons_total": len(horizons),
                    }
                )
            if source_receipts:
                result = _native_verify(
                    paths,
                    version,
                    parsing_workers=parsing_workers,
                    progress=progress,
                    source_proof=source_proof,
                    source_proof_sha256=source_proof_sha256,
                )
            elif parsing_workers or progress is not None:
                result = _native_verify(
                    paths, version, parsing_workers=parsing_workers, progress=progress
                )
            else:
                result = _native_verify(paths, version)
        else:
            result = row["native_verification"]
        _native_check(result, version)
        checks[str(horizon)] = result
        evaluations[str(horizon)] = {
            "research_version": version,
            "manifest_path": path.relative_to(paths.workspace_root).as_posix(),
            "manifest_sha256": sha256_file(path),
        }
    assert intelligence_path is not None
    intelligence = read_json(intelligence_path)
    if (
        intelligence.get("final_test_outcomes_inspected") is not False
        or intelligence.get("all_events_retained") is not True
        or intelligence["event_count"] != intelligence["scheduled_event_count"]
        or intelligence["inputs"]["max_events"] is not None
        or intelligence["inputs"]["event_registry_id"] != registry_version
        or sha256_file(intelligence_path) != receipt.get("intelligence_manifest_sha256")
        or intelligence["inputs"]["sentiment_policy"]["preprocessing_version"]
        != "sec-sentence-quality-wordpiece-v2"
    ):
        raise ValueError("Primary readiness requires the complete locked intelligence population")
    for filename, digest in intelligence["files"].items():
        if not filename.startswith("events/"):
            _binding(paths, bindings, confined_path(intelligence_path.parent, filename), digest)
    sec_sources = [
        path
        for path in (paths.workspace_root / "sec_metadata").glob("*/manifest.json")
        if sha256_file(path) == intelligence["inputs"]["sec_manifest_sha256"]
    ]
    if len(sec_sources) != 1:
        raise ValueError("Primary intelligence requires its explicit frozen SEC source")
    _binding(paths, bindings, sec_sources[0], intelligence["inputs"]["sec_manifest_sha256"])
    result_inputs = {
        "registry_version": registry_version,
        "intelligence_version": intelligence["intelligence_version"],
        "intelligence_manifest_path": intelligence_path.relative_to(
            paths.workspace_root
        ).as_posix(),
        "evaluations": evaluations,
        "protocol": registry["protocol"],
        "primary_horizon": protocol.primary_horizon,
        "primary_family": protocol.primary_family,
        "primary_b_variant": protocol.primary_b_variant,
        "native_checks": checks,
    }
    if source_receipts:
        result_inputs["verification_strategy"] = "shared-source-two-full-replays-v1"
        result_inputs["source_verification_receipts"] = [
            {
                "purpose": row["purpose"],
                "source_verification_version": row["source_verification_version"],
                "identity_inputs_sha256": identity(row["identity_inputs"]),
                "manifest_sha256": stage["summary"]["source_proof_sha256"],
            }
            for row, stage in zip(source_receipts, receipt["source_stages"], strict=True)
        ]
    return result_inputs, bindings, registry


def load_primary(paths: ProjectPaths, version: str | None = None) -> dict[str, Any]:
    """Verify the selected registered readiness proof without inference or writes."""
    selected = version or _active_version(paths)
    path, manifest = registered_manifest(paths, selected, "primary")
    if (
        manifest.get("schema_version") != PRIMARY_SCHEMA
        or manifest.get("primary_version") != selected
        or manifest.get("final_test_read") is not False
        or selected != "research_primary_" + identity(manifest["identity_inputs"])[:24]
    ):
        raise ValueError("Primary readiness identity or final-test lock differs")
    for relative, digest in manifest["bindings"].items():
        _binding(paths, {}, confined_path(paths.workspace_root, relative), digest)
    proof_path = path.parent / "verification_receipt.json"
    proof = checked_json(proof_path, manifest["verification_receipt_sha256"])
    gate = checked_json(path.parent / "hosted_ci_gate.json", proof["hosted_ci_gate_sha256"])
    if gate != proof["hosted_ci_gate"]:
        raise ValueError("Published hosted CI evidence differs from its pipeline receipt")
    expected, bindings, _ = _inputs(paths, proof, replay_native=False)
    expected["pipeline_receipt_sha256"] = manifest["identity_inputs"]["pipeline_receipt_sha256"]
    if expected != manifest["identity_inputs"] or bindings != manifest["bindings"]:
        raise ValueError("Primary readiness parent/source inventory differs")
    return manifest


def _recover_failed_publication(
    paths: ProjectPaths,
    directory: Path,
    version: str,
    inputs: dict[str, Any],
    bindings: dict[str, str],
    proof: dict[str, Any],
) -> None:
    pending_path = directory / "manifest.json"
    if not pending_path.exists():
        return
    pending = read_json(pending_path)
    if (
        pending.get("research_version") != version
        or pending.get("stage") != "primary"
        or pending.get("identity_inputs") != inputs
        or pending.get("bindings") != bindings
        or pending.get("verification_receipt_sha256") != identity(proof)
    ):
        raise ValueError("Unregistered primary publication binds different content")
    with DuckDBConnectionFactory(paths.database).connect(read_only=True) as connection:
        state = connection.execute(
            "SELECT status FROM ops.job_runs WHERE run_id=?", [pending["run_id"]]
        ).fetchone()
    if state != ("FAILED",):
        raise ValueError("Unregistered primary publication is not a confirmed failed run")
    digest = sha256_file(pending_path)
    write_bytes(directory / f"unregistered_manifest_{digest}.json", pending_path.read_bytes())
    # Only this confined, confirmed FAILED, unregistered pointer is replaced.
    pending_path.unlink()


def promote_primary_research(
    paths: ProjectPaths,
    pipeline_receipt: Path,
    *,
    ci_gate: Path,
    parsing_workers: int = 0,
    progress: Callable[[dict[str, Any]], None] | None = None,
    source_proof: Path | None = None,
    source_proof_sha256: str | None = None,
) -> dict[str, Any]:
    """Independently verify all three generations, then publish readiness atomically."""
    from structural_break.common.logging import new_run_id
    from structural_break.config.loader import load_config
    from structural_break.services.foundation import git_revision
    from structural_break.storage.database import migrate
    from structural_break.storage.registry import Registration, RunRegistry

    receipt_body = pipeline_receipt.read_bytes()
    receipt = json.loads(receipt_body)
    if not isinstance(receipt, dict):
        raise ValueError("The pipeline receipt must contain one object")
    gate_body = ci_gate.read_bytes()
    if hashlib.sha256(gate_body).hexdigest() != receipt.get("hosted_ci_gate_sha256") or json.loads(
        gate_body
    ) != receipt.get("hosted_ci_gate"):
        raise ValueError("Hosted CI evidence bytes differ from the pipeline receipt")
    inputs, bindings, _ = _inputs(
        paths,
        receipt,
        replay_native=True,
        parsing_workers=parsing_workers,
        progress=progress,
        source_proof=source_proof,
        source_proof_sha256=source_proof_sha256,
    )
    inputs["pipeline_receipt_sha256"] = hashlib.sha256(receipt_body).hexdigest()
    # Replace assertions from the operational receipt with this fresh scientific replay.
    proof = dict(receipt)
    proof["completed_generations"] = [
        {
            **row,
            "native_verification": inputs["native_checks"][str(row["horizon"])],
        }
        for row in receipt["completed_generations"]
    ]
    version = "research_primary_" + identity(inputs)[:24]
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    existing = version in primary_versions(paths)
    directory = paths.artifacts / "research" / version
    if not existing:
        _recover_failed_publication(paths, directory, version, inputs, bindings, proof)
    run_id = new_run_id()
    registry = RunRegistry(factory, paths.workspace_root)
    registry.start(
        run_id,
        "promote-primary-research",
        load_config(paths.project_root / "configs"),
        git_revision(paths.project_root),
        version,
    )
    try:
        if existing:
            manifest = load_primary(paths, version)
        else:
            write_bytes(directory / "hosted_ci_gate.json", gate_body)
            proof_path = write_bytes(
                directory / "verification_receipt.json", canonical_bytes(proof)
            )
            manifest = {
                "schema_version": PRIMARY_SCHEMA,
                "primary_version": version,
                "research_version": version,
                "stage": "primary",
                "run_id": run_id,
                "identity_inputs": inputs,
                "bindings": bindings,
                "verification_receipt_sha256": sha256_file(proof_path),
                "final_test_read": False,
                "verification_scope": (
                    "Two complete source reconstructions bracket fitting; publication rechecks "
                    "all bound source hashes and native models; presentation checks "
                    "published artifacts."
                    if inputs.get("verification_strategy") == "shared-source-two-full-replays-v1"
                    else "Fresh native and raw-source verification at promotion; "
                    "read-only presentation "
                    "checks registered source manifests and every published artifact it consumes."
                ),
            }
            write_bytes(directory / "manifest.json", canonical_bytes(manifest))
        manifest_path = directory / "manifest.json"

        def publication(connection: duckdb.DuckDBPyConnection) -> None:
            if not existing:
                connection.execute(
                    "INSERT INTO analytics.research_versions VALUES (?,?,?,?,?,?)",
                    [
                        version,
                        "primary",
                        identity(inputs["protocol"]),
                        manifest_path.relative_to(paths.workspace_root).as_posix(),
                        sha256_file(manifest_path),
                        run_id,
                    ],
                )
            connection.execute(
                "INSERT INTO ops.active_primary_research VALUES (TRUE,?) "
                "ON CONFLICT(singleton) DO UPDATE SET primary_version=excluded.primary_version",
                [version],
            )

        registry.finish(
            run_id,
            status="SUCCESS",
            record_count=30,
            artifacts=(Registration("research-primary", version, manifest_path),),
            publish=publication,
        )
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        raise
    return load_primary(paths, version)
