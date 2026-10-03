"""One explicit ingestion job builds, validates and publishes frozen Phase 1 inputs."""

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from structural_break.common.logging import configure_logging, new_run_id
from structural_break.config.loader import config_hash
from structural_break.config.models import ProjectConfig, RuntimeSettings
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.http import FetchedResponse, HttpClient, SourceError
from structural_break.data.market import (
    VIX_URL,
    build_market_context,
    download_market,
    normalize_actions,
    normalize_prices,
    normalize_vix,
    validate_market,
    validate_market_context,
    validate_vix,
)
from structural_break.data.sec import (
    fetch_company_tickers,
    fetch_submissions,
    normalize_filings,
    parse_json_response,
)
from structural_break.data.snapshots import (
    RawInventory,
    freeze_frames,
    json_bytes,
    lineage,
    verify_snapshot,
    verify_sources,
)
from structural_break.pairs.reference import build_reference, required_tickers
from structural_break.services.foundation import git_revision
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import segment, sha256_file, write_bytes
from structural_break.storage.publication import (
    canonical_aliases,
    publish_catalogue,
    record_quality,
)
from structural_break.storage.registry import Registration, RunRegistry


class DataQualityError(ValueError):
    """A snapshot failed a release-blocking source/data contract."""


def source_id(provider: str, snapshot_id: str) -> str:
    return f"{provider}_{segment(snapshot_id)}"


