"""Immutable engineering bundle for slices, cost grids and portfolio accounting."""

import platform
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from structural_break.backtest.contracts import SHA256, ExecutionConfig, FrozenModel
from structural_break.backtest.costs import CostGridPolicy, cost_sensitivity_report
from structural_break.backtest.experiment import (
    ArtifactBinding,
    LadderInputDocument,
    LadderLabelDocument,
    LadderRowsDocument,
    RuntimeBinding,
    SourceBinding,
    checksum,
    json_bytes,
    read_bounded,
    runtime_bindings,
    source_bindings,
    strict_json,
)
from structural_break.backtest.ladder import evaluate_ladder
from structural_break.backtest.ladder_contracts import LadderPolicy
from structural_break.backtest.ladder_fixtures import fixture_ladder
from structural_break.backtest.portfolio import (
    PortfolioPolicy,
    PortfolioProposal,
    simulate_portfolio,
)
from structural_break.backtest.portfolio_fixtures import fixture_portfolio
from structural_break.backtest.reporting import build_comparison_report
from structural_break.backtest.robustness import (
    PointInTimeContext,
    RobustnessPolicy,
    build_robustness_report,
    fixture_contexts,
)
from structural_break.backtest.simulator import canonical_bytes
from structural_break.backtest.uncertainty import EconomicBootstrapPolicy, paired_month_bootstrap
from structural_break.storage.files import write_bytes

INPUT_NAMES = (
    "ladder-input.json",
    "ladder-policy.json",
    "execution-config.json",
    "labels.json",
    "contexts.json",
    "robustness-policy.json",
    "bootstrap-policy.json",
    "cost-grid.json",
    "portfolio-input.json",
    "portfolio-policy.json",
    "portfolio-execution-config.json",
)
OUTPUT_NAMES = (
    "ladder-rows.json",
    "comparison-report.json",
    "robustness-report.json",
    "uncertainty-report.json",
    "cost-report.json",
    "portfolio-result.json",
    "summary.md",
)
ARTIFACT_NAMES = (*INPUT_NAMES, *OUTPUT_NAMES)


class ContextDocument(FrozenModel):
    schema_version: Literal["phase6-context-document-v1"] = "phase6-context-document-v1"
    contexts: Annotated[tuple[PointInTimeContext, ...], Field(max_length=100_000)] = ()


class PortfolioInputDocument(FrozenModel):
    schema_version: Literal["phase6-portfolio-input-v1"] = "phase6-portfolio-input-v1"
    proposals: Annotated[tuple[PortfolioProposal, ...], Field(min_length=1, max_length=100_000)]

    @model_validator(mode="after")
    def unique_proposals(self) -> Self:
        if len({p.request.event_id for p in self.proposals}) != len(self.proposals):
            raise ValueError("Portfolio input event identities must be unique")
        return self


class AnalysisIdentity(FrozenModel):
    version: Literal["phase6-analysis-v1"] = "phase6-analysis-v1"
    mode: Literal["SYNTHETIC_FIXTURE"] = "SYNTHETIC_FIXTURE"
    inputs: tuple[ArtifactBinding, ...]
    sources: tuple[SourceBinding, ...]
    python_version: str
    runtime: tuple[RuntimeBinding, ...]

    @model_validator(mode="after")
    def input_inventory(self) -> Self:
        if tuple(binding.path for binding in self.inputs) != INPUT_NAMES:
            raise ValueError("Analysis identity requires the exact canonical input inventory")
        return self


class AnalysisManifest(FrozenModel):
    schema_version: Literal["phase6-analysis-v1"] = "phase6-analysis-v1"
    analysis_id: SHA256
    identity: AnalysisIdentity
    status: Literal["COMPLETE"] = "COMPLETE"
    ladder_events_n: Annotated[int, Field(ge=1)]
    portfolio_proposals_n: Annotated[int, Field(ge=1)]
    artifacts: tuple[ArtifactBinding, ...]
    scientific_acceptance: Literal[False] = False
    final_test_unlocked: Literal[False] = False

    @model_validator(mode="after")
    def exact_inventory(self) -> Self:
        if self.analysis_id != checksum(canonical_bytes(self.identity)):
            raise ValueError("Analysis identity checksum mismatch")
        if tuple(binding.path for binding in self.artifacts) != ARTIFACT_NAMES:
            raise ValueError("Analysis requires the exact canonical artifact inventory")
        return self


