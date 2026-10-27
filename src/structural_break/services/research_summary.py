"""Read-only presentation of the current walk-forward study, separate from legacy bundles.

The manifest pins bytes and cohort/role metadata. It is a presentation snapshot,
not a scientific acceptance certificate or authorization to unlock final outcomes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

ADOPTED = "Adopted book (with monitor exit)"
COMPARATOR = "Same book without the monitor exit"
BOOKS = (ADOPTED, COMPARATOR)
METRICS = {
    "ROC AUC": ("AUC", True, 3),
    "PR AUC": ("PR", True, 3),
    "Brier score": ("Brier", False, 4),
    "Log loss": ("LL", False, 4),
}
PERIODS = {
    "2018–2023 · confirmation": (2018, 2023, "2018–2023 (holdout)", "2018-23"),
    "2010–2017 · selection": (2010, 2017, "2010–2017 (selection)", "2010-17"),
}


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ModelRecord(_Contract):
    id: str
    source_name: str
    name: str
    role: str
    explanation: str


class Cohort(_Contract):
    id: str
    n: int = Field(gt=0)
    definition: str


class PresentationManifest(_Contract):
    schema_version: Literal[1]
    final_test: Literal["locked"]
    files: dict[str, str]
    models: list[ModelRecord]
    cohorts: dict[str, Cohort]
    source: str
    precision: str


class BookStats(_Contract):
    sharpe: float
    cagr: float = Field(gt=-1)
    cagr_with_cash: float = Field(gt=-1)
    max_drawdown: float = Field(ge=-1, le=0)
    volatility: float = Field(ge=0)
    turnover: float = Field(ge=0)
    cost: float = Field(ge=0)


class Audit(_Contract):
    trials: int = Field(gt=0)
    pbo: float = Field(ge=0, le=1)
    dsr_2010_2023: dict[str, float]
    dsr_2018_2023: dict[str, float]
    rank: int


class Desk(_Contract):
    entry_scored: int = Field(ge=0)
    entry_abstained: int = Field(ge=0)
    monitor_checks: int = Field(ge=0)
    monitor_after_triage: int = Field(ge=0)
    monitor_scored: int = Field(ge=0)
    monitor_abstained: int = Field(ge=0)
    decision: str


class News(_Contract):
    source_2024_2025: str
    toned_session_ratio: float = Field(gt=0)
    coverage_ratio: float = Field(gt=0)
    decision: str


class ResearchSummary(_Contract):
    design: list[tuple[str, str]]
    stats: dict[str, dict[str, BookStats]]
    goal1: list[dict[str, str | float]]
    audit: Audit
    desk: Desk
    news: News
    decisions: str


@dataclass(frozen=True)
class ResearchSummaryService:
    manifest: PresentationManifest
    summary: ResearchSummary
    daily: pd.DataFrame
    snapshot_id: str

    def forecasts(self, period: str) -> pd.DataFrame:
        """One matched population per period; do not infer missing model scores."""
        suffix = PERIODS[period][3]
        rows = []
        for model, values in zip(self.manifest.models, self.summary.goal1, strict=True):
            rows.append(
                {
                    "id": model.id,
                    "Model": model.name,
                    "Role": model.role,
                    **{
                        name: float(values[f"{prefix} {suffix}"])
                        for name, (prefix, _, _) in METRICS.items()
                    },
                }
            )
        return pd.DataFrame(rows)

    def book_stats(self, period: str) -> pd.DataFrame:
        source_period = PERIODS[period][2]
        return pd.DataFrame(
            [
                {"Book": name, **self.summary.stats[name][source_period].model_dump()}
                for name in BOOKS
            ]
        )

    def curves(self, period: str, *, drawdown: bool = False) -> pd.DataFrame:
        """Rebase each period on its preceding close; both series include cash interest."""
        start, end, _, _ = PERIODS[period]
        dates = self.daily["session_date"]
        selected: pd.DataFrame = self.daily.loc[dates.dt.year.between(start, end)].copy()
        preceding = self.daily.loc[dates.dt.year.lt(start)]
        for name in BOOKS:
            base = float(preceding.iloc[-1][name]) if len(preceding) else 1.0
            selected[name] = selected[name] / base
            if drawdown:
                selected[name] = selected[name] / selected[name].cummax().clip(lower=1) - 1
        return selected


def read_summary(folder: Path) -> ResearchSummaryService:
    """Verify bounded presentation bytes before parsing, with no analytical writes."""
    manifest_bytes = (folder / "presentation.json").read_bytes()
    manifest = PresentationManifest.model_validate_json(manifest_bytes)
    if set(manifest.files) != {"summary.json", "book_daily.parquet"}:
        raise ValueError("Unexpected presentation artifacts")
    for name, expected in manifest.files.items():
        actual = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("Presentation artifact hash mismatch")
    summary = ResearchSummary.model_validate_json((folder / "summary.json").read_bytes())
    if [m.id for m in manifest.models] != ["A", "R0", "B_rule_ou", "B_rule_ou_track"]:
        raise ValueError("Unexpected retained model roster")
    if set(manifest.cohorts) != set(PERIODS):
        raise ValueError("Missing matched cohort metadata")
    if len(summary.goal1) != len(manifest.models):
        raise ValueError("Incomplete forecast comparison")
    for model, row in zip(manifest.models, summary.goal1, strict=True):
        if row.get("model") != model.source_name:
            raise ValueError("Forecast role/source mismatch")
        for suffix in ("2010-17", "2018-23"):
            for prefix, _, _ in METRICS.values():
                value = row[f"{prefix} {suffix}"]
                if isinstance(value, str) or not np.isfinite(value) or value < 0:
                    raise ValueError("Invalid forecast measurement")
                if prefix != "LL" and value > 1:
                    raise ValueError("Forecast measurement out of range")
    if set(summary.stats) != set(BOOKS):
        raise ValueError("Incomplete book comparator")
    for periods in summary.stats.values():
        if set(periods) != {p[2] for p in PERIODS.values()} | {"2010–2023"}:
            raise ValueError("Unexpected book period")
    desk = summary.desk
    if (
        desk.monitor_scored + desk.monitor_abstained != desk.monitor_after_triage
        or desk.monitor_after_triage > desk.monitor_checks
    ):
        raise ValueError("Inconsistent monitor denominators")
    daily = pd.read_parquet(folder / "book_daily.parquet")
    if set(daily.columns) != {"session_date", *BOOKS} or daily.empty:
        raise ValueError("Unexpected book curve schema")
    dates = pd.to_datetime(daily["session_date"], errors="raise")
    if (
        dates.isna().any()
        or dates.duplicated().any()
        or not dates.is_monotonic_increasing
        or dates.min().year != 2010
        or dates.max().year != 2023
    ):
        raise ValueError("Invalid development curve dates; final test is locked")
    values = daily[list(BOOKS)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Invalid book NAV")
    daily["session_date"] = dates
    for start, end, _, _ in PERIODS.values():
        if not dates.dt.year.between(start, end).any():
            raise ValueError("Missing book period")
    return ResearchSummaryService(
        manifest, summary, daily, hashlib.sha256(manifest_bytes).hexdigest()
    )


def artifact_identity(folder: Path) -> tuple[str, ...]:
    """Cache by every file's bytes: changed data cannot reuse an earlier verification."""
    return tuple(
        hashlib.sha256((folder / name).read_bytes()).hexdigest()
        for name in ("presentation.json", "summary.json", "book_daily.parquet")
    )
