"""Adversarial adapter checks; test doubles never certify genuine acceptance."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from structural_break.agents import historical, historical_review
from structural_break.agents.contracts import AgentInput
from structural_break.agents.historical import AcceptedHistoricalInputs, RegisteredSources
from structural_break.agents.inputs import PreparedInputs
from structural_break.config.paths import ProjectPaths
from structural_break.research.primary import PrimaryNotReadyError
from structural_break.storage.files import write_bytes


@pytest.fixture
def registered_sources(tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch):
    """A source double isolates sampling/replay; production constructors are not bypassed."""
    sources = object.__new__(RegisteredSources)
    sources.paths = ProjectPaths(project_root, tmp_path)
    sources.registry_path = write_bytes(tmp_path / "registry/manifest.json", b"registered fixture")
    sources.registry = {"research_version": "fixture-registered-development"}
    sources.universe_directory = tmp_path / "universe"
    write_bytes(sources.universe_directory / "manifest.json", b"fixture-universe")
    sources.sec_manifest_sha256 = "a" * 64
    sources.events = pd.DataFrame(
        [
            {
                "event_id": f"source-event-{index}",
                "pair_id": "AAA__BBB",
                "event_timestamp": "2022-01-03T21:00:00+00:00",
                "evidence_cutoff": "2022-01-03T21:00:00+00:00",
                "leg_a": "AAA",
                "leg_b": "BBB",
                "leg_a_security_id": "AAA",
                "leg_b_security_id": "BBB",
            }
            for index in range(60)
        ]
    )

    def snapshot(_sources, _selected, directory):
        write_bytes(directory / "raw.txt", b"Fixed historical evidence.")
        return {"raw.txt": hashlib.sha256(b"Fixed historical evidence.").hexdigest()}, ()

    def pack(event_id: str, *, cache_paths: ProjectPaths | None = None) -> dict[str, Any]:
        assert cache_paths is not None
        text = (cache_paths.workspace_root / "raw.txt").read_text()
        missing = event_id.endswith("0")
        return {
            "event_id": event_id,
            "coverage_status": "UNKNOWN" if missing else "COMPLETE",
            "chunks": []
            if missing
            else [
                {
                    "chunk_id": "chunk_A",
                    "leg": "A",
                    "security_id": "AAA",
                    "filing_id": "0000000001-21-000001",
                    "sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "chunk_text": text,
                    "acceptance_datetime_utc": "2021-12-30T21:00:00+00:00",
                }
            ],
        }

    monkeypatch.setattr(historical_review, "_snapshot", snapshot)
    monkeypatch.setattr(sources, "pack", pack)
    return sources


def _export(sources, tmp_path):
    return historical_review.export_historical_review(sources, tmp_path / "review", count=50)


def test_blind_source_selection_replay_and_complete_denominators(registered_sources, tmp_path):
    path = _export(registered_sources, tmp_path)
    result = historical_review.verify_historical_review(registered_sources, path.parent)
    assert result["selected_count"] == 50
    assert result["completed_count"] == 0
    assert sum(result["source_coverage_counts"].values()) == 50
    assert result["source_coverage_counts"]["UNKNOWN"] > 0
    assert result["genuine_quality_gate_passed"] is False
    assert _export(registered_sources, tmp_path) == path
    manifest = json.loads(path.read_bytes())
    for case in manifest["cases"]:
        projection = json.loads((path.parent / case["source_file"]).read_bytes())
        assert "model_b_probability" not in projection
        assert "y_revert_success" not in projection
        assert "catalysts" not in projection
        assert projection["offset_coordinate_system"] == "stored-cleaned-chunk-character-v1"


def test_raw_snapshot_preserves_failed_receipt_without_inventing_response_body(
    tmp_path, project_root, monkeypatch
):
    cache = tmp_path / "original-cache"
    accession = "0000000001-21-000001"
    folder = f"data/raw/sec/filings/0000000001/{accession}"
    raw_path = f"{folder}/index.json"
    write_bytes(cache / folder / "response_manifest.json", b"fixture-validated-manifest")
    write_bytes(cache / (raw_path + ".response.json"), b"fixture-failed-response-receipt")
    sources = SimpleNamespace(cache_paths=ProjectPaths(project_root, cache), filings=pd.DataFrame())
    event = {"leg_a_security_id": "AAA", "leg_b_security_id": "BBB"}
    filing = {"filing_id": accession, "cik": "1"}
    monkeypatch.setattr(historical_review, "select_event_filings", lambda *_args: ([filing], {}))
    monkeypatch.setattr(
        historical_review,
        "cache_filing",
        lambda *_args, **_kwargs: [{"raw_file_path": raw_path, "sha256": None, "status": "FAILED"}],
    )
    # Save the production implementation before the source-double fixture replaces it.
    files, missing = historical_review._snapshot(sources, [event], tmp_path / "capture")
    assert missing == ()
    assert raw_path not in files
    assert raw_path + ".response.json" in files
    assert not (tmp_path / "capture" / raw_path).exists()
    assert not (cache / raw_path).exists()


@pytest.mark.parametrize("count", [1, 49, 101, True])
def test_genuine_review_rejects_undersized_or_invalid_sample(registered_sources, tmp_path, count):
    with pytest.raises(ValueError, match="50..100"):
        historical_review.export_historical_review(registered_sources, tmp_path, count=count)


def test_genuine_review_never_silently_downsamples(registered_sources, tmp_path):
    with pytest.raises(ValueError, match="downsampling"):
        historical_review.export_historical_review(registered_sources, tmp_path, count=100)


@pytest.mark.parametrize("tamper", ["selection", "source", "raw", "denominator", "acceptance"])
def test_review_rejects_tampering(registered_sources, tmp_path, tamper):
    path = _export(registered_sources, tmp_path)
    manifest = json.loads(path.read_bytes())
    if tamper == "selection":
        (path.parent / "selection.json").write_text("{}")
    elif tamper == "source":
        (path.parent / manifest["cases"][0]["source_file"]).write_text("{}")
    elif tamper == "raw":
        (path.parent / "capture/raw.txt").write_text("Changed evidence.")
    elif tamper == "denominator":
        manifest["cases"].pop()
        path.write_text(json.dumps(manifest))
    else:
        manifest["genuine_quality_gate_passed"] = True
        path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        historical_review.verify_historical_review(registered_sources, path.parent)


def test_annotation_binds_exact_manifest_and_retains_unknown(registered_sources, tmp_path):
    path = _export(registered_sources, tmp_path)
    blank = json.loads((path.parent / "annotations.blank.json").read_bytes())
    blank.update(
        reviewer_id="fixture-reviewer",
        reviewed_at="2026-10-11T05:00:00+00:00",
        human_review_attested=True,
    )
    for row in blank["annotations"]:
        row.update(
            source_completeness="UNKNOWN",
            source_support="INSUFFICIENT",
            catalyst={
                "event_type": "UNKNOWN",
                "affected_leg": "UNKNOWN",
                "direction": "UNKNOWN",
                "materiality": "UNKNOWN",
                "relationship_relevance": "UNKNOWN",
                "citations": [],
            },
        )
    annotations = tmp_path / "annotations.json"
    annotations.write_text(json.dumps(blank))
    result = historical_review.verify_historical_review(
        registered_sources, path.parent, annotations
    )
    assert result["completed_count"] == 50
    assert result["semantic_accuracy_measured"] is False
    blank["review_manifest_sha256"] = "f" * 64
    annotations.write_text(json.dumps(blank))
    with pytest.raises(ValueError, match="exact review manifest"):
        historical_review.verify_historical_review(registered_sources, path.parent, annotations)


def test_annotation_cannot_upgrade_missing_sources(registered_sources, tmp_path):
    path = _export(registered_sources, tmp_path)
    blank = json.loads((path.parent / "annotations.blank.json").read_bytes())
    blank.update(
        reviewer_id="fixture-reviewer",
        reviewed_at="2026-10-11T05:00:00+00:00",
        human_review_attested=True,
    )
    for row in blank["annotations"]:
        row.update(
            source_completeness="COMPLETE",
            source_support="INSUFFICIENT",
            catalyst={
                "event_type": "UNKNOWN",
                "affected_leg": "UNKNOWN",
                "direction": "UNKNOWN",
                "materiality": "UNKNOWN",
                "relationship_relevance": "UNKNOWN",
                "citations": [],
            },
        )
    annotations = tmp_path / "annotations.json"
    annotations.write_text(json.dumps(blank))
    with pytest.raises(ValueError, match="upgrade incomplete"):
        historical_review.verify_historical_review(registered_sources, path.parent, annotations)


def test_historical_adapter_requires_registered_primary_before_loading_model(paths, monkeypatch):
    called = []

    def unavailable(_paths, version):
        called.append(version)
        raise PrimaryNotReadyError("Primary v2 outputs have not been published")

    monkeypatch.setattr(historical, "load_primary", unavailable)
    monkeypatch.setattr(historical.joblib, "load", lambda _body: pytest.fail("unsafe model load"))
    with pytest.raises(PrimaryNotReadyError):
        AcceptedHistoricalInputs(
            paths,
            primary_version="explicit-missing-primary",
            sec_directory=paths.workspace_root,
            sec_manifest_sha256="a" * 64,
            cache_workspace=paths.workspace_root,
        )
    assert called == ["explicit-missing-primary"]


@pytest.mark.parametrize("probability", [0.1, float("nan"), float("inf")])
def test_historical_selected_native_probability_replay_is_required(probability):
    adapter = object.__new__(AcceptedHistoricalInputs)
    adapter.sources = SimpleNamespace(
        event=lambda _id: {"event_id": "event", "event_timestamp": "2022-01-03T21:00:00+00:00"}
    )
    adapter.rows = pd.DataFrame({"event_id": ["event"], "x": [1.0]})
    adapter.predictions = pd.DataFrame(
        {
            "event_id": ["event"],
            "research_partition": ["assessment"],
            "logistic_B_both_raw": [0.7],
            "logistic_B_both_calibrated": [0.8],
        }
    )
    adapter.model = SimpleNamespace(
        columns=("x",),
        predict=lambda _rows: np.array([probability]),
        estimator=SimpleNamespace(predict_proba=lambda _rows: np.array([[0.3, 0.7]])),
    )
    with pytest.raises(ValueError, match="independent replay"):
        adapter.event("event")


def test_mock_inventory_rejects_historical_rebranding(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "phase5-accepted-historical-inputs-v1",
                "mode": "accepted_historical",
                "accepted": True,
            }
        )
    )
    with pytest.raises(ValueError):
        PreparedInputs(path)


@pytest.mark.parametrize("tamper", [None, "publication", "model", "code", "event", "duplicate"])
def test_historical_export_binds_publication_code_and_fresh_replay(
    project_root, tmp_path, monkeypatch, tamper
):
    event = AgentInput.model_validate_json(
        (project_root / "tests/fixtures/phase5/input.json").read_bytes()
    )
    proof = write_bytes(tmp_path / "registered-primary.json", b"fixture-primary")
    adapter = SimpleNamespace(
        paths=ProjectPaths(project_root, tmp_path),
        primary={"primary_version": "fixture-primary"},
        sources=SimpleNamespace(
            registry={"research_version": "fixture-registry"}, sec_manifest_sha256="a" * 64
        ),
        evaluation={"research_version": "fixture-native"},
        model_sha256="b" * 64,
        event=lambda _id: event,
    )
    monkeypatch.setattr(historical, "registered_manifest", lambda *_args: (proof, {}))
    path = historical.export_historical_inputs(adapter, (event.event_id,), tmp_path / "inputs")
    manifest = json.loads(path.read_bytes())
    assert manifest["mode"] == "accepted_historical"
    assert manifest["genuine_agent_quality_evaluated"] is False
    if tamper is None:
        assert historical.verify_historical_inputs(adapter, path) == 1
        return
    if tamper == "publication":
        manifest["primary_manifest_sha256"] = "0" * 64
    elif tamper == "model":
        manifest["model_sha256"] = "0" * 64
    elif tamper == "code":
        manifest["adapter_identity"]["source_sha256"] = "0" * 64
    elif tamper == "duplicate":
        manifest["entries"].append(dict(manifest["entries"][0]))
    else:
        (path.parent / manifest["entries"][0]["path"]).write_text("{}")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        historical.verify_historical_inputs(adapter, path)


def test_genuine_source_chunks_retain_raw_hash_and_chunk_coordinates(project_root):
    fixture = AgentInput.model_validate_json(
        (project_root / "tests/fixtures/phase5/input.json").read_bytes()
    )
    original = fixture.evidence[0]
    chunks = historical.source_chunks(
        {
            "chunks": [
                {
                    "chunk_id": original.chunk_id,
                    "leg": original.leg,
                    "security_id": original.security_id,
                    "filing_id": original.filing_id,
                    "sha256": original.document_sha256,
                    "chunk_text": original.text,
                    "acceptance_datetime_utc": original.source_timestamp.isoformat(),
                }
            ]
        }
    )
    assert chunks[0].document_sha256 == original.document_sha256
    assert chunks[0].end_offset == len(original.text)
    assert chunks[0].start_offset == 0


@pytest.mark.parametrize("tamper", [None, "future", "parameters", "status", "snapshot"])
def test_registered_relationship_join_preserves_historical_status_and_parameters(
    tmp_path, monkeypatch, tamper
):
    sources = object.__new__(RegisteredSources)
    sources.registry_path = tmp_path / "registry/manifest.json"
    source_identity = {"fixture": "source-identity"}
    sources.registry = {
        "pair_manifests": [{"pair_id": "AAA__BBB", "sha256": "a" * 64}],
        "source": source_identity,
    }
    pair_manifest = {
        "pair_id": "AAA__BBB",
        "identity": historical.research_identity(source_identity),
    }
    snapshot = {
        "relationship_snapshot_id": "snapshot",
        "pair_id": "AAA__BBB",
        "estimation_timestamp": "2021-12-30T21:00:00+00:00",
        "effective_start_at": "2022-01-03T14:30:00+00:00",
        "effective_end_at": "2022-02-01T14:30:00+00:00",
        "pair_status": "WATCH",
        "alpha": 0.0,
        "beta": 1.0,
        "spread_mean": 0.0,
        "spread_std": 0.1,
    }
    event = {
        "pair_id": "AAA__BBB",
        "relationship_snapshot_id": "snapshot",
        "event_timestamp": "2022-01-03T21:00:00+00:00",
        "baseline1_eligible": False,
        **{key: snapshot[key] for key in ("alpha", "beta", "spread_mean", "spread_std")},
    }
    if tamper == "future":
        snapshot["estimation_timestamp"] = "2022-01-04T21:00:00+00:00"
    elif tamper == "parameters":
        event["beta"] = 2.0
    elif tamper == "status":
        event["baseline1_eligible"] = True
    elif tamper == "snapshot":
        event["relationship_snapshot_id"] = "another-snapshot"
    monkeypatch.setattr(historical, "checked_json", lambda _path, _sha: pair_manifest)
    monkeypatch.setattr(historical, "read_frame", lambda *_args: pd.DataFrame([snapshot]))
    if tamper is None:
        assert sources.relationship(event)["pair_status"] == "WATCH"
    else:
        with pytest.raises(ValueError):
            sources.relationship(event)


@pytest.mark.parametrize("partition", ["assessment", "fit", "calibration"])
def test_accepted_projection_preserves_tone_provenance_and_safe_execution_gates(
    project_root, monkeypatch, partition
):
    """Adapter projection test only: raw/native acceptance gates have separate tests."""
    original = AgentInput.model_validate_json(
        (project_root / "tests/fixtures/phase5/input.json").read_bytes()
    )
    identity = {
        key: original.model_dump(mode="json")[key]
        for key in (
            "event_id",
            "pair_id",
            "event_timestamp",
            "leg_a_security_id",
            "leg_b_security_id",
        )
    }
    identity["evidence_cutoff"] = identity["event_timestamp"]
    adapter = object.__new__(AcceptedHistoricalInputs)
    pack = {
        "event_id": original.event_id,
        "pair_id": original.pair_id,
        "event_timestamp": identity["event_timestamp"],
        "evidence_cutoff": identity["evidence_cutoff"],
        "coverage_status": "COMPLETE",
        "chunks": [
            {
                "chunk_id": row.chunk_id,
                "leg": row.leg,
                "security_id": row.security_id,
                "filing_id": row.filing_id,
                "sha256": row.document_sha256,
                "chunk_text": row.text,
                "acceptance_datetime_utc": row.source_timestamp.isoformat(),
            }
            for row in original.evidence
        ],
    }
    from structural_break.research.intelligence import _sha

    pack["evidence_hash"] = _sha(pack)
    adapter.sources = SimpleNamespace(
        event=lambda _id: dict(identity),
        pack=lambda _id: dict(pack),
        registry={"research_version": "fixture-registry"},
        relationship=lambda _event: {"pair_status": "ACTIVE"},
    )
    adapter.rows = pd.DataFrame({"event_id": [original.event_id], "x": [1.0]})
    adapter.predictions = pd.DataFrame(
        {
            "event_id": [original.event_id],
            "research_partition": [partition],
            "logistic_B_both_raw": [0.7],
            "logistic_B_both_calibrated": [0.8],
        }
    )
    adapter.model = SimpleNamespace(
        columns=("x",),
        predict=lambda _rows: np.array([0.8]),
        estimator=SimpleNamespace(predict_proba=lambda _rows: np.array([[0.3, 0.7]])),
    )
    adapter.evidence_mapping = pd.DataFrame(
        {
            "event_id": [original.event_id],
            "pair_id": [original.pair_id],
            "event_timestamp": [original.event_timestamp],
        }
    )
    filename = "events/" + hashlib.sha256(original.event_id.encode()).hexdigest() + ".json"
    tone_policy = {
        "model_name": "ProsusAI/finbert",
        "model_revision": "4556d13015211d73dccd3fdd39d39232506f3e43",
        "preprocessing_version": "sec-sentence-quality-wordpiece-v2",
    }
    tone = {"policy": tone_policy, "chunks": [], "legs": {}}
    for leg, security in (("A", original.leg_a_security_id), ("B", original.leg_b_security_id)):
        tone["chunks"].append({"leg": leg, "token_count": 10, "eligible_token_count": 8})
        tone["legs"][leg] = {
            "security_id": security,
            "status": "PARTIAL",
            "source_coverage_status": "COMPLETE",
            "scored_token_count": 4,
            "token_coverage": 0.4,
            "unknown_chunk_count": 0,
            "probabilities": {"positive": 0.5, "negative": 0.2, "neutral": 0.3},
            "net": 0.3,
        }
    record = {
        "event": dict(identity),
        "scheduled": True,
        "pack": pack,
        "catalyst_pack": pack,
        "extraction": {
            "event_type": "UNKNOWN",
            "affected_leg": "UNKNOWN",
            "direction": "UNKNOWN",
            "materiality": "UNKNOWN",
            "relationship_relevance": "UNKNOWN",
            "citations": [],
        },
        "tone": tone,
    }
    adapter.intelligence = {
        "source_identity": {"records": [{"file": filename, "sha256": "a" * 64}]},
        "inputs": {"sentiment_policy": tone_policy},
    }
    adapter.intelligence_path = project_root / "tests/fixtures/phase5/input.json"
    adapter.quant_events = pd.DataFrame(
        {
            "event_id": [original.event_id],
            "baseline1_eligible": [True],
            "relationship_version": [original.lineage.relationship_version],
        }
    )
    adapter.quant_features = pd.DataFrame(
        {
            "event_id": [original.event_id],
            "z_signed": [2.4],
            "feature_cutoff_timestamp": [original.event_timestamp],
        }
    )
    adapter.model_sha256 = "b" * 64
    adapter.evaluation = {"research_version": "fixture-accepted-evaluation"}
    monkeypatch.setattr(historical, "checked_json", lambda _path, _hash: record)
    monkeypatch.setattr(historical, "validate_stored_extraction", lambda *_args: None)
    monkeypatch.setattr(historical, "validate_sentiment_result", lambda *_args, **_kwargs: None)
    if partition != "assessment":
        with pytest.raises(ValueError, match="out-of-sample"):
            adapter.event(original.event_id)
        return
    projected = adapter.event(original.event_id)
    assert projected.quant.model_b_probability == 0.8
    assert projected.pair_status == "ACTIVE"
    assert projected.gates.liquidity_ok is None
    assert projected.gates.implementation_ok is None
    assert projected.tones[0].raw_token_count == 10
    assert projected.tones[0].excluded_token_count == 2
    assert projected.tones[0].budget_omitted_token_count == 4
    assert projected.tones[0].weights_sha256 == historical.FINBERT_WEIGHTS_SHA256