def _reference(
    paths: ProjectPaths, config: ProjectConfig, raw_manifest: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    entries = raw_manifest["sources"]
    ticker_entry = next(item for item in entries if item["role"] == "sec_ticker_map")
    reference_entry = next(item for item in entries if item["role"] == "reference_config")
    ticker_map = json.loads(
        confined_path(paths.workspace_root, ticker_entry["raw_file_path"]).read_bytes()
    )
    frames = build_reference(
        config,
        confined_path(paths.workspace_root, reference_entry["raw_file_path"]),
        ticker_map,
        source_snapshot_id=ticker_entry["source_snapshot_id"],
        data_snapshot_id=raw_manifest["data_snapshot_id"],
        raw_file_path=ticker_entry["raw_file_path"],
        sha256=ticker_entry["sha256"],
        retrieved_at=datetime.fromisoformat(ticker_entry["retrieved_at_utc"]),
    )
    for frame in frames:
        for key, value in lineage(ticker_entry).items():
            frame[key] = value
        frame["data_snapshot_id"] = raw_manifest["data_snapshot_id"]
        frame["reference_file_path"] = reference_entry["raw_file_path"]
        frame["reference_sha256"] = reference_entry["sha256"]
    return frames


def capture_sources(
    paths: ProjectPaths,
    config: ProjectConfig,
    snapshot_id: str,
    get: Callable[[str], FetchedResponse],
    *,
    start: date,
    end: date,
    downloader: Callable[..., pd.DataFrame | None] | None = None,
    synthetic: bool = False,
    code_revision: str | None = None,
) -> dict[str, Any]:
    inventory = RawInventory(paths, snapshot_id)
    reference = paths.project_root / "configs/securities.yaml"
    inventory.capture_bytes(
        f"raw/reference/{snapshot_id}.yaml",
        FetchedResponse(
            reference.read_bytes(), "project://configs/securities.yaml", 200, datetime.now(UTC)
        ),
        role="reference_config",
        provider="MANUAL_REFERENCE",
        source_snapshot_id=source_id("reference", snapshot_id),
        library_version="config-v1",
    )
    mapping_response = fetch_company_tickers(get)
    mapping_entry = inventory.capture_bytes(
        f"raw/sec/company_tickers/{source_id('sec', snapshot_id)}.json",
        mapping_response,
        role="sec_ticker_map",
        provider="SEC",
        source_snapshot_id=source_id("sec", snapshot_id),
    )
    securities, _, sector_map = build_reference(
        config,
        reference,
        parse_json_response(mapping_response),
        source_snapshot_id=mapping_entry["source_snapshot_id"],
        data_snapshot_id=snapshot_id,
        raw_file_path=mapping_entry["raw_file_path"],
        sha256=mapping_entry["sha256"],
        retrieved_at=mapping_response.retrieved_at,
    )
    tickers = required_tickers(config, reference)
    try:
        raw = download_market(
            tickers, start, end, downloader=downloader, attempts=config.data.source_attempts
        )
    except RuntimeError as error:
        raise SourceError("https://query1.finance.yahoo.com/v8/finance/chart", None) from error
    for ticker, frame in sorted(raw.items()):
        retrieved = pd.Timestamp(frame["retrieved_at_utc"].iloc[0]).to_pydatetime()
        parameters: dict[str, object] = {
            "ticker": ticker,
            "start": start.isoformat(),
            "end_exclusive": (end + timedelta(days=1)).isoformat(),
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
            "repair": False,
            "prepost": False,
        }
        common: dict[str, Any] = {
            "provider": "YAHOO_YFINANCE",
            "source_snapshot_id": source_id("yahoo", snapshot_id),
            "retrieved_at": retrieved,
            "source_url": str(frame["source_url"].iloc[0]),
            "library_version": version("yfinance"),
            "identity": ticker,
            "parameters": parameters,
        }
        inventory.capture_frame(
            f"raw/yahoo/prices/{ticker}/{common['source_snapshot_id']}.parquet",
            frame,
            role="yahoo_prices",
            **common,
        )
        actions = frame.loc[frame["dividends"].ne(0) | frame["stock_splits"].ne(0)].copy()
        inventory.capture_frame(
            f"raw/yahoo/actions/{ticker}/{common['source_snapshot_id']}.parquet",
            actions,
            role="yahoo_actions",
            **common,
        )
    inventory.capture_bytes(
        f"raw/cboe/vix/{source_id('cboe', snapshot_id)}_VIX_History.csv",
        get(VIX_URL),
        role="vix_history",
        provider="CBOE",
        source_snapshot_id=source_id("cboe", snapshot_id),
    )
    ciks = tuple(securities["cik"].tolist())
    for cik, filename, response in fetch_submissions(ciks, start, end, get):
        relative = (
            f"raw/sec/submissions/{cik}/{source_id('sec', snapshot_id)}.json"
            if filename == f"CIK{cik}.json"
            else f"raw/sec/submissions/{cik}/history/{source_id('sec', snapshot_id)}/{filename}"
        )
        inventory.capture_bytes(
            relative,
            response,
            role="sec_submissions",
            provider="SEC",
            source_snapshot_id=source_id("sec", snapshot_id),
            identity=cik,
        )
    metadata: dict[str, object] = {
        "format_version": 1,
        "synthetic": synthetic,
        "created_at": datetime.now(UTC).isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "config_hash": config_hash(config),
        "config_snapshot": config.model_dump(mode="json"),
        "pair_universe_version": config.universe.version,
        "security_reference_version": str(securities["reference_version"].iloc[0]),
        "sector_etfs": sector_map["sector_etf"].tolist(),
        "tickers": list(tickers),
        "code_revision": code_revision or git_revision(paths.project_root),
        "source_library_versions": {
            "yfinance": version("yfinance"),
            "exchange_calendars": version("exchange_calendars"),
        },
    }
    path = inventory.freeze(metadata)
    return json.loads(path.read_bytes())  # type: ignore[no-any-return]


def curate_sources(
    paths: ProjectPaths,
    config: ProjectConfig,
    raw_manifest: dict[str, Any],
    *,
    output_snapshot_id: str | None = None,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, object]]]:
    verify_sources(paths, raw_manifest)
    if raw_manifest["config_hash"] != config_hash(config):
        raise DataQualityError("Raw snapshot configuration differs from current research settings")
    working = dict(raw_manifest)
    if output_snapshot_id is not None:
        working["data_snapshot_id"] = output_snapshot_id
    securities, pairs, sector_map = _reference(paths, config, working)
    start, end = date.fromisoformat(raw_manifest["start"]), date.fromisoformat(raw_manifest["end"])
    raw_prices: dict[str, pd.DataFrame] = {}
    sec_inputs = []
    vix = None
    for entry in working["sources"]:
        path = confined_path(paths.workspace_root, entry["raw_file_path"])
        provenance = lineage(entry)
        provenance["data_snapshot_id"] = working["data_snapshot_id"]
        if entry["role"] == "yahoo_prices":
            frame = pq.read_table(path).to_pandas()
            for key, value in provenance.items():
                frame[key] = value
            raw_prices[entry["identity"]] = frame
        elif entry["role"] == "vix_history":
            vix = normalize_vix(path.read_bytes(), start - timedelta(days=10), end)
            for key, value in provenance.items():
                vix[key] = value
        elif entry["role"] == "sec_submissions":
            sec_inputs.append((entry["identity"], json.loads(path.read_bytes()), provenance))
    if vix is None:
        raise DataQualityError("Official VIX history missing from source snapshot")
    prices = normalize_prices(raw_prices)
    actions = normalize_actions(prices)
    # Action observations have their own immutable native-source file inventory.
    action_entries = {
        entry["identity"]: entry for entry in working["sources"] if entry["role"] == "yahoo_actions"
    }
    for ticker, entry in action_entries.items():
        for key, value in lineage(entry).items():
            if key != "data_snapshot_id":
                actions.loc[actions["ticker"].eq(ticker), key] = value
    context = build_market_context(prices, vix, sector_map["sector_etf"].tolist())
    filings = normalize_filings(sec_inputs, start, end)
    identity = dict(zip(securities["cik"], securities["security_id"], strict=True))
    filings["security_id"] = filings["cik"].map(identity).astype("string")
    if filings["security_id"].isna().any():
        raise DataQualityError("SEC index contains an issuer outside the approved security master")
    frames = {
        "reference/security_master.parquet": securities,
        "reference/pair_universe.parquet": pairs,
        "reference/sector_etf_map.parquet": sector_map,
        "curated/market/prices_daily.parquet": prices,
        "curated/market/corporate_actions.parquet": actions,
        "curated/market/market_context_daily.parquet": context,
        "curated/evidence/sec_filing_index.parquet": filings,
    }
    quality = validate_market(
        prices,
        start,
        end,
        expected_tickers=working["tickers"],
        benchmark_tickers=["SPY", *sector_map["sector_etf"].tolist()],
        max_source_age_days=config.data.source_max_age_days,
        max_missing_session_fraction=config.data.max_missing_session_fraction,
        as_of=datetime.fromisoformat(raw_manifest["created_at"]),
    )
    quality.extend(validate_market_context(context))
    quality.extend(validate_vix(vix, start - timedelta(days=10), end))
    captured_at = datetime.fromisoformat(raw_manifest["created_at"])
    for entry in working["sources"]:
        retrieved = datetime.fromisoformat(entry["retrieved_at_utc"])
        invalid = retrieved.tzinfo is None or retrieved > captured_at
        stale = not invalid and captured_at - retrieved > timedelta(
            days=config.data.source_max_age_days
        )
        if invalid or stale:
            quality.append(
                {
                    "dataset": entry["role"],
                    "check": "source_timestamp" if invalid else "source_freshness",
                    "severity": "FAIL" if invalid else "WARN",
                    "affected_rows": entry["row_count"] or 1,
                    "message": "Invalid source retrieval time"
                    if invalid
                    else "Stale raw retrieval",
                }
            )
    if (vix["vix_observed_at_utc"] > pd.Timestamp(captured_at)).any():
        quality.append(
            {
                "dataset": "market.vix_daily",
                "check": "vix_timestamp",
                "severity": "FAIL",
                "affected_rows": int(
                    (vix["vix_observed_at_utc"] > pd.Timestamp(captured_at)).sum()
                ),
                "message": "VIX observation proxy is after raw snapshot capture",
            }
        )
    missing_acceptance = int((~filings["point_in_time_eligible"]).sum())
    if missing_acceptance:
        quality.append(
            {
                "dataset": "ref.sec_filing_index",
                "check": "missing_acceptance",
                "severity": "WARN",
                "affected_rows": missing_acceptance,
                "message": "Missing/invalid acceptance timestamps retained as ineligible",
            }
        )
    for dataset, frame in frames.items():
        if frame.empty:
            if "corporate_actions" not in dataset:
                quality.append(
                    {
                        "dataset": dataset,
                        "check": "empty_dataset",
                        "severity": "FAIL",
                        "affected_rows": 0,
                        "message": "Required dataset has no rows",
                    }
                )
            continue
        for field in ("data_snapshot_id", "source_snapshot_id", "raw_file_path", "sha256"):
            # Context is a multi-source join with explicit prefixed provenance.
            columns = (
                [field] if field in frame else [c for c in frame if str(c).endswith("_" + field)]
            )
            if not columns or frame[columns].isna().any(axis=None):
                quality.append(
                    {
                        "dataset": dataset,
                        "check": "row_lineage",
                        "severity": "FAIL",
                        "affected_rows": len(frame),
                        "message": f"Missing {field} provenance",
                    }
                )
    for finding in quality:
        if finding["severity"] == "ERROR":
            finding["severity"] = "FAIL"
    for dataset, frame in frames.items():
        quality.append(
            {
                "dataset": dataset,
                "check": "validated_rows",
                "severity": "INFO",
                "affected_rows": len(frame),
                "message": "Source, schema and row-lineage checks completed",
            }
        )
    return frames, quality


