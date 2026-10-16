"""Generation-bound historical ladder declarations; outcome-free until a frozen run.

A binding names the exact registered v2 generations an inventory reads. ACCEPTED
bindings are derived only from the published primary readiness record. Explicit
path-and-checksum bindings to an unpublished pack are UNACCEPTED_ENGINEERING:
they may build a selection inventory, but they cannot reach a frozen policy,
the execution engine or an accepted experiment manifest.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import Field, model_validator

from structural_break.backtest.contracts import (
    SHA256,
    FrozenModel,
    Identifier,
    development_date,
    utc,
)
from structural_break.backtest.ladder_contracts import (
    LadderPolicy,
    Probability,
    RungSelection,
    check_selection_chain,
)

Acceptance: TypeAlias = Literal["ACCEPTED", "UNACCEPTED_ENGINEERING"]
Partition: TypeAlias = Literal["fit", "calibration", "assessment"]
PRICE_ADJUSTMENT_POLICY = "yahoo-retrospective-adjclose-ratio-v1"
INVENTORY_RULE = "nonoverlapping-episode-events-v1"
QualityFlag: TypeAlias = Literal["OK", "ZERO_VOLUME"]
# Decision 35: one common A/B trading threshold, plus reported sensitivities.
# The bound v2 reporting threshold (0.65) is always an admissible sensitivity.
HEADLINE_TRADING_THRESHOLD = 0.30
SENSITIVITY_TRADING_THRESHOLDS = (0.20, 0.40)


class ManifestBinding(FrozenModel):
    role: Literal["evaluation", "registry", "market"]
    version: Identifier
    path: Identifier
    sha256: SHA256

    @model_validator(mode="after")
    def portable(self) -> Self:
        if "\\" in self.path or self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("Manifest bindings use portable workspace-relative paths")
        return self


class GenerationBinding(FrozenModel):
    schema_version: Literal["historical-generation-binding-v1"] = "historical-generation-binding-v1"
    acceptance: Acceptance
    primary_version: Identifier | None = None
    horizon_sessions: Literal[10, 20, 30]
    evaluation: ManifestBinding
    registry: ManifestBinding
    market: ManifestBinding
    prices_sha256: SHA256
    pair_universe_sha256: SHA256
    protocol_hash: SHA256
    development_end: date
    assessment_start: date
    assessment_end: date
    candidate_threshold: Probability

    @model_validator(mode="after")
    def coherent(self) -> Self:
        roles = (self.evaluation.role, self.registry.role, self.market.role)
        if roles != ("evaluation", "registry", "market"):
            raise ValueError("Generation binding roles must be evaluation, registry and market")
        if (self.acceptance == "ACCEPTED") != (self.primary_version is not None):
            raise ValueError("Only a published primary readiness record establishes acceptance")
        development_date(self.development_end)
        if not self.assessment_start <= self.assessment_end <= self.development_end:
            raise ValueError("Assessment window must lie inside the development period")
        return self


class HistoricalSpec(FrozenModel):
    """Declared population, selection policy and price conventions for one horizon."""

    schema_version: Literal["historical-ladder-spec-v1"] = "historical-ladder-spec-v1"
    binding: GenerationBinding
    ladder: LadderPolicy
    window_start: date
    window_end: date
    admitted_partitions: Annotated[tuple[Partition, ...], Field(min_length=1, max_length=3)] = (
        "assessment",
    )
    inventory_rule: Literal["nonoverlapping-episode-events-v1"] = "nonoverlapping-episode-events-v1"
    price_adjustment_policy: Literal["yahoo-retrospective-adjclose-ratio-v1"] = (
        "yahoo-retrospective-adjclose-ratio-v1"
    )
    fill_quality_flags: tuple[QualityFlag, ...] = ("OK",)
    close_quality_flags: tuple[QualityFlag, ...] = ("OK", "ZERO_VOLUME")

    @model_validator(mode="after")
    def coherent(self) -> Self:
        ladder, binding = self.ladder, self.binding
        if ladder.status == "FIXTURE":
            raise ValueError("Historical inventories cannot use a synthetic fixture policy")
        if ladder.horizon_sessions != binding.horizon_sessions:
            raise ValueError("Ladder horizon must match the bound evaluation generation")
        if ladder.full_system != "NOT_RUN":
            raise ValueError("No accepted controller generation exists; Full System is not run")
        if binding.acceptance != "ACCEPTED" and ladder.status != "DRAFT":
            raise ValueError("Unaccepted engineering bindings cannot use a frozen policy")
        approved = (
            HEADLINE_TRADING_THRESHOLD,
            *SENSITIVITY_TRADING_THRESHOLDS,
            binding.candidate_threshold,
        )
        if ladder.candidate_threshold not in approved:
            raise ValueError("The trading threshold must be an approved Decision 35 value")
        if not self.window_start <= self.window_end <= binding.development_end:
            raise ValueError("Inventory window must lie inside the development period")
        if self.admitted_partitions == ("assessment",) and not (
            binding.assessment_start <= self.window_start
            and self.window_end <= binding.assessment_end
        ):
            raise ValueError("An assessment-only inventory must lie inside the assessment window")
        if len(set(self.admitted_partitions)) != len(self.admitted_partitions):
            raise ValueError("Admitted partitions must be unique")
        if not set(self.fill_quality_flags) <= set(self.close_quality_flags):
            raise ValueError("Executable opens must satisfy at least the close quality rule")
        return self


class SuppressedCrossing(FrozenModel):
    """A fresh raw crossing in the window that the horizon's episode registry omits."""

    crossing_id: Identifier
    pair_id: Identifier
    event_date: date
    reason: Literal["NOT_IN_HORIZON_EVENT_REGISTRY"] = "NOT_IN_HORIZON_EVENT_REGISTRY"


class InventoryRow(FrozenModel):
    """Selection-only row: no price path is simulated and no label is read."""

    event_id: Identifier
    pair_id: Identifier
    signal_at: datetime
    partition: Partition | None
    state_sha256: SHA256
    request_sha256: SHA256
    raw_fresh: bool | None
    selections: Annotated[tuple[RungSelection, ...], Field(min_length=5, max_length=5)]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if utc(self.signal_at).year >= 2024:
            raise ValueError("Historical inventories cannot open locked 2024+ outcomes")
        check_selection_chain(self.selections)
        return self


class HistoricalInventory(FrozenModel):
    schema_version: Literal["historical-ladder-inventory-v1"] = "historical-ladder-inventory-v1"
    spec_sha256: SHA256
    acceptance: Acceptance
    rows: Annotated[tuple[InventoryRow, ...], Field(max_length=100_000)]
    suppressed: Annotated[tuple[SuppressedCrossing, ...], Field(max_length=100_000)]
    simulated: Literal[False] = False
    labels_read: Literal[False] = False
    final_test_read: Literal[False] = False

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({row.event_id for row in self.rows}) != len(self.rows):
            raise ValueError("Inventory event identities must be unique")
        if len({row.crossing_id for row in self.suppressed}) != len(self.suppressed):
            raise ValueError("Suppressed crossing identities must be unique")
        return self
