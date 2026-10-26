"""Resumable independent research workspace, causal engines and immutable publication."""

from __future__ import annotations

import importlib
import io
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.common.logging import new_run_id
from structural_break.config.loader import config_hash, load_config
from structural_break.config.models import Pair, ProjectConfig, UniverseConfig
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.econometrics.engine import build_relationship_history
from structural_break.ml.dataset import build_event_dataset
from structural_break.research.market import verify_market_capture
from structural_break.research.protocol import (
    ResearchProtocol,
    canonical_bytes,
    experiment_config,
    identity,
    load_protocol,
    protocol_model,
)
from structural_break.research.universe import verify_universe_freeze
from structural_break.services.foundation import git_revision
from structural_break.storage.database import DuckDBConnectionFactory, migrate
from structural_break.storage.files import sha256_file, write_bytes
from structural_break.storage.registry import Registration, RunRegistry

_WORKER_MARKET: dict[str, pd.DataFrame] = {}


def _initialize_worker(market_directory: str) -> None:
    """A process-local read snapshot; discarded when this pool closes."""
    directory = Path(market_directory)
    _WORKER_MARKET.clear()
    for name in ("prices", "security_master", "market_context"):
        _WORKER_MARKET[name] = pd.read_parquet(directory / f"{name}.parquet")


def frame_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    return buffer.getvalue()


def computational_identity(project: Path) -> dict[str, Any]:
    paths = sorted((project / "src/structural_break").rglob("*.py"))
    return {
        "source_sha256": identity(
            {p.relative_to(project).as_posix(): sha256_file(p) for p in paths}
        ),
        "libraries": {
            name: version(name)
            for name in ("numpy", "pandas", "statsmodels", "scikit-learn", "xgboost", "pyarrow")
        },
    }


