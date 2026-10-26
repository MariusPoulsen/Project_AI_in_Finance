"""Read-only queries behind the full research application (PLAN P7).

All filtering and aggregation lives here so Streamlit page code only lays out
widgets and charts. The service holds an already-verified `AppBundle` and never
trains, predicts, downloads or writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from structural_break.app_bundle.contracts import (
    FAMILIES,
    RUNGS,
    VARIANTS,
    AppBundle,
    BundleIdentity,
    HorizonData,
    PairSeries,
)
from structural_break.app_bundle.features import BLOCK_ORDER, feature_block, feature_label

VARIANT_LABELS = {
    "A": "A · quantitative",
    "B_metadata": "B · + SEC metadata",
    "B_tone": "B · + FinBERT tone",
    "B_catalyst": "B · + Gemma catalysts",
    "B_both": "B · all SEC evidence",
}
RUNG_LABELS = {
    "BASELINE_0": "Baseline 0 · every fresh crossing",
    "BASELINE_1": "Baseline 1 · econometrically ACTIVE",
    "MODEL_A": "Model A selected",
    "MODEL_B": "Model B selected",
    "FULL_SYSTEM": "Full System (agents)",
}
PARTITION_ORDER = ("fit", "calibration", "assessment")
COVERAGE_LABELS = {
    "sec_a_metadata_coverage_unknown": "Leg A SEC metadata UNKNOWN",
    "sec_b_metadata_coverage_unknown": "Leg B SEC metadata UNKNOWN",
    "sentiment_both_known": "FinBERT tone known for both legs",
    "event_type_UNKNOWN": "Catalyst UNKNOWN (unscheduled/invalid)",
    "event_type_NONE": "Catalyst extracted: none found",
}


@dataclass(frozen=True)
class ScannerFilters:
    start: date
    end: date
    partitions: tuple[str, ...] = ("assessment",)
    business_groups: tuple[str, ...] = ()
    active_only: bool = False
    min_probability: float = 0.0
    pair_query: str = ""


@dataclass(frozen=True)
class Headline:
    horizon: int
    family: str
    a_brier: float | None
    b_brier: float | None
    delta: float | None
    interval: tuple[float, float] | None
    interval_below_zero: bool
    quarter_blocks: int | None
    a_auc: float | None
    b_auc: float | None
    n: int
    positives: int
    prevalence_brier: float | None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


class ResearchApplicationService:
    def __init__(self, bundle: AppBundle) -> None:
        self.bundle = bundle
        self._series_cache: dict[str, PairSeries | None] = {}

    # ------------------------------------------------------------------ identity
    @property
    def identity(self) -> BundleIdentity:
        return self.bundle.identity

    @property
    def protocol(self) -> dict[str, Any]:
        return self.bundle.identity.protocol

    def horizons(self) -> tuple[int, ...]:
        return tuple(h for h in self.identity.horizons if h in self.bundle.horizons)

    def data(self, horizon: int) -> HorizonData:
        if horizon not in self.bundle.horizons:
            raise ValueError("Select a published predeclared horizon")
        return self.bundle.horizons[horizon]

    def version_line(self, horizon: int | None = None) -> str:
        identity = self.identity
        parts = [f"Primary {identity.primary_version}", f"Registry {identity.registry_version}"]
        if horizon is not None:
            parts.append(f"Evaluation h{horizon} {identity.evaluations.get(horizon, 'n/a')}")
            if horizon in identity.experiments:
                parts.append(f"Backtest {identity.experiments[horizon][:16]}")
        parts.append(f"Bundle {identity.bundle_id}")
        return " · ".join(parts)

    def periods(self) -> list[dict[str, Any]]:
        p = self.protocol
        return [
            {
                "period": "Formation warm-up",
                "start": p["data_start"],
                "end": p["fit_start"],
                "use": "504-session warm-up only",
            },
            {
                "period": "Fit",
                "start": p["fit_start"],
                "end": p["fit_end"],
                "use": "Model fitting; forward tuning folds "
                "{', '.join(map(str, p['tuning_years']))}",
            },
            {
                "period": "Calibration",
                "start": p["calibration_start"],
                "end": p["calibration_end"],
                "use": "Sigmoid calibration only",
            },
            {
                "period": "Assessment",
                "start": p["assessment_start"],
                "end": p["assessment_end"],
                "use": "Independent A vs B comparison (already observed)",
            },
            {
                "period": "Final test",
                "start": "2024-01-01",
                "end": "2025-12-31",
                "use": "LOCKED — not in this application",
            },
        ]

    # ------------------------------------------------------------- headline
    def headline(self, horizon: int, family: str | None = None) -> Headline:
        report = self.data(horizon).report
        family = family or self.protocol["primary_family"]
        b_name = "B_" + self.protocol["primary_b_variant"]
        models = report["models"][family]
        a, b = models["A"]["calibrated_assessment"], models[b_name]["calibrated_assessment"]
        paired = models[b_name].get("paired_assessment", {})
        interval = paired.get("quarter_block_percentile_interval_95")
        prevalence = report.get("fitting_prevalence_baseline", {}).get("assessment", {})
        return Headline(
            horizon=horizon,
            family=family,
            a_brier=_float(a.get("brier")),
            b_brier=_float(b.get("brier")),
            delta=_float(paired.get("brier_delta_B_minus_A")),
            interval=(float(interval[0]), float(interval[1])) if interval else None,
            interval_below_zero=bool(paired.get("interval_below_zero", False)),
            quarter_blocks=paired.get("observed_quarter_blocks"),
            a_auc=_float(a.get("roc_auc")),
            b_auc=_float(b.get("roc_auc")),
            n=int(a.get("n") or 0),
            positives=int(a.get("positives") or 0),
            prevalence_brier=_float(prevalence.get("brier")),
        )

    def verdict(self, headline: Headline) -> tuple[str, str]:
        """Plain-language reading of the predeclared primary comparison."""
        if headline.delta is None or headline.interval is None:
            return "unavailable", "The paired comparison is not available for this selection."
        low, high = headline.interval
        if high < 0:
            return "favours_b", "Model B has lower Brier loss and the 95% interval lies below zero."
        if low > 0:
            return "favours_a", "Model A has lower Brier loss and the 95% interval lies above zero."
        direction = "B" if headline.delta < 0 else "A"
        return (
            "inconclusive",
            f"The point estimate favours Model {direction}, but the 95% quarter-block interval "
            "includes zero: no established difference.",
        )

    def universe_counts(self, horizon: int) -> dict[str, int]:
        events = self.data(horizon).events
        return {
            "events": len(events),
            "pairs": int(events["pair_id"].nunique()),
            "issuers": len(set(events["leg_a"]) | set(events["leg_b"])),
            "groups": int(events["business_group"].nunique()),
            "assessment_events": int(events["research_partition"].eq("assessment").sum()),
        }

    # ------------------------------------------------------- model comparison
    def comparison(self, horizon: int, *, active_only: bool = False) -> pd.DataFrame:
        report = self.data(horizon).report
        rows = []
        for family, variants in report["models"].items():
            for variant, model in variants.items():
                metrics = (
                    model["calibrated_assessment_slices"]["ACTIVE"].get("True", {})
                    if active_only
                    else model["calibrated_assessment"]
                )
                paired = model.get("paired_assessment", {})
                if active_only:
                    delta = (
                        paired.get("slices", {})
                        .get("ACTIVE", {})
                        .get("True", {})
                        .get("brier_delta_B_minus_A")
                    )
                    interval = None
                else:
                    delta = paired.get("brier_delta_B_minus_A")
                    interval = paired.get("quarter_block_percentile_interval_95")
                rows.append(
                    {
                        "family": family,
                        "variant": variant,
                        "model": VARIANT_LABELS.get(variant, variant),
                        "primary": (
                            horizon == self.protocol["primary_horizon"]
                            and family == self.protocol["primary_family"]
                            and variant in {"A", "B_" + self.protocol["primary_b_variant"]}
                        ),
                        "n": metrics.get("n"),
                        "positives": metrics.get("positives"),
                        "brier": _float(metrics.get("brier")),
                        "log_loss": _float(metrics.get("log_loss")),
                        "roc_auc": _float(metrics.get("roc_auc")),
                        "pr_auc": _float(metrics.get("pr_auc")),
                        "pair_balanced_brier": _float(metrics.get("pair_balanced_brier")),
                        "issuer_balanced_brier": _float(metrics.get("issuer_balanced_brier")),
                        "delta_brier_B_minus_A": _float(delta),
                        "ci_low": _float(interval[0]) if interval else None,
                        "ci_high": _float(interval[1]) if interval else None,
                    }
                )
        frame = pd.DataFrame(rows)
        order = {name: index for index, name in enumerate(VARIANTS)}
        frame["_order"] = frame["variant"].map(order)
        return frame.sort_values(["family", "_order"]).drop(columns="_order").reset_index(drop=True)

    def curves(self, horizon: int, kind: str, family: str) -> pd.DataFrame:
        curves = self.data(horizon).curves
        if curves.empty:
            return curves
        rows = curves.loc[curves["kind"].eq(kind) & curves["family"].eq(family)].copy()
        rows["model"] = rows["variant"].map(VARIANT_LABELS)
        return rows

    def slices(self, horizon: int, dimension: str, family: str, variant: str) -> pd.DataFrame:
        model = self.data(horizon).report["models"][family][variant]
        calibrated = model["calibrated_assessment_slices"].get(dimension, {})
        paired = model.get("paired_assessment", {}).get("slices", {}).get(dimension, {})
        rows = []
        for group, metrics in calibrated.items():
            rows.append(
                {
                    "group": group,
                    "n": int(metrics.get("n") or 0),
                    "positives": int(metrics.get("positives") or 0),
                    "pairs": metrics.get("pairs"),
                    "brier": _float(metrics.get("brier")),
                    "roc_auc": _float(metrics.get("roc_auc")),
                    "delta_brier_B_minus_A": _float(
                        paired.get(group, {}).get("brier_delta_B_minus_A")
                    ),
                }
            )
        return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)

    def importance(self, horizon: int, family: str, variant: str, top: int = 15) -> pd.DataFrame:
        table = self.data(horizon).importance
        if table.empty:
            return table
        rows = table.loc[table["family"].eq(family) & table["variant"].eq(variant)].copy()
        rows["label"] = rows["feature"].map(feature_label)
        rows["block"] = rows["feature"].map(feature_block)
        return rows.sort_values("mean_abs_contribution", ascending=False).head(top)

    def block_importance(self, horizon: int, family: str, variant: str) -> pd.DataFrame:
        table = self.data(horizon).importance
        if table.empty:
            return table
        rows = table.loc[table["family"].eq(family) & table["variant"].eq(variant)]
        grouped = rows.groupby("block")["mean_abs_contribution"].sum().reset_index()
        grouped["share"] = grouped["mean_abs_contribution"] / grouped["mean_abs_contribution"].sum()
        grouped["_order"] = grouped["block"].map({b: i for i, b in enumerate(BLOCK_ORDER)})
        return grouped.sort_values("_order").drop(columns="_order")

    def tuning(self, horizon: int, family: str, variant: str) -> pd.DataFrame:
        model = self.data(horizon).report["models"][family][variant]
        rows = []
        for candidate in model.get("tuning", []):
            parameters = ", ".join(f"{k}={v}" for k, v in candidate["parameters"].items())
            row: dict[str, Any] = {
                "parameters": parameters,
                "mean_forward_brier": _float(candidate.get("mean_brier")),
                "chosen": candidate["parameters"] == model.get("chosen_parameters"),
            }
            for fold in candidate.get("folds", []):
                row[f"brier_{fold['year']}"] = _float(fold.get("brier"))
            rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ scanner
    def scanner(self, horizon: int, filters: ScannerFilters) -> pd.DataFrame:
        events = self.data(horizon).events
        family = self.protocol["primary_family"]
        b_name = f"{family}_B_{self.protocol['primary_b_variant']}_calibrated"
        a_name = f"{family}_A_calibrated"
        dates = pd.to_datetime(events["event_date"]).dt.date
        mask = dates.between(filters.start, filters.end)
        if filters.partitions:
            mask &= events["research_partition"].isin(filters.partitions)
        if filters.business_groups:
            mask &= events["business_group"].isin(filters.business_groups)
        if filters.active_only:
            mask &= events["baseline1_eligible"].eq(True)
        mask &= events[b_name].ge(filters.min_probability)
        if filters.pair_query:
            query = filters.pair_query.strip().upper()
            mask &= events["pair_id"].str.upper().str.contains(query, regex=False)
        rows = events.loc[mask].copy()
        output = pd.DataFrame(
            {
                "event_id": rows["event_id"],
                "date": pd.to_datetime(rows["event_date"]).dt.date,
                "pair": rows["pair_id"],
                "group": rows["business_group"],
                "period": rows["research_partition"],
                "ACTIVE": rows["baseline1_eligible"].astype(bool),
                "z_at_event": rows["z_signed"] if "z_signed" in rows else np.nan,
                "p_A": rows[a_name].astype(float),
                "p_B": rows[b_name].astype(float),
            }
        )
        output["B_minus_A"] = output["p_B"] - output["p_A"]
        output["catalyst"] = (
            rows["catalyst_event_type"] if "catalyst_event_type" in rows else "UNKNOWN"
        )
        output["outcome"] = np.where(rows["y_revert_success"].eq(1), "Reverted", "Did not revert")
        return output.sort_values(["date", "p_B"], ascending=[False, False]).reset_index(drop=True)

    def scanner_summary(self, rows: pd.DataFrame) -> dict[str, Any]:
        if rows.empty:
            return {"events": 0, "pairs": 0, "reverted": None, "mean_p_b": None}
        return {
            "events": len(rows),
            "pairs": int(rows["pair"].nunique()),
            "reverted": float(rows["outcome"].eq("Reverted").mean()),
            "mean_p_b": float(rows["p_B"].mean()),
            "mean_p_a": float(rows["p_A"].mean()),
        }

    def business_groups(self, horizon: int) -> list[str]:
        return sorted(self.data(horizon).events["business_group"].dropna().unique().tolist())

    # -------------------------------------------------------------- pair detail
    def pairs(self) -> pd.DataFrame:
        return self.bundle.pairs

    def hero_pair(self, horizon: int) -> str | None:
        """A showcase pair with daily history and the most ACTIVE assessment events."""
        pairs = self.bundle.pairs
        candidates = [
            p for p in self.identity.showcase_pairs if p in set(pairs["pair_id"])
        ] or pairs.loc[pairs["series_available"], "pair_id"].tolist()
        if not candidates:
            return None
        events = self.data(horizon).events
        assessed = events.loc[
            events["pair_id"].isin(candidates) & events["research_partition"].eq("assessment")
        ]
        score = (
            assessed.assign(active=assessed["baseline1_eligible"].astype(bool))
            .groupby("pair_id")
            .agg(active=("active", "sum"), n=("event_id", "size"))
        )
        if "KO__PEP" in candidates:
            return "KO__PEP"
        if score.empty:
            return candidates[0]
        score = score.sort_values(["active", "n"], ascending=False)
        return str(score.index[0])

    def pair_series(self, pair_id: str) -> PairSeries | None:
        if pair_id in self._series_cache:
            return self._series_cache[pair_id]
        bundle = self.bundle
        series: PairSeries | None = None
        if len(bundle.pair_state) and pair_id in set(bundle.pair_state["pair_id"]):
            legs = pair_id.split("__")
            series = PairSeries(
                pair_id,
                bundle.pair_state.loc[bundle.pair_state["pair_id"].eq(pair_id)].reset_index(
                    drop=True
                ),
                bundle.pair_prices.loc[bundle.pair_prices["ticker"].isin(legs)].reset_index(
                    drop=True
                ),
                bundle.pair_snapshots.loc[bundle.pair_snapshots["pair_id"].eq(pair_id)].reset_index(
                    drop=True
                )
                if len(bundle.pair_snapshots)
                else pd.DataFrame(),
                bundle.pair_crossings.loc[bundle.pair_crossings["pair_id"].eq(pair_id)].reset_index(
                    drop=True
                )
                if len(bundle.pair_crossings)
                else pd.DataFrame(),
            )
        elif bundle.pair_loader is not None:
            series = bundle.pair_loader(pair_id)
        self._series_cache[pair_id] = series
        return series

    def normalised_prices(self, series: PairSeries, start: date, end: date) -> pd.DataFrame:
        prices: pd.DataFrame = series.prices.copy()
        prices["trading_date"] = pd.to_datetime(prices["trading_date"])
        prices = pd.DataFrame(prices.loc[prices["trading_date"].dt.date.between(start, end)])
        if prices.empty:
            return prices
        first = prices.sort_values("trading_date").groupby("ticker")["adj_close"].transform("first")
        prices["index"] = 100 * prices["adj_close"] / first
        return prices

    def pair_events(self, horizon: int, pair_id: str) -> pd.DataFrame:
        events = self.data(horizon).events
        family = self.protocol["primary_family"]
        b_name = f"{family}_B_{self.protocol['primary_b_variant']}_calibrated"
        rows = events.loc[events["pair_id"].eq(pair_id)].copy()
        rows = rows.assign(
            date=pd.to_datetime(rows["event_date"]),
            p_A=rows[f"{family}_A_calibrated"].astype(float),
            p_B=rows[b_name].astype(float),
            outcome=np.where(rows["y_revert_success"].eq(1), "Reverted", "Did not revert"),
        )
        return rows.sort_values("date", ascending=False).reset_index(drop=True)

    def explanation(self, horizon: int, event_id: str, model: str) -> dict[str, Any] | None:
        data = self.data(horizon)
        totals = data.contribution_totals
        if totals.empty:
            return None
        total = totals.loc[totals["event_id"].eq(event_id) & totals["model"].eq(model)]
        if total.empty:
            return None
        parts = data.contributions.loc[
            data.contributions["event_id"].eq(event_id) & data.contributions["model"].eq(model)
        ].copy()
        parts["label"] = parts["feature"].map(feature_label)
        parts["block"] = parts["feature"].map(feature_block)
        parts = parts.sort_values("contribution", key=np.abs, ascending=False)
        row = total.iloc[0]
        return {
            "base": float(row["base"]),
            "other": float(row["other"]),
            "margin": float(row["margin"]),
            "raw_probability": float(row["raw_probability"]),
            "calibrated_probability": float(row["calibrated_probability"]),
            "contributions": parts.reset_index(drop=True),
        }

    def evidence(self, horizon: int, event_id: str) -> dict[str, str]:
        """SEC evidence fields as display strings; missing stays UNKNOWN, never zero."""
        events = self.data(horizon).events
        row = events.loc[events["event_id"].eq(event_id)]
        if row.empty:
            return {}
        values = row.iloc[0].to_dict()

        def number(name: str, pattern: str, *, unknown_flag: str | None = None) -> str:
            if unknown_flag is not None and values.get(unknown_flag) == 1:
                return "UNKNOWN"
            value = _float(values.get(name))
            return "UNKNOWN" if value is None else pattern.format(value)

        catalyst = str(values.get("catalyst_event_type", "UNKNOWN"))
        tone_known = _float(values.get("sentiment_both_known"))
        return {
            "Leg A latest 8-K": number(
                "sec_a_days_since_latest_8k",
                "{:.0f} days ago",
                unknown_flag="sec_a_metadata_coverage_unknown",
            ),
            "Leg B latest 8-K": number(
                "sec_b_days_since_latest_8k",
                "{:.0f} days ago",
                unknown_flag="sec_b_metadata_coverage_unknown",
            ),
            "Leg A FinBERT net tone": number("sentiment_a_net", "{:+.2f}"),
            "Leg B FinBERT net tone": number("sentiment_b_net", "{:+.2f}"),
            "Tone known for both legs": "UNKNOWN"
            if tone_known is None
            else ("Yes" if tone_known == 1 else "No"),
            "Catalyst type": catalyst.replace("_", " ").title()
            if catalyst not in {"UNKNOWN", "NONE"}
            else ("None found" if catalyst == "NONE" else "UNKNOWN"),
            "Catalyst direction": str(values.get("catalyst_direction", "UNKNOWN")).title()
            if catalyst != "UNKNOWN"
            else "UNKNOWN",
            "Catalyst materiality": str(values.get("catalyst_materiality", "UNKNOWN")).title()
            if catalyst != "UNKNOWN"
            else "UNKNOWN",
            "Affected leg": str(values.get("catalyst_affected_leg", "UNKNOWN"))
            if catalyst != "UNKNOWN"
            else "UNKNOWN",
            "Extraction confidence": number("extraction_confidence", "{:.0%}")
            if catalyst != "UNKNOWN"
            else "UNKNOWN",
        }

    # ------------------------------------------------------------------ monitor
    def cohorts(self, horizon: int) -> pd.DataFrame:
        cohorts = self.data(horizon).report.get("cohorts", {})
        rows = [
            {"period": name, **{k: v for k, v in values.items()}}
            for name, values in cohorts.items()
        ]
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        frame["success_rate"] = frame["positives"] / frame["n"].where(frame["n"] > 0)
        order = {name: index for index, name in enumerate(PARTITION_ORDER)}
        frame = frame.sort_values("period", key=lambda p: p.map(order))
        columns = ["period", "n", "positives", "success_rate", "pairs", "issuers", "ACTIVE"]
        return frame.reindex(columns=[c for c in columns if c in frame]).reset_index(drop=True)

    def events_by_year(self, horizon: int) -> pd.DataFrame:
        events = self.data(horizon).events
        years = pd.to_datetime(events["event_date"]).dt.year
        grouped = (
            events.assign(year=years)
            .groupby(["year", "research_partition"])
            .agg(events=("event_id", "size"), reverted=("y_revert_success", "mean"))
            .reset_index()
        )
        return grouped

    def coverage(self, horizon: int) -> pd.DataFrame:
        coverage = self.data(horizon).report.get("text_coverage", {})
        rows = []
        for period, data in coverage.items():
            for year, values in data.get("yearly", {}).items():
                n = values.get("n", 0)
                for flag, ones in values.get("flags", {}).items():
                    rows.append(
                        {
                            "period": period,
                            "year": int(year),
                            "flag": flag,
                            "label": COVERAGE_LABELS.get(flag, flag),
                            "n": n,
                            "share": ones / n if n else None,
                        }
                    )
        return pd.DataFrame(rows)

    def coverage_table(self, horizon: int) -> pd.DataFrame:
        """Indicator × period shares, with each period's event denominator in the header."""
        rows = self.coverage_summary(horizon)
        if rows.empty:
            return rows
        rows["column"] = rows["period"].str.capitalize() + " (n=" + rows["events"].astype(str) + ")"
        order = {name: index for index, name in enumerate(PARTITION_ORDER)}
        columns = rows.drop_duplicates("period").sort_values("period", key=lambda p: p.map(order))[
            "column"
        ]
        table = rows.pivot_table(
            index="indicator", columns="column", values="share", aggfunc="first"
        )
        return table.reindex(columns=list(columns)).reset_index()

    def coverage_summary(self, horizon: int) -> pd.DataFrame:
        coverage = self.data(horizon).report.get("text_coverage", {})
        rows = []
        for period, data in coverage.items():
            n = data.get("n", 0)
            for flag, values in data.get("flags", {}).items():
                rows.append(
                    {
                        "period": period,
                        "indicator": COVERAGE_LABELS.get(flag, flag),
                        "events": n,
                        "flagged": values.get("ones"),
                        "share": values.get("ones", 0) / n if n else None,
                        "missing": values.get("missing"),
                    }
                )
        return pd.DataFrame(rows)

    def drift_features(self, horizon: int) -> list[str]:
        profile = self.data(horizon).feature_profile
        return [] if profile.empty else sorted(profile["feature"].unique().tolist())

    def drift(self, horizon: int, feature: str) -> pd.DataFrame:
        profile = self.data(horizon).feature_profile
        rows = profile.loc[profile["feature"].eq(feature)].copy()
        rows["period"] = rows["year"].map(self._period_of_year)
        return rows.sort_values("year")

    def _period_of_year(self, year: int) -> str:
        p = self.protocol
        if year <= int(str(p["fit_end"])[:4]):
            return "fit"
        if year <= int(str(p["calibration_end"])[:4]):
            return "calibration"
        return "assessment"

    def inventory(self, horizon: int) -> pd.DataFrame:
        report = self.data(horizon).report
        rows = []
        for family in FAMILIES:
            for variant in VARIANTS:
                model = report["models"].get(family, {}).get(variant)
                if model is None:
                    continue
                calibrator = model.get("calibrator", {})
                rows.append(
                    {
                        "bundle": f"{family}_{variant}",
                        "features": len(model.get("feature_columns", [])),
                        "chosen_parameters": ", ".join(
                            f"{k}={v}" for k, v in model.get("chosen_parameters", {}).items()
                        ),
                        "calibrator_slope": _float(calibrator.get("slope")),
                        "calibrator_intercept": _float(calibrator.get("intercept")),
                        "calibrator_status": calibrator.get("status"),
                        "reload_max_error": _float(model.get("reload_max_error")),
                        "assessment_brier": _float(model["calibrated_assessment"].get("brier")),
                    }
                )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------- strategy lab
    def strategy(self, horizon: int) -> dict[str, Any] | None:
        return self.data(horizon).strategy

    def strategy_rungs(self, horizon: int, role: str = "HEADLINE") -> pd.DataFrame:
        summary = self.strategy(horizon)
        if not summary:
            return pd.DataFrame()
        rows = pd.DataFrame(summary["rungs"])
        rows = rows.loc[rows["role"].eq(role)].copy()
        rows["label"] = rows["rung"].map(RUNG_LABELS)
        rows["_order"] = rows["rung"].map({r: i for i, r in enumerate(RUNGS)})
        return (
            rows.sort_values(["threshold", "_order"]).drop(columns="_order").reset_index(drop=True)
        )

    def strategy_thresholds(self, horizon: int) -> pd.DataFrame:
        summary = self.strategy(horizon)
        if not summary:
            return pd.DataFrame()
        rows = pd.DataFrame(summary["rungs"])
        rows = rows.loc[
            rows["role"].isin(["HEADLINE", "THRESHOLD_SENSITIVITY"])
            & rows["rung"].isin(["MODEL_A", "MODEL_B"])
        ]
        return rows.sort_values(["threshold", "rung"]).reset_index(drop=True)

    def strategy_costs(self, horizon: int, rung: str) -> pd.DataFrame:
        summary = self.strategy(horizon)
        if not summary:
            return pd.DataFrame()
        rows = pd.DataFrame(summary["cost_grid"])
        return rows.loc[rows["rung"].eq(rung)].reset_index(drop=True)

    def strategy_comparisons(self, horizon: int) -> pd.DataFrame:
        summary = self.strategy(horizon)
        if not summary:
            return pd.DataFrame()
        rows = []
        for item in summary["comparisons"]:
            left = RUNG_LABELS[item["left"]].split(" ·")[0]
            label = f"{left} → {RUNG_LABELS[item['right']].split(' ·')[0]}"
            if item.get("status") == "NOT_RUN":
                rows.append(
                    {
                        "comparison": label,
                        "status": "NOT_RUN",
                        "estimate": None,
                        "low": None,
                        "high": None,
                        "note": item.get("reason"),
                    }
                )
                continue
            known = item.get("common_known", {})
            interval = known.get("interval")
            rows.append(
                {
                    "comparison": label,
                    "status": "RUN",
                    "estimate": _float(known.get("estimate")),
                    "low": _float(interval[0]) if interval else None,
                    "high": _float(interval[1]) if interval else None,
                    "note": known.get("unavailable_reason")
                    or f"{known.get('contributing_months')} populated months",
                }
            )
        return pd.DataFrame(rows)

    def strategy_nav(self, horizon: int) -> pd.DataFrame:
        nav = self.data(horizon).strategy_nav
        if nav.empty:
            return nav
        nav = nav.copy()
        nav["at"] = pd.to_datetime(nav["at"], utc=True)
        nav["date"] = nav["at"].dt.tz_convert(None).dt.normalize()
        daily = nav.sort_values("at").groupby(["rung", "date"], as_index=False).last()
        daily["label"] = daily["rung"].map(RUNG_LABELS)
        return daily

    def strategy_portfolios(self, horizon: int) -> pd.DataFrame:
        summary = self.strategy(horizon)
        if not summary:
            return pd.DataFrame()
        rows = pd.DataFrame(summary["portfolios"])
        rows["label"] = rows["rung"].map(RUNG_LABELS)
        return rows

    def strategy_trades(self, horizon: int, rung: str, disposition: str) -> pd.DataFrame:
        trades = self.data(horizon).strategy_trades
        if trades.empty or rung not in trades:
            return pd.DataFrame()
        rows = trades.loc[trades[rung].eq(disposition)].copy()
        for name in ("net_return", "gross_return", "mae", "mfe"):
            if name in rows:
                rows[name + "_bps"] = rows[name].astype(float) * 1e4
        return rows.reset_index(drop=True)

    def trade_outcomes(self, horizon: int, rung: str) -> pd.DataFrame:
        """Selected vs withheld priced trade returns (rejected-trade analysis)."""
        trades = self.data(horizon).strategy_trades
        if trades.empty or rung not in trades:
            return pd.DataFrame()
        rows = trades.loc[
            trades["status"].eq("COMPLETE") & trades[rung].isin(["SELECTED", "WITHHELD"])
        ]
        return pd.DataFrame(
            {
                "disposition": rows[rung].map(
                    {"SELECTED": "Selected", "WITHHELD": "Withheld (counterfactual)"}
                ),
                "net_bps": rows["net_return"].astype(float) * 1e4,
                "reason": rows["reason"],
            }
        )
