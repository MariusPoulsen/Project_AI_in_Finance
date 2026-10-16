"""Outcome-free strategy inputs and separate development-only evaluation labels.

These typed declarations are fixture adapters, not independent verification of
native models, SEC generations or stored historical controller receipts.
"""

from datetime import date, datetime, timedelta
from math import isclose
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import Field, model_validator

from structural_break.agents.contracts import ControllerDecision
from structural_break.backtest.contracts import (
    SHA256,
    FrozenModel,
    Identifier,
    PairTradeRequest,
    PairTradeResult,
    Price,
    canonical_sessions,
    development_date,
    utc,
)

Rung: TypeAlias = Literal["BASELINE_0", "BASELINE_1", "MODEL_A", "MODEL_B", "FULL_SYSTEM"]
RUNG_ORDER: tuple[Rung, ...] = ("BASELINE_0", "BASELINE_1", "MODEL_A", "MODEL_B", "FULL_SYSTEM")
Probability = Annotated[float, Field(ge=0, le=1)]
SelectionReason: TypeAlias = Literal[
    "NOT_FRESH",
    "FRESH_CROSSING",
    "UNKNOWN_PREVIOUS_CLOSE",
    "UNKNOWN_SIGNAL_CLOSE",
    "PAIR_ACTIVE",
    "PAIR_NOT_ACTIVE",
    "PAIR_STATUS_UNKNOWN",
    "MISSING_MODEL_A",
    "MISSING_MODEL_B",
    "MODEL_A_BELOW_THRESHOLD",
    "MODEL_B_BELOW_THRESHOLD",
    "MODEL_A_SELECTED",
    "MODEL_B_SELECTED",
    "AGENT_UNSCHEDULED",
    "MISSING_CONTROLLER",
    "CONTROLLER_CANDIDATE",
    "CONTROLLER_REVIEW",
    "CONTROLLER_NO_TRADE",
    "CONTROLLER_ABSTAIN",
    "BASE_RULE_WITHHELD",
    "BASE_RULE_UNAVAILABLE",
]


class PreviousClose(FrozenModel):
    session_date: date
    close_a: Price
    close_b: Price
    z: Annotated[float, Field(ge=-1000, le=1000)]
    snapshot_id: Identifier

    @model_validator(mode="after")
    def development_only(self) -> Self:
        development_date(self.session_date)
        return self


class StoredPrediction(FrozenModel):
    model_role: Literal["A", "B-metadata", "B-tone", "B-catalyst", "B-both"]
    model_family: Literal["logistic", "xgboost"]
    horizon_sessions: Literal[10, 20, 30]
    model_bundle_id: Identifier
    calibrator_id: Identifier
    information_cutoff: datetime
    probability: Probability


class StoredController(FrozenModel):
    investigation_id: SHA256
    input_sha256: SHA256
    event_id: Identifier
    pair_id: Identifier
    information_cutoff: datetime
    snapshot_id: Identifier
    model_b_bundle_id: Identifier
    schedule_id: SHA256
    decision: ControllerDecision


