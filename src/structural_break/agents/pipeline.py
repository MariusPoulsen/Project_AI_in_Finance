"""Bounded historical debate with immutable role caches and Python authorization.

The explicit batch boundary consumes frozen inputs. It never downloads evidence,
fits models, observes outcomes, or runs from an ordinary application page.
"""

import hashlib
import importlib
import importlib.metadata
import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast

from pydantic import BaseModel, Field, ValidationError, model_validator

from structural_break.agents.contracts import (
    AdvocateReport,
    AgentInput,
    AgentPolicy,
    ControllerDecision,
    FrozenModel,
    ReasonCode,
    SynthesisReport,
    ValidationReport,
    validate_citations,
)
from structural_break.agents.prompts import PROMPT_VERSION, build_role_prompt
from structural_break.decision.agent_policy import (
    decide,
    failure_decision,
    preflight,
)
from structural_break.intelligence.extraction import ProviderFailure
from structural_break.storage.files import write_bytes

GRAPH_VERSION: Literal["phase5-bounded-debate-v1"] = "phase5-bounded-debate-v1"
RESULT_VERSION: Literal["phase5-investigation-v1"] = "phase5-investigation-v1"
ROLES = (
    "mean_reversion_opening",
    "structural_break_opening",
    "mean_reversion_rebuttal",
    "structural_break_rebuttal",
    "synthesis",
    "validation",
)
PROVIDER_FAILURE_CODES = frozenset(
    {
        "INVALID_AGENT_PROMPT_REQUEST",
        "INVALID_AGENT_PROMPT_PREDECESSORS",
        "AGENT_PROMPT_BOUNDS_EXCEEDED",
        "PROVIDER_REDIRECT_REJECTED",
        "PROVIDER_RESPONSE_TOO_LARGE",
        "INVALID_PROVIDER_RESPONSE",
        "INVALID_AGENT_ROLE",
        "INVALID_AGENT_PROVIDER_REQUEST",
        "INCOMPLETE_PROVIDER_RESPONSE",
        "PROVIDER_TIMEOUT",
        "PROVIDER_UNAVAILABLE",
        "REQUEST_BUDGET_EXHAUSTED",
        "DURABLE_DAY_BUDGET_EXHAUSTED",
        "UNREGISTERED_BUDGET_MODEL",
        "MOCK_RESPONSE_UNAVAILABLE",
        "PROVIDER_AUTHENTICATION_FAILED",
        "PROVIDER_QUOTA_OR_RATE_LIMIT",
        "PROVIDER_MODEL_UNAVAILABLE",
        "PROVIDER_REQUEST_REJECTED",
        "MISSING_PROVIDER_KEY",
    }
)
Role = Literal[
    "mean_reversion_opening",
    "structural_break_opening",
    "mean_reversion_rebuttal",
    "structural_break_rebuttal",
    "synthesis",
    "validation",
]
Report = AdvocateReport | SynthesisReport | ValidationReport


class RoleProvider(Protocol):
    @property
    def mode(self) -> str: ...

    @property
    def calls(self) -> int: ...

    def identity_for(self, role: str) -> dict[str, object]: ...

    def generate(
        self, role: str, prompt: str, output_schema: dict[str, object]
    ) -> dict[str, object]: ...


class StageRecord(FrozenModel):
    role: Role
    status: Literal["VALID", "FAILED", "SKIPPED"]
    report: Report | None = None
    error_code: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def coherent_stage(self) -> "StageRecord":
        if self.status == "VALID":
            if self.report is None or self.error_code is not None:
                raise ValueError("Valid stage must contain a report and no failure")
            check_role(self.role, self.report)
        elif self.report is not None or self.error_code is None:
            raise ValueError("Failed/skipped stage must contain a fixed failure code only")
        return self


class InvestigationResult(FrozenModel):
    schema_version: Literal["phase5-investigation-v1"] = RESULT_VERSION
    run_id: str
    graph_version: Literal["phase5-bounded-debate-v1"] = GRAPH_VERSION
    prompt_version: str
    mode: Literal["mock", "live"]
    input: AgentInput
    policy: AgentPolicy
    identity_json: str
    stages: tuple[StageRecord, ...] = Field(max_length=6)
    decision: ControllerDecision
    provider_calls: int = Field(ge=0)


class DebateState(TypedDict, total=False):
    mean_reversion_opening: StageRecord
    structural_break_opening: StageRecord
    mean_reversion_rebuttal: StageRecord
    structural_break_rebuttal: StageRecord
    synthesis: StageRecord
    validation: StageRecord


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def implementation_identity() -> dict[str, object]:
    """Invalidate caches for any implementation, schema, policy or runtime change."""
    package = Path(__file__).resolve().parents[1]
    paths = [
        package / "agents" / name
        for name in ("pipeline.py", "contracts.py", "providers.py", "prompts.py", "budgets.py")
    ] + [package / "decision/agent_policy.py"]
    return {
        "source_sha256": {
            path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        },
        "langgraph": importlib.metadata.version("langgraph"),
        "pydantic": importlib.metadata.version("pydantic"),
    }


