"""Explicit immutable fixture experiments and independent deterministic replay."""

import hashlib
import importlib.metadata
import json
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from structural_break.backtest.contracts import SHA256, ExecutionConfig, FrozenModel, Identifier
from structural_break.backtest.ladder import evaluate_ladder
from structural_break.backtest.ladder_contracts import (
    RUNG_ORDER,
    EvaluationLabel,
    LadderEvent,
    LadderPolicy,
    LadderRow,
)
from structural_break.backtest.reporting import build_comparison_report
from structural_break.backtest.simulator import canonical_bytes
from structural_break.storage.files import write_bytes

EXPERIMENT_VERSION = "pair-ladder-experiment-v1"
ARTIFACT_NAMES = (
    "input.json",
    "policy.json",
    "execution-config.json",
    "labels.json",
    "rows.json",
    "report.json",
    "summary.md",
)
MAX_DOCUMENT_BYTES = 64_000_000


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_bounded(path: Path) -> bytes:
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Ladder artifact exceeds its bounded document size")
    raw = path.read_bytes()
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Ladder artifact exceeds its bounded document size")
    return raw


def strict_json(raw: bytes) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate ladder artifact JSON key")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"Nonfinite ladder artifact JSON constant: {value}")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)


class LadderInputDocument(FrozenModel):
    schema_version: Literal["pair-ladder-input-v1"] = "pair-ladder-input-v1"
    events: Annotated[tuple[LadderEvent, ...], Field(min_length=1, max_length=100_000)]

    @model_validator(mode="after")
    def unique_synthetic_inputs(self) -> Self:
        if len({event.state.event_id for event in self.events}) != len(self.events):
            raise ValueError("Ladder event identities must be unique")
        if any(event.request.data_kind != "SYNTHETIC_FIXTURE" for event in self.events):
            raise ValueError("Genuine captured ladder adapters are not implemented")
        return self


class LadderLabelDocument(FrozenModel):
    schema_version: Literal["pair-ladder-labels-v1"] = "pair-ladder-labels-v1"
    labels: Annotated[tuple[EvaluationLabel, ...], Field(max_length=100_000)] = ()


class LadderRowsDocument(FrozenModel):
    schema_version: Literal["pair-ladder-rows-v1"] = "pair-ladder-rows-v1"
    rows: Annotated[tuple[LadderRow, ...], Field(min_length=1, max_length=100_000)]


class SourceBinding(FrozenModel):
    path: Identifier
    sha256: SHA256


class RuntimeBinding(FrozenModel):
    package: Identifier
    version: Identifier


class ExperimentIdentity(FrozenModel):
    version: Literal["pair-ladder-experiment-v1"] = "pair-ladder-experiment-v1"
    mode: Literal["SYNTHETIC_FIXTURE"] = "SYNTHETIC_FIXTURE"
    input_sha256: SHA256
    policy_sha256: SHA256
    execution_config_sha256: SHA256
    labels_sha256: SHA256
    sources: tuple[SourceBinding, ...]
    python_version: Identifier
    runtime: tuple[RuntimeBinding, ...]


class ArtifactBinding(FrozenModel):
    path: Identifier
    sha256: SHA256
    size_bytes: Annotated[int, Field(ge=0, le=MAX_DOCUMENT_BYTES)]


class ExperimentManifest(FrozenModel):
    schema_version: Literal["pair-ladder-experiment-v1"] = "pair-ladder-experiment-v1"
    experiment_id: SHA256
    identity: ExperimentIdentity
    status: Literal["COMPLETE"] = "COMPLETE"
    population_id: Identifier
    policy_version: Identifier
    horizon_sessions: Literal[10, 20, 30]
    event_count: Annotated[int, Field(ge=1)]
    scientific_acceptance: Literal[False] = False
    genuine_quality_evidence: Literal[False] = False
    final_test_unlocked: Literal[False] = False
    artifacts: tuple[ArtifactBinding, ...]

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        if self.experiment_id != checksum(canonical_bytes(self.identity)):
            raise ValueError("Ladder experiment identity checksum mismatch")
        if tuple(binding.path for binding in self.artifacts) != ARTIFACT_NAMES:
            raise ValueError("Ladder artifact inventory must contain every canonical file")
        return self


