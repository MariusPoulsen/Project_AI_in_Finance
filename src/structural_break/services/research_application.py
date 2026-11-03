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
    AppBundle,
    BundleIdentity,
    HorizonData,
    PairSeries,
)

PARTITION_ORDER = ("fit", "calibration", "assessment")


@dataclass(frozen=True)
class ScannerFilters:
    start: date
    end: date
    partitions: tuple[str, ...] = ("assessment",)
    business_groups: tuple[str, ...] = ()
    active_only: bool = False
    min_probability: float = 0.0
    pair_query: str = ""


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

    # ------------------------------------------------------------- headline
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
        # The full pair histories (through the last scored year) take precedence over the
        # showcase series embedded in the bundle, which end with the development period.
        if bundle.pair_loader is not None:
            series = bundle.pair_loader(pair_id)
        elif len(bundle.pair_state) and pair_id in set(bundle.pair_state["pair_id"]):
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

    # ------------------------------------------------------------------ monitor
    # ------------------------------------------------------------- strategy lab
