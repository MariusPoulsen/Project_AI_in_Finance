"""Explicit research-v2 batch commands in a separate, final-test-locked workspace."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.config.loader import load_config
from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths, confined_path, find_project_root
from structural_break.data.http import HttpClient
from structural_break.data.sec import COMPANY_TICKERS_URL
from structural_break.intelligence.gemma import GemmaProvider
from structural_break.intelligence.sentiment import (
    LEGACY_PREPROCESSING_VERSION,
    QUALITY_PREPROCESSING_VERSION,
    FinBERTPolicy,
    HuggingFaceFinBERT,
)
from structural_break.research.intelligence import build_event_intelligence, collect_sec_metadata
from structural_break.research.market import collect_market
from structural_break.research.model_job import train_research_models, verify_research_models
from structural_break.research.protocol import ResearchProtocol, identity, load_protocol
from structural_break.research.runner import _registered_manifest, build_research_registry
from structural_break.research.scheduling import DEFAULT_CATALYST_EVENTS
from structural_break.research.universe import freeze_universe
from structural_break.storage.files import segment

_COMMANDS = (
    "freeze-universe",
    "capture-market",
    "collect-sec",
    "build-registry",
    "build-intelligence",
    "audit-checkpoints",
    "train-models",
    "verify-models",
    "promote-primary",
)


def evidence_events(
    paths: ProjectPaths, registry_version: str
) -> tuple[pd.DataFrame, dict[str, Any], ResearchProtocol]:
    """Union fixed pair/UTC cutoffs across horizons, without decoding targets.

    Only the two allowlisted event metadata columns are read from registered
    Parquet bytes. Evidence identities do not include horizons, labels, scores or
    eventual resolutions, so shared pair/time observations use one source pack.
    """
    segment(registry_version)
    parent = _registered_manifest(paths, registry_version)
    if parent is None or parent["stage"] != "registry":
        raise ValueError("Evidence collection requires a successfully registered research registry")
    protocol = ResearchProtocol.model_validate(parent["protocol"])
    directory = paths.artifacts / "research" / registry_version
    frames = []
    for horizon in (protocol.primary_horizon, *protocol.sensitivity_horizons):
        name = f"h{horizon}_events"
        entries = [item for item in parent["files"] if item["name"] == name]
        if len(entries) != 1:
            raise ValueError("Registered research horizon must have one event inventory")
        item = entries[0]
        body = confined_path(directory, item["path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("Registered research event bytes changed before metadata projection")
        frame = pd.read_parquet(io.BytesIO(body), columns=["pair_id", "event_timestamp"])
        for value in frame["event_timestamp"]:
            stamp = pd.Timestamp(value)
            if pd.isna(stamp) or stamp.tzinfo is None:
                raise ValueError(
                    "Research evidence event timestamps must be explicit timezone-aware"
                )
            if not protocol.fit_start <= stamp.tz_convert("UTC").date() <= protocol.development_end:
                raise ValueError(
                    "Research evidence event is outside the frozen development history"
                )
        frame["event_timestamp"] = pd.to_datetime(frame["event_timestamp"], utc=True)
        frames.append(frame)
    events = pd.concat(frames, ignore_index=True).drop_duplicates(["pair_id", "event_timestamp"])
    if events.empty:
        raise ValueError("No development events are available for research evidence")
    if events["pair_id"].isna().any() or events["pair_id"].astype(str).eq("").any():
        raise ValueError("Research evidence requires a fixed nonempty pair identity")
    events = events.sort_values(["event_timestamp", "pair_id"]).reset_index(drop=True)
    events["event_timestamp"] = events["event_timestamp"].map(lambda value: value.isoformat())
    events["event_id"] = [
        "research_evidence_"
        + identity({"pair_id": row.pair_id, "timestamp": row.event_timestamp})[:24]
        for row in events.itertuples(index=False)
    ]
    events["evidence_cutoff"] = events["event_timestamp"]
    return events[["event_id", "pair_id", "event_timestamp", "evidence_cutoff"]], parent, protocol


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=_COMMANDS)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--universe-config", type=Path)
    parser.add_argument(
        "--sec-source", default="source_v3", help="Immutable SEC metadata source version"
    )
    parser.add_argument(
        "--sec-directory", type=Path, help="Exact SEC company directory JSON for freeze"
    )
    parser.add_argument("--registry-version", help="Explicit successfully registered event version")
    parser.add_argument(
        "--model-version", help="Explicit successfully registered evaluation version"
    )
    parser.add_argument("--batch-name", help="New immutable intelligence batch directory name")
    parser.add_argument("--resume-audit", type=Path, help="Previously verified checkpoint audit")
    parser.add_argument("--resume-audit-sha256", help="Exact checksum of the checkpoint audit")
    parser.add_argument("--checkpoint-source", type=Path, help="Preserved partial batch to audit")
    parser.add_argument(
        "--checkpoint-baseline", type=Path, help="Frozen checkpoint inventory receipt"
    )
    parser.add_argument("--checkpoint-baseline-sha256", help="Exact baseline receipt checksum")
    parser.add_argument("--audit-output", type=Path, help="New immutable checkpoint audit receipt")
    parser.add_argument("--progress-file", type=Path, help="Atomic operational progress JSON file")
    parser.add_argument(
        "--pipeline-receipt", type=Path, help="Completed, verified three-horizon pipeline receipt"
    )
    parser.add_argument(
        "--ci-gate", type=Path, help="Exact hosted CI evidence bound by the receipt"
    )
    parser.add_argument(
        "--workers", type=int, default=2, choices=range(1, 5), help="Registry workers only"
    )
    parser.add_argument(
        "--source-prefetch",
        type=int,
        choices=(0, 1),
        default=0,
        help="Overlap one next-event SEC source preparation with current-event inference",
    )
    parser.add_argument("--horizon", type=int)
    parser.add_argument(
        "--max-events", type=int, help="Explicit partial source/inference inventory"
    )
    parser.add_argument(
        "--catalyst-max-events",
        type=int,
        default=DEFAULT_CATALYST_EVENTS,
        help="Target-blind year/business-group Gemma pilot limit (default 500)",
    )
    parser.add_argument("--max-issuers", type=int, help="Explicit partial SEC metadata inventory")
    parser.add_argument("--tickers", nargs="+", help="Explicit source dry-run ticker subset")
    parser.add_argument(
        "--offline", action="store_true", help="Use previously cached SEC source bytes"
    )
    parser.add_argument(
        "--download-model", action="store_true", help="Acquire public pinned FinBERT assets"
    )
    parser.add_argument(
        "--sentiment-preprocessing",
        choices=(LEGACY_PREPROCESSING_VERSION, QUALITY_PREPROCESSING_VERSION),
        default=QUALITY_PREPROCESSING_VERSION,
        help="Versioned FinBERT sentence policy; legacy captures remain independently readable",
    )
    parser.add_argument(
        "--no-gemma", action="store_true", help="Explicit FinBERT-only source batch"
    )
    parser.add_argument(
        "--no-finbert", action="store_true", help="Explicit Gemma-only source batch"
    )
    return parser


def _progress(record: dict[str, Any]) -> None:
    print(json.dumps(record, sort_keys=True, allow_nan=False), flush=True)


class _FileProgress:
    """Best-effort operational status; stdout remains the authoritative job log."""

    def __init__(self, path: Path, command: str, batch: str | None) -> None:
        self.path = path.resolve()
        if self.path.exists():
            raise ValueError("A detached run requires a new progress file")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, Any] = {
            "schema_version": "research-job-progress-v1",
            "command": command,
            "batch_name": batch,
            "pid": os.getpid(),
            "started_at_utc": datetime.now(UTC).isoformat(),
            "completed_checkpoint_count": 0,
            "final_test_unlocked": False,
        }
        self({"status": "STARTING"})

    def __call__(self, record: dict[str, Any]) -> None:
        _progress(record)
        self.state.update(record)
        self.state["observed_at_utc"] = datetime.now(UTC).isoformat()
        if record.get("stage") == "EVENT_INTELLIGENCE":
            self.state["status"] = "RUNNING"
            self.state["completed_checkpoint_count"] = max(
                self.state["completed_checkpoint_count"], record["completed"]
            )
        if record.get("stage") == "CHECKPOINT_AUDIT_APPLIED":
            self.state["status"] = "RUNNING"
        temporary = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(self.state, sort_keys=True, indent=2, allow_nan=False), encoding="utf-8"
            )
            temporary.replace(self.path)
        except OSError as error:
            # A transient status-file lock must not stop canonical computation.
            print(
                json.dumps({"status": "PROGRESS_WRITE_FAILED", "error_type": type(error).__name__}),
                file=sys.stderr,
                flush=True,
            )


def run_command(
    args: argparse.Namespace,
    paths: ProjectPaths,
    runtime: RuntimeSettings,
    progress: Any = None,
) -> dict[str, Any]:
    """Dispatch one authorized job; no implicit next-stage execution or final run."""
    protocol_path = args.protocol or paths.project_root / "configs/research_v2.yaml"
    protocol = load_protocol(protocol_path)
    universe_directory = confined_path(paths.workspace_root, "universe/source_v1")
    market_directory = confined_path(paths.workspace_root, "market/source_v1")
    sec_directory = confined_path(paths.workspace_root, f"sec_metadata/{segment(args.sec_source)}")
    contact = runtime.sec_user_agent.get_secret_value() if runtime.sec_user_agent else None
    progress_callback = progress or _progress
    if args.command == "promote-primary":
        if args.pipeline_receipt is None:
            raise ValueError("promote-primary requires an explicit --pipeline-receipt")
        if args.ci_gate is None:
            raise ValueError("promote-primary requires explicit --ci-gate evidence")
        from structural_break.research.primary import promote_primary_research

        return promote_primary_research(paths, args.pipeline_receipt, ci_gate=args.ci_gate)
    if args.command == "freeze-universe":
        source = (
            args.sec_directory.read_bytes()
            if args.sec_directory
            else HttpClient(contact).get(COMPANY_TICKERS_URL).body
        )
        return freeze_universe(
            args.universe_config or paths.project_root / "configs/research_v2_universe.yaml",
            load_config(paths.project_root / "configs"),
            source,
            universe_directory,
        )
    if args.command == "capture-market":
        return collect_market(
            universe_directory,
            market_directory,
            protocol.data_start,
            protocol.development_end,
            tickers=args.tickers,
            progress=progress_callback,
        )
    if args.command == "collect-sec":
        return collect_sec_metadata(
            universe_directory,
            sec_directory,
            protocol.data_start,
            protocol.development_end,
            max_issuers=args.max_issuers,
            sec_user_agent=contact,
            progress=progress_callback,
        )
    if args.command == "build-registry":
        return build_research_registry(
            paths, protocol_path, universe_directory, market_directory, workers=args.workers
        )
    if args.command == "verify-models":
        if not args.model_version:
            raise ValueError("verify-models requires an explicit --model-version")
        return verify_research_models(paths, segment(args.model_version))
    if not args.registry_version:
        raise ValueError("This research job requires an explicit --registry-version")
    registry_version = segment(args.registry_version)
    batch = segment(args.batch_name or registry_version)
    intelligence_directory = confined_path(paths.workspace_root, f"intelligence/{batch}")
    if args.command == "train-models":
        horizon = args.horizon if args.horizon is not None else protocol.primary_horizon
        return train_research_models(
            paths, registry_version, intelligence_directory, horizon=horizon
        )
    events, parent, frozen_protocol = evidence_events(paths, registry_version)
    if frozen_protocol.model_dump(mode="json") != protocol.model_dump(mode="json"):
        raise ValueError("Evidence collection protocol differs from the registered event freeze")
    provider = None
    if not args.no_gemma:
        provider = GemmaProvider(
            protocol.extraction_model,
            min_interval_seconds=protocol.extraction_interval_seconds,
            max_calls=protocol.extraction_max_calls,
            max_chunks=2 * protocol.extraction_max_chunks_per_leg,
            max_evidence_chars=protocol.extraction_max_pack_chars,
            credential=lambda: (
                runtime.llm_api_key.get_secret_value() if runtime.llm_api_key else None
            ),
        )
    tone_policy = FinBERTPolicy(
        model_name=protocol.sentiment_model,
        model_revision=protocol.sentiment_revision,
        preprocessing_version=args.sentiment_preprocessing,
    )
    backend = None
    if not args.no_finbert:
        # XET downloads were unavailable on the verified Windows host; the same
        # official HTTP weight bytes are hash-checked by the pinned local adapter.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        backend = HuggingFaceFinBERT(
            paths.project_root / "data/cache/huggingface",
            tone_policy,
            local_files_only=not args.download_model,
        )
    return build_event_intelligence(
        events,
        universe_directory,
        sec_directory,
        intelligence_directory,
        provider=provider,
        model_name=protocol.extraction_model,
        provider_config={"max_tokens": 1600, "seed": protocol.seed},
        sentiment_backend=backend,
        sentiment_policy=tone_policy,
        cache_workspace=paths.workspace_root / "cache",
        max_events=args.max_events,
        catalyst_max_events=args.catalyst_max_events,
        max_retries=protocol.extraction_retries,
        sec_user_agent=contact,
        offline=args.offline,
        event_registry_id=registry_version,
        market_manifest_sha256=next(
            item["sha256"] for item in parent["inputs"] if item["role"] == "market"
        ),
        progress=progress_callback,
        source_prefetch=bool(getattr(args, "source_prefetch", 0)),
        resume_audit=getattr(args, "resume_audit", None),
        resume_audit_sha256=getattr(args, "resume_audit_sha256", None),
        checkpoint_source=getattr(args, "checkpoint_source", None),
        checkpoint_baseline=getattr(args, "checkpoint_baseline", None),
        checkpoint_baseline_sha256=getattr(args, "checkpoint_baseline_sha256", None),
        audit_output=getattr(args, "audit_output", None),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    progress = None
    try:
        project = find_project_root(args.project_root)
        runtime = RuntimeSettings(_env_file=project / ".env")
        paths = ProjectPaths.resolve(
            project, args.workspace_root or runtime.workspace_root or project / "data/research_v2"
        )
        if paths.workspace_root == project:
            raise ValueError(
                "Research-v2 requires a separate workspace from the Phase 4 experiment"
            )
        if any(
            value is not None and value < 1
            for value in (args.max_events, args.max_issuers, args.catalyst_max_events)
        ):
            raise ValueError("Explicit partial inventory limits must be positive")
        if args.command == "audit-checkpoints" and args.audit_output is None:
            raise ValueError("audit-checkpoints requires a new --audit-output receipt")
        if args.command != "audit-checkpoints" and args.audit_output is not None:
            raise ValueError("--audit-output is restricted to audit-checkpoints")
        if args.progress_file is not None:
            if not args.progress_file.resolve().is_relative_to(project / ".acceptance"):
                raise ValueError(
                    "Operational progress must stay in the project acceptance directory"
                )
            progress = _FileProgress(args.progress_file, args.command, args.batch_name)
        result = (
            run_command(args, paths, runtime)
            if progress is None
            else run_command(args, paths, runtime, progress=progress)
        )
        summary = {
            name: result[name]
            for name in (
                "freeze_id",
                "data_snapshot_id",
                "research_version",
                "primary_version",
                "intelligence_version",
                "included_security_count",
                "included_pair_count",
                "filing_count",
                "event_count",
                "scheduled_event_count",
                "catalyst_selected_event_count",
                "catalyst_scheduled_event_count",
                "catalyst_call_upper_bound",
                "native_max_errors",
                "paired_comparison_reproduced",
                "final_test_read",
                "checkpoint_count",
                "audit_sha256",
                "audit_path",
            )
            if name in result
        }
        (progress or _progress)({"status": "SUCCESS", "command": args.command, **summary})
        return 0
    except Exception as error:
        # Provider/source/validation exception text may contain credentials.
        if progress is not None:
            progress({"status": "FAILED", "error_type": type(error).__name__})
        print(
            json.dumps(
                {"status": "FAILED", "command": args.command, "error_type": type(error).__name__}
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