def check_role(role: str, report: Report) -> None:
    if "opening" in role or "rebuttal" in role:
        expected_role = "MEAN_REVERSION" if role.startswith("mean") else "STRUCTURAL_BREAK"
        expected_stage = "OPENING" if role.endswith("opening") else "REBUTTAL"
        if not isinstance(report, AdvocateReport) or (
            report.role != expected_role or report.stage != expected_stage
        ):
            raise ValueError("Role/stage mismatch")
    elif role == "synthesis" and not isinstance(report, SynthesisReport):
        raise ValueError("Synthesis schema mismatch")
    elif role == "validation" and not isinstance(report, ValidationReport):
        raise ValueError("Validation schema mismatch")


def report_type(role: str) -> type[AdvocateReport] | type[SynthesisReport] | type[ValidationReport]:
    if role == "synthesis":
        return SynthesisReport
    if role == "validation":
        return ValidationReport
    return AdvocateReport


def _write_envelope(path: Path, payload: dict[str, object]) -> None:
    envelope = {"sha256": digest(payload), "payload": payload}
    write_bytes(path, (canonical_json(envelope) + "\n").encode())


def _read_envelope(path: Path) -> dict[str, object]:
    def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate agent cache keys")
            value[key] = item
        return value

    envelope = json.loads(path.read_bytes(), object_pairs_hook=unique_keys)
    if not isinstance(envelope, dict) or set(envelope) != {"sha256", "payload"}:
        raise ValueError("Invalid agent cache envelope")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or digest(payload) != envelope["sha256"]:
        raise ValueError("Agent cache checksum mismatch")
    return cast(dict[str, object], payload)


def run_investigation(
    event: AgentInput,
    policy: AgentPolicy,
    provider: RoleProvider,
    output_dir: Path,
    *,
    attempt_id: str = "initial",
) -> InvestigationResult:
    """Run at most six role calls, or replay validated cached outputs.

    Terminal failures are durable. A deliberate retry needs a new attempt ID;
    valid role outputs are retained. This avoids silently repeating failed jobs.
    Provider-owned transport retries count against its explicit call budget.
    """
    if provider.mode not in {"mock", "live"}:
        raise ValueError("Provider mode must be explicit")
    if policy.status == "FIXTURE" and provider.mode != "mock":
        raise ValueError("Fixture thresholds cannot authorize live investigation")
    if not attempt_id or len(attempt_id) > 80:
        raise ValueError("A bounded explicit attempt identity is required")
    identity = investigation_identity(event, policy, provider)
    run_id = digest({"identity": identity, "attempt_id": attempt_id})
    result_path = output_dir / "runs" / run_id / "result.json"
    if result_path.exists():
        stored = _read_envelope(result_path)
        result = InvestigationResult.model_validate_json(canonical_json(stored))
        verify_investigation(result, event, policy, provider, attempt_id=attempt_id)
        return result

    initial_calls = provider.calls
    early = preflight(event, policy)
    if early is not None:
        stages: tuple[StageRecord, ...] = ()
        decision = early
    else:
        graph = _build_graph(event, provider, output_dir, identity)
        state = cast(DebateState, graph.invoke({}, config={"max_concurrency": 2}))
        stages = tuple(state[cast(Role, role)] for role in ROLES)
        decision = _decision(event, policy, stages)
    result = InvestigationResult(
        run_id=run_id,
        prompt_version=PROMPT_VERSION,
        mode=cast(Literal["mock", "live"], provider.mode),
        input=event,
        policy=policy,
        identity_json=canonical_json(identity),
        stages=stages,
        decision=decision,
        provider_calls=provider.calls - initial_calls,
    )
    _write_envelope(result_path, result.model_dump(mode="json"))
    return result


def investigation_identity(
    event: AgentInput, policy: AgentPolicy, provider: RoleProvider
) -> dict[str, object]:
    """Stable exact binding shared by fresh runs and cheap checkpoint verification."""
    return {
        "input": event.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json"),
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "implementation": implementation_identity(),
        "provider": {role: provider.identity_for(role) for role in ROLES},
        "mode": provider.mode,
    }


def verify_investigation(
    result: InvestigationResult,
    event: AgentInput,
    policy: AgentPolicy,
    provider: RoleProvider,
    *,
    attempt_id: str = "initial",
) -> None:
    """Replay source grounding and Python policy without graph/provider/file replay."""
    identity = investigation_identity(event, policy, provider)
    if result.identity_json != canonical_json(identity):
        raise ValueError("Stored investigation identity mismatch")
    run_id = digest({"identity": identity, "attempt_id": attempt_id})
    _verify_result(result, event, policy, run_id, provider.mode)


