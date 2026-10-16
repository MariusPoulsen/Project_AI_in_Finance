"""Blinded genuine SEC review, frozen before reading the selected source captures."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, cast

from structural_break.agents.contracts import AgentInput, FrozenModel, SourceChunk
from structural_break.agents.historical import RegisteredSources, read_frame, source_chunks
from structural_break.agents.pipeline import canonical_json, digest
from structural_break.agents.review import CompletedReview
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.intelligence.evidence import cache_filing, select_event_filings
from structural_break.research.intelligence import RESEARCH_EVIDENCE_POLICY, _offline_only
from structural_break.storage.files import sha256_file, write_bytes

VERSION = "phase5-genuine-blind-source-review-v1"


def _bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode()


def _ranked(sources: RegisteredSources, count: int, seed: str) -> list[dict[str, Any]]:
    if type(count) is not int or not 50 <= count <= 100 or not 1 <= len(seed) <= 200:
        raise ValueError("Genuine review requires 50..100 events and a bounded explicit seed")
    if count > len(sources.events):
        raise ValueError("Review exceeds the registered population; no silent downsampling")
    return sorted(
        cast(list[dict[str, Any]], sources.events.to_dict("records")),
        key=lambda event: digest(
            {
                "event_id": event["event_id"],
                "pair_id": event["pair_id"],
                "event_timestamp": event["event_timestamp"],
                "seed": seed,
            }
        ),
    )[:count]


def _identity(sources: RegisteredSources, *, count: int, seed: str) -> dict[str, object]:
    selected = _ranked(sources, count, seed)
    source_root = Path(__file__).resolve().parents[1]
    recipe_files = (
        "agents/historical_review.py",
        "intelligence/evidence.py",
        "research/intelligence.py",
        "research/availability.py",
        "data/sec.py",
        "research/universe.py",
        "config/paths.py",
        "storage/files.py",
    )
    recipe = {
        name: hashlib.sha256((source_root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in recipe_files
    }
    for component in (
        RegisteredSources.__init__,
        RegisteredSources.event,
        RegisteredSources.pack,
        read_frame,
        source_chunks,
        FrozenModel,
        SourceChunk,
    ):
        recipe[component.__qualname__] = hashlib.sha256(
            inspect.getsource(component).replace("\r\n", "\n").encode()
        ).hexdigest()
    return {
        "schema_version": VERSION,
        "mode": "genuine_sources",
        "registry_version": sources.registry["research_version"],
        "registry_manifest_sha256": sha256_file(sources.registry_path),
        "sec_manifest_sha256": sources.sec_manifest_sha256,
        "universe_manifest_sha256": sha256_file(sources.universe_directory / "manifest.json"),
        "population_identity_sha256": digest(sources.events.to_dict("records")),
        "available_count": len(sources.events),
        "selected_count": count,
        "seed": seed,
        "selection_policy": "event-identity-sha256-v1",
        "selected_events": selected,
        "evidence_policy_version": RESEARCH_EVIDENCE_POLICY.version,
        "source_recipe_sha256": digest(recipe),
    }


def _projection(event: dict[str, Any], pack: dict[str, Any]) -> dict[str, object]:
    return {
        **event,
        "declared_source_coverage": pack["coverage_status"],
        "evidence_policy_version": RESEARCH_EVIDENCE_POLICY.version,
        "offset_coordinate_system": "stored-cleaned-chunk-character-v1",
        "evidence": [row.model_dump(mode="json") for row in source_chunks(pack)],
        "source_pack": pack,
    }


def _snapshot(
    sources: RegisteredSources, selected: list[dict[str, Any]], directory: Path
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Copy only declared accession receipts and their validated response bodies."""
    files: dict[str, str] = {}
    missing: set[str] = set()
    accessions: dict[str, dict[str, Any]] = {}
    for event in selected:
        filings, _ = select_event_filings(
            event,
            sources.filings,
            [event["leg_a_security_id"], event["leg_b_security_id"]],
            RESEARCH_EVIDENCE_POLICY,
        )
        for filing in filings:
            accessions[str(filing["filing_id"])] = dict(filing)
    for filing in accessions.values():
        documents = cache_filing(sources.cache_paths, filing, _offline_only, offline=True)
        relative = (
            f"data/raw/sec/filings/{str(filing['cik']).zfill(10)}/{filing['filing_id']}/"
            "response_manifest.json"
        )
        manifest_path = confined_path(sources.cache_paths.workspace_root, relative)
        if not manifest_path.is_file():
            missing.add(relative)
            continue  # Even partial bodies without a manifest are not accepted captures.
        captures = [relative]
        for document in documents:
            path = document.get("raw_file_path")
            if path is not None:
                captures.append(str(path) + ".response.json")
                if document.get("sha256") is not None:
                    captures.append(str(path))
        for path in captures:
            raw = confined_path(sources.cache_paths.workspace_root, path).read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            if path in files and files[path] != checksum:
                raise ValueError("Selected immutable SEC captures changed during snapshot")
            write_bytes(confined_path(directory, path), raw)
            files[path] = checksum
    return files, tuple(sorted(missing))


