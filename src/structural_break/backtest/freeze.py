"""Phase 6 freeze manifest and the explicit final-test unlock gate.

The freeze manifest records, from independently verified accepted historical
experiments, everything the specification requires to be frozen before the
final test: the universe and market capture, label policy, feature schema,
Model A/B bundles and calibrators, trading thresholds, controller status,
execution/cost and analysis policies, and code/runtime identities. It also
carries the validation-decision checklist. It never unlocks the final test.

Unlocking needs a separate owner-authored record that binds the exact freeze
manifest checksum and states the authorization verbatim. Nothing in this module
creates that record, fetches 2024-2025 data or runs the final test.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from structural_break.backtest.contracts import SHA256, FrozenModel, Identifier, utc
from structural_break.backtest.experiment import RuntimeBinding, SourceBinding, strict_json
from structural_break.backtest.historical import HistoricalSources
from structural_break.backtest.historical_contracts import GenerationBinding
from structural_break.backtest.historical_experiment import (
    MAX_ARTIFACT_BYTES,
    SpecsDocument,
    read_manifest,
    run_historical_experiment,
    verify_historical_experiment,
)
from structural_break.backtest.policy_diagnostics import policy_diagnostics
from structural_break.backtest.production_policy import (
    ANALYSIS_CONFIG,
    HEADLINE_CONFIG,
    SENSITIVITY_CONFIG,
    load_analysis_policies,
    load_headline,
)
from structural_break.backtest.simulator import canonical_bytes
from structural_break.storage.files import write_bytes

FREEZE_VERSION = "p6-freeze-manifest-v1"
REQUIRED_HORIZONS = (10, 20, 30)
UNLOCK_STATEMENT = (
    "I authorize the 2024-2025 final test under this exact frozen manifest. "
    "No method, threshold, policy or prompt will be changed after viewing its results."
)
EXECUTION_CONVENTION = (
    "Signal at the XNYS close; enter at the next open with frozen beta-weighted share units; "
    "monitor closes with frozen snapshot parameters; exit at the next open after convergence "
    "(|z|<=0.5), same-side adverse stop (s*z>=3) or the horizon close; no refits, fills or "
    "price interpolation; unknown executions are never zero"
)


def checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class HorizonFreeze(FrozenModel):
    horizon_sessions: Literal[10, 20, 30]
    experiment_id: SHA256
    experiment_manifest_sha256: SHA256
    verification_status: Literal["VERIFIED_HISTORICAL_REPLAY"]
    binding: GenerationBinding
    feature_schema_version: Identifier
    label_policy_version: Identifier
    model_family: Literal["logistic", "xgboost"]
    model_b_variant: Identifier
    model_a_bundle_id: Identifier
    model_a_calibrator_id: Identifier
    model_b_bundle_id: Identifier
    model_b_calibrator_id: Identifier
    trading_thresholds: tuple[float, ...]
    execution_policy_versions: tuple[Identifier, ...]
    combinations_n: Annotated[int, Field(ge=1)]


class ConfigFile(FrozenModel):
    name: Identifier
    sha256: SHA256


class DecisionItem(FrozenModel):
    name: Identifier
    status: Literal["CLOSED", "DEFERRED", "OPEN"]
    reference: Identifier
    note: Annotated[str, Field(max_length=500)]


class FreezeIdentity(FrozenModel):
    version: Literal["p6-freeze-manifest-v1"] = "p6-freeze-manifest-v1"
    primary_version: Identifier
    protocol_hash: SHA256
    registry: Identifier
    registry_manifest_sha256: SHA256
    market_snapshot_id: Identifier
    prices_sha256: SHA256
    pair_universe_sha256: SHA256
    development_end: str
    horizons: Annotated[tuple[HorizonFreeze, ...], Field(min_length=1, max_length=3)]
    config_files: tuple[ConfigFile, ...]
    controller: Literal["DEFERRED_NOT_RUN"] = "DEFERRED_NOT_RUN"
    execution_convention: str = EXECUTION_CONVENTION
    sources: tuple[SourceBinding, ...]
    python_version: Identifier
    runtime: tuple[RuntimeBinding, ...]
    decisions: tuple[DecisionItem, ...]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        horizons = [item.horizon_sessions for item in self.horizons]
        if horizons != sorted(set(horizons)):
            raise ValueError("Freeze horizons must be unique and ordered")
        for item in self.horizons:
            binding = item.binding
            if (
                binding.acceptance != "ACCEPTED"
                or binding.primary_version != self.primary_version
                or binding.protocol_hash != self.protocol_hash
                or binding.registry.sha256 != self.registry_manifest_sha256
                or binding.market.version != self.market_snapshot_id
                or binding.prices_sha256 != self.prices_sha256
                or binding.pair_universe_sha256 != self.pair_universe_sha256
            ):
                raise ValueError("Every frozen horizon must bind the same accepted generations")
        return self


class FreezeManifest(FrozenModel):
    schema_version: Literal["p6-freeze-manifest-v1"] = "p6-freeze-manifest-v1"
    freeze_id: SHA256
    identity: FreezeIdentity
    all_decisions_closed: bool
    open_decisions: tuple[Identifier, ...]
    final_test_unlocked: Literal[False] = False
    final_test_read: Literal[False] = False

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.freeze_id != checksum(canonical_bytes(self.identity)):
            raise ValueError("Freeze identity checksum mismatch")
        open_items = tuple(item.name for item in self.identity.decisions if item.status == "OPEN")
        if open_items != self.open_decisions or self.all_decisions_closed != (not open_items):
            raise ValueError("Freeze decision summary differs from its checklist")
        return self


class FinalTestUnlock(FrozenModel):
    """Owner-authored record; the code never writes one."""

    schema_version: Literal["p6-final-test-unlock-v1"] = "p6-final-test-unlock-v1"
    freeze_manifest_sha256: SHA256
    freeze_id: SHA256
    authorized_by: Identifier
    authorized_at: datetime
    statement: str

    @model_validator(mode="after")
    def explicit(self) -> Self:
        utc(self.authorized_at)
        if self.statement != UNLOCK_STATEMENT:
            raise ValueError("The unlock statement must match the required authorization verbatim")
        return self


def _read(path: Path) -> bytes:
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Freeze input exceeds its bounded size")
    raw = path.read_bytes()
    strict_json(raw)
    return raw


def _horizon(
    manifest_path: Path, sources: HistoricalSources, verification: dict[str, object]
) -> tuple[HorizonFreeze, tuple[SourceBinding, ...], str, tuple[RuntimeBinding, ...]]:
    manifest = read_manifest(manifest_path)
    if (
        verification.get("status") != "VERIFIED_HISTORICAL_REPLAY"
        or verification.get("experiment_id") != manifest.experiment_id
    ):
        raise ValueError("Freeze requires an independently verified experiment")
    if sources.binding != manifest.identity.binding:
        raise ValueError("Freeze sources differ from the verified experiment binding")
    item = next(entry for entry in manifest.artifacts if entry.path == "specs.json")
    raw = (manifest_path.parent / "specs.json").read_bytes()
    if checksum(raw) != item.sha256:
        raise ValueError("Bound specification artifact checksum differs")
    specs = SpecsDocument.model_validate_json(raw).specs
    ladder = specs[0].ladder
    versions = sources.registry_frame(
        f"h{manifest.horizon_sessions}_events", ["feature_schema_version"]
    )["feature_schema_version"].unique()
    if len(versions) != 1:
        raise ValueError("Horizon events must bind one feature schema version")
    policies = json.loads((manifest_path.parent / "policies.json").read_bytes())["policies"]
    freeze = HorizonFreeze(
        horizon_sessions=manifest.horizon_sessions,
        experiment_id=manifest.experiment_id,
        experiment_manifest_sha256=checksum(manifest_path.read_bytes()),
        verification_status="VERIFIED_HISTORICAL_REPLAY",
        binding=manifest.identity.binding,
        feature_schema_version=str(versions[0]),
        label_policy_version=ladder.label_policy_version,
        model_family=ladder.model_family,
        model_b_variant=ladder.model_b_variant,
        model_a_bundle_id=ladder.model_a_bundle_id,
        model_a_calibrator_id=ladder.model_a_calibrator_id,
        model_b_bundle_id=ladder.model_b_bundle_id,
        model_b_calibrator_id=ladder.model_b_calibrator_id,
        trading_thresholds=tuple(
            spec.ladder.candidate_threshold
            for spec in specs
            if spec.ladder.candidate_threshold is not None
        ),
        execution_policy_versions=tuple(str(policy["version"]) for policy in policies),
        combinations_n=len(manifest.combinations),
    )
    identity = manifest.identity
    return freeze, identity.sources, identity.python_version, identity.runtime


def _decisions(configs: Path, horizons: Sequence[int]) -> tuple[DecisionItem, ...]:
    headline = load_headline(configs)
    analysis = load_analysis_policies(configs)
    complete = tuple(sorted(horizons)) == REQUIRED_HORIZONS

    def item(name: str, closed: bool, reference: str, note: str) -> DecisionItem:
        return DecisionItem(
            name=name, status="CLOSED" if closed else "OPEN", reference=reference, note=note
        )

    return (
        item(
            "execution_cost_borrow_eligibility_policy",
            headline.status == "FROZEN",
            "DECISIONS 36",
            "Headline v2 policy and its 24-variant sensitivity set",
        ),
        item(
            "trading_threshold",
            True,
            "DECISIONS 36",
            "Common A/B threshold 0.30; 0.20, 0.40 and 0.65 reported",
        ),
        item(
            "analysis_policies",
            analysis.robustness.status == "FROZEN",
            "DECISIONS 36, 39",
            "Month bootstrap, portfolio and robustness slice policies",
        ),
        item(
            "accepted_development_experiments",
            complete,
            "DECISIONS 37, 38",
            "Verified accepted experiments for every predeclared horizon (10/20/30)",
        ),
        DecisionItem(
            name="full_system_controller",
            status="DEFERRED",
            reference="DECISIONS 40",
            note="Multi-agent layer deferred; Full System is NOT_RUN and excluded",
        ),
    )


def build_freeze_manifest(
    entries: Sequence[tuple[Path, HistoricalSources, dict[str, object]]],
    configs: Path,
    output_dir: Path,
) -> Path:
    """Write the content-addressed freeze manifest from verified experiments."""
    if not entries:
        raise ValueError("A freeze manifest needs at least one verified experiment")
    parts = sorted(
        (_horizon(path, sources, verification) for path, sources, verification in entries),
        key=lambda part: part[0].horizon_sessions,
    )
    if len({(part[1], part[2], part[3]) for part in parts}) != 1:
        raise ValueError("Every frozen experiment must share one code and runtime identity")
    first = parts[0][0].binding
    if first.primary_version is None:
        raise ValueError("Freeze requires an accepted primary publication")
    identity = FreezeIdentity(
        primary_version=first.primary_version,
        protocol_hash=first.protocol_hash,
        registry=first.registry.version,
        registry_manifest_sha256=first.registry.sha256,
        market_snapshot_id=first.market.version,
        prices_sha256=first.prices_sha256,
        pair_universe_sha256=first.pair_universe_sha256,
        development_end=first.development_end.isoformat(),
        horizons=tuple(part[0] for part in parts),
        config_files=tuple(
            ConfigFile(name=name, sha256=checksum((configs / name).read_bytes()))
            for name in (HEADLINE_CONFIG, SENSITIVITY_CONFIG, ANALYSIS_CONFIG)
        ),
        sources=parts[0][1],
        python_version=parts[0][2],
        runtime=parts[0][3],
        decisions=_decisions(configs, [part[0].horizon_sessions for part in parts]),
    )
    open_items = tuple(item.name for item in identity.decisions if item.status == "OPEN")
    manifest = FreezeManifest(
        freeze_id=checksum(canonical_bytes(identity)),
        identity=identity,
        all_decisions_closed=not open_items,
        open_decisions=open_items,
    )
    directory = output_dir / "freeze" / manifest.freeze_id
    return write_bytes(directory / "freeze-manifest.json", canonical_bytes(manifest))


def require_final_test_unlock(freeze_path: Path, unlock_path: Path | None) -> FreezeManifest:
    """Refuse unless every decision is closed and the owner bound this exact freeze."""
    raw = _read(freeze_path)
    manifest = FreezeManifest.model_validate_json(raw)
    if not manifest.all_decisions_closed:
        raise PermissionError(
            "Final test stays locked: open decisions " + ", ".join(manifest.open_decisions)
        )
    if unlock_path is None:
        raise PermissionError("Final test stays locked: no owner unlock record was supplied")
    unlock = FinalTestUnlock.model_validate_json(_read(unlock_path))
    if unlock.freeze_manifest_sha256 != checksum(raw) or unlock.freeze_id != manifest.freeze_id:
        raise PermissionError("Final test stays locked: unlock binds a different freeze manifest")
    return manifest


def run_acceptance(
    open_sources: Callable[[int], HistoricalSources],
    configs: Path,
    output_dir: Path,
    *,
    horizons: Sequence[int] = (20, 10, 30),
) -> dict[str, Any]:
    """Official acceptance run: experiment, fresh replay and diagnostics per horizon.

    The freeze manifest is written last from the verified experiments. Its
    checklist reports what remains open; the final test stays locked.
    """
    entries: list[tuple[Path, HistoricalSources, dict[str, object]]] = []
    horizon_results: dict[str, Any] = {}
    for horizon in horizons:
        sources = open_sources(horizon)
        if sources.binding.horizon_sessions != horizon:
            raise ValueError("Opened sources do not bind the requested horizon")
        manifest = run_historical_experiment(sources, configs, output_dir)
        verification = verify_historical_experiment(manifest, sources, configs)
        diagnostics = policy_diagnostics(sources)
        body = (json.dumps(diagnostics, indent=2, sort_keys=True) + "\n").encode("utf-8")
        diagnostics_path = write_bytes(
            output_dir / "policy-diagnostics" / checksum(body) / "diagnostics.json", body
        )
        entries.append((manifest, sources, verification))
        horizon_results[str(horizon)] = {
            "manifest": str(manifest),
            "verification": verification,
            "diagnostics": str(diagnostics_path),
        }
    freeze_path = build_freeze_manifest(entries, configs, output_dir)
    freeze = FreezeManifest.model_validate_json(freeze_path.read_bytes())
    return {
        "status": "ACCEPTANCE_RUN_COMPLETE",
        "horizons": horizon_results,
        "freeze_manifest": str(freeze_path),
        "freeze_id": freeze.freeze_id,
        "open_decisions": list(freeze.open_decisions),
        "post_hoc_development": True,
        "full_system": "NOT_RUN",
        "final_test_unlocked": False,
    }
