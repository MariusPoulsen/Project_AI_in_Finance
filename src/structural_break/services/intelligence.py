"""Explicit SEC batches; immutable evidence/extractions and read-only queries."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from structural_break.config.loader import config_hash
from structural_break.config.models import ProjectConfig, RuntimeSettings
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.http import HttpClient, SourceError
from structural_break.data.snapshots import content_identity, json_bytes
from structural_break.intelligence.event_features import build_event_feature_frame
from structural_break.intelligence.evidence import (
    EvidencePolicy,
    build_evidence_pack,
    cache_filing,
    parse_documents,
    select_event_filings,
)
from structural_break.intelligence.extraction import (
    ExtractionProvider,
    LiteLLMProvider,
    ProviderFailure,
    extract_pack,
    validate_pack,
)
from structural_break.services.foundation import git_revision
from structural_break.services.model_a import (
    ModelARepository,
    UnpublishedVersionError,
    _archive_unregistered,
    _freeze_frames,
    _read_frames,
    ml_computation_identity,
)
from structural_break.services.model_b import model_b_feature_schema
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import segment, sha256_file, write_bytes
from structural_break.storage.model_a import insert_frame
from structural_break.storage.publication import canonical_aliases
from structural_break.storage.registry import Registration, RunRegistry


def evidence_policy(config: ProjectConfig) -> EvidencePolicy:
    settings = config.agents
    return EvidencePolicy(
        version=settings.evidence_policy_version,
        recent_8k_days=settings.recent_8k_days,
        periodic_days=settings.periodic_days,
        periodic_extension_days=settings.periodic_extension_days,
        chunk_chars=settings.chunk_chars,
        max_chunks_per_leg=settings.max_chunks_per_leg,
        max_total_chars=settings.max_evidence_chars,
    )


def _provider_unavailable(request: dict[str, Any]) -> dict[str, Any]:
    raise ProviderFailure("OFFLINE_EXTRACTION_NOT_CACHED", retriable=False)


def extraction_schedule(events: pd.DataFrame) -> list[dict[str, Any]]:
    """Outcome-blind pilot coverage: validation, round-robin train years, final."""
    ordered = events.sort_values(["event_timestamp", "event_id"])
    records = cast(list[dict[str, Any]], ordered.to_dict("records"))
    validation = [row for row in records if row["partition"] == "validation"]
    years: dict[int, list[dict[str, Any]]] = {}
    for row in records:
        if row["partition"] == "train":
            years.setdefault(pd.Timestamp(row["event_timestamp"]).year, []).append(row)
    training = []
    while any(years.values()):
        for year in sorted(years):
            if years[year]:
                training.append(years[year].pop(0))
    remaining = [row for row in records if row["partition"] not in {"train", "validation"}]
    return [*validation, *training, *remaining]


def _publish(
    connection: duckdb.DuckDBPyConnection,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    run_id: str,
) -> None:
    identity = manifest["event_feature_version"]
    path = paths.artifacts / "intelligence" / identity / "manifest.json"
    connection.execute(
        "INSERT INTO analytics.event_intelligence_versions VALUES (?,?,?,?,?)",
        [
            identity,
            manifest["dataset_version"],
            path.relative_to(paths.workspace_root).as_posix(),
            sha256_file(path),
            run_id,
        ],
    )
    for frame, table, columns in (
        (
            "extractions",
            "event_extractions",
            ("event_id", "extraction_id", "event_type", "affected_leg", "status", "evidence_hash"),
        ),
        (
            "model_b_features",
            "model_b_event_features",
            ("event_id", "event_available_at", "evidence_available"),
        ),
        (
            "evidence_packs",
            "evidence_packs",
            ("event_id", "evidence_hash", "coverage_status", "pack_path"),
        ),
    ):
        insert_frame(connection, table, frames[frame], columns, "event_feature_version", identity)
    connection.execute(
        "INSERT INTO ops.active_event_intelligence VALUES (true,?) "
        "ON CONFLICT(singleton) DO UPDATE SET event_feature_version=excluded.event_feature_version",
        [identity],
    )
    chunk_file = next(
        item for item in manifest["files"] if item["dataset"] == "clean_document_chunks"
    )
    chunk_path = (
        confined_path(paths.workspace_root, chunk_file["path"]).as_posix().replace("'", "''")
    )
    connection.execute(
        f"CREATE OR REPLACE VIEW ref.document_chunks AS SELECT * FROM read_parquet('{chunk_path}')"
    )


def _source_filings(paths: ProjectPaths, parent: dict[str, Any]) -> pd.DataFrame:
    from structural_break.data.snapshots import verify_snapshot

    path = paths.data / "snapshots" / parent["data_snapshot_id"] / "manifest.json"
    with DuckDBConnectionFactory(paths.database).connect() as connection:
        registered = connection.execute(
            "SELECT checksum FROM ops.dataset_versions WHERE dataset_version=?",
            [parent["data_snapshot_id"]],
        ).fetchone()
    if registered is None or sha256_file(path) != registered[0]:
        raise ValueError("Frozen SEC metadata snapshot manifest is not registered or changed")
    manifest: dict[str, Any] = json.loads(path.read_bytes())
    verify_snapshot(paths, manifest)
    if manifest["data_snapshot_id"] != parent["data_snapshot_id"]:
        raise ValueError("SEC source differs from the event's frozen snapshot")
    entry = next(
        item
        for item in manifest["curated_files"]
        if item["dataset"] == "curated/evidence/sec_filing_index.parquet"
    )
    return pd.DataFrame(
        pq.read_table(confined_path(paths.workspace_root, entry["path"])).to_pandas()
    )


def build_event_intelligence(
    paths: ProjectPaths,
    config: ProjectConfig,
    runtime: RuntimeSettings | None = None,
    *,
    dataset_version: str | None = None,
    event_feature_version: str | None = None,
    fixture: bool = False,
    offline: bool = False,
    sec_retry_attempt: str | None = None,
    provider: ExtractionProvider | None = None,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Retain every parent event; UNKNOWN evidence is data, never an exclusion."""
    from structural_break.common.logging import configure_logging, new_run_id

    paths.create_directories()
    factory = DuckDBConnectionFactory(paths.database)
    migrate(factory, paths.migrations)
    parent = ModelARepository(paths).dataset_manifest(dataset_version)
    parent_frames = _read_frames(paths, parent)
    events = parent_frames["divergence_events"].copy()
    if bool(parent["synthetic"]) != fixture:
        raise ValueError("Synthetic evidence fixtures require a synthetic event dataset")
    run_id = new_run_id()
    registry = RunRegistry(factory, paths.workspace_root)
    revision = git_revision(paths.project_root)
    registry.start(run_id, "build-intelligence", config, revision, parent["dataset_version"])
    try:
        policy = evidence_policy(config)
        runtime = runtime or RuntimeSettings()
        supplemental_manifest: dict[str, Any] | None = None
        if fixture:
            from structural_break.intelligence.fixtures import MockProvider, make_evidence_fixture

            filing_index, get = make_evidence_fixture(events, paths)
            provider = provider or MockProvider()
            provider_name, model_name = "mock", "deterministic-sec-fixture-v1"
        else:
            filing_index = _source_filings(paths, parent)
            agent = runtime.sec_user_agent.get_secret_value() if runtime.sec_user_agent else None
            get = HttpClient(
                agent,
                timeout=config.data.source_timeout_seconds,
                attempts=config.data.source_attempts,
                sec_requests_per_second=config.data.sec_requests_per_second,
            ).get
            from structural_break.data.sec_identity import (
                apply_reviewed_sec_identities,
                recover_historical_sec_index,
            )

            try:
                supplemental, supplemental_manifest = recover_historical_sec_index(
                    paths,
                    config,
                    get,
                    parent_snapshot_id=parent["data_snapshot_id"],
                    offline=offline,
                )
                filing_index = pd.concat([filing_index, supplemental], ignore_index=True)
            except (FileNotFoundError, SourceError):
                # A failed administrative recovery remains missing evidence; it does not
                # erase the source gap or remove a difficult event from the cohort.
                supplemental_manifest = None
            filing_index = apply_reviewed_sec_identities(filing_index)
            provider_name = provider_name or runtime.llm_provider or config.agents.provider
            model_name = model_name or runtime.llm_model or config.agents.model
            if not provider_name or not model_name:
                raise ValueError(
                    "Live or cached extraction requires declared provider/model aliases"
                )
            if provider is None:
                if offline:
                    provider = _provider_unavailable
                else:
                    if not runtime.llm_api_key:
                        raise ValueError("Set SB_LLM_API_KEY locally before live extraction")
                    # The SDK reads this secret through the injected completion wrapper;
                    # it never enters requests, cache identities or serialized config.
                    import importlib

                    sdk = cast(Any, importlib.import_module("litellm"))
                    sdk.telemetry = False

                    def completion(**kwargs: Any) -> Any:
                        assert runtime is not None and runtime.llm_api_key is not None
                        return sdk.completion(
                            api_key=runtime.llm_api_key.get_secret_value(), **kwargs
                        )

                    alias = str(model_name)
                    if "/" not in alias:
                        alias = f"{provider_name}/{alias}"
                    provider = LiteLLMProvider(
                        alias,
                        min_interval_seconds=config.agents.extraction_min_interval_seconds,
                        max_calls=config.agents.extraction_max_calls,
                        completion=completion,
                    )
        assert provider is not None
        if offline:
            provider = _provider_unavailable
        selected_by_event: dict[str, list[dict[str, Any]]] = {}
        coverage_by_event: dict[str, Any] = {}
        all_filings: dict[str, dict[str, Any]] = {}
        for event in cast(list[dict[str, Any]], events.to_dict("records")):
            # P1 uses US:ticker; the independent market fixture uses plain tickers.
            legs = str(event["pair_id"]).split("__")
            if not fixture:
                legs = [f"US:{ticker}" for ticker in legs]
            selected, coverage = select_event_filings(
                event,
                filing_index,
                legs,
                policy,
            )
            selected_by_event[event["event_id"]] = selected
            coverage_by_event[event["event_id"]] = coverage
            for filing in selected:
                key = f"{filing['security_id']}:{filing['filing_id']}"
                all_filings[key] = filing
        documents: list[dict[str, Any]] = []
        logger = configure_logging()
        for number, filing in enumerate(all_filings.values(), 1):
            documents.extend(
                cache_filing(paths, filing, get, offline=offline, attempt_id=sec_retry_attempt)
            )
            if number % 25 == 0 or number == len(all_filings):
                logger.info(
                    "SEC document cache progress",
                    extra={
                        "stage": "cache",
                        "record_count": number,
                        "total_filings": len(all_filings),
                        "status": "RUNNING",
                    },
                )
        chunks = parse_documents(documents, policy)
        packs: list[dict[str, Any]] = []
        extractions = []
        for event in extraction_schedule(events):
            pack: dict[str, Any] = dict(
                build_evidence_pack(
                    event,
                    selected_by_event[event["event_id"]],
                    chunks,
                    coverage_by_event[event["event_id"]],
                    policy,
                )
            )
            pack["synthetic"] = fixture
            validate_pack(pack)
            extraction = extract_pack(
                pack,
                provider,
                paths.data / "cache",
                provider_name=str(provider_name),
                model_name=str(model_name),
                prompt_version=config.agents.extraction_prompt_version,
                max_retries=config.agents.max_retries,
                timeout_seconds=config.agents.timeout_seconds,
                synthetic=fixture,
                provider_config={"max_tokens": config.agents.extraction_max_output_tokens},
            )
            packs.append(pack)
            extractions.append(extraction)
        packs.sort(key=lambda item: (item["event_timestamp"], item["event_id"]))
        extractions.sort(key=lambda item: (item["event_timestamp"], item["event_id"]))
        extracted = pd.DataFrame(extractions)
        block = build_event_feature_frame(events, extracted, parent["dataset_version"])
        features = parent_frames["event_features"].merge(
            block[
                [
                    "event_id",
                    *[name for name in block if name not in parent_frames["event_features"]],
                ]
            ],
            on="event_id",
            validate="one_to_one",
        )
        schema = model_b_feature_schema(parent["feature_schema"])
        features["feature_schema_version"] = schema["version"]
        identity = {
            "dataset_version": parent["dataset_version"],
            "data_snapshot_id": parent["data_snapshot_id"],
            "relationship_version": parent["relationship_version"],
            "config_hash": config_hash(config),
            "computation_identity": ml_computation_identity(),
            "evidence_policy": asdict(policy),
            "extraction_provider": str(provider_name),
            "extraction_model": str(model_name),
            "extraction_prompt_version": config.agents.extraction_prompt_version,
            "evidence_hashes": [pack["evidence_hash"] for pack in packs],
            "extraction_ids": extracted["extraction_id"].tolist(),
        }
        version = segment(
            event_feature_version or "event_intelligence_" + content_identity(identity)[:24]
        )
        with factory.connect() as connection:
            exists = connection.execute(
                "SELECT count(*) FROM analytics.event_intelligence_versions "
                "WHERE event_feature_version=?",
                [version],
            ).fetchone()
        if exists and exists[0]:
            existing = EvidenceRepository(paths).manifest(version)
            if any(existing.get(key) != value for key, value in identity.items()):
                raise ValueError(
                    "Evidence generation identity conceals changed input or extraction"
                )
            registry.finish(run_id, status="SUCCESS", record_count=len(features))
            return existing
        destination = paths.artifacts / "intelligence" / version
        _archive_unregistered(paths, destination, run_id)
        pack_index = []
        raw_inventory: dict[str, str] = {}
        for pack in packs:
            path = write_bytes(
                destination / "packs" / f"{segment(pack['event_id'])}.json", json_bytes(pack)
            )
            pack_index.append(
                {
                    "event_id": pack["event_id"],
                    "evidence_hash": pack["evidence_hash"],
                    "coverage_status": pack.get("coverage_status", "UNKNOWN"),
                    "pack_path": path.relative_to(paths.workspace_root).as_posix(),
                }
            )
        for document in documents:
            relative = document.get("raw_file_path")
            if relative and document.get("sha256"):
                raw_inventory[str(relative)] = str(document["sha256"])
        frames = {
            "model_b_features": features,
            "extractions": extracted,
            "evidence_packs": pd.DataFrame(pack_index),
            "document_chunks": chunks,
            "clean_document_chunks": chunks.loc[
                chunks["status"].eq("OK") & chunks["chunk_id"].notna()
            ].reset_index(drop=True),
            "filing_index": filing_index,
            "documents": pd.DataFrame(
                [
                    {key: value for key, value in document.items() if key != "local_path"}
                    for document in documents
                ]
            ),
        }
        files = _freeze_frames(paths, destination, frames)
        for item in pack_index:
            files.append(
                {
                    "dataset": "evidence_pack",
                    "path": item["pack_path"],
                    "sha256": sha256_file(confined_path(paths.workspace_root, item["pack_path"])),
                }
            )
        for extraction in extractions:
            response_path = write_bytes(
                destination / "extractions" / f"{segment(extraction['event_id'])}.json",
                json_bytes(extraction),
            )
            files.append(
                {
                    "dataset": "extraction_response",
                    "path": response_path.relative_to(paths.workspace_root).as_posix(),
                    "sha256": sha256_file(response_path),
                }
            )
        files.extend(
            {"dataset": "raw_sec_document", "path": path, "sha256": sha}
            for path, sha in sorted(raw_inventory.items())
        )
        if supplemental_manifest is not None:
            supplemental_path = confined_path(
                paths.workspace_root, supplemental_manifest["manifest_path"]
            )
            files.append(
                {
                    "dataset": "sec_identity_manifest",
                    "path": supplemental_manifest["manifest_path"],
                    "sha256": sha256_file(supplemental_path),
                }
            )
            files.extend(
                {"dataset": "sec_identity_source", **item}
                for item in supplemental_manifest["files"]
            )
        parent_path = paths.artifacts / "events" / parent["dataset_version"] / "manifest.json"
        manifest = {
            **identity,
            "event_feature_version": version,
            "synthetic": fixture,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "code_revision": revision,
            "run_id": run_id,
            "config_snapshot": config.model_dump(mode="json"),
            "feature_schema": schema,
            "files": files,
            "parent_event_manifest": {
                "path": parent_path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(parent_path),
            },
            "upstream_event_manifest_sha256": sha256_file(parent_path),
            "counts": {name: len(frame) for name, frame in frames.items()},
            "extraction_status_counts": extracted["status"].value_counts().to_dict(),
            "final_test_outcomes_computed": False,
            "confidence_meaning": "Provider self-reported certainty, not calibrated accuracy",
            "extraction_schedule": "validation-then-training-year-round-robin-final-last-v1",
            "supplemental_sec_source": supplemental_manifest,
        }
        _verify_scientific_content(paths, manifest)
        path = write_bytes(destination / "manifest.json", json_bytes(manifest))
        chunk_file = next(item for item in files if item["dataset"] == "clean_document_chunks")
        with canonical_aliases(
            paths, [{**chunk_file, "dataset": "curated/evidence/document_chunks.parquet"}]
        ):
            registry.finish(
                run_id,
                status="SUCCESS",
                record_count=len(events),
                artifacts=(Registration("event-intelligence", version, path),),
                publish=lambda connection: _publish(connection, paths, manifest, frames, run_id),
            )
        configure_logging().info(
            "Event intelligence published", extra={"run_id": run_id, "status": "SUCCESS"}
        )
        return manifest
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        raise