def export_historical_review(
    sources: RegisteredSources, output_dir: Path, *, count: int = 50, seed: str = "phase5-review-v1"
) -> Path:
    """Publish real source packets; never imply completed annotations or model quality."""
    identity = _identity(sources, count=count, seed=seed)
    directory = output_dir / digest(identity)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        verify_historical_review(sources, directory)
        return manifest_path
    selected = _ranked(sources, count, seed)
    # Selection is persisted before any source-body/cache coverage inspection.
    write_bytes(directory / "selection.json", _bytes(identity))
    raw_files, missing = _snapshot(sources, selected, directory / "capture")
    capture_paths = ProjectPaths(sources.paths.project_root, directory / "capture")
    cases = []
    for event in selected:
        pack = sources.pack(event["event_id"], cache_paths=capture_paths)
        body = _bytes(_projection(event, pack))
        checksum = hashlib.sha256(body).hexdigest()
        path = f"sources/{checksum}.json"
        write_bytes(directory / path, body)
        cases.append(
            {
                "event_id": event["event_id"],
                "source_file": path,
                "source_sha256": checksum,
                "input_sha256": digest(pack),
                "source_coverage": pack["coverage_status"],
                "evidence_chunk_count": len(pack["chunks"]),
            }
        )
    manifest = {
        **identity,
        "selection_sha256": sha256_file(directory / "selection.json"),
        "raw_files": raw_files,
        "missing_accession_manifests": missing,
        "cases": cases,
        "human_annotations_complete": False,
        "semantic_accuracy_measured": False,
        "genuine_quality_gate_passed": False,
    }
    body = _bytes(manifest)
    write_bytes(manifest_path, body)
    blank = {
        "review_manifest_sha256": hashlib.sha256(body).hexdigest(),
        "reviewer_id": None,
        "reviewed_at": None,
        "human_review_attested": False,
        "annotations": [
            {
                "event_id": case["event_id"],
                "source_completeness": None,
                "catalyst": None,
                "source_support": None,
                "notes": "",
            }
            for case in cases
        ],
    }
    write_bytes(directory / "annotations.blank.json", (json.dumps(blank, indent=2) + "\n").encode())
    write_bytes(
        directory / "README.md",
        (
            b"# Genuine blind SEC source review\n\n"
            b"The sample was frozen from registered historical event identities before "
            b"source inspection. No probabilities, outcomes or suggested catalyst "
            b"classifications are included. Missing raw captures remain UNKNOWN and count "
            b"in the sample. Read each source JSON, then complete a copy of "
            b"annotations.blank.json with your reviewer ID, timezone-aware review time "
            b"and human attestation.\n\n"
            b"For every case label source completeness; catalyst category, affected leg, "
            b"direction, materiality "
            b"and relationship relevance; exact citations (chunk_id, leg, quote); source support "
            b"SUPPORTED/UNSUPPORTED/INSUFFICIENT; and notes. UNKNOWN has no invented "
            b"properties or citations. NONE requires complete bounded source coverage. "
            b"Citation offsets address the stored cleaned chunk, not original HTML "
            b"characters. Raw document hashes, parser chunk IDs, filename and order remain "
            b"in source_pack. Modern issuer capture and retrospective parser limitations "
            b"still apply.\n\nValidation checks format, provenance and citations. It does "
            b"not establish that your semantic interpretation is correct or measure "
            b"agent accuracy. Model-based interpretation review is separate.\n"
        ),
    )
    verify_historical_review(sources, directory)
    return manifest_path


