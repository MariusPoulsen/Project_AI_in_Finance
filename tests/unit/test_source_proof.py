"""Complete proof identity, full-byte checks and purpose must fail closed."""

import json
from pathlib import Path
from typing import Any

import pytest

from structural_break.config.paths import ProjectPaths
from structural_break.research import intelligence, source_proof
from structural_break.storage.files import sha256_file


@pytest.fixture
def source_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    paths = ProjectPaths(tmp_path / "project", tmp_path / "workspace")
    universe = paths.workspace_root / "universe/source_v1"
    sec = paths.workspace_root / "sec_metadata/source_v3"
    directory = paths.workspace_root / "intelligence/fixture"
    for base in (universe, sec, directory, paths.workspace_root / "cache"):
        base.mkdir(parents=True)

    def store(base: Path, name: str, body: bytes) -> tuple[str, str]:
        (base / name).write_bytes(body)
        return name, sha256_file(base / name)

    for base in (universe, sec):
        files = dict([store(base, "source.txt", b"frozen metadata")])
        (base / "manifest.json").write_text(json.dumps({"files": files}))
    registry = {
        "protocol": {"final_test_locked": True},
        "inputs": [{"role": "universe", "path": "universe/source_v1/manifest.json"}],
    }
    registry_path = paths.workspace_root / "registry.json"
    registry_path.write_text(json.dumps(registry))
    monkeypatch.setattr(
        source_proof, "registered_manifest", lambda *a, **k: (registry_path, registry)
    )
    manifest = {
        "schema_version": "research-event-intelligence-v2",
        "event_count": 2,
        "scheduled_event_count": 2,
        "all_events_retained": True,
        "final_test_outcomes_inspected": False,
        "intelligence_version": "fixture",
        "inputs": {
            "max_events": None,
            "event_registry_id": "registry",
            "events_sha256": "a" * 64,
            "sec_manifest_sha256": sha256_file(sec / "manifest.json"),
        },
        "source_identity": {"records": [{"file": "a"}, {"file": "b"}]},
        "files": dict(
            [
                store(directory, "features.parquet", b"unchanged features"),
                store(directory, "checkpoint.json", b"unchanged checkpoint"),
            ]
        ),
        "cache_files": dict([store(paths.workspace_root / "cache", "raw.txt", b"unchanged raw")]),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    calls = []

    def reconstruct(*a: object, **k: object) -> dict[str, Any]:
        calls.append("complete verifier called")
        return json.loads((directory / "manifest.json").read_bytes())

    monkeypatch.setattr(intelligence, "verify_event_intelligence", reconstruct)
    return paths, directory, manifest, calls


def test_mint_always_calls_complete_verifier_and_purposes_are_distinct(source_fixture: Any) -> None:
    paths, directory, _, calls = source_fixture
    initial = source_proof.mint_source_proof(paths, "registry", directory, purpose="fitting_input")
    again = source_proof.mint_source_proof(paths, "registry", directory, purpose="fitting_input")
    final = source_proof.mint_source_proof(
        paths, "registry", directory, purpose="independent_publication"
    )
    assert len(calls) == 3 and initial == again
    assert final["source_proof_sha256"] != initial["source_proof_sha256"]


@pytest.mark.parametrize("filename", ["raw", "checkpoint", "features", "metadata", "proof"])
def test_changed_bound_bytes_or_proof_are_rejected(source_fixture: Any, filename: str) -> None:
    paths, directory, _, _ = source_fixture
    result = source_proof.mint_source_proof(paths, "registry", directory, purpose="fitting_input")
    proof_path = Path(result["source_proof_path"])
    target = {
        "raw": paths.workspace_root / "cache/raw.txt",
        "checkpoint": directory / "checkpoint.json",
        "features": directory / "features.parquet",
        "metadata": paths.workspace_root / "sec_metadata/source_v3/source.txt",
        "proof": proof_path,
    }[filename]
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum differs|bytes changed"):
        source_proof.validate_source_proof(
            paths,
            "registry",
            directory,
            proof_path,
            result["source_proof_sha256"],
            purpose="fitting_input",
        )


def test_fit_receipt_cannot_substitute_for_final_independent_reconstruction(
    source_fixture: Any,
) -> None:
    paths, directory, _, _ = source_fixture
    result = source_proof.mint_source_proof(paths, "registry", directory, purpose="fitting_input")
    with pytest.raises(ValueError, match="purpose differs"):
        source_proof.validate_source_proof(
            paths,
            "registry",
            directory,
            Path(result["source_proof_path"]),
            result["source_proof_sha256"],
            purpose="independent_publication",
        )


@pytest.mark.parametrize(
    "update",
    [
        {"all_events_retained": False},
        {"scheduled_event_count": 1},
        {"event_count": 1},
        {"final_test_outcomes_inspected": True},
    ],
)
def test_partial_or_unlocked_population_cannot_mint_a_proof(
    source_fixture: Any, update: Any
) -> None:
    paths, directory, manifest, calls = source_fixture
    manifest.update(update)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="complete locked"):
        source_proof.mint_source_proof(paths, "registry", directory, purpose="fitting_input")
    assert calls == []


def test_every_validation_rehashes_the_complete_inventory_and_rejects_stale_code(
    source_fixture: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, directory, _, calls = source_fixture
    result = source_proof.mint_source_proof(paths, "registry", directory, purpose="fitting_input")
    proof_path = Path(result["source_proof_path"])
    observed: list[dict[str, Any]] = []
    for _ in range(2):
        source_proof.validate_source_proof(
            paths,
            "registry",
            directory,
            proof_path,
            result["source_proof_sha256"],
            purpose="fitting_input",
            progress=observed.append,
        )
    completed = [row for row in observed if row["source_hash_audit_complete"]]
    assert len(completed) == 2 and all(row["checked_source_files"] == 5 for row in completed)
    assert len(calls) == 1
    monkeypatch.setattr(
        source_proof, "computational_identity", lambda *_: {"source_sha256": "changed"}
    )
    with pytest.raises(ValueError, match="scope"):
        source_proof.validate_source_proof(
            paths,
            "registry",
            directory,
            proof_path,
            result["source_proof_sha256"],
            purpose="fitting_input",
        )
