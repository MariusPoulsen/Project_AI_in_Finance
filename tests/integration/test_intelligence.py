"""SEC batch publication, bounded-cache resume, and scientific lineage checks."""

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from structural_break.config.loader import load_config
from structural_break.config.paths import ProjectPaths
from structural_break.data.snapshots import json_bytes
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.extraction import validate_pack
from structural_break.intelligence.fixtures import MockProvider
from structural_break.services.intelligence import EvidenceRepository, build_event_intelligence
from structural_break.services.model_a import ModelARepository, build_events
from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.files import sha256_file


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    root = Path(__file__).resolve().parents[2]
    config = load_config(root / "configs")
    paths = ProjectPaths.resolve(root, tmp_path_factory.mktemp("p4_evidence_jobs") / "workspace")
    events = build_events(paths, config, fixture=True, event_version="p4_evidence_events")
    evidence = build_event_intelligence(paths, config, fixture=True)
    return paths, config, events, evidence


@pytest.fixture
def copied(published, tmp_path):
    original, *rest = published
    destination = tmp_path / "workspace"
    shutil.copytree(original.workspace_root, destination)
    return ProjectPaths.resolve(original.project_root, destination), *rest


def _rewrite_manifest(paths, manifest):
    path = paths.artifacts / "intelligence" / manifest["event_feature_version"] / "manifest.json"
    path.write_bytes(json_bytes(manifest))
    with DuckDBConnectionFactory(paths.database).connect(read_only=False) as connection:
        connection.execute(
            "UPDATE analytics.event_intelligence_versions SET checksum=? "
            "WHERE event_feature_version=?",
            [sha256_file(path), manifest["event_feature_version"]],
        )


def test_published_evidence_retains_all_rows_and_original_quantitative_values(copied):
    paths, config, events, evidence = copied
    frames = EvidenceRepository(paths).frames()
    parent = ModelARepository(paths).dataset_frames(events["dataset_version"])
    actual = frames["model_b_features"].set_index("event_id").sort_index()
    original = parent["event_features"].set_index("event_id").sort_index()
    assert len(actual) == len(parent["divergence_events"])
    quantitative = events["feature_schema"]["feature_columns"]
    pd.testing.assert_frame_equal(actual[quantitative], original[quantitative], check_dtype=False)
    assert set(EVENT_FEATURE_NAMES) <= set(actual)
    assert frames["extractions"]["status"].eq("UNKNOWN").any()
    assert frames["extractions"]["synthetic"].all()
    assert frames["evidence_packs"]["event_id"].nunique() == len(actual)
    raw = {
        item["path"]: item["sha256"]
        for item in evidence["files"]
        if item["dataset"] == "raw_sec_document"
    }
    usable = frames["document_chunks"].loc[frames["document_chunks"]["status"].eq("OK")]
    for chunk in usable.to_dict("records"):
        assert raw[chunk["raw_file_path"]] == chunk["sha256"]
        assert hashlib.sha256(chunk["chunk_text"].encode()).hexdigest() == chunk["text_sha256"]
    assert evidence["final_test_outcomes_computed"] is False
    canonical = pd.read_parquet(paths.data / "curated/evidence/document_chunks.parquet")
    pd.testing.assert_frame_equal(canonical, usable.reset_index(drop=True), check_dtype=False)
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        assert connection.execute("SELECT count(*) FROM ref.document_chunks").fetchone()[0] == len(
            canonical
        )


def test_evidence_publication_failure_restores_canonical_chunks_and_view(copied, monkeypatch):
    paths, config, events, evidence = copied
    import structural_break.services.intelligence as service

    canonical = paths.data / "curated/evidence/document_chunks.parquet"
    before_hash = sha256_file(canonical)
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        before_view = connection.execute(
            "SELECT sql FROM duckdb_views() WHERE schema_name='ref' AND view_name='document_chunks'"
        ).fetchone()[0]
    original = service._publish

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Injected intelligence publication failure")

    monkeypatch.setattr(service, "_publish", fail)
    with pytest.raises(RuntimeError, match="Injected intelligence"):
        build_event_intelligence(
            paths, config, fixture=True, event_feature_version="failed_evidence"
        )
    assert sha256_file(canonical) == before_hash
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        after_view = connection.execute(
            "SELECT sql FROM duckdb_views() WHERE schema_name='ref' AND view_name='document_chunks'"
        ).fetchone()[0]
        assert (
            connection.execute(
                "SELECT count(*) FROM analytics.event_intelligence_versions "
                "WHERE event_feature_version='failed_evidence'"
            ).fetchone()[0]
            == 0
        )
    assert after_view == before_view
    assert EvidenceRepository(paths).manifest() == evidence


