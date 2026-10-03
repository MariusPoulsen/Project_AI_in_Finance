"""Validated research settings. Credentials are deliberately a separate object."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Version = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Pair(SettingsModel):
    leg_a: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9.-]*$")]
    leg_b: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9.-]*$")]
    peer_group: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def distinct_legs(self) -> Self:
        if self.leg_a == self.leg_b:
            raise ValueError("Pair legs must be distinct")
        return self

    @property
    def pair_id(self) -> str:
        return f"{self.leg_a}__{self.leg_b}"


class UniverseConfig(SettingsModel):
    version: Version
    orientation: Literal["leg_a_is_y"]
    pairs: tuple[Pair, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_pairs(self) -> Self:
        identities = [frozenset((pair.leg_a, pair.leg_b)) for pair in self.pairs]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate or reversed pairs are forbidden")
        return self


class DataConfig(SettingsModel):
    version: Version
    start: date
    end: date
    calendar: Literal["XNYS"]
    market_source: Literal["yahoo"]
    volatility_source: Literal["cboe"]
    historical_evidence: Literal["sec"]
    evidence_timestamp: Literal["accepted_at"]
    optional_news_enabled: Literal[False]
    source_timeout_seconds: PositiveInt = 30
    source_attempts: Annotated[int, Field(strict=True, ge=1, le=5)] = 3
    sec_requests_per_second: Annotated[float, Field(gt=0, le=5)] = 2
    max_missing_session_fraction: Probability = 0.0
    source_max_age_days: PositiveInt = 30
    vix_context_lag_sessions: Literal[1] = 1

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.start >= self.end:
            raise ValueError("Data start must precede end")
        return self


class EconometricsConfig(SettingsModel):
    version: Version
    formation_days: PositiveInt
    refit: Literal["monthly"]
    cointegration_alpha: Probability
    entry_z: Annotated[float, Field(gt=0)]
    success_z: Annotated[float, Field(ge=0)]
    adverse_z: Annotated[float, Field(gt=0)]
    horizon_days: PositiveInt

    @model_validator(mode="after")
    def ordered_boundaries(self) -> Self:
        if not self.success_z < self.entry_z < self.adverse_z:
            raise ValueError("Require success_z < entry_z < adverse_z")
        return self


class Period(SettingsModel):
    start: date
    end: date

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.start > self.end:
            raise ValueError("Period start must not follow end")
        return self


class MLConfig(SettingsModel):
    version: Version
    feature_schema_version: Version
    train: Period
    validation: Period
    final_test: Period
    embargo_days: PositiveInt
    final_test_locked: Literal[True]
    calibration: Literal["sigmoid"]
    seed: Annotated[int, Field(strict=True, ge=0)]

    @model_validator(mode="after")
    def disjoint_periods(self) -> Self:
        if (
            not self.train.end
            < self.validation.start
            <= self.validation.end
            < self.final_test.start
        ):
            raise ValueError("Train, validation and final test must be ordered and disjoint")
        return self


class AgentsConfig(SettingsModel):
    version: Version
    prompt_graph_version: Version
    mode: Literal["mock", "live"]
    provider: str | None
    model: str | None
    timeout_seconds: PositiveInt
    max_retries: Annotated[int, Field(strict=True, ge=0, le=5)]
    historical_web_browsing: Literal[False]

    @model_validator(mode="after")
    def live_aliases(self) -> Self:
        if self.mode == "live" and (not self.provider or not self.model):
            raise ValueError("Live mode requires explicit provider and model aliases")
        return self


class DecisionConfig(SettingsModel):
    version: Version
    status: Literal["draft", "frozen"]
    candidate_probability: Probability | None
    break_risk_limit: Probability | None
    fail_closed_status: Literal["ABSTAIN"]

    @model_validator(mode="after")
    def frozen_policy(self) -> Self:
        if self.status == "frozen" and (
            self.candidate_probability is None or self.break_risk_limit is None
        ):
            raise ValueError("Frozen policy requires calibrated and reviewed thresholds")
        return self


class BacktestConfig(SettingsModel):
    version: Version
    status: Literal["draft", "frozen"]
    execution: Literal["next_open"]
    transaction_cost_bps: Annotated[float, Field(ge=0)] | None
    annual_borrow_bps: Annotated[float, Field(ge=0)] | None

    @model_validator(mode="after")
    def frozen_assumptions(self) -> Self:
        if self.status == "frozen" and (
            self.transaction_cost_bps is None or self.annual_borrow_bps is None
        ):
            raise ValueError("Frozen backtest requires explicit cost assumptions")
        return self


class AppConfig(SettingsModel):
    version: Version
    demo_mode: bool = Field(strict=True)
    read_only: Literal[True]
    cache_ttl_seconds: PositiveInt
    row_limit: PositiveInt


class ProjectConfig(SettingsModel):
    universe: UniverseConfig
    data: DataConfig
    econometrics: EconometricsConfig
    ml: MLConfig
    agents: AgentsConfig
    decision: DecisionConfig
    backtest: BacktestConfig
    app: AppConfig

    @model_validator(mode="after")
    def coherent_research_window(self) -> Self:
        if self.ml.embargo_days < self.econometrics.horizon_days:
            raise ValueError("Embargo must cover the complete label horizon")
        if self.data.start > self.ml.train.start or self.data.end < self.ml.final_test.end:
            raise ValueError("Data range must cover all research partitions")
        return self


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SB_", extra="ignore", frozen=True)
    workspace_root: str | None = None
    llm_api_key: SecretStr | None = None
    sec_user_agent: SecretStr | None = None