class LadderState(FrozenModel):
    event_id: Identifier
    pair_id: Identifier
    signal_at: datetime
    snapshot_id: Identifier
    previous: PreviousClose | None = None
    pair_status: Literal["ACTIVE", "WATCH", "RETIRED", "UNKNOWN"]
    model_a: StoredPrediction | None = None
    model_b: StoredPrediction | None = None
    agent_scheduled: bool = False
    full_schedule_id: SHA256 | None = None
    controller: StoredController | None = None
    sector: Identifier = "UNKNOWN"
    source_coverage: Literal["COMPLETE", "PARTIAL", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def identity_and_clocks(self) -> Self:
        signal = utc(self.signal_at)
        if signal.year >= 2024:
            raise ValueError("Ladder inputs cannot open locked 2024+ outcomes")
        for prediction in (self.model_a, self.model_b):
            if prediction is not None and utc(prediction.information_cutoff) != signal:
                raise ValueError("Stored prediction must bind this exact event information cutoff")
        if self.model_a is not None and self.model_a.model_role != "A":
            raise ValueError("Model A input must identify the A bundle")
        if self.model_b is not None and not self.model_b.model_role.startswith("B-"):
            raise ValueError("Model B input must identify a structured B bundle")
        if (self.agent_scheduled or self.controller is not None) and self.full_schedule_id is None:
            raise ValueError("Investigations must bind an explicit frozen schedule")
        if self.controller is not None:
            controller = self.controller
            if (
                controller.event_id != self.event_id
                or controller.pair_id != self.pair_id
                or utc(controller.information_cutoff) != signal
                or controller.snapshot_id != self.snapshot_id
                or controller.schedule_id != self.full_schedule_id
                or self.model_b is None
                or controller.model_b_bundle_id != self.model_b.model_bundle_id
                or controller.decision.model_b_probability != self.model_b.probability
            ):
                raise ValueError("Stored controller event/model/snapshot/schedule binding mismatch")
        return self


class LadderEvent(FrozenModel):
    state: LadderState
    request: PairTradeRequest

    @model_validator(mode="after")
    def exact_join(self) -> Self:
        state, request = self.state, self.request
        if (
            state.event_id != request.event_id
            or state.pair_id != request.pair_id
            or utc(state.signal_at) != utc(request.signal_at)
            or state.snapshot_id != request.snapshot.snapshot_id
        ):
            raise ValueError("Selection inputs must bind the exact execution request")
        previous = state.previous
        if previous is not None:
            signal_date = request.sessions[0].session_date
            prior_sessions = canonical_sessions(signal_date - timedelta(days=14), signal_date)
            if len(prior_sessions) < 2 or previous.session_date != prior_sessions[-2][0]:
                raise ValueError("Fresh crossing requires the immediately preceding XNYS close")
            if previous.snapshot_id != request.snapshot.snapshot_id:
                raise ValueError("Prior and current z must use the same signal snapshot")
            if not isclose(
                previous.z,
                request.snapshot.z(previous.close_a, previous.close_b),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError("Previous z must reconcile to its prices and signal snapshot")
        return self


class LadderPolicy(FrozenModel):
    version: Identifier
    population_id: Identifier
    status: Literal["DRAFT", "FROZEN", "FIXTURE"]
    horizon_sessions: Literal[10, 20, 30] = 20
    candidate_threshold: Probability | None = None
    model_family: Literal["logistic", "xgboost"] = "logistic"
    model_a_bundle_id: Identifier
    model_a_calibrator_id: Identifier
    model_b_bundle_id: Identifier
    model_b_calibrator_id: Identifier
    model_b_variant: Literal["B-metadata", "B-tone", "B-catalyst", "B-both"] = "B-both"
    controller_policy_version: Identifier
    label_policy_version: Identifier


class RungSelection(FrozenModel):
    rung: Rung
    disposition: Literal["SELECTED", "WITHHELD", "UNAVAILABLE"]
    reason_codes: Annotated[tuple[SelectionReason, ...], Field(min_length=1, max_length=4)]

    @property
    def selected(self) -> bool:
        return self.disposition == "SELECTED"

    @property
    def available(self) -> bool:
        return self.disposition != "UNAVAILABLE"


class LadderRow(FrozenModel):
    event_id: Identifier
    pair_id: Identifier
    signal_at: datetime
    state_sha256: SHA256
    request_sha256: SHA256
    raw_fresh: bool | None
    selections: Annotated[tuple[RungSelection, ...], Field(min_length=5, max_length=5)]
    execution: PairTradeResult | None

    @model_validator(mode="after")
    def coherent_rows(self) -> Self:
        if utc(self.signal_at).year >= 2024:
            raise ValueError("Ladder rows cannot open locked 2024+ outcomes")
        if tuple(selection.rung for selection in self.selections) != RUNG_ORDER:
            raise ValueError("Every event must preserve all five rungs in canonical order")
        if (self.raw_fresh is True) != (self.execution is not None):
            raise ValueError("Every fresh event requires one shared counterfactual execution")
        if self.execution is not None and (
            self.execution.event_id != self.event_id
            or self.execution.pair_id != self.pair_id
            or self.execution.request_sha256 != self.request_sha256
        ):
            raise ValueError("Shared execution must bind this exact event request")
        selected = {selection.rung for selection in self.selections if selection.selected}
        if selected - {"BASELINE_0"} and "BASELINE_0" not in selected:
            raise ValueError("All filtered strategies require a fresh raw signal")
        if selected & {"MODEL_A", "MODEL_B", "FULL_SYSTEM"} and "BASELINE_1" not in selected:
            raise ValueError("Model and controller selection require historical ACTIVE")
        if "FULL_SYSTEM" in selected and "MODEL_B" not in selected:
            raise ValueError("Full System must remain a subset of Model B")
        return self


class EvaluationLabel(FrozenModel):
    event_id: Identifier
    pair_id: Identifier
    signal_at: datetime
    horizon_sessions: Literal[10, 20, 30]
    label_policy_version: Identifier
    label_manifest_sha256: SHA256
    complete_window_end: date
    label_success: Literal[0, 1]

    @model_validator(mode="after")
    def full_development_window(self) -> Self:
        signal = utc(self.signal_at)
        development_date(signal.date())
        development_date(self.complete_window_end)
        sessions = canonical_sessions(signal.date(), self.complete_window_end)
        if (
            len(sessions) != self.horizon_sessions + 1
            or sessions[-1][0] != self.complete_window_end
            or utc(sessions[0][2]) != signal
        ):
            raise ValueError("Evaluation labels must bind the complete target session window")
        return self
