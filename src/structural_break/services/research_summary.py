"""Read-only presentation of the current walk-forward study, separate from legacy bundles.

The manifest pins bytes and cohort/role metadata. It is a presentation snapshot,
not a scientific acceptance certificate or authorization to unlock final outcomes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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
    comparison: dict[str, dict[str, dict[str, float]]] = Field(default_factory=dict)


class StudyExport(_Contract):
    schema_version: Literal[1]
    models: list[dict[str, str]]
    regional: list[dict[str, str | float | int | None]]
    sources: dict[str, str]
    availability: list[dict[str, str]]


@dataclass(frozen=True)
class ResearchSummaryService:
    manifest: PresentationManifest
    summary: ResearchSummary
    daily: pd.DataFrame
    snapshot_id: str
    study: StudyExport
    root: Path

    def catalogue(self) -> pd.DataFrame:
        return pd.DataFrame(self.study.models)

    def forecast_comparison(self, period: str) -> pd.DataFrame:
        rows = self.forecasts(period).set_index("id")
        records = []
        for model in self.study.models:
            key = model["id"]
            record: dict[str, Any] = {
                "id": key,
                "Model": model["Model"],
                "Role": model["Role"],
                "Scope": model["Scope"],
                "Status": model["Status"],
                **{metric: None for metric in METRICS},
            }
            if key in rows.index:
                record.update({str(k): v for k, v in rows.loc[key].to_dict().items()})
                record["Scope"] = self.manifest.cohorts[period].id
            records.append(record)
        return pd.DataFrame(records)

    def book_comparison(self, period: str) -> pd.DataFrame:
        rows = self.book_stats(period)
        rows["Selection"] = "Model B / R0"
        rows["Monitor"] = ["On", "Off"]
        source_period = f"{PERIODS[period][0]}-{PERIODS[period][1]}"
        extra = []
        for source, label in (
            ("best forecaster (bag5, monitor)", "B+rule+ou · bag5"),
            ("full model (FULL, monitor)", "Full model"),
        ):
            values = self.summary.comparison.get(source, {}).get(source_period)
            if values is None:
                raise ValueError("Missing current book comparison")
            extra.append(
                {
                    "Book": label + " + monitor",
                    "Selection": label,
                    "Monitor": "On",
                    "sharpe": values["sharpe"],
                    "cagr": values["cagr"],
                    "cagr_with_cash": None,
                    "max_drawdown": values["maxdd"],
                    "volatility": values["vol"],
                    "turnover": values["turnover"],
                    "cost": values["cost"],
                }
            )
        return pd.DataFrame([*rows.to_dict(orient="records"), *extra])

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
    required = {"summary.json", "book_daily.parquet", "study.json"}
    if not required <= set(manifest.files) or not set(manifest.files) <= required | {
        "roc.png",
        "calibration.png",
    }:
        raise ValueError("Unexpected presentation artifacts")
    for name, expected in manifest.files.items():
        actual = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError("Presentation artifact hash mismatch")
    summary = ResearchSummary.model_validate_json((folder / "summary.json").read_bytes())
    study = StudyExport.model_validate_json((folder / "study.json").read_bytes())
    if [m["id"] for m in study.models] != [
        "BASELINE_0",
        "BASELINE_1",
        "A",
        "R0",
        "B_rule_ou",
        "B_rule_ou_track",
        "FULL",
    ]:
        raise ValueError("Unexpected study catalogue")
    seen: set[tuple[str, str]] = set()
    regional_counts: dict[str, list[int | float | str | None]] = {}
    for record in study.regional:
        if record["Period"] not in {"2011–2017", "2018–2023"}:
            raise ValueError("Invalid regional period")
        if record["Model"] not in {"Desk base · no agent scores", "Full model"}:
            raise ValueError("Unexpected regional model")
        identity = (str(record["Period"]), str(record["Model"]))
        if identity in seen:
            raise ValueError("Duplicate regional measurement")
        seen.add(identity)
        regional_counts.setdefault(identity[0], []).append(record["Events"])
        for metric in ("ROC AUC", "Brier score", "Log loss"):
            measurement = record[metric]
            if measurement is None and metric == "Log loss":
                continue
            if not isinstance(measurement, (float, int)) or not np.isfinite(measurement):
                raise ValueError("Invalid regional measurement")
            if measurement < 0 or (metric != "Log loss" and measurement > 1):
                raise ValueError("Regional measurement out of range")
    if any(len(counts) != 2 or counts[0] != counts[1] for counts in regional_counts.values()):
        raise ValueError("Regional comparison must retain a matched denominator")
    if set(summary.comparison) != {
        "adopted (R0, monitor)",
        "best forecaster (bag5, monitor)",
        "full model (FULL, monitor)",
    }:
        raise ValueError("Incomplete current book selection comparison")
    for books in summary.comparison.values():
        if set(books) != {"2010-2017", "2018-2023", "2010-2023"}:
            raise ValueError("Invalid comparison book periods")
        for book_values in books.values():
            if not all(np.isfinite(v) for v in book_values.values()):
                raise ValueError("Invalid comparison book metrics")
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
        manifest, summary, daily, hashlib.sha256(manifest_bytes).hexdigest(), study, folder
    )


def artifact_identity(folder: Path) -> tuple[str, ...]:
    """Cache by every file's bytes: changed data cannot reuse an earlier verification."""
    manifest = PresentationManifest.model_validate_json((folder / "presentation.json").read_bytes())
    allowed = {"summary.json", "book_daily.parquet", "study.json", "roc.png", "calibration.png"}
    if not set(manifest.files) <= allowed:
        raise ValueError("Unexpected presentation artifacts")
    return tuple(
        hashlib.sha256((folder / name).read_bytes()).hexdigest()
        for name in ("presentation.json", *sorted(manifest.files))
    )