def source_bindings() -> tuple[SourceBinding, ...]:
    package = Path(__file__).resolve().parents[1]
    names = (
        "backtest/contracts.py",
        "backtest/simulator.py",
        "backtest/ladder_contracts.py",
        "backtest/ladder.py",
        "backtest/reporting.py",
        "backtest/experiment.py",
        "backtest/cli.py",
        "agents/contracts.py",
        "ml/model.py",
    )
    return tuple(
        SourceBinding(
            path=name, sha256=checksum((package / name).read_bytes().replace(b"\r\n", b"\n"))
        )
        for name in names
    )


def runtime_bindings() -> tuple[RuntimeBinding, ...]:
    return tuple(
        RuntimeBinding(package=name, version=importlib.metadata.version(name))
        for name in ("pydantic", "numpy", "pandas", "scikit-learn", "exchange-calendars")
    )


def _identity(artifacts: dict[str, bytes]) -> ExperimentIdentity:
    return ExperimentIdentity(
        input_sha256=checksum(artifacts["input.json"]),
        policy_sha256=checksum(artifacts["policy.json"]),
        execution_config_sha256=checksum(artifacts["execution-config.json"]),
        labels_sha256=checksum(artifacts["labels.json"]),
        sources=source_bindings(),
        python_version=platform.python_version(),
        runtime=runtime_bindings(),
    )


def _summary(report: dict[str, object]) -> bytes:
    # The numeric JSON is canonical. This small technical preview does not claim
    # a portfolio equity series or interpret synthetic outcomes as usefulness.
    natural = report.get("natural_rungs")
    if not isinstance(natural, dict):
        raise ValueError("Comparison report has no canonical rung summaries")
    lines = []
    for rung in RUNG_ORDER:
        record = natural.get(rung)
        if not isinstance(record, dict):
            raise ValueError("Comparison report is missing a rung")
        economics = record.get("selected_economics")
        if not isinstance(economics, dict):
            raise ValueError("Comparison report has no execution coverage summary")
        mean_net = economics.get("mean_net_return")
        mean_text = f"{mean_net:.6f}" if isinstance(mean_net, (float, int)) else "undefined"
        lines.append(
            f"| {rung} | {record['population_n']} | {record['selected_n']} | "
            f"{record['unavailable_n']} | {economics['priced_n']} | "
            f"{economics['unknown_return_n']} | {mean_text} |"
        )
    content = (
        "# Synthetic strategy comparison\n\n"
        "Engineering fixture only. These invented observations do not establish "
        "predictive improvement, agent quality or economic profitability.\n\n"
        "All five filters share one event simulator and execution policy. "
        "Missing labels and executions retain their denominators. "
        "See `report.json` for natural and matched populations and exact counts.\n\n"
        "| Strategy | Input rows | Selected | Unavailable decision | Priced selected | "
        "Unknown selected return | Mean selected net return |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n"
        + "\n".join(lines)
        + "\n\nReturns are fractions of event entry gross notional, conditional on "
        "completed execution. Unknown executions retain their counts and do not "
        "receive zero returns. These event means are not portfolio returns.\n\n"
        "The common A/B population requires both scores, rather than both filters "
        "accepting the event. The scheduled B/Full comparison retains missing "
        "controller records and failed/abstained investigations. NO TRADE vetoes "
        "are reported separately from REVIEW, ABSTAIN and unscheduled events. "
        "No semantic human evaluation or statistical uncertainty is claimed.\n"
    )
    return content.encode()