def _decision(
    event: AgentInput, policy: AgentPolicy, stages: tuple[StageRecord, ...]
) -> ControllerDecision:
    if len(stages) != 6 or any(stage.status != "VALID" for stage in stages):
        code: ReasonCode = (
            "MECHANICAL_VALIDATION_FAILED"
            if any(stage.error_code == "MECHANICAL_VALIDATION_FAILED" for stage in stages)
            else "INVESTIGATION_BUDGET_EXHAUSTED"
            if any(
                stage.error_code in {"REQUEST_BUDGET_EXHAUSTED", "DURABLE_DAY_BUDGET_EXHAUSTED"}
                for stage in stages
            )
            else "AGENT_FAILURE"
        )
        return failure_decision(event, policy, code)
    reports = tuple(stage.report for stage in stages if stage.report is not None)
    if validate_citations(event, reports):
        return failure_decision(event, policy, "MECHANICAL_VALIDATION_FAILED")
    validation = stages[-1].report
    if not isinstance(validation, ValidationReport):
        return failure_decision(event, policy, "AGENT_FAILURE")
    return decide(event, policy, validation)


def _verify_result(
    result: InvestigationResult, event: AgentInput, policy: AgentPolicy, run_id: str, mode: str
) -> None:
    if result.input != event or result.policy != policy or result.run_id != run_id:
        raise ValueError("Cached investigation binding mismatch")
    if result.mode != mode or result.prompt_version != PROMPT_VERSION:
        raise ValueError("Cached investigation mode/prompt mismatch")
    if result.stages and tuple(stage.role for stage in result.stages) != ROLES:
        raise ValueError("Cached investigation stages mismatch")
    early = preflight(event, policy)
    expected = early if early is not None else _decision(event, policy, result.stages)
    if expected != result.decision:
        raise ValueError("Cached controller output is not reproducible")


class InvokableGraph(Protocol):
    def invoke(self, input: object, config: dict[str, object]) -> object: ...


def _build_graph(
    event: AgentInput,
    provider: RoleProvider,
    output_dir: Path,
    identity: dict[str, object],
) -> InvokableGraph:
    try:
        graph_module = importlib.import_module("langgraph.graph")
    except ImportError:
        raise RuntimeError(
            "Install the locked agents extra: uv sync --frozen --extra agents"
        ) from None
    builder = graph_module.StateGraph(DebateState)

    def make_node(role: Role, previous: tuple[str, ...]) -> Callable[[DebateState], DebateState]:
        def node(state: DebateState) -> DebateState:
            if any(state[cast(Role, name)].status != "VALID" for name in previous):
                record = StageRecord(role=role, status="SKIPPED", error_code="UPSTREAM_FAILURE")
                return cast(DebateState, {role: record})
            prior = {
                name: cast(BaseModel, state[cast(Role, name)].report).model_dump(mode="json")
                for name in previous
            }
            try:
                schema = report_type(role).model_json_schema()
                prompt = build_role_prompt(role, event.model_dump(mode="json"), prior or None)
                request: dict[str, object] = {
                    "identity": identity,
                    "role": role,
                    "prompt": prompt,
                    "schema": schema,
                }
                cache_path = output_dir / "roles" / f"{digest(request)}.json"
                if cache_path.exists():
                    cached = _read_envelope(cache_path)
                    if cached.get("request_sha256") != digest(request):
                        raise ValueError("Role request binding mismatch")
                    report = report_type(role).model_validate_json(canonical_json(cached["report"]))
                else:
                    payload = provider.generate(role, prompt, schema)
                    report = report_type(role).model_validate_json(canonical_json(payload))
                check_role(role, report)
                if validate_citations(event, (report,)):
                    record = StageRecord(
                        role=role, status="FAILED", error_code="MECHANICAL_VALIDATION_FAILED"
                    )
                else:
                    if not cache_path.exists():
                        _write_envelope(
                            cache_path,
                            {
                                "request_sha256": digest(request),
                                "report": report.model_dump(mode="json"),
                            },
                        )
                    record = StageRecord(role=role, status="VALID", report=report)
            except ProviderFailure as exc:
                code = exc.reason if exc.reason in PROVIDER_FAILURE_CODES else "PROVIDER_FAILURE"
                record = StageRecord(role=role, status="FAILED", error_code=code)
            except (ValidationError, ValueError, KeyError, TypeError):
                record = StageRecord(role=role, status="FAILED", error_code="INVALID_ROLE_OUTPUT")
            except Exception:
                # Do not persist credential-bearing provider errors or source prose.
                record = StageRecord(role=role, status="FAILED", error_code="AGENT_RUNTIME_FAILURE")
            return cast(DebateState, {role: record})

        return node

    openings = ROLES[:2]
    debate = ROLES[:4]
    for role in ROLES:
        previous: tuple[str, ...] = (
            () if role in openings else openings if role in ROLES[2:4] else debate
        )
        if role == "validation":
            previous = ROLES[:5]
        builder.add_node(role, make_node(cast(Role, role), previous))
    for opening in openings:
        builder.add_edge(graph_module.START, opening)
    for rebuttal in ROLES[2:4]:
        builder.add_edge(list(openings), rebuttal)
    builder.add_edge(list(ROLES[2:4]), "synthesis")
    builder.add_edge("synthesis", "validation")
    builder.add_edge("validation", graph_module.END)
    return cast(InvokableGraph, builder.compile())
