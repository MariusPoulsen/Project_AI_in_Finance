"""Strict, outcome-blind experiment contracts and independent source identities."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import Field, model_validator

from structural_break.config.loader import UniqueKeyLoader
from structural_break.config.models import ProjectConfig, SettingsModel, UniverseConfig


class ResearchProtocol(SettingsModel):
    version: str
    data_start: date
    development_end: date
    fit_start: date
    fit_end: date
    tuning_years: tuple[int, ...]
    calibration_start: date
    calibration_end: date
    assessment_start: date
    assessment_end: date
    final_test_locked: Literal[True]
    population: Literal["estimable"]
    primary_horizon: int = Field(gt=0)
    sensitivity_horizons: tuple[int, ...]
    formation_sessions: int = Field(ge=252)
    entry_z: float = Field(gt=0)
    success_z: float = Field(ge=0)
    adverse_z: float = Field(gt=0)
    seed: int = Field(ge=0)
    logistic_c: tuple[float, ...]
    xgb_candidates: tuple[dict[str, int | float], ...]
    primary_family: Literal["logistic"]
    primary_b_variant: Literal["both"]
    candidate_threshold: float = Field(gt=0, lt=1)
    bootstrap_replicates: int = Field(ge=100)
    bootstrap_calendar_months: Literal[3]
    sentiment_model: str
    sentiment_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    metadata_feature_policy: Literal["sec-item-recency-v1"]
    extraction_provider: Literal["gemma"]
    extraction_model: str = Field(pattern=r"^gemma-[a-z0-9.-]+$")
    extraction_max_calls: int = Field(ge=1, le=1000)
    extraction_interval_seconds: float = Field(ge=7)
    extraction_retries: int = Field(ge=0, le=1)
    extraction_max_pack_chars: int = Field(ge=4000, le=12000)
    extraction_max_chunks_per_leg: int = Field(ge=1, le=4)
    extraction_order: Literal["chronological"]
    flash_reserved_for_agents: Literal[True]
    paid_api_enabled: Literal[False]

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if not (
            self.data_start
            < self.fit_start
            < self.fit_end
            < self.calibration_start
            <= self.calibration_end
            < self.assessment_start
            <= self.assessment_end
            <= self.development_end
            < date(2024, 1, 1)
        ):
            raise ValueError("Development dates must be ordered and exclude the locked final test")
        if not self.success_z < self.entry_z < self.adverse_z:
            raise ValueError("Target boundaries are not ordered")
        horizons = (self.primary_horizon, *self.sensitivity_horizons)
        if len(set(horizons)) != len(horizons) or any(h < 1 for h in horizons):
            raise ValueError("Target horizons must be positive and unique")
        if not self.logistic_c or any(c <= 0 for c in self.logistic_c):
            raise ValueError("Regularization grid must be finite and positive")
        if not self.xgb_candidates or not self.tuning_years:
            raise ValueError("Predeclared grids and forward tuning periods are required")
        if tuple(sorted(set(self.tuning_years))) != self.tuning_years or any(
            not self.fit_start.year < y <= self.fit_end.year for y in self.tuning_years
        ):
            raise ValueError("Forward tuning must be within classifier fitting history")
        return self


class FinalTestProtocol(ResearchProtocol):
    """Decision 118: the frozen research protocol extended to the final-test end.

    Identical to the research protocol except that the development end may pass 2023
    only as far as ``periods.data_end()``: the development end while the final test is
    locked (the rehearsal), 2025-12-31 after the owner's unlock record. The research
    fitting, calibration and assessment windows are unchanged, so the research models
    never fit or assess a final-test row; those rows fall in the ``excluded`` partition.
    """

    @model_validator(mode="after")
    def chronological(self) -> Self:
        from structural_break import periods

        if not self.version.startswith("final-test-"):
            raise ValueError("A final-test protocol version starts with 'final-test-'")
        if not (
            self.data_start
            < self.fit_start
            < self.fit_end
            < self.calibration_start
            <= self.calibration_end
            < self.assessment_start
            <= self.assessment_end
            <= self.development_end
        ):
            raise ValueError("Final-test protocol dates must be ordered")
        if self.development_end > periods.data_end():
            raise ValueError(
                "The final-test protocol reaches past the unlocked data end: the final test "
                "is locked until the owner's unlock record cites the freeze manifest"
            )
        return self


def protocol_model(values: Any) -> ResearchProtocol:
    """The research or final-test protocol, chosen by its version."""
    version = values.get("version", "") if isinstance(values, dict) else ""
    model = FinalTestProtocol if str(version).startswith("final-test-") else ResearchProtocol
    return model.model_validate(values)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def identity(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_protocol(path: Path) -> ResearchProtocol:
    return protocol_model(yaml.load(path.read_text("utf-8"), Loader=UniqueKeyLoader))


def experiment_config(
    reference: ProjectConfig,
    protocol: ResearchProtocol,
    universe: UniverseConfig,
    horizon: int,
) -> ProjectConfig:
    """Use the canonical causal engines, with new versioned dates and targets.

    The configuration retains a *locked* final partition solely for validation
    of shared settings. The research runner truncates inputs to development_end
    and never builds any final rows. Shared target construction calls its combined
    calibration/assessment interval `validation`; evaluation separates it again.
    """
    if horizon not in (protocol.primary_horizon, *protocol.sensitivity_horizons):
        raise ValueError("Horizon was not predeclared")
    values = reference.model_dump(mode="python")
    values["universe"] = universe.model_dump(mode="python")
    values["data"].update(start=protocol.data_start)
    values["econometrics"].update(
        version=f"research-v2-h{horizon}",
        formation_days=protocol.formation_sessions,
        horizon_days=horizon,
        entry_z=protocol.entry_z,
        success_z=protocol.success_z,
        adverse_z=protocol.adverse_z,
    )
    values["ml"].update(
        version=f"research-v2-h{horizon}",
        label_policy_version=f"research-v2-close-h{horizon}",
        split_version="research-v2-fit-calibration-assessment",
        train={"start": protocol.fit_start, "end": protocol.fit_end},
        validation={"start": protocol.calibration_start, "end": protocol.assessment_end},
        embargo_days=horizon,
        seed=protocol.seed,
    )
    return ProjectConfig.model_validate(values)


def partition_rows(rows: Any, protocol: ResearchProtocol) -> Any:
    """Assign periods with full-window purging, independent of early resolution."""
    import pandas as pd

    result = rows.copy()
    days = pd.to_datetime(result["event_date"], errors="raise").dt.date
    ends = pd.to_datetime(result["horizon_end_date"], errors="raise").dt.date
    if days.isna().any() or ends.isna().any() or ends.le(days).any():
        raise ValueError("Every research label window must end after its observed event date")
    if days.gt(protocol.development_end).any():
        raise ValueError("Research evaluation must not receive final-test events")
    result["research_partition"] = "excluded"
    for name, lower, upper in (
        ("fit", protocol.fit_start, protocol.fit_end),
        ("calibration", protocol.calibration_start, protocol.calibration_end),
        ("assessment", protocol.assessment_start, protocol.assessment_end),
    ):
        mask = days.between(lower, upper) & ends.le(upper)
        result.loc[mask, "research_partition"] = name
    return result