def verify_historical_review(
    sources: RegisteredSources, review_dir: Path, annotations_path: Path | None = None
) -> dict[str, object]:
    """Replay only the frozen review sample from its local source snapshot."""
    raw = (review_dir / "manifest.json").read_bytes()
    if len(raw) > 8_000_000:
        raise ValueError("Review manifest exceeds its bounded size")
    manifest = json.loads(raw)
    identity = _identity(sources, count=manifest["selected_count"], seed=manifest["seed"])
    if any(manifest.get(key) != value for key, value in identity.items()):
        raise ValueError("Review does not bind the exact registered target-blind selection")
    selection = (review_dir / "selection.json").read_bytes()
    if (
        selection != _bytes(identity)
        or hashlib.sha256(selection).hexdigest() != manifest["selection_sha256"]
    ):
        raise ValueError("Frozen review selection checksum mismatch")
    if any(
        manifest.get(key) is not False
        for key in (
            "human_annotations_complete",
            "semantic_accuracy_measured",
            "genuine_quality_gate_passed",
        )
    ):
        raise ValueError("Source packet cannot self-attest semantic acceptance")
    capture_root = review_dir / "capture"
    for path, checksum in manifest["raw_files"].items():
        if sha256_file(confined_path(capture_root, path)) != checksum:
            raise ValueError("Review raw-source snapshot checksum mismatch")
    for path in manifest["missing_accession_manifests"]:
        if confined_path(capture_root, path).exists():
            raise ValueError("Previously unavailable captures cannot mutate a frozen review")
    capture_paths = ProjectPaths(sources.paths.project_root, capture_root)
    selected = _ranked(sources, manifest["selected_count"], manifest["seed"])
    if len(manifest["cases"]) != len(selected):
        raise ValueError("Every selected review event must remain in the denominator")
    projections = {}
    for event, case in zip(selected, manifest["cases"], strict=True):
        pack = sources.pack(event["event_id"], cache_paths=capture_paths)
        projection = _projection(event, pack)
        expected = _bytes(projection)
        checksum = hashlib.sha256(expected).hexdigest()
        if case != {
            "event_id": event["event_id"],
            "source_file": f"sources/{checksum}.json",
            "source_sha256": checksum,
            "input_sha256": digest(pack),
            "source_coverage": pack["coverage_status"],
            "evidence_chunk_count": len(pack["chunks"]),
        }:
            raise ValueError("Review source projection does not replay from frozen raw bytes")
        if confined_path(review_dir, case["source_file"]).read_bytes() != expected:
            raise ValueError("Review source packet checksum mismatch")
        projections[event["event_id"]] = projection
    completed = 0
    if annotations_path is not None:
        if annotations_path.stat().st_size > 2_000_000:
            raise ValueError("Review annotations exceed the bounded response size")
        review = CompletedReview.model_validate_json(annotations_path.read_bytes())
        if review.review_manifest_sha256 != hashlib.sha256(raw).hexdigest():
            raise ValueError("Annotations must bind the exact review manifest")
        if {row.event_id for row in review.annotations} != set(projections):
            raise ValueError("Every selected case requires exactly one human annotation")
        for row in review.annotations:
            source = projections[row.event_id]
            coverage = source["declared_source_coverage"]
            if row.source_completeness == "COMPLETE" and coverage != "COMPLETE":
                raise ValueError("Annotation cannot upgrade incomplete source acquisition")
            # Existing mechanical citation/clock/issuer checks, with no fitted score.
            AgentInput.model_validate_json(
                canonical_json(
                    {
                        **{
                            key: source[key]
                            for key in (
                                "event_id",
                                "pair_id",
                                "event_timestamp",
                                "leg_a_security_id",
                                "leg_b_security_id",
                            )
                        },
                        "pair_status": "UNKNOWN",
                        "quant": {"model_b_probability": None},
                        "gates": {
                            "market_data_ok": False,
                            "model_inputs_ok": False,
                            "source_timestamps_ok": True,
                            "source_coverage": row.source_completeness,
                            "liquidity_ok": None,
                            "implementation_ok": None,
                        },
                        "lineage": {
                            "registry_id": sources.registry["research_version"],
                            "model_bundle_id": "source-review-no-model",
                            "model_version": "not-applicable",
                            "calibrator_version": "not-applicable",
                            "relationship_version": "not-applicable",
                            "evidence_policy_version": RESEARCH_EVIDENCE_POLICY.version,
                            "source_manifest_sha256": sources.sec_manifest_sha256,
                        },
                        "evidence": source["evidence"],
                        "catalysts": [row.catalyst.model_dump(mode="json")],
                    }
                )
            )
        completed = len(review.annotations)
    counts = {
        status: sum(case["source_coverage"] == status for case in manifest["cases"])
        for status in ("COMPLETE", "PARTIAL", "UNKNOWN")
    }
    return {
        "status": "SOURCE_SAMPLE_REPLAY_VERIFIED",
        "mode": "genuine_sources",
        "selected_count": len(selected),
        "completed_count": completed,
        "source_coverage_counts": counts,
        "genuine_quality_gate_passed": False,
        "semantic_accuracy_measured": False,
    }