def _sources() -> tuple[SourceBinding, ...]:
    package = Path(__file__).resolve().parents[1]
    names = (
        "backtest/costs.py",
        "backtest/robustness.py",
        "backtest/uncertainty.py",
        "backtest/portfolio.py",
        "backtest/analysis.py",
    )
    return (
        *source_bindings(),
        *(
            SourceBinding(
                path=name, sha256=checksum((package / name).read_bytes().replace(b"\r\n", b"\n"))
            )
            for name in names
        ),
    )


def _bindings(names: tuple[str, ...], artifacts: dict[str, bytes]) -> tuple[ArtifactBinding, ...]:
    return tuple(
        ArtifactBinding(
            path=name, sha256=checksum(artifacts[name]), size_bytes=len(artifacts[name])
        )
        for name in names
    )


def _identity(artifacts: dict[str, bytes]) -> AnalysisIdentity:
    return AnalysisIdentity(
        inputs=_bindings(INPUT_NAMES, artifacts),
        sources=_sources(),
        python_version=platform.python_version(),
        runtime=runtime_bindings(),
    )


def fixture_analysis_inputs() -> dict[str, BaseModel]:
    events, policy, execution, labels = fixture_ladder()
    proposals, portfolio_policy, portfolio_execution = fixture_portfolio()
    return {
        "ladder-input.json": LadderInputDocument(events=events),
        "ladder-policy.json": policy,
        "execution-config.json": execution,
        "labels.json": LadderLabelDocument(labels=labels),
        "contexts.json": ContextDocument(contexts=fixture_contexts(events)),
        "robustness-policy.json": RobustnessPolicy(),
        "bootstrap-policy.json": EconomicBootstrapPolicy(),
        "cost-grid.json": CostGridPolicy(),
        "portfolio-input.json": PortfolioInputDocument(proposals=proposals),
        "portfolio-policy.json": portfolio_policy,
        "portfolio-execution-config.json": portfolio_execution,
    }


def _calculate(inputs: dict[str, bytes]) -> tuple[dict[str, bytes], int, int]:
    for name in INPUT_NAMES:
        strict_json(inputs[name])
    events = LadderInputDocument.model_validate_json(inputs["ladder-input.json"]).events
    policy = LadderPolicy.model_validate_json(inputs["ladder-policy.json"])
    execution = ExecutionConfig.model_validate_json(inputs["execution-config.json"])
    labels = LadderLabelDocument.model_validate_json(inputs["labels.json"]).labels
    contexts = ContextDocument.model_validate_json(inputs["contexts.json"]).contexts
    robustness_policy = RobustnessPolicy.model_validate_json(inputs["robustness-policy.json"])
    bootstrap_policy = EconomicBootstrapPolicy.model_validate_json(inputs["bootstrap-policy.json"])
    costs = CostGridPolicy.model_validate_json(inputs["cost-grid.json"])
    proposals = PortfolioInputDocument.model_validate_json(inputs["portfolio-input.json"]).proposals
    portfolio_policy = PortfolioPolicy.model_validate_json(inputs["portfolio-policy.json"])
    portfolio_execution = ExecutionConfig.model_validate_json(
        inputs["portfolio-execution-config.json"]
    )
    rows = evaluate_ladder(events, policy, execution)
    comparison = build_comparison_report(events, rows, policy, labels=labels)
    robustness = build_robustness_report(
        events, rows, policy, labels=labels, contexts=contexts, slice_policy=robustness_policy
    )
    uncertainty = paired_month_bootstrap(events, rows, policy, bootstrap_policy=bootstrap_policy)
    sensitivities = cost_sensitivity_report(events, policy, execution, costs, labels=labels)
    portfolio = simulate_portfolio(proposals, portfolio_policy, portfolio_execution)
    summary = (
        "# Synthetic robustness and portfolio checks\n\n"
        "These invented cases verify engineering. They do not establish Model B improvement, "
        "agent quality or profitability. Genuine historical integration and production "
        "execution/portfolio assumptions remain pending.\n\n"
        f"- Ladder inventory: {len(events)} events, with all five selection records retained.\n"
        f"- Cost grid: {sensitivities['scenario_n']} predeclared scenarios; "
        "selection is unchanged across costs.\n"
        "- Robustness: year, pair, sector, sign, coverage, stress and event-category slices; "
        "missing context remains UNKNOWN and small populations are flagged.\n"
        f"- Economic month bootstrap: {bootstrap_policy.replicates} paired seeded draws; "
        f"intervals require {bootstrap_policy.minimum_populated_months_for_interval} "
        "contributing populated months for each estimand. This is separate from "
        "the existing v2 forecast quarter bootstrap.\n"
        f"- Separate portfolio accounting fixture: {len(proposals)} proposals; "
        "fixed entry shares, chronological open/close valuation, costs and borrow, "
        "overlap/capacity and exposure. This is not a five-strategy portfolio assessment.\n\n"
        "See the bound JSON reports for complete counts, missing observations and "
        "valuation status. A missing held quote leaves subsequent NAV unknown. "
        "Portfolio gross exposure is capped at entry; passive price drift is disclosed "
        "rather than silently rebalanced. All scientific acceptance flags remain false; "
        "2024–2025 outcomes remain locked.\n"
    ).encode()
    return (
        {
            "ladder-rows.json": canonical_bytes(LadderRowsDocument(rows=rows)),
            "comparison-report.json": json_bytes(comparison),
            "robustness-report.json": json_bytes(robustness),
            "uncertainty-report.json": json_bytes(uncertainty),
            "cost-report.json": json_bytes(sensitivities),
            "portfolio-result.json": canonical_bytes(portfolio),
            "summary.md": summary,
        },
        len(events),
        len(proposals),
    )