def _write_frames(directory: Path, frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    entries = []
    for name, frame in frames.items():
        path = write_bytes(directory / f"{name}.parquet", frame_bytes(frame))
        entries.append(
            {"name": name, "path": path.name, "sha256": sha256_file(path), "rows": len(frame)}
        )
    return entries


def verify_files(directory: Path, manifest: dict[str, Any]) -> None:
    for item in manifest["files"]:
        if sha256_file(confined_path(directory, item["path"])) != item["sha256"]:
            raise ValueError(f"Research artifact checksum mismatch: {item['name']}")


def _pair_dataset(arguments: dict[str, Any]) -> dict[str, Any]:
    # Each pair already has its own worker. Nested BLAS pools inflate runtime
    # and oversubscribe Colab/local CPUs without changing the fitted objective.
    controls = importlib.import_module("threadpoolctl")
    with controls.threadpool_limits(limits=1):
        return _pair_dataset_inner(arguments)


def _pair_dataset_inner(arguments: dict[str, Any]) -> dict[str, Any]:
    """One pair bounds memory; full raw/monthly/daily audits stay available."""
    market = Path(arguments["market_directory"])
    cache = Path(arguments["cache_directory"])
    protocol = protocol_model(arguments["protocol"])
    config = ProjectConfig.model_validate(arguments["config"])
    pair = pd.DataFrame([arguments["pair"]])
    pair_id = str(arguments["pair"]["pair_id"])
    directory = cache / pair_id
    key = arguments["identity"]
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        manifest: dict[str, Any] = json.loads(manifest_path.read_bytes())
        if manifest["identity"] != key:
            raise ValueError("Cached pair computation identity differs")
        verify_files(directory, manifest)
        return manifest
    prices = _WORKER_MARKET.get("prices")
    if prices is None:
        _initialize_worker(str(market))
        prices = _WORKER_MARKET["prices"]
    tickers = (arguments["pair"]["leg_a"], arguments["pair"]["leg_b"])
    prices = prices.loc[prices["ticker"].isin(tickers)].copy()
    prices = prices.loc[pd.to_datetime(prices["trading_date"]).dt.date.le(protocol.development_end)]
    securities = _WORKER_MARKET["security_master"]
    securities = securities.loc[securities["ticker"].isin(tickers)].copy()
    context = _WORKER_MARKET["market_context"]
    context = context.loc[context["sector_etf"].isin(securities["sector_etf"])]
    source_id = str(arguments["data_snapshot_id"])
    relation_id = f"research_relationships_{key[:24]}"
    snapshots, daily, crossings = build_relationship_history(
        prices,
        pair,
        config.econometrics,
        data_snapshot_id=source_id,
        config_hash=config_hash(config),
        start=protocol.fit_start,
        end=protocol.development_end,
        created_at=datetime.fromisoformat(arguments["created_at"]),
    )
    frames = {
        "relationship_snapshots": snapshots,
        "daily_pair_state": daily,
        "raw_crossings": crossings,
    }
    counts: dict[str, Any] = {
        "monthly_attempts": len(snapshots),
        "ACTIVE_months": int(snapshots["pair_status"].eq("ACTIVE").sum()),
        "raw_crossings": len(crossings),
        "horizons": {},
    }
    for horizon in (protocol.primary_horizon, *protocol.sensitivity_horizons):
        horizon_config = experiment_config(config, protocol, config.universe, horizon)
        dataset = build_event_dataset(
            prices,
            pair,
            securities,
            context,
            snapshots,
            daily,
            crossings,
            horizon_config,
            data_snapshot_id=source_id,
            relationship_version=relation_id,
            dataset_version=f"research_events_{key[:24]}_h{horizon}",
            population=protocol.population,
        )
        for name, frame in (
            ("events", dataset.events),
            ("features", dataset.features),
            ("targets", dataset.targets),
            ("partitions", dataset.partitions),
        ):
            frames[f"h{horizon}_{name}"] = frame
        counts["horizons"][str(horizon)] = {
            "events": len(dataset.events),
            "supervised": int(dataset.partitions["supervised_eligible"].sum()),
            "positives": int(dataset.targets["y_revert_success"].fillna(0).sum()),
            "ACTIVE": int(dataset.events["baseline1_eligible"].sum()),
        }
    manifest = {
        "pair_id": pair_id,
        "identity": key,
        "files": _write_frames(directory, frames),
        "counts": counts,
    }
    write_bytes(manifest_path, canonical_bytes(manifest))
    return manifest


def _registered_manifest(paths: ProjectPaths, research_version: str) -> dict[str, Any] | None:
    factory = DuckDBConnectionFactory(paths.database, coordinated=True)
    migrate(factory, paths.migrations)
    with factory.connect() as connection:
        row = connection.execute(
            "SELECT manifest_path,checksum FROM analytics.research_versions "
            "WHERE research_version=?",
            [research_version],
        ).fetchone()
    if row is None:
        return None
    path = confined_path(paths.workspace_root, row[0])
    if sha256_file(path) != row[1]:
        raise ValueError("Registered research manifest changed")
    manifest: dict[str, Any] = json.loads(path.read_bytes())
    verify_files(path.parent, manifest)
    if manifest["research_version"] != research_version:
        raise ValueError("Registered research version does not match its manifest")
    if manifest["stage"] == "registry":
        for filename, field in (
            ("source_freeze.json", "source_freeze_sha256"),
            ("funnel.json", "funnel_sha256"),
        ):
            if sha256_file(path.parent / filename) != manifest[field]:
                raise ValueError("Research source freeze or funnel changed")
        frozen = json.loads((path.parent / "source_freeze.json").read_bytes())
        if frozen["source"] != manifest["source"] or not frozen["final_test_locked"]:
            raise ValueError("Research source freeze content differs")
        for item in manifest["pair_manifests"]:
            pair_directory = confined_path(path.parent / "pairs", item["pair_id"])
            pair_path = pair_directory / "manifest.json"
            if sha256_file(pair_path) != item["sha256"]:
                raise ValueError("Research pair manifest changed")
            pair_manifest = json.loads(pair_path.read_bytes())
            if pair_manifest["pair_id"] != item["pair_id"] or pair_manifest["identity"] != identity(
                manifest["source"]
            ):
                raise ValueError("Research pair source binding differs")
            verify_files(pair_directory, pair_manifest)
        if "inputs" in manifest:
            inputs = {item["role"]: item for item in manifest["inputs"]}
            for item in inputs.values():
                if sha256_file(confined_path(paths.workspace_root, item["path"])) != item["sha256"]:
                    raise ValueError("Research upstream source manifest changed")
            universe_directory = confined_path(
                paths.workspace_root, inputs["universe"]["path"]
            ).parent
            market_directory = confined_path(paths.workspace_root, inputs["market"]["path"]).parent
            verify_universe_freeze(universe_directory)
            verify_market_capture(market_directory, universe_directory)
    return manifest


def publish_research(
    paths: ProjectPaths,
    config: ProjectConfig,
    protocol: ResearchProtocol,
    stage: str,
    research_version: str,
    directory: Path,
    manifest: dict[str, Any],
    frames: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Manifest registration and read views commit together in the separate DB."""
    if stage not in {
        "registry",
        "evaluation",
        "intelligence",
    } or not directory.resolve().is_relative_to(paths.artifacts.resolve()):
        raise ValueError("Research publication must use its own artifacts directory and stage")
    factory = DuckDBConnectionFactory(paths.database, coordinated=True)
    migrate(factory, paths.migrations)
    existing = _registered_manifest(paths, research_version)
    if existing is not None:
        return existing
    pending_path = directory / "manifest.json"
    if pending_path.exists():
        pending: dict[str, Any] = json.loads(pending_path.read_bytes())
        if (
            pending.get("research_version") != research_version
            or pending.get("stage") != stage
            or pending.get("protocol_hash") != identity(protocol.model_dump(mode="json"))
            or any(pending.get(k) != v for k, v in manifest.items())
        ):
            raise ValueError("Unregistered research publication binds different content")
        verify_files(directory, pending)
        with factory.connect() as connection:
            state = connection.execute(
                "SELECT status FROM ops.job_runs WHERE run_id=?", [pending["run_id"]]
            ).fetchone()
        if state != ("FAILED",):
            raise ValueError("Unregistered research publication is not a confirmed failed run")
        digest = sha256_file(pending_path)
        write_bytes(directory / f"unregistered_manifest_{digest}.json", pending_path.read_bytes())
        # This exact file is unregistered, failed, archived and under the checked
        # research artifact root. Immutable scientific data/pair caches remain.
        pending_path.unlink()
    run_id = new_run_id()
    registry = RunRegistry(factory, paths.workspace_root)
    registry.start(
        run_id, f"research-v2-{stage}", config, git_revision(paths.project_root), research_version
    )
    try:
        manifest = {
            **manifest,
            "research_version": research_version,
            "stage": stage,
            "run_id": run_id,
            "protocol": protocol.model_dump(mode="json"),
            "protocol_hash": identity(protocol.model_dump(mode="json")),
            "code_revision": git_revision(paths.project_root),
            "files": _write_frames(directory, frames),
        }
        manifest_path = write_bytes(directory / "manifest.json", canonical_bytes(manifest))

        def publication(connection: Any) -> None:
            relative = manifest_path.relative_to(paths.workspace_root).as_posix()
            connection.execute(
                "INSERT INTO analytics.research_versions VALUES (?,?,?,?,?,?)",
                [
                    research_version,
                    stage,
                    manifest["protocol_hash"],
                    relative,
                    sha256_file(manifest_path),
                    run_id,
                ],
            )
            # Version-specific views preserve P3/P4 aliases. Validate the SQL
            # identifier and escape the confined local path as a SQL literal.
            for name in frames:
                view = f"research_{stage}_{name}_{research_version.rsplit('_', 1)[-1]}"
                if not view.replace("_", "").isalnum():
                    raise ValueError("Invalid research view identifier")
                parquet_literal = str(directory / f"{name}.parquet").replace("'", "''")
                connection.execute(
                    f"CREATE VIEW analytics.{view} AS "
                    f"SELECT * FROM read_parquet('{parquet_literal}')"
                )

        registry.finish(
            run_id,
            status="SUCCESS",
            record_count=sum(len(f) for f in frames.values()),
            artifacts=(Registration(f"research-{stage}", research_version, manifest_path),),
            publish=publication,
        )
        return manifest
    except Exception as error:
        registry.finish(run_id, status="FAILED", error_type=type(error).__name__)
        raise


def build_research_registry(
    paths: ProjectPaths,
    protocol_path: Path,
    universe_directory: Path,
    market_directory: Path,
    *,
    workers: int = 2,
) -> dict[str, Any]:
    if not 1 <= workers <= 4:
        raise ValueError("Use one to four pair workers")
    paths.create_directories()
    protocol = load_protocol(protocol_path)
    universe_manifest = verify_universe_freeze(universe_directory)
    market_manifest = verify_market_capture(market_directory, universe_directory)
    reference = load_config(paths.project_root / "configs")
    pairs = pd.read_parquet(market_directory / "pair_universe.parquet")
    universe = UniverseConfig(
        version="research-v2-survivor-peers",
        orientation="leg_a_is_y",
        pairs=tuple(
            Pair(leg_a=r["leg_a"], leg_b=r["leg_b"], peer_group=r["peer_group"])
            for r in pairs.to_dict("records")
        ),
    )
    config = experiment_config(reference, protocol, universe, protocol.primary_horizon)
    computation = computational_identity(paths.project_root)
    source = {
        "protocol": protocol.model_dump(mode="json"),
        "computation": computation,
        "universe_manifest_sha256": sha256_file(universe_directory / "manifest.json"),
        "market_manifest_sha256": sha256_file(market_directory / "manifest.json"),
        "universe_identity": universe_manifest["freeze_id"],
        "market_identity": market_manifest.get("data_snapshot_id"),
    }
    key = identity(source)
    generation = f"research_registry_{key[:24]}"
    existing = _registered_manifest(paths, generation)
    if existing is not None:
        return existing
    directory = paths.artifacts / "research" / generation
    freeze_path = directory / "source_freeze.json"
    if freeze_path.exists():
        freeze = json.loads(freeze_path.read_bytes())
        if freeze["source"] != source:
            raise ValueError("Research source freeze differs from computation")
    else:
        freeze = {
            "source": source,
            "created_at": datetime.now(UTC).isoformat(),
            "code_revision": git_revision(paths.project_root),
            "final_test_locked": True,
        }
        write_bytes(freeze_path, canonical_bytes(freeze))
    cache = directory / "pairs"
    arguments = [
        {
            "market_directory": str(market_directory),
            "cache_directory": str(cache),
            "protocol": protocol.model_dump(mode="json"),
            "config": config.model_dump(mode="json"),
            "pair": row,
            "identity": key,
            "created_at": freeze["created_at"],
            "data_snapshot_id": market_manifest["data_snapshot_id"],
        }
        for row in pairs.sort_values("pair_id").to_dict("records")
    ]
    manifests = []
    if workers == 1:
        _initialize_worker(str(market_directory))
        results: Any = map(_pair_dataset, arguments)
        for result in results:
            manifests.append(result)
            print(
                json.dumps(
                    {
                        "stage": "registry",
                        "completed_pairs": len(manifests),
                        "total_pairs": len(arguments),
                        "pair_id": result["pair_id"],
                    }
                ),
                flush=True,
            )
    else:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_initialize_worker,
            initargs=(str(market_directory),),
        ) as executor:
            for result in executor.map(_pair_dataset, arguments):
                manifests.append(result)
                print(
                    json.dumps(
                        {
                            "stage": "registry",
                            "completed_pairs": len(manifests),
                            "total_pairs": len(arguments),
                            "pair_id": result["pair_id"],
                        }
                    ),
                    flush=True,
                )
    if computational_identity(paths.project_root) != computation:
        raise ValueError(
            "Source code changed during research computation; publish a new generation"
        )
    frames = {}
    verify_universe_freeze(universe_directory)
    verify_market_capture(market_directory, universe_directory)
    for horizon in (protocol.primary_horizon, *protocol.sensitivity_horizons):
        for name in ("events", "features", "targets", "partitions"):
            field = f"h{horizon}_{name}"
            frames[field] = pd.concat(
                [pd.read_parquet(cache / m["pair_id"] / f"{field}.parquet") for m in manifests],
                ignore_index=True,
            )
    write_bytes(
        directory / "funnel.json",
        canonical_bytes({"pairs": [m["counts"] for m in manifests], "final_test_read": False}),
    )
    manifest = {
        "source": source,
        "inputs": [
            {
                "role": role,
                "path": (location / "manifest.json").relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(location / "manifest.json"),
            }
            for role, location in (("universe", universe_directory), ("market", market_directory))
        ],
        "source_freeze_sha256": sha256_file(freeze_path),
        "pair_manifests": [
            {"pair_id": m["pair_id"], "sha256": sha256_file(cache / m["pair_id"] / "manifest.json")}
            for m in manifests
        ],
        "funnel_sha256": sha256_file(directory / "funnel.json"),
        "final_test_read": False,
    }
    return publish_research(
        paths, config, protocol, "registry", generation, directory, manifest, frames
    )