def test_original_evidence_pack_hash_and_normalized_extraction_hash_are_distinct(copied):
    paths, config, events, evidence = copied
    frames = EvidenceRepository(paths).frames()
    extracted = frames["extractions"].set_index("event_id")
    for index in frames["evidence_packs"].to_dict("records"):
        pack = json.loads((paths.workspace_root / index["pack_path"]).read_bytes())
        assert index["evidence_hash"] == pack["evidence_hash"]
        expected = hashlib.sha256(
            json.dumps(
                validate_pack(pack), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        assert extracted.loc[index["event_id"], "evidence_hash"] == expected
        assert expected != pack["evidence_hash"]


def test_literal_offline_never_calls_even_injected_provider(copied):
    paths, config, events, evidence = copied

    def forbidden(request):
        pytest.fail("offline=True must never call a configured/injected LLM provider")

    replay = build_event_intelligence(paths, config, fixture=True, offline=True, provider=forbidden)
    frames = EvidenceRepository(paths).frames(replay["event_feature_version"])
    assert len(frames["model_b_features"]) == evidence["counts"]["model_b_features"]


def test_successful_extractions_reuse_exact_ids(copied):
    paths, config, events, evidence = copied
    provider = MockProvider()
    original = EvidenceRepository(paths).frames()["extractions"].set_index("event_id")
    replay = build_event_intelligence(paths, config, fixture=True, provider=provider)
    assert replay == evidence
    assert provider.calls == int(original["status"].eq("UNKNOWN").sum())
    after = EvidenceRepository(paths).frames()["extractions"].set_index("event_id")
    assert after["extraction_id"].equals(original["extraction_id"])


def test_prepublication_document_failure_is_audited_without_replacing_generation(
    copied, monkeypatch
):
    paths, config, events, evidence = copied

    def fail(*args, **kwargs):
        raise RuntimeError("Injected SEC capture failure")

    monkeypatch.setattr("structural_break.services.intelligence.cache_filing", fail)
    with pytest.raises(RuntimeError, match="Injected SEC"):
        build_event_intelligence(paths, config, fixture=True)
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        failed = connection.execute(
            "SELECT error_type FROM ops.job_runs WHERE job='build-intelligence' AND status='FAILED'"
        ).fetchall()
    assert failed == [("RuntimeError",)]
    assert EvidenceRepository(paths).manifest() == evidence


def test_unknown_resume_publishes_new_version_and_preserves_old_generation(copied):
    paths, config, events, evidence = copied

    def unknown(request):
        return {
            "event_type": "UNKNOWN",
            "affected_leg": "UNKNOWN",
            "direction": "UNKNOWN",
            "materiality": "UNKNOWN",
            "relationship_relevance": "UNKNOWN",
            "extraction_confidence": None,
            "citations": [],
        }

    # A new prompt version forces a fresh request identity, preserving existing cache.
    updated = config.model_copy(
        update={
            "agents": config.agents.model_copy(
                update={"extraction_prompt_version": "resume-integration-v1"}
            )
        }
    )
    first = build_event_intelligence(paths, updated, fixture=True, provider=unknown)
    failed_rows = EvidenceRepository(paths).frames(first["event_feature_version"])["extractions"]
    assert failed_rows["status"].eq("UNKNOWN").all()
    second = build_event_intelligence(paths, updated, fixture=True, provider=MockProvider())
    assert first["event_feature_version"] != second["event_feature_version"]
    before = failed_rows.set_index("event_id")
    after = (
        EvidenceRepository(paths)
        .frames(second["event_feature_version"])["extractions"]
        .set_index("event_id")
    )
    changed = after["status"].eq("SUCCESS")
    assert changed.any()
    assert (after.loc[changed, "extraction_id"] != before.loc[changed, "extraction_id"]).all()
    assert EvidenceRepository(paths).manifest(first["event_feature_version"]) == first
    assert EvidenceRepository(paths).manifest(evidence["event_feature_version"]) == evidence
    assert len(after) == len(before)


@pytest.mark.parametrize(
    "kind",
    [
        "coverage",
        "source_selection",
        "quantitative",
        "event_numeric",
        "availability",
        "schema",
        "raw_inventory",
    ],
)
def test_reader_rejects_scientific_inconsistency_even_with_updated_file_checksums(copied, kind):
    paths, config, events, evidence = copied
    if kind in {"coverage", "source_selection"}:
        item = next(entry for entry in evidence["files"] if entry["dataset"] == "evidence_pack")
        path = paths.workspace_root / item["path"]
        pack = json.loads(path.read_bytes())
        if kind == "coverage":
            pack["coverage"]["A"]["status"] = "UNKNOWN"
        else:
            pack["selected_filing_ids"] = []
        path.write_bytes(json_bytes(pack))
        item["sha256"] = sha256_file(path)
    elif kind in {"quantitative", "event_numeric", "availability", "schema"}:
        item = next(entry for entry in evidence["files"] if entry["dataset"] == "model_b_features")
        path = paths.workspace_root / item["path"]
        frame = pq.read_table(path).to_pandas()
        if kind == "quantitative":
            frame.loc[0, "abs_z"] += 0.1
        elif kind == "event_numeric":
            position = frame["extraction_confidence"].first_valid_index()
            frame.loc[position, "extraction_confidence"] += 1e-6
        elif kind == "availability":
            frame.loc[0, "event_available_at"] -= pd.Timedelta(days=1)
        else:
            frame.loc[0, "event_feature_schema_version"] = "forged-schema"
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)
        item["sha256"] = sha256_file(path)
    else:
        evidence["files"] = [
            item for item in evidence["files"] if item["dataset"] != "raw_sec_document"
        ]
    _rewrite_manifest(paths, evidence)
    with pytest.raises(ValueError):
        EvidenceRepository(paths).manifest()