def run_ladder_experiment(
    events: Sequence[LadderEvent],
    policy: LadderPolicy,
    execution_config: ExecutionConfig,
    output_dir: Path,
    *,
    labels: Sequence[EvaluationLabel] = (),
) -> Path:
    """Publish all rows/report together, with the manifest written last."""
    inputs = LadderInputDocument(events=tuple(events))
    label_document = LadderLabelDocument(labels=tuple(labels))
    sources_before = source_bindings()
    runtime_before = runtime_bindings()
    rows = evaluate_ladder(inputs.events, policy, execution_config)
    report = build_comparison_report(inputs.events, rows, policy, labels=label_document.labels)
    artifacts = {
        "input.json": canonical_bytes(inputs),
        "policy.json": canonical_bytes(policy),
        "execution-config.json": canonical_bytes(execution_config),
        "labels.json": canonical_bytes(label_document),
        "rows.json": canonical_bytes(LadderRowsDocument(rows=rows)),
        "report.json": json_bytes(report),
        "summary.md": _summary(report),
    }
    identity = _identity(artifacts)
    if identity.sources != sources_before or identity.runtime != runtime_before:
        raise ValueError("Ladder source or runtime changed during computation")
    experiment_id = checksum(canonical_bytes(identity))
    manifest = ExperimentManifest(
        experiment_id=experiment_id,
        identity=identity,
        population_id=policy.population_id,
        policy_version=policy.version,
        horizon_sessions=policy.horizon_sessions,
        event_count=len(inputs.events),
        artifacts=tuple(
            ArtifactBinding(
                path=name, sha256=checksum(artifacts[name]), size_bytes=len(artifacts[name])
            )
            for name in ARTIFACT_NAMES
        ),
    )
    directory = output_dir / "experiments" / experiment_id
    for name in ARTIFACT_NAMES:
        write_bytes(directory / name, artifacts[name])
    return write_bytes(directory / "manifest.json", canonical_bytes(manifest))


def verify_ladder_experiment(manifest_path: Path) -> dict[str, object]:
    """Verify file/code/runtime identities, then independently reconstruct outputs."""
    raw_manifest = read_bounded(manifest_path)
    strict_json(raw_manifest)
    manifest = ExperimentManifest.model_validate_json(raw_manifest)
    directory = manifest_path.resolve().parent
    artifacts: dict[str, bytes] = {}
    for binding in manifest.artifacts:
        path = (directory / binding.path).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("Ladder artifact escapes its declared inventory")
        raw = read_bounded(path)
        if checksum(raw) != binding.sha256 or len(raw) != binding.size_bytes:
            raise ValueError("Ladder artifact checksum/size mismatch")
        artifacts[binding.path] = raw
    if _identity(artifacts) != manifest.identity:
        raise ValueError("Ladder input, source or runtime identity differs from this verifier")
    for name in ARTIFACT_NAMES:
        if name.endswith(".json"):
            strict_json(artifacts[name])
    inputs = LadderInputDocument.model_validate_json(artifacts["input.json"])
    policy = LadderPolicy.model_validate_json(artifacts["policy.json"])
    config = ExecutionConfig.model_validate_json(artifacts["execution-config.json"])
    labels = LadderLabelDocument.model_validate_json(artifacts["labels.json"])
    if (
        manifest.population_id != policy.population_id
        or manifest.policy_version != policy.version
        or manifest.horizon_sessions != policy.horizon_sessions
        or manifest.event_count != len(inputs.events)
    ):
        raise ValueError("Ladder manifest population/policy binding mismatch")
    rows = evaluate_ladder(inputs.events, policy, config)
    report = build_comparison_report(inputs.events, rows, policy, labels=labels.labels)
    expected = {
        "rows.json": canonical_bytes(LadderRowsDocument(rows=rows)),
        "report.json": json_bytes(report),
        "summary.md": _summary(report),
    }
    if any(artifacts[name] != raw for name, raw in expected.items()):
        raise ValueError("Ladder outputs do not match independent deterministic replay")
    if _identity(artifacts) != manifest.identity:
        raise ValueError("Ladder source or runtime changed during verification")
    return {
        "status": "VERIFIED_SYNTHETIC_REPLAY",
        "experiment_id": manifest.experiment_id,
        "event_count": manifest.event_count,
        "mode": manifest.identity.mode,
        "scientific_acceptance": False,
        "genuine_quality_evidence": False,
        "final_test_unlocked": False,
    }
