"""Two full reconstructions, with complete bound-byte checks between model stages.

A receipt never blesses a sample or a builder cache. Only the complete verifier
can mint it; the operational pipeline must also bind the real command/exit/logs.
This module changes verification cadence, not cohorts, features or model math.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.research.primary import registered_manifest
from structural_break.research.protocol import canonical_bytes, identity
from structural_break.research.runner import computational_identity
from structural_break.research.source_paths import sec_source_directory
from structural_break.storage.files import sha256_file, write_bytes

SourcePurpose = Literal["fitting_input", "independent_publication"]
STRATEGY = "shared-source-two-full-replays-v1"
SCHEMA = "research-full-source-verification-v1"
Progress = Callable[[dict[str, Any]], None]


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Source verification requires an object")
    return value


def _scope(
    paths: ProjectPaths, registry_version: str, intelligence_directory: Path
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    registry_path, registry = registered_manifest(
        paths, registry_version, "registry", coordinated=True
    )
    manifest_path = intelligence_directory / "manifest.json"
    manifest = _read(manifest_path)
    inputs = manifest["inputs"]
    count = manifest.get("event_count")
    if (
        manifest.get("schema_version") != "research-event-intelligence-v2"
        or type(count) is not int
        or count < 1
        or manifest.get("all_events_retained") is not True
        or manifest.get("scheduled_event_count") != count
        or inputs.get("max_events") is not None
        or len(manifest["source_identity"]["records"]) != count
        or inputs.get("event_registry_id") != registry_version
        or manifest.get("final_test_outcomes_inspected") is not False
        or registry["protocol"].get("final_test_locked") is not True
    ):
        raise ValueError("Shared source proof requires the complete locked event population")
    universe = confined_path(
        paths.workspace_root,
        next(row["path"] for row in registry["inputs"] if row["role"] == "universe"),
    ).parent
    sec = sec_source_directory(paths, intelligence_directory)
    scope = {
        "registry_version": registry_version,
        "registry_manifest_sha256": sha256_file(registry_path),
        "intelligence_directory": intelligence_directory.relative_to(
            paths.workspace_root
        ).as_posix(),
        "intelligence_version": manifest["intelligence_version"],
        "intelligence_manifest_sha256": sha256_file(manifest_path),
        "universe_manifest_sha256": sha256_file(universe / "manifest.json"),
        "sec_manifest_sha256": sha256_file(sec / "manifest.json"),
        "event_count": count,
        "event_registry_sha256": inputs["events_sha256"],
        "features_sha256": manifest["files"]["features.parquet"],
        "source_identity_sha256": identity(manifest["source_identity"]),
        "verifier_computation": computational_identity(paths.project_root),
        "python_version": platform.python_version(),
    }
    if scope["sec_manifest_sha256"] != inputs["sec_manifest_sha256"]:
        raise ValueError("Source proof SEC parent differs")
    return scope, manifest, universe, sec


def _bindings(
    paths: ProjectPaths, directory: Path, manifest: dict[str, Any], universe: Path, sec: Path
) -> Iterator[tuple[Path, str]]:
    for base, items in (
        (directory, manifest["files"]),
        (paths.workspace_root / "cache", manifest["cache_files"]),
        (universe, _read(universe / "manifest.json")["files"]),
        (sec, _read(sec / "manifest.json")["files"]),
    ):
        for filename, digest in items.items():
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Source proof bound checksum is malformed")
            yield confined_path(base, filename), digest


def mint_source_proof(
    paths: ProjectPaths,
    registry_version: str,
    intelligence_directory: Path,
    *,
    purpose: SourcePurpose,
    event_workers: int = 0,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Always perform a complete fresh reconstruction, even if proof bytes exist."""
    from structural_break.research.intelligence import verify_event_intelligence

    if purpose not in {"fitting_input", "independent_publication"}:
        raise ValueError("Source proof purpose must be explicit")
    if type(event_workers) is not int or event_workers not in (0, 4):
        raise ValueError("Independent event verification permits zero or four workers")
    scope, manifest, universe, sec = _scope(paths, registry_version, intelligence_directory)
    verified = verify_event_intelligence(
        intelligence_directory,
        universe,
        sec,
        cache_workspace=paths.workspace_root / "cache",
        event_workers=event_workers,
        progress=progress,
    )
    after, current, _, _ = _scope(paths, registry_version, intelligence_directory)
    if verified != manifest or current != manifest or after != scope:
        raise ValueError("Source inputs or verifier changed during complete reconstruction")
    content = {
        "schema_version": SCHEMA,
        "verification_strategy": STRATEGY,
        "purpose": purpose,
        "identity_inputs": scope,
        "complete_raw_reconstruction": True,
        "initial_parser_cache_empty": True,
        "builder_parser_cache_used": False,
        "event_workers": event_workers,
        "verified_event_count": scope["event_count"],
        "final_test_read": False,
    }
    version = "research_source_verification_" + identity(content)[:24]
    receipt = {**content, "source_verification_version": version}
    directory = confined_path(paths.artifacts, f"source_verification/{version}")
    path = write_bytes(directory / "manifest.json", canonical_bytes(receipt))
    return {
        "source_verification_version": version,
        "source_proof_path": str(path),
        "source_proof_sha256": sha256_file(path),
        "source_proof_purpose": purpose,
        "event_count": scope["event_count"],
        "intelligence_version": scope["intelligence_version"],
        "complete_raw_reconstruction": True,
        "event_workers": event_workers,
        "final_test_read": False,
    }


