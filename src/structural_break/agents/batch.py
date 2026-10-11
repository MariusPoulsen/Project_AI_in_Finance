"""Target-blind frozen scheduling, resumable checkpoints and complete denominators.

This is explicit analytical orchestration. It consumes immutable analyst inputs;
it cannot download data, fit models, select on outcomes or unlock final tests.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal, Self, cast

from pydantic import Field, model_validator

from structural_break.agents.budgets import (
    ExclusiveLease,
    canonical,
    fingerprint,
    read_envelope,
    write_envelope,
)
from structural_break.agents.contracts import (
    SHA256,
    AgentInput,
    AgentPolicy,
    ControllerDecision,
    FrozenModel,
    Identifier,
)
from structural_break.agents.pipeline import (
    GRAPH_VERSION,
    ROLES,
    InvestigationResult,
    RoleProvider,
    implementation_identity,
    run_investigation,
    verify_investigation,
)
from structural_break.agents.prompts import PROMPT_VERSION
from structural_break.decision.agent_policy import failure_decision, preflight

SCHEDULE_VERSION: Literal["phase5-target-blind-schedule-v1"] = "phase5-target-blind-schedule-v1"
BATCH_VERSION: Literal["phase5-resumable-batch-v1"] = "phase5-resumable-batch-v1"
Disposition = Literal["INVESTIGATED", "PREFLIGHT_SKIP", "NOT_SCHEDULED", "BUDGET_EXHAUSTED"]


class ScheduleRow(FrozenModel):
    ordinal: Annotated[int, Field(ge=0)]
    event_id: Identifier
    pair_id: Identifier
    event_timestamp: datetime
    input_sha256: SHA256
    eligible: bool
    selected: bool
    preflight_decision: ControllerDecision | None


def _selection_key(seed: str, event_id: str, pair_id: str, timestamp: datetime) -> str:
    # Deliberately excludes probabilities, features, source content and outcomes.
    return fingerprint(
        {
            "seed": seed,
            "event_id": event_id,
            "pair_id": pair_id,
            "event_timestamp": timestamp.isoformat(),
        }
    )


class FrozenSchedule(FrozenModel):
    version: Literal["phase5-target-blind-schedule-v1"] = SCHEDULE_VERSION
    seed: Identifier
    max_investigations: Annotated[int, Field(ge=0)] | None
    policy_sha256: SHA256
    rows: tuple[ScheduleRow, ...] = Field(min_length=1)

    @cached_property
    def schedule_id(self) -> str:
        return fingerprint(self.model_dump(mode="json"))

    @cached_property
    def eligible_count(self) -> int:
        return sum(row.eligible for row in self.rows)

    @cached_property
    def selected_count(self) -> int:
        return sum(row.selected for row in self.rows)

    @model_validator(mode="after")
    def coherent_selection(self) -> Self:
        if len({row.event_id for row in self.rows}) != len(self.rows):
            raise ValueError("Schedule must preserve unique event identifiers")
        order = sorted(
            self.rows,
            key=lambda row: (
                _selection_key(self.seed, row.event_id, row.pair_id, row.event_timestamp),
                row.event_id,
            ),
        )
        if tuple(order) != self.rows or [row.ordinal for row in self.rows] != list(
            range(len(self.rows))
        ):
            raise ValueError("Schedule order must be the frozen target-blind hash order")
        selected_count = 0
        for row in self.rows:
            if (
                row.event_timestamp.utcoffset() is None
                or row.event_timestamp.astimezone(UTC).year >= 2024
            ):
                raise ValueError("Schedules require explicit development timestamps")
            if row.eligible != (row.preflight_decision is None):
                raise ValueError("Schedule eligibility differs from deterministic preflight")
            selected = row.eligible and (
                self.max_investigations is None or selected_count < self.max_investigations
            )
            if row.selected != selected:
                raise ValueError("Schedule selection differs from its frozen cap")
            selected_count += int(selected)
        return self


def freeze_schedule(
    events: Sequence[AgentInput],
    policy: AgentPolicy,
    *,
    seed: str = "phase5-target-blind-v1",
    max_investigations: int | None = None,
) -> FrozenSchedule:
    """Freeze an explicit optional cap before inference, retaining every input row."""
    if max_investigations is not None and (
        type(max_investigations) is not int or max_investigations < 0
    ):
        raise ValueError("Investigation cap must be an explicit nonnegative integer")
    preliminary: list[ScheduleRow] = []
    for event in events:
        early = preflight(event, policy)
        preliminary.append(
            ScheduleRow(
                ordinal=0,
                event_id=event.event_id,
                pair_id=event.pair_id,
                event_timestamp=event.event_timestamp,
                input_sha256=fingerprint(event.model_dump(mode="json")),
                eligible=early is None,
                selected=False,
                preflight_decision=early,
            )
        )
    preliminary.sort(
        key=lambda row: (
            _selection_key(seed, row.event_id, row.pair_id, row.event_timestamp),
            row.event_id,
        )
    )
    selected = 0
    rows: list[ScheduleRow] = []
    for ordinal, row in enumerate(preliminary):
        include = row.eligible and (max_investigations is None or selected < max_investigations)
        rows.append(row.model_copy(update={"ordinal": ordinal, "selected": include}))
        selected += int(include)
    return FrozenSchedule(
        seed=seed,
        max_investigations=max_investigations,
        policy_sha256=fingerprint(policy.model_dump(mode="json")),
        rows=tuple(rows),
    )


class EventCheckpoint(FrozenModel):
    version: Literal["phase5-resumable-batch-v1"] = BATCH_VERSION
    batch_id: SHA256
    schedule_id: SHA256
    ordinal: Annotated[int, Field(ge=0)]
    event_id: Identifier
    input_sha256: SHA256
    disposition: Disposition
    decision: ControllerDecision
    investigation: InvestigationResult | None


class BatchProgress(FrozenModel):
    batch_id: SHA256
    schedule_id: SHA256
    mode: Literal["mock", "live"]
    quality_evidence: bool
    total_count: Annotated[int, Field(ge=1)]
    eligible_count: Annotated[int, Field(ge=0)]
    selected_count: Annotated[int, Field(ge=0)]
    completed_count: Annotated[int, Field(ge=0)]
    new_provider_calls: Annotated[int, Field(ge=0)]
    status_counts: dict[str, int]
    disposition_counts: dict[str, int]
    complete: bool
    batch_dir: str
    manifest_path: str | None


def _batch_identity(
    schedule: FrozenSchedule, policy: AgentPolicy, provider: RoleProvider, attempt_id: str
) -> dict[str, object]:
    if provider.mode not in {"mock", "live"} or not attempt_id or len(attempt_id) > 80:
        raise ValueError("Batch requires an explicit mode and bounded attempt identity")
    if provider.mode == "live" and policy.status != "FROZEN":
        raise ValueError("Live batches require a frozen policy, never fixture thresholds")
    role_identities = {role: provider.identity_for(role) for role in ROLES}
    if provider.mode == "live" and any(
        not isinstance(identity.get("durable_budget"), dict)
        for identity in role_identities.values()
    ):
        raise ValueError("Live batches require a durable attempt journal for every provider role")
    return {
        "version": BATCH_VERSION,
        "schedule_id": schedule.schedule_id,
        "policy": policy.model_dump(mode="json"),
        "provider": role_identities,
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "implementation": implementation_identity(),
        "batch_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "attempt_id": attempt_id,
        "mode": provider.mode,
    }


def _check_event(row: ScheduleRow, event: AgentInput, policy: AgentPolicy) -> None:
    if (
        row.event_id != event.event_id
        or row.pair_id != event.pair_id
        or row.event_timestamp != event.event_timestamp
        or row.input_sha256 != fingerprint(event.model_dump(mode="json"))
        or row.preflight_decision != preflight(event, policy)
    ):
        raise ValueError("Frozen schedule input/preflight binding mismatch")


def run_batch(
    schedule: FrozenSchedule,
    events: Sequence[AgentInput],
    policy: AgentPolicy,
    provider: RoleProvider,
    output_dir: Path,
    *,
    attempt_id: str = "initial",
    max_events: int | None = None,
) -> BatchProgress:
    """Resume terminal checkpoints with lightweight integrity/policy replay only.

    max_events limits newly published rows for an intentional pause; it is not a
    scientific sample cap. Failed investigations remain terminal ABSTAIN records.
    A retry requires a new explicit attempt ID, preserving the previous batch.
    """
    if max_events is not None and (type(max_events) is not int or max_events < 0):
        raise ValueError("Pause limit must be a nonnegative integer")
    if len(events) != len(schedule.rows) or schedule.policy_sha256 != fingerprint(
        policy.model_dump(mode="json")
    ):
        raise ValueError("Batch population or policy differs from its frozen schedule")
    # Store only identifiers/indexes. A file-backed input Sequence can keep large
    # evidence bundles on disk without retaining every source pack in memory.
    inventory: object = getattr(events, "event_ids", None)
    if inventory is not None:
        if (
            not isinstance(inventory, tuple)
            or len(inventory) != len(events)
            or any(not isinstance(event_id, str) for event_id in inventory)
        ):
            raise ValueError("Prepared input identifier inventory is invalid")
        indexes = {event_id: index for index, event_id in enumerate(inventory)}
    else:
        indexes = {event.event_id: index for index, event in enumerate(events)}
    if len(indexes) != len(events) or set(indexes) != {row.event_id for row in schedule.rows}:
        raise ValueError("Batch population differs from the scheduled event identifiers")
    identity = _batch_identity(schedule, policy, provider, attempt_id)
    batch_id = fingerprint(identity)
    batch_dir = output_dir / "batches" / batch_id
    initial_calls = provider.calls
    statuses: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    entries: list[dict[str, object]] = []
    new_events = 0
    attributed_calls = 0
    with ExclusiveLease(output_dir / "batch.lock", purpose="phase5-batch"):
        identity_path = batch_dir / "identity.json"
        if identity_path.exists():
            if read_envelope(identity_path) != identity:
                raise ValueError("Stored batch identity mismatch")
        else:
            write_envelope(identity_path, identity)
        write_envelope(batch_dir / "schedule.json", schedule.model_dump(mode="json"))
        expected_files = {f"{row.ordinal:09d}.json" for row in schedule.rows}
        if any(path.name not in expected_files for path in (batch_dir / "events").glob("*.json")):
            raise ValueError("Batch contains an unexpected event checkpoint")
        progress_path = batch_dir / "progress.json"
        previous_completed = 0
        if progress_path.exists():
            previous_progress = read_envelope(progress_path)
            completed = previous_progress.get("completed_count")
            if (
                previous_progress.get("batch_id") != batch_id
                or type(completed) is not int
                or not 0 <= completed <= len(schedule.rows)
                or any(
                    not (batch_dir / "events" / f"{index:09d}.json").exists()
                    for index in range(completed)
                )
            ):
                raise ValueError("Batch progress anchor has missing checkpoints")
            previous_completed = completed
        manifest_path = batch_dir / "manifest.json"
        if manifest_path.exists():
            existing_manifest = read_envelope(manifest_path)
            if existing_manifest.get("batch_id") != batch_id or any(
                not (batch_dir / "events" / name).exists() for name in expected_files
            ):
                raise ValueError("Complete manifest has missing checkpoints or wrong identity")
        for row in schedule.rows:
            checkpoint_path = batch_dir / "events" / f"{row.ordinal:09d}.json"
            exists = checkpoint_path.exists()
            if not exists and max_events is not None and new_events >= max_events:
                continue
            event = events[indexes[row.event_id]]
            _check_event(row, event, policy)
            stored = (
                EventCheckpoint.model_validate_json(canonical(read_envelope(checkpoint_path)))
                if exists
                else None
            )
            investigation: InvestigationResult | None = None
            disposition: Disposition
            if not row.eligible:
                assert row.preflight_decision is not None
                decision, disposition = row.preflight_decision, "PREFLIGHT_SKIP"
            elif not row.selected:
                decision = failure_decision(event, policy, "INVESTIGATION_NOT_SCHEDULED")
                disposition = "NOT_SCHEDULED"
            else:
                # run_investigation verifies existing receipts without invoking
                # the graph/provider. Corrupt role caches can never hide a changed
                # decision; the terminal controller is replayed on every resume.
                if stored is not None:
                    if stored.investigation is None:
                        raise ValueError("Investigated checkpoint has no bound result")
                    investigation = stored.investigation
                    verify_investigation(
                        investigation, event, policy, provider, attempt_id=attempt_id
                    )
                else:
                    investigation = run_investigation(
                        event,
                        policy,
                        provider,
                        output_dir / "investigations",
                        attempt_id=attempt_id,
                    )
                decision = investigation.decision
                disposition = (
                    "BUDGET_EXHAUSTED"
                    if "INVESTIGATION_BUDGET_EXHAUSTED" in decision.reason_codes
                    else "INVESTIGATED"
                )
            checkpoint = EventCheckpoint(
                batch_id=batch_id,
                schedule_id=schedule.schedule_id,
                ordinal=row.ordinal,
                event_id=row.event_id,
                input_sha256=row.input_sha256,
                disposition=disposition,
                decision=decision,
                investigation=investigation,
            )
            payload = checkpoint.model_dump(mode="json")
            if exists:
                if stored != checkpoint:
                    raise ValueError("Stored batch checkpoint is not reproducible")
            else:
                write_envelope(checkpoint_path, payload)
                new_events += 1
            statuses[decision.status] += 1
            dispositions[disposition] += 1
            attributed_calls += investigation.provider_calls if investigation is not None else 0
            entries.append(
                {"ordinal": row.ordinal, "event_id": row.event_id, "sha256": fingerprint(payload)}
            )
            # Progress is replaceable operational state, never a registered
            # scientific manifest or a basis for trusting checkpoints.
            if not exists:
                write_envelope(
                    batch_dir / "progress.json",
                    {
                        "batch_id": batch_id,
                        "completed_count": max(previous_completed, len(entries)),
                        "total_count": len(schedule.rows),
                        "updated_at": datetime.now(UTC).isoformat(),
                        "status_counts": dict(statuses),
                    },
                    replace=True,
                )
        complete = len(entries) == len(schedule.rows)
        manifest = {
            "version": BATCH_VERSION,
            "batch_id": batch_id,
            "schedule_id": schedule.schedule_id,
            "mode": provider.mode,
            "quality_evidence": False,
            "total_count": len(schedule.rows),
            "eligible_count": schedule.eligible_count,
            "selected_count": schedule.selected_count,
            "status_counts": dict(statuses),
            "disposition_counts": dict(dispositions),
            "provider_attempts_attributed_to_results": attributed_calls,
            "checkpoints": entries,
            "complete": True,
            "scientific_acceptance": False,
        }
        if complete:
            write_envelope(manifest_path, manifest)
        elif manifest_path.exists():
            raise ValueError("A complete batch manifest has missing checkpoints")
    return BatchProgress(
        batch_id=batch_id,
        schedule_id=schedule.schedule_id,
        mode=cast(Literal["mock", "live"], provider.mode),
        quality_evidence=False,
        total_count=len(schedule.rows),
        eligible_count=schedule.eligible_count,
        selected_count=schedule.selected_count,
        completed_count=len(entries),
        new_provider_calls=provider.calls - initial_calls,
        status_counts=dict(statuses),
        disposition_counts=dict(dispositions),
        complete=complete,
        batch_dir=str(batch_dir),
        manifest_path=str(manifest_path) if complete else None,
    )