def run_analysis(inputs: dict[str, BaseModel], output_dir: Path) -> Path:
    if tuple(inputs) != INPUT_NAMES:
        raise ValueError("Analysis requires the exact ordered input inventory")
    artifacts = {name: canonical_bytes(inputs[name]) for name in INPUT_NAMES}
    identity = _identity(artifacts)
    outputs, events_n, proposals_n = _calculate(artifacts)
    if identity != _identity(artifacts):
        raise ValueError("Analysis source/runtime changed during computation")
    artifacts.update(outputs)
    analysis_id = checksum(canonical_bytes(identity))
    manifest = AnalysisManifest(
        analysis_id=analysis_id,
        identity=identity,
        ladder_events_n=events_n,
        portfolio_proposals_n=proposals_n,
        artifacts=_bindings(ARTIFACT_NAMES, artifacts),
    )
    directory = output_dir / "analyses" / analysis_id
    for name in ARTIFACT_NAMES:
        write_bytes(directory / name, artifacts[name])
    return write_bytes(directory / "manifest.json", canonical_bytes(manifest))


def verify_analysis(manifest_path: Path) -> dict[str, object]:
    raw = read_bounded(manifest_path)
    strict_json(raw)
    manifest = AnalysisManifest.model_validate_json(raw)
    directory = manifest_path.resolve().parent
    artifacts: dict[str, bytes] = {}
    for binding in manifest.artifacts:
        path = (directory / binding.path).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("Analysis artifact escapes the declared inventory")
        data = read_bounded(path)
        if len(data) != binding.size_bytes or checksum(data) != binding.sha256:
            raise ValueError("Analysis artifact checksum/size mismatch")
        artifacts[binding.path] = data
    if _identity(artifacts) != manifest.identity:
        raise ValueError("Analysis inputs, source or runtime differ from this verifier")
    expected, events_n, proposals_n = _calculate(artifacts)
    if manifest.ladder_events_n != events_n or manifest.portfolio_proposals_n != proposals_n:
        raise ValueError("Analysis manifest population binding mismatch")
    if any(artifacts[name] != expected[name] for name in OUTPUT_NAMES):
        raise ValueError("Analysis outputs differ from independent deterministic replay")
    if _identity(artifacts) != manifest.identity:
        raise ValueError("Analysis source/runtime changed during verification")
    return {
        "status": "VERIFIED_SYNTHETIC_ANALYSIS",
        "analysis_id": manifest.analysis_id,
        "ladder_events_n": events_n,
        "portfolio_proposals_n": proposals_n,
        "scientific_acceptance": False,
        "final_test_unlocked": False,
    }
