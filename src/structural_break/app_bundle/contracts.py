"""Typed containers shared by bundle builders, bundle I/O and the app service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

BUNDLE_SCHEMA_VERSION = "app-bundle-v1"
HORIZONS = (20, 10, 30)
FAMILIES = ("logistic", "xgboost")
VARIANTS = ("A", "B_metadata", "B_tone", "B_catalyst", "B_both")
EXPLAINED_VARIANTS = ("A", "B_both")
RUNGS = ("BASELINE_0", "BASELINE_1", "MODEL_A", "MODEL_B", "FULL_SYSTEM")

Source = Literal["workspace", "bundle", "synthetic"]


@dataclass(frozen=True)
class BundleIdentity:
    """Every value the app displays is traceable to these accepted identities."""

    schema_version: str
    source: Source
    synthetic: bool
    primary_version: str
    registry_version: str
    intelligence_version: str
    evaluations: dict[int, str]
    experiments: dict[int, str]
    protocol: dict[str, Any]
    showcase_pairs: tuple[str, ...]
    explanation_status: str
    bundle_id: str

    @property
    def primary_horizon(self) -> int:
        return int(self.protocol["primary_horizon"])

    @property
    def horizons(self) -> tuple[int, ...]:
        return (
            self.primary_horizon,
            *(int(value) for value in self.protocol["sensitivity_horizons"]),
        )


@dataclass
class HorizonData:
    """Presentation tables for one predeclared horizon."""

    report: dict[str, Any]
    events: pd.DataFrame
    curves: pd.DataFrame
    importance: pd.DataFrame
    contributions: pd.DataFrame
    contribution_totals: pd.DataFrame
    feature_profile: pd.DataFrame
    strategy: dict[str, Any] | None = None
    strategy_nav: pd.DataFrame = field(default_factory=pd.DataFrame)
    strategy_trades: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass
class PairSeries:
    """Frozen daily state, prices and monthly relationship history of one pair."""

    pair_id: str
    state: pd.DataFrame
    prices: pd.DataFrame
    snapshots: pd.DataFrame
    crossings: pd.DataFrame


@dataclass
class AppBundle:
    identity: BundleIdentity
    horizons: dict[int, HorizonData]
    pairs: pd.DataFrame
    pair_state: pd.DataFrame
    pair_prices: pd.DataFrame
    pair_snapshots: pd.DataFrame
    pair_crossings: pd.DataFrame
    # Workspace mode loads any pair lazily through verified registry reads.
    pair_loader: Callable[[str], PairSeries] | None = None
