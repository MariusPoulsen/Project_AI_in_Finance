"""Explicit registered-source and accepted-model bridges; never download or fit.

Source review does not depend on an accepted model. Scored agent inputs do:
the registered primary publication binds hosted CI and independent native/source
acceptance, then this adapter replays only the explicitly requested event.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from structural_break.agents.contracts import AgentInput, SourceChunk
from structural_break.agents.pipeline import canonical_json, digest
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.intelligence.extraction import validate_stored_extraction
from structural_break.intelligence.sentiment import (
    FINBERT_WEIGHTS_SHA256,
    FinBERTPolicy,
    validate_sentiment_result,
)
from structural_break.research.intelligence import (
    RESEARCH_EVIDENCE_POLICY,
    _coverage_bounds,
    _event_inputs,
    _event_pack,
    _offline_only,
    verify_sec_metadata,
)
from structural_break.research.primary import (
    checked_file,
    checked_json,
    load_primary,
    registered_manifest,
)
from structural_break.research.protocol import identity as research_identity
from structural_break.storage.files import sha256_file, write_bytes


def read_frame(
    directory: Path, manifest: dict[str, Any], name: str, *, columns: list[str] | None = None
) -> pd.DataFrame:
    """Decode the exact bytes checked, with explicit target-free projections."""
    path = checked_file(directory, manifest, name)
    item = next(row for row in manifest["files"] if row["name"] == name)
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != item["sha256"]:
        raise ValueError("Registered research artifact changed before decoding")
    return pd.read_parquet(io.BytesIO(body), columns=columns)


def source_chunks(pack: Mapping[str, Any]) -> tuple[SourceChunk, ...]:
    """Offsets address the stored cleaned chunk, never pretend to be HTML offsets."""
    return tuple(
        SourceChunk.model_validate_json(
            canonical_json(
                {
                    "chunk_id": row["chunk_id"],
                    "leg": row["leg"],
                    "security_id": row["security_id"],
                    "filing_id": row["filing_id"],
                    "document_sha256": row["sha256"],
                    "start_offset": 0,
                    "end_offset": len(row["chunk_text"]),
                    "source_timestamp": row["acceptance_datetime_utc"],
                    "text": row["chunk_text"],
                }
            )
        )
        for row in pack["chunks"]
    )


class RegisteredSources:
    """Explicit SQL-registered registry, source-v3 metadata and offline raw captures."""

    def __init__(
        self,
        paths: ProjectPaths,
        *,
        registry_version: str,
        sec_directory: Path,
        sec_manifest_sha256: str,
        cache_workspace: Path,
    ) -> None:
        self.paths = paths
        self.registry_path, self.registry = registered_manifest(paths, registry_version, "registry")
        if self.registry.get("final_test_read") is not False:
            raise ValueError("Registered development registry must retain the final-test lock")
        universe = [row for row in self.registry["inputs"] if row["role"] == "universe"]
        if len(universe) != 1:
            raise ValueError("Registry requires one frozen universe")
        universe_path = confined_path(paths.workspace_root, universe[0]["path"])
        checked_json(universe_path, universe[0]["sha256"])
        self.universe_directory = universe_path.parent
        self.sec_directory = sec_directory.resolve()
        checked_json(self.sec_directory / "manifest.json", sec_manifest_sha256)
        self.sec_manifest = verify_sec_metadata(self.sec_directory, self.universe_directory)
        from structural_break.research.availability import ACCEPTANCE_POLICY

        if self.sec_manifest["inputs"].get("acceptance_policy") != ACCEPTANCE_POLICY:
            raise ValueError("Phase 5 requires conservative SEC source-v3 availability")
        self.sec_manifest_sha256 = sec_manifest_sha256
        self.cache_paths = ProjectPaths(paths.project_root, cache_workspace.resolve())
        pairs = pd.read_parquet(self.universe_directory / "pair_universe.parquet")
        identities = read_frame(
            self.registry_path.parent,
            self.registry,
            "h20_events",
            columns=["event_id", "pair_id", "event_timestamp"],
        )
        self.events = _event_inputs(identities, pairs)
        self.filings = pd.read_parquet(self.sec_directory / "filings.parquet")
        coverage = json.loads((self.sec_directory / "coverage.json").read_bytes())
        self.coverage = _coverage_bounds(coverage, self.filings)

    def event(self, event_id: str) -> dict[str, Any]:
        rows = self.events.loc[self.events["event_id"].eq(event_id)]
        if len(rows) != 1:
            raise ValueError("Event is outside the explicit development registry")
        return dict(rows.iloc[0])

    def pack(self, event_id: str, *, cache_paths: ProjectPaths | None = None) -> dict[str, Any]:
        event = self.event(event_id)
        securities = [event["leg_a_security_id"], event["leg_b_security_id"]]
        filings = self.filings.loc[self.filings["security_id"].isin(securities)]
        return _event_pack(
            event,
            filings,
            self.coverage,
            cache_paths or self.cache_paths,
            _offline_only,
            offline=True,
        )[0]

    def relationship(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Load the checksum-bound pair snapshot selected by the registry event."""
        pair_id = str(event["pair_id"])
        entries = [row for row in self.registry["pair_manifests"] if row["pair_id"] == pair_id]
        if len(entries) != 1:
            raise ValueError("Event requires one registered pair relationship manifest")
        pair_path = confined_path(self.registry_path.parent, f"pairs/{pair_id}/manifest.json")
        manifest = checked_json(pair_path, entries[0]["sha256"])
        if manifest["pair_id"] != pair_id or manifest["identity"] != research_identity(
            self.registry["source"]
        ):
            raise ValueError("Pair relationship identity differs from its registry")
        snapshots = read_frame(pair_path.parent, manifest, "relationship_snapshots")
        selected = snapshots.loc[
            snapshots["relationship_snapshot_id"].eq(event["relationship_snapshot_id"])
        ]
        if len(selected) != 1:
            raise ValueError("Event requires one exact registered monthly relationship")
        snapshot = dict(selected.iloc[0])
        cutoff = pd.Timestamp(event["event_timestamp"])
        if (
            pd.Timestamp(snapshot["estimation_timestamp"]) > cutoff
            or pd.Timestamp(snapshot["effective_start_at"]) > cutoff
            or pd.Timestamp(snapshot["effective_end_at"]) <= cutoff
        ):
            raise ValueError("Relationship was unavailable or inactive at the event cutoff")
        if snapshot["pair_id"] != pair_id or snapshot["pair_status"] not in {
            "ACTIVE",
            "WATCH",
            "RETIRED",
        }:
            raise ValueError("Relationship pair/status is invalid")
        for field in ("alpha", "beta", "spread_mean", "spread_std"):
            if not math.isclose(
                float(snapshot[field]), float(event[field]), abs_tol=1e-12, rel_tol=0
            ):
                raise ValueError(
                    "Event relationship parameters differ from the registered snapshot"
                )
        if bool(event["baseline1_eligible"]) != (snapshot["pair_status"] == "ACTIVE"):
            raise ValueError("Event ACTIVE subset differs from the frozen relationship status")
        return snapshot