def _verify_scientific_content(paths: ProjectPaths, manifest: dict[str, Any]) -> None:
    """Reconstruct citations/features from the immutable sources without an LLM."""
    from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
    from structural_break.intelligence.extraction import validate_stored_extraction
    from structural_break.services.model_b import merge_model_b_rows
    from structural_break.storage.relationships import payload_json

    frames = _read_frames(paths, manifest)
    parent = ModelARepository(paths).dataset_manifest(manifest["dataset_version"])
    parent_frames = _read_frames(paths, parent)
    events = parent_frames["divergence_events"]
    ids = set(events["event_id"])
    for name in ("model_b_features", "extractions", "evidence_packs"):
        frame = frames[name]
        if frame["event_id"].duplicated().any() or set(frame["event_id"]) != ids:
            raise ValueError("SEC intelligence changed the event cohort")
    schema = model_b_feature_schema(parent["feature_schema"])
    if manifest["feature_schema"] != schema:
        raise ValueError("Model B schema differs from its frozen quantitative parent")
    merge_model_b_rows(parent_frames, frames["model_b_features"], schema)
    policy = EvidencePolicy(**manifest["evidence_policy"])
    if manifest["synthetic"]:
        from structural_break.intelligence.fixtures import make_evidence_fixture

        source_index, _ = make_evidence_fixture(events, paths)
    else:
        from structural_break.data.sec_identity import apply_reviewed_sec_identities

        source_index = _source_filings(paths, parent)
        extra = manifest.get("supplemental_sec_source")
        if extra is not None:
            source_index = pd.concat(
                [
                    source_index,
                    pd.read_parquet(
                        confined_path(paths.workspace_root, extra["curated_filing_index_path"])
                    ),
                ],
                ignore_index=True,
            )
        source_index = apply_reviewed_sec_identities(source_index)
    try:
        pd.testing.assert_frame_equal(
            frames["filing_index"], source_index, check_dtype=False, check_index_type=False
        )
    except AssertionError as error:
        raise ValueError("Stored SEC index differs from the frozen source metadata") from error
    raw_inventory = {
        item["path"]: item["sha256"]
        for item in manifest["files"]
        if item["dataset"] == "raw_sec_document"
    }
    for chunk in frames["document_chunks"].to_dict("records"):
        if (
            chunk["status"] == "OK"
            and raw_inventory.get(str(chunk["raw_file_path"])) != chunk["sha256"]
        ):
            raise ValueError("SEC chunk raw provenance is absent from the verified inventory")
    documents = []
    for original in frames["documents"].to_dict("records"):
        document = json.loads(payload_json(original))
        raw = document.get("raw_file_path")
        if raw:
            document["local_path"] = str(confined_path(paths.workspace_root, raw))
        documents.append(document)
    reparsed = parse_documents(documents, policy)
    try:
        pd.testing.assert_frame_equal(frames["document_chunks"], reparsed, check_dtype=False)
        pd.testing.assert_frame_equal(
            frames["clean_document_chunks"],
            reparsed.loc[reparsed["status"].eq("OK") & reparsed["chunk_id"].notna()].reset_index(
                drop=True
            ),
            check_dtype=False,
        )
    except AssertionError as error:
        raise ValueError("SEC chunks differ from parsing their immutable raw sources") from error
    response_files = [
        item for item in manifest["files"] if item["dataset"] == "extraction_response"
    ]
    responses = [
        json.loads(confined_path(paths.workspace_root, item["path"]).read_bytes())
        for item in response_files
    ]
    response_index = {row["event_id"]: row for row in responses}
    if len(responses) != len(ids) or set(response_index) != ids:
        raise ValueError("Stored extraction responses differ from the event cohort")
    pack_index = frames["evidence_packs"].set_index("event_id")
    for event in cast(list[dict[str, Any]], events.to_dict("records")):
        legs = str(event["pair_id"]).split("__")
        if not manifest["synthetic"]:
            legs = [f"US:{ticker}" for ticker in legs]
        selected, coverage = select_event_filings(event, source_index, legs, policy)
        expected = build_evidence_pack(event, selected, reparsed, coverage, policy)
        expected["synthetic"] = manifest["synthetic"]
        row = pack_index.loc[event["event_id"]]
        pack = json.loads(confined_path(paths.workspace_root, str(row["pack_path"])).read_bytes())
        if (
            json_bytes(expected) != json_bytes(pack)
            or row["evidence_hash"] != pack["evidence_hash"]
        ):
            raise ValueError("Evidence pack differs from deterministic source selection")
        response = response_index[event["event_id"]]
        if (
            response["provider_name"] != manifest["extraction_provider"]
            or response["model_name"] != manifest["extraction_model"]
            or bool(response["synthetic"]) != bool(manifest["synthetic"])
        ):
            raise ValueError("Extraction provider or synthetic lineage differs")
        validate_stored_extraction(pack, response)
    response_frame = pd.DataFrame(responses).sort_values("event_id").reset_index(drop=True)
    stored = frames["extractions"].sort_values("event_id").reset_index(drop=True)
    if [payload_json(row) for row in stored.to_dict("records")] != [
        payload_json(row) for row in response_frame.to_dict("records")
    ]:
        raise ValueError("Extraction table differs from the validated provider responses")
    rebuilt = build_event_feature_frame(events, responses, parent["dataset_version"]).set_index(
        "event_id"
    )
    features = frames["model_b_features"].set_index("event_id").reindex(rebuilt.index)
    event_columns = [
        *EVENT_FEATURE_NAMES,
        "event_available_at",
        "event_feature_schema_version",
    ]
    try:
        pd.testing.assert_frame_equal(
            features[event_columns],
            rebuilt[event_columns],
            check_dtype=False,
        )
    except AssertionError as error:
        raise ValueError(
            "Model B event features differ from stored structured extractions"
        ) from error


