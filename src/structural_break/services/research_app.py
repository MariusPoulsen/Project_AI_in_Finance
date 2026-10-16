"""Presentation DTOs for explicitly promoted, verified research-v2 outputs."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.research.primary import (
    checked_file,
    checked_json,
    load_primary,
    primary_versions,
    registered_manifest,
)


@dataclass(frozen=True)
class PrimaryResearchView:
    primary_version: str
    registry_version: str
    intelligence_version: str
    protocol: dict[str, Any]
    evaluations: dict[int, str]
    reports: dict[int, dict[str, Any]]


class PrimaryResearchService:
    """Read frozen outputs only: no migration, training, prediction or network."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def versions(self) -> tuple[str, ...]:
        return primary_versions(self.paths)

    def view(self, primary_version: str | None = None) -> PrimaryResearchView:
        primary = load_primary(self.paths, primary_version)
        inputs = primary["identity_inputs"]
        versions = {
            int(horizon): item["research_version"]
            for horizon, item in inputs["evaluations"].items()
        }
        reports = {}
        for horizon, version in versions.items():
            path, manifest = registered_manifest(self.paths, version, "evaluation")
            report = checked_json(path.parent / "report.json", manifest["report_sha256"])
            if report["protocol"] != inputs["protocol"] or report["final_test_read"] is not False:
                raise ValueError("Displayed report differs from the selected primary generation")
            reports[horizon] = report
        return PrimaryResearchView(
            primary["primary_version"],
            inputs["registry_version"],
            inputs["intelligence_version"],
            inputs["protocol"],
            versions,
            reports,
        )

    def comparison(
        self, view: PrimaryResearchView, horizon: int, *, active_only: bool = False
    ) -> pd.DataFrame:
        if horizon not in view.evaluations:
            raise ValueError("Select a published predeclared horizon")
        rows = []
        for family, variants in view.reports[horizon]["models"].items():
            for variant, model in variants.items():
                metrics = (
                    model["calibrated_assessment_slices"]["ACTIVE"]["True"]
                    if active_only
                    else model["calibrated_assessment"]
                )
                paired = model.get("paired_assessment", {})
                delta = (
                    paired.get("slices", {})
                    .get("ACTIVE", {})
                    .get("True", {})
                    .get("brier_delta_B_minus_A")
                    if active_only
                    else paired.get("brier_delta_B_minus_A")
                )
                rows.append(
                    {
                        "family": family,
                        "variant": variant,
                        "predeclared_primary": (
                            horizon == view.protocol["primary_horizon"]
                            and family == view.protocol["primary_family"]
                            and variant in {"A", "B_" + view.protocol["primary_b_variant"]}
                        ),
                        **{
                            name: metrics.get(name)
                            for name in (
                                "n",
                                "positives",
                                "brier",
                                "log_loss",
                                "roc_auc",
                                "pr_auc",
                                "pair_balanced_brier",
                                "issuer_balanced_brier",
                                "precision",
                                "coverage",
                            )
                        },
                        "brier_delta_B_minus_A": delta,
                    }
                )
        return pd.DataFrame(rows)

    def predictions(
        self, view: PrimaryResearchView, horizon: int, *, as_of: date, active_only: bool = False
    ) -> pd.DataFrame:
        if horizon not in view.evaluations:
            raise ValueError("Select a published predeclared horizon")
        end = date.fromisoformat(view.protocol["development_end"])
        if as_of > end:
            raise ValueError("The final-test period remains locked")
        path, manifest = registered_manifest(self.paths, view.evaluations[horizon], "evaluation")
        file = checked_file(path.parent, manifest, "predictions")
        body = file.read_bytes()
        expected = next(
            item["sha256"] for item in manifest["files"] if item["name"] == "predictions"
        )
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError("Displayed prediction bytes differ from the registered artifact")
        family = view.protocol["primary_family"]
        variant = "B_" + view.protocol["primary_b_variant"]
        # Explicit column projection avoids decoding outcome/label columns.
        columns = [
            "event_id",
            "event_date",
            "pair_id",
            "leg_a",
            "leg_b",
            "business_group",
            "baseline1_eligible",
            "research_partition",
            f"{family}_A_raw",
            f"{family}_A_calibrated",
            f"{family}_{variant}_raw",
            f"{family}_{variant}_calibrated",
        ]
        rows = pd.read_parquet(io.BytesIO(body), columns=columns)
        dates = pd.to_datetime(rows["event_date"], errors="raise").dt.date
        if dates.isna().any() or dates.gt(end).any():
            raise ValueError("Published predictions include an inadmissible final-test event")
        if not rows["baseline1_eligible"].isin([True, False]).all():
            raise ValueError("Every event needs its actual ACTIVE eligibility")
        rows = rows.loc[dates.le(as_of)].copy()
        if active_only:
            rows = rows.loc[rows["baseline1_eligible"].eq(True)].copy()
        rows = rows.rename(
            columns={
                f"{family}_A_raw": "model_a_raw",
                f"{family}_A_calibrated": "model_a_calibrated",
                f"{family}_{variant}_raw": "model_b_raw",
                f"{family}_{variant}_calibrated": "model_b_calibrated",
                "baseline1_eligible": "ACTIVE_at_event",
            }
        )
        probabilities = rows[
            ["model_a_raw", "model_a_calibrated", "model_b_raw", "model_b_calibrated"]
        ]
        if not probabilities.ge(0).all().all() or not probabilities.le(1).all().all():
            raise ValueError("Stored research probabilities are unavailable or invalid")
        rows["B_meets_research_threshold"] = rows["model_b_calibrated"].ge(
            view.protocol["candidate_threshold"]
        )
        return rows.sort_values(["event_date", "pair_id"], ascending=[False, True])
