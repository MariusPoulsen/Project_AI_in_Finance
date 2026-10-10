"""Source-bound resumability audits, separate from scientific replay acceptance.

An interrupted batch's preserved receipt fixes the checkpoint bytes. A one-time
preflight validates their stored outputs and cached SEC responses, without HTML
parsing, model/tokenizer calls or provider calls. A detached builder may reuse
exact copies after checking this audit and current bytes. Independent scientific
verification must still reconstruct every evidence pack from raw sources.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import KeysView, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.intelligence.evidence import cache_filing, select_event_filings
from structural_break.intelligence.extraction import validate_pack, validate_stored_extraction
from structural_break.intelligence.sentiment import (
    FINBERT_ASSETS_SHA256,
    SENTIMENT_FEATURE_COLUMNS,
    FinBERTPolicy,
    validate_sentiment_result,
)
from structural_break.research.scheduling import MAX_CATALYST_CALLS, build_catalyst_schedule
from structural_break.research.universe import json_bytes, verify_universe_freeze
from structural_break.storage.files import sha256_file, write_bytes

AUDIT_SCHEMA = "research-checkpoint-resume-audit-v1"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Checkpoint audit JSON must be an object")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _check_digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Checkpoint audit requires a SHA-256 digest")
    return value


def _check_files(root: Path, files: Mapping[str, str]) -> None:
    for filename, digest in files.items():
        if sha256_file(confined_path(root, filename)) != _check_digest(digest):
            raise ValueError(f"Checkpoint audit source/file checksum differs: {filename}")


def _parent_inventory(directory: Path) -> dict[str, str]:
    manifest = _json(directory / "manifest.json")
    files = dict(manifest["files"])
    files["manifest.json"] = sha256_file(directory / "manifest.json")
    _check_files(directory, files)
    return files


def _compatible_inputs(old: Mapping[str, Any], new: Mapping[str, Any]) -> None:
    if set(old) != set(new) or any(old[name] != new[name] for name in old if name != "code_sha256"):
        raise ValueError("Checkpoint reuse must preserve every scientific batch input")
    _check_digest(old["code_sha256"])
    _check_digest(new["code_sha256"])


def _canonical_inputs(
    events: pd.DataFrame,
    inputs: Mapping[str, Any],
    schedule: Mapping[str, Any],
    frozen_universe_dir: Path,
    sec_metadata_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Local import keeps the builder free to import this module without a cycle.
    from structural_break.research.intelligence import (
        RESEARCH_EVIDENCE_POLICY,
        _event_inputs,
    )

    freeze = _json(frozen_universe_dir / "manifest.json")
    if inputs["universe_freeze_id"] != freeze["freeze_id"] or inputs[
        "sec_manifest_sha256"
    ] != sha256_file(sec_metadata_dir / "manifest.json"):
        raise ValueError("Checkpoint audit frozen parent identity differs")
    pairs = pd.read_parquet(frozen_universe_dir / "pair_universe.parquet")
    clean = _event_inputs(events, pairs)
    if _digest(clean.to_dict("records")) != inputs["events_sha256"]:
        raise ValueError("Checkpoint audit exact event registry differs")
    expected = build_catalyst_schedule(
        clean.loc[:, ["event_id", "pair_id", "event_timestamp"]],
        pairs,
        max_events=inputs["catalyst_max_events"],
        max_calls=inputs["provider_limits"]["max_calls"] or MAX_CATALYST_CALLS,
        max_retries=inputs["max_retries"],
    )
    if (
        dict(schedule) != expected
        or inputs["catalyst_schedule_sha256"] != expected["schedule_sha256"]
    ):
        raise ValueError("Checkpoint audit target-blind catalyst schedule differs")
    from dataclasses import asdict

    if inputs["evidence_policy"] != asdict(RESEARCH_EVIDENCE_POLICY):
        raise ValueError("Checkpoint audit evidence policy differs")
    FinBERTPolicy(**inputs["sentiment_policy"])
    return clean, pd.read_parquet(sec_metadata_dir / "filings.parquet")


def _checkpoint_inventory(directory: Path) -> dict[str, str]:
    folder = directory / "events"
    files = {}
    if not folder.is_dir():
        raise ValueError("Checkpoint audit has no event checkpoint directory")
    for path in folder.iterdir():
        if not path.is_file() or re.fullmatch(r"[0-9a-f]{64}\.json", path.name) is None:
            raise ValueError("Checkpoint inventory contains an unexpected file")
        files[f"events/{path.name}"] = sha256_file(path)
    return files


def _baseline(
    source_dir: Path, receipt_path: Path, receipt_sha256: str
) -> tuple[dict[str, Any], dict[str, str]]:
    if sha256_file(receipt_path) != _check_digest(receipt_sha256):
        raise ValueError("Preserved checkpoint baseline receipt checksum differs")
    baseline = _json(receipt_path)
    if baseline.get("recorded_processes_absent") is not True:
        raise ValueError("Checkpoint reuse requires a preserved stopped attempt")
    entries = baseline["checkpoint_inventory"]
    if not isinstance(entries, list) or len(entries) != baseline["checkpoint_count"]:
        raise ValueError("Preserved checkpoint baseline inventory/count differs")
    files = {}
    for entry in entries:
        filename = entry["filename"]
        if not isinstance(filename, str) or re.fullmatch(r"[0-9a-f]{64}\.json", filename) is None:
            raise ValueError("Preserved checkpoint baseline filename is invalid")
        relative = f"events/{filename}"
        if relative in files:
            raise ValueError("Preserved checkpoint baseline repeats a filename")
        files[relative] = _check_digest(entry["sha256"])
        if (source_dir / relative).stat().st_size != entry["size_bytes"]:
            raise ValueError("Preserved checkpoint baseline size differs")
    if files != _checkpoint_inventory(source_dir):
        raise ValueError("Preserved checkpoint bytes differ from the stopped attempt")
    if (
        sha256_file(source_dir / "inputs.json") != baseline["inputs_sha256"]
        or sha256_file(source_dir / "catalyst_schedule.json")
        != baseline["catalyst_schedule_sha256"]
    ):
        raise ValueError("Preserved checkpoint baseline inputs or schedule differ")
    return _json(source_dir / "inputs.json"), files


def prepare_checkpoint_audit(
    source_dir: Path,
    events: pd.DataFrame,
    expected_inputs: Mapping[str, Any],
    expected_schedule: Mapping[str, Any],
    *,
    frozen_universe_dir: Path,
    sec_metadata_dir: Path,
    cache_workspace: Path,
    target_dir: Path,
    baseline_receipt_path: Path,
    baseline_receipt_sha256: str,
    receipt_path: Path,
) -> dict[str, Any]:
    """Audit original immutable checkpoint bytes before a different-code batch.

    The caller copies exact bytes into ``target_dir``; this function never copies
    or repairs data. Only ``code_sha256`` may differ between old/new inputs. This
    audit authorizes resumability, not model/publication acceptance.
    """
    from structural_break.research.intelligence import (
        RESEARCH_EVIDENCE_POLICY,
        SubmissionClockState,
        _empty_pack,
        _offline_only,
        _pair_filing_indices,
        _submission_clock_state,
        _validate_empty_clock_coverage,
        _validate_submission_clock,
        verify_sec_metadata,
    )

    if source_dir.resolve() == target_dir.resolve() or (target_dir / "manifest.json").exists():
        raise ValueError("Engineering resume requires a distinct incomplete batch")
    old_inputs, checkpoints = _baseline(source_dir, baseline_receipt_path, baseline_receipt_sha256)
    _compatible_inputs(old_inputs, expected_inputs)
    if _json(source_dir / "catalyst_schedule.json") != dict(expected_schedule):
        raise ValueError("Checkpoint resume source schedule differs")
    verify_universe_freeze(frozen_universe_dir)
    verify_sec_metadata(sec_metadata_dir, frozen_universe_dir)
    clean, filings = _canonical_inputs(
        events, expected_inputs, expected_schedule, frozen_universe_dir, sec_metadata_dir
    )
    pair_filings = _pair_filing_indices(clean, filings)
    catalyst_ids = set(expected_schedule["selected_event_ids"])
    policy = FinBERTPolicy(**expected_inputs["sentiment_policy"])
    paths = ProjectPaths(Path(__file__).resolve().parents[3], cache_workspace.resolve())
    # One current raw-response validation per distinct accession, not per event.
    documents: dict[str, list[dict[str, object]]] = {}
    clock_states: dict[str, SubmissionClockState] = {}
    earliest_cutoffs: dict[str, pd.Timestamp] = {}
    selected_rows: dict[str, dict[str, Any]] = {}
    checked: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(cast(list[dict[str, Any]], clean.to_dict("records"))):
        filename = "events/" + hashlib.sha256(event["event_id"].encode()).hexdigest() + ".json"
        if filename not in checkpoints:
            continue
        record = _json(source_dir / filename)
        scheduled = expected_inputs["max_events"] is None or index < expected_inputs["max_events"]
        catalyst = scheduled and event["event_id"] in catalyst_ids
        if (
            record["event"] != event
            or record["scheduled"] is not scheduled
            or record["catalyst_scheduled"] is not catalyst
        ):
            raise ValueError("Checkpoint exact event identity or scheduling differs")
        pack = record["pack"]
        validate_pack(pack)
        for name in ("event_id", "pair_id", "event_timestamp", "evidence_cutoff"):
            if pack[name] != event[name]:
                raise ValueError("Checkpoint evidence pack event identity differs")
        if scheduled:
            selected, _ = select_event_filings(
                event,
                pair_filings[event["pair_id"]],
                [event["leg_a_security_id"], event["leg_b_security_id"]],
                RESEARCH_EVIDENCE_POLICY,
            )
            if record["selected_filing_count"] != len(selected) or pack["selected_filing_ids"] != (
                sorted(str(row["filing_id"]) for row in selected)
            ):
                raise ValueError("Checkpoint frozen admissible filing selection differs")
            if pack["evidence_hash"] != _digest(
                {name: value for name, value in pack.items() if name != "evidence_hash"}
            ):
                raise ValueError("Checkpoint evidence pack checksum differs")
            for filing in selected:
                accession = str(filing["filing_id"])
                if accession not in documents:
                    documents[accession] = cache_filing(paths, filing, _offline_only, offline=True)
                    selected_rows[accession] = dict(filing)
                    clock_states[accession] = _submission_clock_state(
                        documents[accession], filing, pd.Timestamp(event["evidence_cutoff"])
                    )
                cutoff = pd.Timestamp(event["evidence_cutoff"])
                earliest_cutoffs[accession] = min(earliest_cutoffs.get(accession, cutoff), cutoff)
            _validate_empty_clock_coverage(
                pack,
                selected,
                {
                    str(filing["filing_id"])
                    for filing in selected
                    if clock_states[str(filing["filing_id"])]
                    is SubmissionClockState.EMPTY_ACCEPTANCE
                },
            )
            selected_index = {str(row["filing_id"]): row for row in selected}
            for chunk in pack["chunks"]:
                chunk_filing = selected_index.get(chunk["filing_id"])
                if (
                    chunk_filing is None
                    or any(
                        chunk[name] != chunk_filing[name] for name in ("security_id", "form", "leg")
                    )
                    or pd.Timestamp(chunk["acceptance_datetime_utc"])
                    != pd.Timestamp(cast(str, chunk_filing["acceptance_datetime_utc"]))
                ):
                    raise ValueError("Checkpoint evidence chunk filing provenance differs")
                if not any(
                    row.get("raw_file_path") == chunk["raw_file_path"]
                    and row.get("sha256") == chunk["sha256"]
                    and row.get("source_url") == chunk["source_url"]
                    and row.get("status") == "DOWNLOADED"
                    for row in documents[chunk["filing_id"]]
                ):
                    raise ValueError("Checkpoint evidence chunk cached raw response differs")
        elif pack != _empty_pack(event, RESEARCH_EVIDENCE_POLICY):
            raise ValueError("Unscheduled checkpoint cannot contain evidence")
        if record["catalyst_pack"] != (
            pack if catalyst else _empty_pack(event, RESEARCH_EVIDENCE_POLICY)
        ) or (not catalyst and record["extraction"]["status"] != "UNKNOWN"):
            raise ValueError("Checkpoint catalyst evidence violates its frozen schedule")
        validate_stored_extraction(record["catalyst_pack"], record["extraction"])
        if (
            any(
                record["extraction"][name] != expected_inputs[key]
                for name, key in (
                    ("provider_name", "provider"),
                    ("model_name", "model"),
                    ("prompt_version", "prompt_version"),
                )
            )
            or record["extraction"]["provider_config_hash"]
            != hashlib.sha256(
                json.dumps(
                    expected_inputs["provider_config"],
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            or record["extraction"]["synthetic"] is not False
        ):
            raise ValueError("Checkpoint stored provider/configuration identity differs")
        tone_features = validate_sentiment_result(
            pack,
            record["tone"],
            leg_security_ids=[event["leg_a_security_id"], event["leg_b_security_id"]],
            policy=policy,
        )
        for chunk in record["tone"]["chunks"]:
            if (
                chunk.get("scored_window_count", 0)
                and chunk.get("runtime", {}).get("model_assets_sha256") != FINBERT_ASSETS_SHA256
            ):
                raise ValueError("Checkpoint tone output lacks exact pinned model assets")
        checked[filename] = {
            "sha256": checkpoints[filename],
            "event_id": event["event_id"],
            "event_index": index,
            "tone_features": tone_features,
        }
    if set(checked) != set(checkpoints):
        raise ValueError("Checkpoint baseline contains events outside the exact registry")
    source_files: dict[str, str] = {}
    for accession, inventory in documents.items():
        filing = selected_rows[accession]
        _validate_submission_clock(inventory, filing, earliest_cutoffs[accession])
        folder = paths.data_path(f"raw/sec/filings/{filing['cik']}/{accession}")
        if not (folder / "response_manifest.json").is_file():
            raise ValueError("Checkpoint selected accession has no completed source inventory")
        for source in folder.rglob("*"):
            if source.is_file() and "attempts" not in source.relative_to(folder).parts:
                source_files[source.relative_to(paths.workspace_root).as_posix()] = sha256_file(
                    source
                )
    # Recheck preserved bytes after potentially slow stored-window validation.
    if _checkpoint_inventory(source_dir) != checkpoints:
        raise ValueError("Checkpoint baseline changed during the preflight audit")
    receipt: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA,
        "status": "CHECKPOINT_RESUME_AUDITED_NOT_RAW_REPLAY_ACCEPTED",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_dir": str(source_dir.resolve()),
        "target_dir": str(target_dir.resolve()),
        "cache_workspace": str(cache_workspace.resolve()),
        "old_inputs": old_inputs,
        "inputs": dict(expected_inputs),
        "source_inputs_sha256": sha256_file(source_dir / "inputs.json"),
        "baseline_receipt_sha256": baseline_receipt_sha256,
        "schedule": dict(expected_schedule),
        "checkpoint_count": len(checked),
        "event_count": len(clean),
        "checkpoints": checked,
        "source_files": source_files,
        "universe_files": _parent_inventory(frozen_universe_dir),
        "sec_metadata_files": _parent_inventory(sec_metadata_dir),
        "finbert_assets_sha256": dict(FINBERT_ASSETS_SHA256),
        "raw_text_reconstructed": False,
        "neural_or_provider_calls": 0,
        "independent_verification_accepted": False,
        "final_test_outcomes_inspected": False,
    }
    receipt["audit_id"] = "resume_audit_" + _digest(receipt)[:24]
    write_bytes(receipt_path, json_bytes(receipt))
    return receipt


@dataclass(frozen=True)
class VerifiedCheckpointAudit:
    """Small validated reuse index; full evidence packs are loaded one at a time."""

    directory: Path
    checkpoints: Mapping[str, Mapping[str, Any]]

    @property
    def filenames(self) -> KeysView[str]:
        return self.checkpoints.keys()

    def load_record(self, filename: str) -> dict[str, Any]:
        expected = self.checkpoints[filename]
        path = confined_path(self.directory, filename)
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != expected["sha256"]:
            raise ValueError("Audited checkpoint changed before reuse")
        return cast(dict[str, Any], json.loads(body))

    def tone_features(self, filename: str) -> dict[str, float | None]:
        return cast(dict[str, float | None], dict(self.checkpoints[filename]["tone_features"]))


def verify_checkpoint_audit(
    receipt_path: Path,
    output_dir: Path,
    inputs: Mapping[str, Any],
    events: pd.DataFrame,
    schedule: Mapping[str, Any],
    *,
    frozen_universe_dir: Path,
    sec_metadata_dir: Path,
    cache_workspace: Path,
    expected_audit_sha256: str,
) -> VerifiedCheckpointAudit:
    """Check a trusted preflight digest/current bytes once before fast reuse.

    The detached command must bind ``expected_audit_sha256`` from the completed
    preflight. Neither this receipt nor its cached stored-output features replace
    the unconditional raw-source reconstruction in independent verification.
    """
    if sha256_file(receipt_path) != _check_digest(expected_audit_sha256):
        raise ValueError("Checkpoint resume audit receipt checksum differs")
    receipt = _json(receipt_path)
    if receipt.get("schema_version") != AUDIT_SCHEMA or receipt.get("audit_id") != (
        "resume_audit_"
        + _digest({name: value for name, value in receipt.items() if name != "audit_id"})[:24]
    ):
        raise ValueError("Checkpoint resume audit content identity differs")
    if (
        receipt["inputs"] != dict(inputs)
        or receipt["schedule"] != dict(schedule)
        or receipt["target_dir"] != str(output_dir.resolve())
        or receipt["cache_workspace"] != str(cache_workspace.resolve())
    ):
        raise ValueError("Checkpoint resume audit belongs to different batch inputs/paths")
    _compatible_inputs(receipt["old_inputs"], inputs)
    if (
        receipt["raw_text_reconstructed"] is not False
        or receipt["independent_verification_accepted"] is not False
        or receipt["final_test_outcomes_inspected"] is not False
        or receipt["neural_or_provider_calls"] != 0
        or receipt["finbert_assets_sha256"] != FINBERT_ASSETS_SHA256
    ):
        raise ValueError("Checkpoint resume audit scope or pinned assets differs")
    clean, _ = _canonical_inputs(events, inputs, schedule, frozen_universe_dir, sec_metadata_dir)
    if receipt["event_count"] != len(clean) or receipt["checkpoint_count"] != len(
        receipt["checkpoints"]
    ):
        raise ValueError("Checkpoint resume audit event/checkpoint count differs")
    for root, name in (
        (frozen_universe_dir, "universe_files"),
        (sec_metadata_dir, "sec_metadata_files"),
        (cache_workspace, "source_files"),
    ):
        _check_files(root, receipt[name])
    rows = cast(list[dict[str, Any]], clean.to_dict("records"))
    for filename, checkpoint in receipt["checkpoints"].items():
        index = checkpoint["event_index"]
        if type(index) is not int or not 0 <= index < len(rows):
            raise ValueError("Checkpoint resume audit event index is invalid")
        event_id = rows[index]["event_id"]
        if (
            checkpoint["event_id"] != event_id
            or filename != ("events/" + hashlib.sha256(event_id.encode()).hexdigest() + ".json")
            or set(checkpoint["tone_features"]) != set(SENTIMENT_FEATURE_COLUMNS)
        ):
            raise ValueError("Checkpoint resume audit event/feature identity differs")
    _check_files(output_dir, {name: row["sha256"] for name, row in receipt["checkpoints"].items()})
    return VerifiedCheckpointAudit(output_dir.resolve(), receipt["checkpoints"])