class AcceptedHistoricalInputs:
    """Load exact primary logistic B-both, replaying selected native probabilities.

    Absence of the registered primary publication is a hard readiness error. A
    supplied manifest or acceptance boolean alone can never enable this bridge.
    Hard implementation/liquidity eligibility remains UNKNOWN until a separate
    point-in-time execution policy is frozen, so this input cannot approve trades.
    """

    def __init__(
        self,
        paths: ProjectPaths,
        *,
        primary_version: str,
        sec_directory: Path,
        sec_manifest_sha256: str,
        cache_workspace: Path,
    ) -> None:
        self.primary = load_primary(paths, primary_version)
        self.paths = paths
        identity = self.primary["identity_inputs"]
        if (
            identity["primary_horizon"],
            identity["primary_family"],
            identity["primary_b_variant"],
        ) != (20, "logistic", "both"):
            raise ValueError("Adapter requires the predeclared primary logistic B-both/H20")
        self.sources = RegisteredSources(
            paths,
            registry_version=identity["registry_version"],
            sec_directory=sec_directory,
            sec_manifest_sha256=sec_manifest_sha256,
            cache_workspace=cache_workspace,
        )
        generation = identity["evaluations"]["20"]["research_version"]
        self.evaluation_path, self.evaluation = registered_manifest(paths, generation, "evaluation")
        parent = next(row for row in self.evaluation["parents"] if row["role"] == "intelligence")
        self.intelligence_path = confined_path(paths.workspace_root, parent["path"])
        self.intelligence = checked_json(self.intelligence_path, parent["sha256"])
        inputs = self.intelligence["inputs"]
        if (
            inputs["sec_manifest_sha256"] != sec_manifest_sha256
            or inputs["evidence_policy"] != asdict(RESEARCH_EVIDENCE_POLICY)
            or inputs["sentiment_policy"]["preprocessing_version"]
            != "sec-sentence-quality-wordpiece-v2"
        ):
            raise ValueError("Accepted inputs disagree with the frozen SEC/FinBERT source policy")
        models = [row for row in self.evaluation["model_files"] if row["name"] == "logistic_B_both"]
        if len(models) != 1:
            raise ValueError("Accepted evaluation lacks the exact native B-both model")
        item = models[0]
        body = confined_path(self.evaluation_path.parent, item["path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("Accepted native model checksum mismatch")
        self.model_sha256 = item["sha256"]
        self.model = joblib.load(io.BytesIO(body))
        self.rows = read_frame(
            self.evaluation_path.parent,
            self.evaluation,
            "model_inputs",
            columns=["event_id", *self.model.columns],
        )
        self.predictions = read_frame(
            self.evaluation_path.parent,
            self.evaluation,
            "predictions",
            columns=[
                "event_id",
                "research_partition",
                "logistic_B_both_raw",
                "logistic_B_both_calibrated",
            ],
        )
        self.quant_events = read_frame(
            self.sources.registry_path.parent, self.sources.registry, "h20_events"
        )
        self.quant_features = read_frame(
            self.sources.registry_path.parent, self.sources.registry, "h20_features"
        )
        mapping_path = self.intelligence_path.parent / "event_mapping.parquet"
        mapping_body = mapping_path.read_bytes()
        if hashlib.sha256(mapping_body).hexdigest() != self.intelligence["files"].get(
            "event_mapping.parquet"
        ):
            raise ValueError("Accepted source mapping checksum mismatch before decoding")
        self.evidence_mapping = pd.read_parquet(
            io.BytesIO(mapping_body),
            columns=["event_id", "pair_id", "event_timestamp"],
        )

    def event(self, event_id: str) -> AgentInput:
        identity = self.sources.event(event_id)
        rows = self.rows.loc[self.rows["event_id"].eq(event_id)]
        stored = self.predictions.loc[self.predictions["event_id"].eq(event_id)]
        if len(rows) != 1 or len(stored) != 1:
            raise ValueError("Event has no accepted calibrated native prediction")
        if stored.iloc[0]["research_partition"] != "assessment" or pd.Timestamp(
            identity["event_timestamp"]
        ).year not in (2022, 2023):
            raise ValueError("Historical agents require out-of-sample 2022–2023 assessment inputs")
        probability = float(self.model.predict(rows)[0])
        raw = float(
            self.model.estimator.predict_proba(rows.loc[:, self.model.columns].astype(float))[0, 1]
        )
        if not (
            math.isclose(
                probability,
                float(stored.iloc[0]["logistic_B_both_calibrated"]),
                abs_tol=1e-12,
                rel_tol=0,
            )
            and math.isclose(
                raw, float(stored.iloc[0]["logistic_B_both_raw"]), abs_tol=1e-12, rel_tol=0
            )
        ):
            raise ValueError("Selected native Model B probability fails independent replay")
        mapping = self.evidence_mapping.loc[
            self.evidence_mapping["pair_id"].eq(identity["pair_id"])
            & pd.to_datetime(self.evidence_mapping["event_timestamp"], utc=True).eq(
                pd.Timestamp(identity["event_timestamp"])
            )
        ]
        if len(mapping) != 1:
            raise ValueError("Event has no unique accepted pair/time source mapping")
        evidence_id = str(mapping.iloc[0]["event_id"])
        filename = "events/" + hashlib.sha256(evidence_id.encode()).hexdigest() + ".json"
        record_entries = [
            row
            for row in self.intelligence["source_identity"]["records"]
            if row["file"] == filename
        ]
        if len(record_entries) != 1:
            raise ValueError("Event has no unique accepted intelligence checkpoint")
        entry = record_entries[0]
        record = checked_json(
            confined_path(self.intelligence_path.parent, entry["file"]), entry["sha256"]
        )
        expected_event = {**identity, "event_id": evidence_id}
        if record["event"] != expected_event or record["scheduled"] is not True:
            raise ValueError("Intelligence event differs from registered identity")
        pack = self.sources.pack(event_id)
        pack["event_id"] = evidence_id
        pack.pop("evidence_hash")
        from structural_break.research.intelligence import _sha

        pack["evidence_hash"] = _sha(pack)
        if pack != record["pack"]:
            raise ValueError("Accepted source pack does not replay from raw cached bytes")
        validate_stored_extraction(record["catalyst_pack"], record["extraction"])
        validate_sentiment_result(
            pack,
            record["tone"],
            leg_security_ids=[identity["leg_a_security_id"], identity["leg_b_security_id"]],
            policy=FinBERTPolicy(**self.intelligence["inputs"]["sentiment_policy"]),
        )
        quant = self.quant_events.loc[self.quant_events["event_id"].eq(event_id)]
        features = self.quant_features.loc[self.quant_features["event_id"].eq(event_id)]
        if len(quant) != 1 or len(features) != 1:
            raise ValueError("Registered quantitative state is not unique")
        q, f = quant.iloc[0], features.iloc[0]
        relationship = self.sources.relationship(dict(q))
        cutoff = pd.Timestamp(identity["event_timestamp"])
        for column in features.columns:
            if column.endswith("available_at") or column == "feature_cutoff_timestamp":
                if pd.isna(f[column]) or pd.Timestamp(f[column]) > cutoff:
                    raise ValueError("Quantitative feature was unavailable at the event close")

        def finite(name: str) -> float | None:
            value = f.get(name)
            return (
                float(value)
                if value is not None and pd.notna(value) and math.isfinite(float(value))
                else None
            )

        extraction = record["extraction"]
        fields = (
            "event_type",
            "affected_leg",
            "direction",
            "materiality",
            "relationship_relevance",
            "citations",
        )
        catalyst = {field: extraction[field] for field in fields}
        tones = []
        for leg in ("A", "B"):
            tone = record["tone"]["legs"][leg]
            chunks = [row for row in record["tone"]["chunks"] if row["leg"] == leg]
            raw_tokens = sum(row["token_count"] for row in chunks)
            eligible = sum(row.get("eligible_token_count", 0) for row in chunks)
            scored = tone["scored_token_count"]
            tones.append(
                {
                    "leg": leg,
                    "security_id": tone["security_id"],
                    "status": tone["status"],
                    "source_coverage": tone["source_coverage_status"],
                    **{
                        key: record["tone"]["policy"][key]
                        for key in ("model_name", "model_revision", "preprocessing_version")
                    },
                    "weights_sha256": FINBERT_WEIGHTS_SHA256,
                    **tone["probabilities"],
                    "net": tone["net"],
                    "token_coverage": tone["token_coverage"],
                    "raw_token_count": raw_tokens,
                    "eligible_token_count": eligible,
                    "excluded_token_count": raw_tokens - eligible,
                    "scored_token_count": scored,
                    "budget_omitted_token_count": eligible - scored,
                    "unknown_chunk_count": tone["unknown_chunk_count"],
                }
            )
        return AgentInput.model_validate_json(
            canonical_json(
                {
                    **{
                        field: identity[field]
                        for field in (
                            "event_id",
                            "pair_id",
                            "event_timestamp",
                            "leg_a_security_id",
                            "leg_b_security_id",
                        )
                    },
                    "pair_status": relationship["pair_status"],
                    "quant": {
                        "model_b_probability": probability,
                        "z_score": finite("z_signed"),
                        "half_life_sessions": finite("half_life"),
                        "beta_drift": finite("beta_drift_pct"),
                        "cointegration_pvalue": finite("coint_pvalue"),
                    },
                    "gates": {
                        "market_data_ok": True,
                        "model_inputs_ok": True,
                        "source_timestamps_ok": True,
                        "source_coverage": pack["coverage_status"],
                        "liquidity_ok": None,
                        "implementation_ok": None,
                    },
                    "lineage": {
                        "registry_id": self.sources.registry["research_version"],
                        "model_bundle_id": self.evaluation["research_version"],
                        "model_version": self.model_sha256,
                        "calibrator_version": self.model_sha256,
                        "relationship_version": q["relationship_version"],
                        "evidence_policy_version": RESEARCH_EVIDENCE_POLICY.version,
                        "source_manifest_sha256": sha256_file(self.intelligence_path),
                    },
                    "evidence": [row.model_dump(mode="json") for row in source_chunks(pack)],
                    "catalysts": [catalyst],
                    "tones": tones,
                }
            )
        )


def export_historical_inputs(
    adapter: AcceptedHistoricalInputs, event_ids: tuple[str, ...], output_dir: Path
) -> Path:
    """Save accepted projections with their publication proof; no mock rebranding."""
    if not event_ids or len(event_ids) > 100_000 or len(set(event_ids)) != len(event_ids):
        raise ValueError("Prepared historical events must be a bounded unique population")
    entries = []
    for event_id in event_ids:
        event = adapter.event(event_id)
        raw = (canonical_json(event.model_dump(mode="json")) + "\n").encode()
        checksum = hashlib.sha256(raw).hexdigest()
        relative = f"inputs/{checksum}.json"
        write_bytes(output_dir / relative, raw)
        entries.append({"event_id": event_id, "path": relative, "sha256": checksum})
    primary_path, _ = registered_manifest(
        adapter.paths, adapter.primary["primary_version"], "primary"
    )
    manifest = {
        "schema_version": "phase5-accepted-historical-inputs-v1",
        "mode": "accepted_historical",
        "primary_version": adapter.primary["primary_version"],
        "primary_manifest_sha256": sha256_file(primary_path),
        "registry_version": adapter.sources.registry["research_version"],
        "sec_manifest_sha256": adapter.sources.sec_manifest_sha256,
        "model_bundle_id": adapter.evaluation["research_version"],
        "model_sha256": adapter.model_sha256,
        "adapter_identity": adapter_identity(),
        "entries": entries,
        "genuine_agent_quality_evaluated": False,
        "final_test_unlocked": False,
    }
    return write_bytes(output_dir / "manifest.json", (canonical_json(manifest) + "\n").encode())


def verify_historical_inputs(adapter: AcceptedHistoricalInputs, manifest_path: Path) -> int:
    """Require fresh publication/native/source replay, never trust an accepted flag."""
    raw = manifest_path.read_bytes()
    if len(raw) > 64_000_000:
        raise ValueError("Historical input inventory exceeds its bounded size")
    manifest = json.loads(raw)
    primary_path, _ = registered_manifest(
        adapter.paths, adapter.primary["primary_version"], "primary"
    )
    expected = {
        "schema_version": "phase5-accepted-historical-inputs-v1",
        "mode": "accepted_historical",
        "primary_version": adapter.primary["primary_version"],
        "primary_manifest_sha256": sha256_file(primary_path),
        "registry_version": adapter.sources.registry["research_version"],
        "sec_manifest_sha256": adapter.sources.sec_manifest_sha256,
        "model_bundle_id": adapter.evaluation["research_version"],
        "model_sha256": adapter.model_sha256,
        "adapter_identity": adapter_identity(),
        "genuine_agent_quality_evaluated": False,
        "final_test_unlocked": False,
    }
    if set(manifest) != {*expected, "entries"} or any(
        manifest.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("Historical inventory disagrees with the accepted primary publication")
    entries = manifest["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100_000:
        raise ValueError("Historical inventory requires a bounded nonempty event population")
    if len({entry["event_id"] for entry in entries}) != len(entries):
        raise ValueError("Historical inventory event identities must be unique")
    for entry in entries:
        event = adapter.event(entry["event_id"])
        expected_raw = (canonical_json(event.model_dump(mode="json")) + "\n").encode()
        checksum = hashlib.sha256(expected_raw).hexdigest()
        if entry != {
            "event_id": event.event_id,
            "path": f"inputs/{checksum}.json",
            "sha256": checksum,
        }:
            raise ValueError("Historical event differs from its native/source replay")
        if confined_path(manifest_path.parent, entry["path"]).read_bytes() != expected_raw:
            raise ValueError("Historical event projection checksum mismatch")
    return len(entries)


def adapter_identity() -> dict[str, object]:
    """Bind projection/replay rules and the runtime without changing accepted models."""
    source_root = Path(__file__).resolve().parents[1]
    source_files = (
        "agents/historical.py",
        "agents/contracts.py",
        "intelligence/evidence.py",
        "intelligence/extraction.py",
        "intelligence/sentiment.py",
        "research/intelligence.py",
        "research/availability.py",
        "research/evaluation.py",
        "ml/model.py",
        "research/primary.py",
    )
    hashes = {
        name: hashlib.sha256((source_root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in source_files
    }
    return {
        "source_sha256": digest(hashes),
        "python_version": sys.version.split()[0],
        "runtime": {
            name: version(name)
            for name in (
                "joblib",
                "numpy",
                "pandas",
                "scikit-learn",
                "pydantic",
                "exchange-calendars",
            )
        },
    }
