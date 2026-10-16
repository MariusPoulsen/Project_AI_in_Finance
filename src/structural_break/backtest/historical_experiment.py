"""Accepted historical ladder experiment: frozen policies, immutable artifacts, replay.

One experiment binds one accepted evaluation generation (one horizon), the
Decision 35 frozen execution policies and trading thresholds, the outcome-free
event inventory and the separate label input. Executions are computed once per
frozen policy and selections once per threshold, because neither depends on the
other; the declared combinations are reported. Every artifact is
content-addressed and the manifest is written last. Verification rebuilds the
events from the bound sources and replays selection, simulation, labels, reports
and summary; it never repairs or overwrites bytes. Results are post-hoc
2022-2023 development assessment, never final-test results.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, model_validator

from structural_break.backtest.contracts import (
    SHA256,
    BoundedNumber,
    ExecutionConfig,
    FrozenModel,
    Identifier,
    PairTradeResult,
    Reason,
    Status,
)
from structural_break.backtest.experiment import (
    RuntimeBinding,
    SourceBinding,
    json_bytes,
    strict_json,
)
from structural_break.backtest.historical import (
    HistoricalSources,
    build_historical_events,
    default_spec,
    historical_labels,
    select_historical_event,
)
from structural_break.backtest.historical_contracts import (
    GenerationBinding,
    HistoricalSpec,
    Partition,
    SuppressedCrossing,
)
from structural_break.backtest.ladder_contracts import (
    RUNG_ORDER,
    EvaluationLabel,
    LadderRow,
    RungSelection,
)
from structural_break.backtest.production_policy import (
    HEADLINE_CONFIG,
    SENSITIVITY_CONFIG,
    expand_policies,
    load_headline,
    load_sensitivities,
)
from structural_break.backtest.reporting import build_comparison_report
from structural_break.backtest.simulator import canonical_bytes, sha256, simulate_pair_trade
from structural_break.storage.files import write_bytes

EXPERIMENT_VERSION = "historical-ladder-experiment-v1"
INPUT_NAMES = ("binding.json", "policies.json", "specs.json", "inventory.json", "labels.json")
OUTPUT_NAMES = (
    "selections.json",
    "executions-primary.json",
    "executions-sensitivity.json",
    "reports.json",
    "summary.md",
)
ARTIFACT_NAMES = INPUT_NAMES + OUTPUT_NAMES
MAX_ARTIFACT_BYTES = 256_000_000
SOURCE_NAMES = (
    "backtest/contracts.py",
    "backtest/simulator.py",
    "backtest/ladder_contracts.py",
    "backtest/ladder.py",
    "backtest/reporting.py",
    "backtest/historical_contracts.py",
    "backtest/historical.py",
    "backtest/production_policy.py",
    "backtest/historical_experiment.py",
    "backtest/experiment.py",
    "agents/contracts.py",
    "ml/model.py",
    "research/primary.py",
)
RUNTIME_PACKAGES = (
    "pydantic",
    "numpy",
    "pandas",
    "pyarrow",
    "scikit-learn",
    "exchange-calendars",
)


def checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class ArtifactBinding(FrozenModel):
    path: Identifier
    sha256: SHA256
    size_bytes: Annotated[int, Field(ge=0, le=MAX_ARTIFACT_BYTES)]


def source_bindings() -> tuple[SourceBinding, ...]:
    package = Path(__file__).resolve().parents[1]
    return tuple(
        SourceBinding(
            path=name, sha256=checksum((package / name).read_bytes().replace(b"\r\n", b"\n"))
        )
        for name in SOURCE_NAMES
    )


def runtime_bindings() -> tuple[RuntimeBinding, ...]:
    return tuple(
        RuntimeBinding(package=name, version=importlib.metadata.version(name))
        for name in RUNTIME_PACKAGES
    )


class EventIdentity(FrozenModel):
    event_id: Identifier
    pair_id: Identifier
    signal_at: str
    partition: Partition | None
    state_sha256: SHA256
    request_sha256: SHA256


class InventoryDocument(FrozenModel):
    schema_version: Literal["historical-event-inventory-v1"] = "historical-event-inventory-v1"
    events: Annotated[tuple[EventIdentity, ...], Field(min_length=1, max_length=100_000)]
    suppressed: Annotated[tuple[SuppressedCrossing, ...], Field(max_length=200_000)]


class PolicySetDocument(FrozenModel):
    schema_version: Literal["historical-policy-set-v1"] = "historical-policy-set-v1"
    headline_file_sha256: SHA256
    sensitivities_file_sha256: SHA256
    policies: Annotated[tuple[ExecutionConfig, ...], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def frozen(self) -> Self:
        if any(
            (policy.schema_version, policy.mode, policy.status)
            != ("pair-execution-policy-v2", "DEVELOPMENT", "FROZEN")
            for policy in self.policies
        ):
            raise ValueError("Historical experiments use only frozen v2 production policies")
        return self


class SpecsDocument(FrozenModel):
    schema_version: Literal["historical-specs-v1"] = "historical-specs-v1"
    specs: Annotated[tuple[HistoricalSpec, ...], Field(min_length=1, max_length=8)]


class LabelsDocument(FrozenModel):
    schema_version: Literal["historical-labels-v1"] = "historical-labels-v1"
    labels: Annotated[tuple[EvaluationLabel, ...], Field(max_length=100_000)]
    unavailable: dict[str, int]


class SelectionRow(FrozenModel):
    event_id: Identifier
    raw_fresh: bool | None
    selections: Annotated[tuple[RungSelection, ...], Field(min_length=5, max_length=5)]


class ThresholdSelections(FrozenModel):
    threshold: float
    spec_sha256: SHA256
    rows: tuple[SelectionRow, ...]


class SelectionsDocument(FrozenModel):
    schema_version: Literal["historical-selections-v1"] = "historical-selections-v1"
    thresholds: tuple[ThresholdSelections, ...]


class PrimaryExecutionsDocument(FrozenModel):
    schema_version: Literal["historical-primary-executions-v1"] = "historical-primary-executions-v1"
    execution_config_sha256: SHA256
    results: tuple[PairTradeResult, ...]


class CompactExecution(FrozenModel):
    """Trade-level record for a sensitivity policy, bound to its full result hash."""

    event_id: Identifier
    execution_config_version: Identifier
    result_sha256: SHA256
    status: Status
    reason: Reason
    holding_sessions: int | None
    gross_return: BoundedNumber | None
    net_return: BoundedNumber | None
    trading_cost: BoundedNumber | None
    borrow_cost: BoundedNumber | None
    mae: BoundedNumber | None
    mfe: BoundedNumber | None


class SensitivityExecutionsDocument(FrozenModel):
    schema_version: Literal["historical-sensitivity-executions-v1"] = (
        "historical-sensitivity-executions-v1"
    )
    results: tuple[CompactExecution, ...]


class HistoricalIdentity(FrozenModel):
    version: Literal["historical-ladder-experiment-v1"] = "historical-ladder-experiment-v1"
    mode: Literal["POST_HOC_DEVELOPMENT_ASSESSMENT"] = "POST_HOC_DEVELOPMENT_ASSESSMENT"
    binding: GenerationBinding
    inputs: tuple[ArtifactBinding, ...]
    sources: tuple[SourceBinding, ...]
    python_version: Identifier
    runtime: tuple[RuntimeBinding, ...]

    @model_validator(mode="after")
    def accepted_inputs(self) -> Self:
        if self.binding.acceptance != "ACCEPTED":
            raise ValueError("Historical experiments require an accepted generation binding")
        if tuple(item.path for item in self.inputs) != INPUT_NAMES:
            raise ValueError("Historical experiment identity must bind every input artifact")
        return self


class Combination(FrozenModel):
    key: Identifier
    threshold: float
    execution_config_version: Identifier
    role: Literal["HEADLINE", "THRESHOLD_SENSITIVITY", "EXECUTION_SENSITIVITY"]


class HistoricalManifest(FrozenModel):
    schema_version: Literal["historical-ladder-manifest-v1"] = "historical-ladder-manifest-v1"
    experiment_id: SHA256
    identity: HistoricalIdentity
    status: Literal["COMPLETE"] = "COMPLETE"
    horizon_sessions: Literal[10, 20, 30]
    event_count: Annotated[int, Field(ge=1)]
    combinations: Annotated[tuple[Combination, ...], Field(min_length=1, max_length=128)]
    post_hoc_development: Literal[True] = True
    full_system: Literal["NOT_RUN"] = "NOT_RUN"
    economic_claims_validated: Literal[False] = False
    final_test_unlocked: Literal[False] = False
    artifacts: tuple[ArtifactBinding, ...]

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        if self.experiment_id != checksum(canonical_bytes(self.identity)):
            raise ValueError("Historical experiment identity checksum mismatch")
        if tuple(item.path for item in self.artifacts) != ARTIFACT_NAMES:
            raise ValueError("Historical artifact inventory must contain every canonical file")
        if self.combinations[0].role != "HEADLINE":
            raise ValueError("The first declared combination must be the headline")
        return self


def _threshold(spec: HistoricalSpec) -> float:
    value = spec.ladder.candidate_threshold
    if value is None:
        raise ValueError("Every historical specification declares its trading threshold")
    return value


def _key(threshold: float, version: str) -> str:
    return f"threshold={threshold:g}|{version}"


def _compact(result: PairTradeResult) -> CompactExecution:
    return CompactExecution(
        event_id=result.event_id,
        execution_config_version=result.execution_config_version,
        result_sha256=sha256(result),
        status=result.status,
        reason=result.reason,
        holding_sessions=result.holding_sessions,
        gross_return=result.gross_return,
        net_return=result.net_return,
        trading_cost=result.trading_cost,
        borrow_cost=result.borrow_cost,
        mae=result.mae,
        mfe=result.mfe,
    )


def _summary(manifest_combinations: Sequence[Combination], reports: dict[str, Any]) -> bytes:
    lines = []
    for combination in manifest_combinations:
        report = reports[combination.key]
        for rung in RUNG_ORDER:
            record = report["natural_rungs"][rung]
            if record.get("status") == "NOT_RUN":
                lines.append(
                    f"| {combination.key} | {rung} | {record['population_n']} | not run "
                    "| - | - | - |"
                )
                continue
            economics = record["selected_economics"]
            mean = economics["mean_net_return"]
            lines.append(
                f"| {combination.key} | {rung} | {record['population_n']} | "
                f"{record['selected_n']} | {economics['priced_n']} | "
                f"{economics['unknown_return_n']} | "
                f"{f'{mean:.6f}' if isinstance(mean, float) else 'undefined'} |"
            )
    return (
        "# Historical strategy ladder (post-hoc development assessment)\n\n"
        "Accepted-generation 2022-2023 development assessment under the Decision 35 "
        "frozen execution policy. These were observed development years; this is "
        "not a final-test result. Full System is not run until an accepted controller "
        "generation exists. Returns are fractions of event entry gross notional for "
        "COMPLETE selected trades only; unknown executions keep their counts and are "
        "never zero. See `reports.json` for denominators, labels and comparisons.\n\n"
        "| Combination | Strategy | Rows | Selected | Priced selected | "
        "Unknown selected return | Mean selected net return |\n"
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |\n" + "\n".join(lines) + "\n"
    ).encode()


def _check_inputs(
    sources: HistoricalSources, configs: Path
) -> tuple[list[ExecutionConfig], list[HistoricalSpec], PolicySetDocument]:
    binding = sources.binding
    if binding.acceptance != "ACCEPTED":
        raise ValueError("Historical experiments require an accepted generation binding")
    headline, sensitivities = load_headline(configs), load_sensitivities(configs)
    policies = [
        policy
        for policy in expand_policies(headline, sensitivities)
        if policy.horizon_sessions == binding.horizon_sessions
    ]
    if not policies:
        raise ValueError("No frozen execution policy matches the bound horizon")
    thresholds = (
        sensitivities.headline_trading_threshold,
        *sensitivities.sensitivity_trading_thresholds,
    )
    specs = [default_spec(sources, status="FROZEN", threshold=value) for value in thresholds]
    document = PolicySetDocument(
        headline_file_sha256=checksum((configs / HEADLINE_CONFIG).read_bytes()),
        sensitivities_file_sha256=checksum((configs / SENSITIVITY_CONFIG).read_bytes()),
        policies=tuple(policies),
    )
    return policies, specs, document


def _compute(
    sources: HistoricalSources, configs: Path
) -> tuple[dict[str, bytes], tuple[Combination, ...], int]:
    """All artifacts from bound sources and frozen configs; deterministic."""
    policies, specs, policy_document = _check_inputs(sources, configs)
    primary = policies[0]
    events, partitions, suppressed = build_historical_events(sources, specs[0])
    inventory = InventoryDocument(
        events=tuple(
            EventIdentity(
                event_id=event.state.event_id,
                pair_id=event.state.pair_id,
                signal_at=event.state.signal_at.isoformat(),
                partition=cast(Partition | None, partition),
                state_sha256=sha256(event.state),
                request_sha256=sha256(event.request),
            )
            for event, partition in zip(events, partitions, strict=True)
        ),
        suppressed=suppressed,
    )
    labels, unavailable = historical_labels(sources, specs[0], events)
    selected = {
        _threshold(spec): [select_historical_event(event, spec) for event in events]
        for spec in specs
    }
    fresh = {
        event.state.event_id: raw_fresh
        for event, (raw_fresh, _) in zip(events, selected[_threshold(specs[0])], strict=True)
    }
    for rows in selected.values():
        if any(
            fresh[event.state.event_id] != raw for event, (raw, _) in zip(events, rows, strict=True)
        ):
            raise ValueError("Freshness must not depend on the trading threshold")
    combinations = [
        Combination(
            key=_key(_threshold(specs[0]), primary.version),
            threshold=_threshold(specs[0]),
            execution_config_version=primary.version,
            role="HEADLINE",
        )
    ]
    combinations += [
        Combination(
            key=_key(_threshold(spec), primary.version),
            threshold=_threshold(spec),
            execution_config_version=primary.version,
            role="THRESHOLD_SENSITIVITY",
        )
        for spec in specs[1:]
    ]
    reports: dict[str, Any] = {}

    def execute(policy: ExecutionConfig) -> dict[str, PairTradeResult]:
        return {
            event.state.event_id: simulate_pair_trade(event.request, policy)
            for event in events
            if fresh[event.state.event_id]
        }

    def report(spec: HistoricalSpec, results: dict[str, PairTradeResult]) -> dict[str, Any]:
        rows = [
            LadderRow(
                event_id=event.state.event_id,
                pair_id=event.state.pair_id,
                signal_at=event.state.signal_at,
                state_sha256=sha256(event.state),
                request_sha256=sha256(event.request),
                raw_fresh=raw_fresh,
                selections=selections,
                execution=results.get(event.state.event_id),
            )
            for event, (raw_fresh, selections) in zip(
                events, selected[_threshold(spec)], strict=True
            )
        ]
        return build_comparison_report(
            events, rows, spec.ladder, labels=labels, historical_spec=spec
        )

    primary_results = execute(primary)
    for combination in combinations:
        spec = next(item for item in specs if _threshold(item) == combination.threshold)
        reports[combination.key] = report(spec, primary_results)
    compact: list[CompactExecution] = []
    for policy in policies[1:]:
        results = execute(policy)
        combination = Combination(
            key=_key(_threshold(specs[0]), policy.version),
            threshold=_threshold(specs[0]),
            execution_config_version=policy.version,
            role="EXECUTION_SENSITIVITY",
        )
        combinations.append(combination)
        reports[combination.key] = report(specs[0], results)
        compact += [
            _compact(results[event.state.event_id])
            for event in events
            if fresh[event.state.event_id]
        ]
        del results
    selections = SelectionsDocument(
        thresholds=tuple(
            ThresholdSelections(
                threshold=_threshold(spec),
                spec_sha256=sha256(spec),
                rows=tuple(
                    SelectionRow(event_id=event.state.event_id, raw_fresh=raw, selections=chosen)
                    for event, (raw, chosen) in zip(events, selected[_threshold(spec)], strict=True)
                ),
            )
            for spec in specs
        )
    )
    artifacts = {
        "binding.json": canonical_bytes(sources.binding),
        "policies.json": canonical_bytes(policy_document),
        "specs.json": canonical_bytes(SpecsDocument(specs=tuple(specs))),
        "inventory.json": canonical_bytes(inventory),
        "labels.json": canonical_bytes(LabelsDocument(labels=labels, unavailable=unavailable)),
        "selections.json": canonical_bytes(selections),
        "executions-primary.json": canonical_bytes(
            PrimaryExecutionsDocument(
                execution_config_sha256=sha256(primary),
                results=tuple(
                    primary_results[event.state.event_id]
                    for event in events
                    if fresh[event.state.event_id]
                ),
            )
        ),
        "executions-sensitivity.json": canonical_bytes(
            SensitivityExecutionsDocument(results=tuple(compact))
        ),
        "reports.json": json_bytes(reports),
    }
    artifacts["summary.md"] = _summary(combinations, reports)
    return artifacts, tuple(combinations), len(events)


def _identity(binding: GenerationBinding, artifacts: dict[str, bytes]) -> HistoricalIdentity:
    return HistoricalIdentity(
        binding=binding,
        inputs=tuple(
            ArtifactBinding(
                path=name, sha256=checksum(artifacts[name]), size_bytes=len(artifacts[name])
            )
            for name in INPUT_NAMES
        ),
        sources=source_bindings(),
        python_version=platform.python_version(),
        runtime=runtime_bindings(),
    )


def run_historical_experiment(sources: HistoricalSources, configs: Path, output_dir: Path) -> Path:
    """Publish every artifact, then the manifest last, in a content-addressed directory."""
    sources_before, runtime_before = source_bindings(), runtime_bindings()
    artifacts, combinations, event_count = _compute(sources, configs)
    identity = _identity(sources.binding, artifacts)
    if identity.sources != sources_before or identity.runtime != runtime_before:
        raise ValueError("Historical experiment source or runtime changed during computation")
    if any(len(raw) > MAX_ARTIFACT_BYTES for raw in artifacts.values()):
        raise ValueError("Historical experiment artifact exceeds its bounded size")
    experiment_id = checksum(canonical_bytes(identity))
    manifest = HistoricalManifest(
        experiment_id=experiment_id,
        identity=identity,
        horizon_sessions=sources.binding.horizon_sessions,
        event_count=event_count,
        combinations=combinations,
        artifacts=tuple(
            ArtifactBinding(
                path=name, sha256=checksum(artifacts[name]), size_bytes=len(artifacts[name])
            )
            for name in ARTIFACT_NAMES
        ),
    )
    directory = output_dir / "historical-experiments" / experiment_id
    for name in ARTIFACT_NAMES:
        write_bytes(directory / name, artifacts[name])
    return write_bytes(directory / "manifest.json", canonical_bytes(manifest))


def read_manifest(manifest_path: Path) -> HistoricalManifest:
    if manifest_path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Historical manifest exceeds its bounded size")
    raw = manifest_path.read_bytes()
    strict_json(raw)
    return HistoricalManifest.model_validate_json(raw)


def verify_historical_experiment(
    manifest_path: Path, sources: HistoricalSources, configs: Path
) -> dict[str, object]:
    """Check stored bytes, then rebuild every artifact from the bound sources."""
    manifest = read_manifest(manifest_path)
    directory = manifest_path.resolve().parent
    if directory.name != manifest.experiment_id:
        raise ValueError("Historical experiment directory is not content-addressed")
    stored: dict[str, bytes] = {}
    for item in manifest.artifacts:
        path = (directory / item.path).resolve()
        if not path.is_relative_to(directory) or path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("Historical artifact escapes or exceeds its declared inventory")
        raw = path.read_bytes()
        if checksum(raw) != item.sha256 or len(raw) != item.size_bytes:
            raise ValueError("Historical artifact checksum/size mismatch")
        stored[item.path] = raw
    if sources.binding != manifest.identity.binding:
        raise ValueError("Verification sources do not reproduce the bound generations")
    if _identity(sources.binding, stored) != manifest.identity:
        raise ValueError("Historical input, source or runtime identity differs from this verifier")
    _, _, policy_document = _check_inputs(sources, configs)
    if canonical_bytes(policy_document) != stored["policies.json"]:
        raise ValueError("Frozen execution configs differ from the bound policy set")
    artifacts, combinations, event_count = _compute(sources, configs)
    if combinations != manifest.combinations or event_count != manifest.event_count:
        raise ValueError("Historical combinations or event count differ on replay")
    if any(artifacts[name] != stored[name] for name in ARTIFACT_NAMES):
        raise ValueError("Historical outputs do not match independent deterministic replay")
    if _identity(sources.binding, artifacts) != manifest.identity:
        raise ValueError("Historical source or runtime changed during verification")
    return {
        "status": "VERIFIED_HISTORICAL_REPLAY",
        "experiment_id": manifest.experiment_id,
        "evaluation_version": manifest.identity.binding.evaluation.version,
        "primary_version": manifest.identity.binding.primary_version,
        "horizon_sessions": manifest.horizon_sessions,
        "event_count": manifest.event_count,
        "combinations": len(manifest.combinations),
        "post_hoc_development": True,
        "full_system": "NOT_RUN",
        "final_test_unlocked": False,
    }