class EvidenceRepository:
    """Every read binds the P3 parent and verifies immutable evidence bytes."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.factory = DuckDBConnectionFactory(paths.database)

    def manifest(
        self, event_feature_version: str | None = None, *, verify: bool = True
    ) -> dict[str, Any]:
        try:
            with self.factory.connect() as connection:
                if event_feature_version is None:
                    row = connection.execute(
                        "SELECT v.manifest_path,v.checksum,v.event_feature_version "
                        "FROM ops.active_event_intelligence a "
                        "JOIN analytics.event_intelligence_versions v "
                        "ON a.event_feature_version=v.event_feature_version WHERE singleton"
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT manifest_path,checksum,event_feature_version "
                        "FROM analytics.event_intelligence_versions WHERE event_feature_version=?",
                        [event_feature_version],
                    ).fetchone()
        except duckdb.CatalogException as error:
            raise UnpublishedVersionError("No published SEC intelligence generation") from error
        if row is None:
            raise UnpublishedVersionError("No published SEC intelligence generation")
        path = confined_path(self.paths.workspace_root, row[0])
        if sha256_file(path) != row[1]:
            raise ValueError("SEC intelligence manifest checksum mismatch")
        manifest: dict[str, Any] = json.loads(path.read_bytes())
        if (
            manifest["event_feature_version"] != row[2]
            or manifest.get("final_test_outcomes_computed") is not False
        ):
            raise ValueError("Evidence identity or final-test lock mismatch")
        if verify:
            parent = ModelARepository(self.paths).dataset_manifest(manifest["dataset_version"])
            reference = manifest["parent_event_manifest"]
            if (
                sha256_file(confined_path(self.paths.workspace_root, reference["path"]))
                != reference["sha256"]
            ):
                raise ValueError("Evidence parent manifest changed")
            if bool(parent["synthetic"]) != bool(manifest["synthetic"]):
                raise ValueError("Synthetic evidence/data mismatch")
            for name in ("data_snapshot_id", "relationship_version"):
                if manifest[name] != parent[name]:
                    raise ValueError("SEC intelligence parent source identity mismatch")
            for item in manifest["files"]:
                if (
                    sha256_file(confined_path(self.paths.workspace_root, item["path"]))
                    != item["sha256"]
                ):
                    raise ValueError("SEC evidence artifact checksum mismatch")
                if item["dataset"] == "evidence_pack":
                    validate_pack(
                        json.loads(
                            confined_path(self.paths.workspace_root, item["path"]).read_bytes()
                        )
                    )
            _verify_scientific_content(self.paths, manifest)
        return manifest

    def active_manifest(self) -> dict[str, Any]:
        return self.manifest()

    def frames(self, event_feature_version: str | None = None) -> dict[str, pd.DataFrame]:
        manifest = self.manifest(event_feature_version)
        return {
            item["dataset"]: pd.DataFrame(
                pq.read_table(confined_path(self.paths.workspace_root, item["path"])).to_pandas()
            )
            for item in manifest["files"]
            if item["dataset"]
            in {"model_b_features", "extractions", "evidence_packs", "document_chunks"}
        }