def ingest_data(
    paths: ProjectPaths,
    config: ProjectConfig,
    runtime: RuntimeSettings,
    *,
    snapshot_id: str | None = None,
    replay_id: str | None = None,
    fixture: Path | None = None,
) -> dict[str, Any]:
    run_id = new_run_id()
    snapshot_id = segment(
        snapshot_id or "snap_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%SZ") + "_" + run_id[:8]
    )
    logger = configure_logging()
    revision = git_revision(paths.project_root)
    paths.create_directories()
    registry = RunRegistry(DuckDBConnectionFactory(paths.database), paths.workspace_root)
    migrate(registry.factory, paths.migrations)
    registry.start(
        run_id,
        "ingest-data" if replay_id is None else "replay-data",
        config,
        revision,
        snapshot_id,
    )
    logger.info(
        "Data snapshot started",
        extra={
            "run_id": run_id,
            "job": "ingest-data",
            "config_hash": config_hash(config),
            "dataset_version": snapshot_id,
            "stage": "capture",
        },
    )
    try:
        existing = paths.data_path(f"snapshots/{snapshot_id}/manifest.json")
        if existing.exists():
            raise ValueError("Snapshot ID already exists; verify/reuse it or choose a new identity")
        if replay_id:
            with registry.factory.connect() as connection:
                registered = connection.execute(
                    """SELECT manifest_path,checksum FROM ops.dataset_versions
                    WHERE dataset_version=?""",
                    [segment(replay_id)],
                ).fetchone()
            if registered is None:
                raise ValueError("Replay requires a successfully registered frozen snapshot")
            original_path = confined_path(paths.workspace_root, registered[0])
            if sha256_file(original_path) != registered[1]:
                raise ValueError("Registered snapshot manifest checksum mismatch")
            original = json.loads(original_path.read_bytes())
            raw_path = paths.data_path(f"snapshots/{segment(replay_id)}/raw_manifest.json")
            if sha256_file(raw_path) != original["raw_manifest_sha256"]:
                raise ValueError("Raw inventory manifest checksum mismatch")
            raw_manifest = json.loads(raw_path.read_bytes())
            write_bytes(
                paths.data_path(f"snapshots/{snapshot_id}/raw_manifest.json"),
                json_bytes({**raw_manifest, "replayed_from": replay_id}),
            )
        else:
            downloader = None
            start, end = config.data.start, config.data.end
            if fixture:
                from structural_break.data.fixture_sources import FixtureSources

                source = FixtureSources(fixture)
                get = source.get
                downloader = source.download
                start, end = source.start, source.end
            else:
                contact = (
                    runtime.sec_user_agent.get_secret_value() if runtime.sec_user_agent else None
                )
                client = HttpClient(
                    contact,
                    timeout=config.data.source_timeout_seconds,
                    attempts=config.data.source_attempts,
                    sec_requests_per_second=config.data.sec_requests_per_second,
                )
                get = client.get
            raw_manifest = capture_sources(
                paths,
                config,
                snapshot_id,
                get,
                start=start,
                end=end,
                downloader=downloader,
                synthetic=fixture is not None,
                code_revision=revision,
            )
        frames, quality = curate_sources(
            paths, config, raw_manifest, output_snapshot_id=snapshot_id
        )
        if any(check["severity"] == "FAIL" for check in quality):
            report = paths.data_path(f"snapshots/{snapshot_id}/quality_failed.json")
            write_bytes(report, json_bytes(quality))
            with registry.factory.connect(read_only=False) as connection:
                record_quality(connection, quality, snapshot_id, run_id)
            raise DataQualityError(f"Snapshot QA failed; see {report}")
        files = freeze_frames(paths, snapshot_id, frames)
        manifest = {
            **raw_manifest,
            "data_snapshot_id": snapshot_id,
            "curated_files": files,
            "quality": quality,
            "curation_code_revision": revision,
            "run_id": run_id,
            "raw_manifest_path": f"data/snapshots/{snapshot_id}/raw_manifest.json",
            "raw_manifest_sha256": sha256_file(
                paths.data_path(f"snapshots/{snapshot_id}/raw_manifest.json")
            ),
            "vix_context_lag_sessions": 1,
            "replayed_from": replay_id,
            "headline_news_enabled": False,
            "sec_timestamp_coverage": {
                "total": len(frames["curated/evidence/sec_filing_index.parquet"]),
                "eligible": int(
                    frames["curated/evidence/sec_filing_index.parquet"][
                        "point_in_time_eligible"
                    ].sum()
                ),
            },
        }
        manifest_path = write_bytes(existing, json_bytes(manifest))
        verify_snapshot(paths, manifest)
        with canonical_aliases(paths, files):
            registry.finish(
                run_id,
                status="SUCCESS",
                record_count=sum(len(f) for f in frames.values()),
                dataset=Registration("dataset", snapshot_id, manifest_path),
                publish=lambda connection: publish_catalogue(connection, paths, manifest, run_id),
            )
        logger.info(
            "Data snapshot published",
            extra={
                "run_id": run_id,
                "dataset_version": snapshot_id,
                "stage": "complete",
                "status": "SUCCESS",
                "record_count": len(frames["curated/market/prices_daily.parquet"]),
            },
        )
        return manifest
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        failure: dict[str, object] = {
            "run_id": run_id,
            "data_snapshot_id": snapshot_id,
            "status": "FAILED",
            "error_type": type(error).__name__,
            "failed_at_utc": datetime.now(UTC).isoformat(),
        }
        if isinstance(error, SourceError):
            failure.update(source_url=error.url, http_status=error.status_code)
            with registry.factory.connect(read_only=False) as connection:
                provider = (
                    "SEC"
                    if "sec.gov" in error.url
                    else "YAHOO_YFINANCE"
                    if "yahoo.com" in error.url
                    else "CBOE"
                )
                connection.execute(
                    """INSERT INTO ops.source_health
                    VALUES (?, 'FAILED', current_timestamp, NULL, ?, ?)
                    ON CONFLICT(source) DO UPDATE SET
                    status='FAILED',checked_at=excluded.checked_at,
                    run_id=excluded.run_id,error_type=excluded.error_type""",
                    [provider, run_id, type(error).__name__],
                )
        write_bytes(
            paths.data_path(f"snapshots/{snapshot_id}/failures/{run_id}.json"), json_bytes(failure)
        )
        logger.error(
            "Data snapshot failed; prior canonical snapshot retained",
            extra={
                "run_id": run_id,
                "dataset_version": snapshot_id,
                "status": "FAILED",
                "error_type": type(error).__name__,
            },
        )
        raise