def validate_source_proof(
    paths: ProjectPaths,
    registry_version: str,
    intelligence_directory: Path,
    proof_path: Path,
    expected_sha256: str,
    *,
    purpose: SourcePurpose,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Rehash every bound file; never replace or silently refresh stale proof."""
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("An exact source proof checksum is required")
    body = proof_path.read_bytes()
    if hashlib.sha256(body).hexdigest() != expected_sha256:
        raise ValueError("Source proof checksum differs")
    proof = json.loads(body)
    if not isinstance(proof, dict):
        raise ValueError("Source verification requires an object")
    scope, manifest, universe, sec = _scope(paths, registry_version, intelligence_directory)
    unsigned = {key: value for key, value in proof.items() if key != "source_verification_version"}
    if (
        proof.get("schema_version") != SCHEMA
        or proof.get("verification_strategy") != STRATEGY
        or proof.get("purpose") != purpose
        or proof.get("identity_inputs") != scope
        or proof.get("verified_event_count") != scope["event_count"]
        or proof.get("complete_raw_reconstruction") is not True
        or proof.get("initial_parser_cache_empty") is not True
        or proof.get("builder_parser_cache_used") is not False
        or type(proof.get("event_workers")) is not int
        or proof.get("event_workers") not in (0, 4)
        or proof.get("final_test_read") is not False
        or proof.get("source_verification_version")
        != "research_source_verification_" + identity(unsigned)[:24]
    ):
        raise ValueError("Source proof scope, full reconstruction or purpose differs")
    expected_path = confined_path(
        paths.artifacts, f"source_verification/{proof['source_verification_version']}/manifest.json"
    )
    if expected_path != proof_path.resolve():
        raise ValueError("Source proof must use its exact immutable artifact path")
    total = sum(
        len(items)
        for items in (
            manifest["files"],
            manifest["cache_files"],
            _read(universe / "manifest.json")["files"],
            _read(sec / "manifest.json")["files"],
        )
    )
    began, last_update = time.monotonic(), 0.0
    for index, (path, digest) in enumerate(
        _bindings(paths, intelligence_directory, manifest, universe, sec), 1
    ):
        if sha256_file(path) != digest:
            raise ValueError("Bound source bytes changed after complete reconstruction")
        now = time.monotonic()
        if progress is not None and (index == total or now - last_update >= 30):
            progress(
                {
                    "status": "RUNNING",
                    "stage": "BOUND_SOURCE_HASH_AUDIT",
                    "checked_source_files": index,
                    "total_source_files": total,
                    "source_hash_audit_elapsed_seconds": round(now - began, 3),
                    "source_hash_audit_complete": index == total,
                    "source_proof_purpose": purpose,
                }
            )
            last_update = now
    if (
        _scope(paths, registry_version, intelligence_directory)[0] != scope
        or sha256_file(proof_path) != expected_sha256
    ):
        raise ValueError("Source inputs or verifier changed during checksum audit")
    return proof
