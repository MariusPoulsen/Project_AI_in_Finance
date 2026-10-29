"""Lazy, checksum-bound full pair histories supplementing the small showcase bundle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.app_bundle.contracts import PairSeries
from structural_break.config.paths import confined_path


@dataclass
class PairHistory:
    root: Path
    manifest: dict[str, Any]

    @classmethod
    def open(cls, root: Path, registry_version: str, pairs: set[str]) -> PairHistory:
        manifest = json.loads((root / "manifest.json").read_bytes())
        if (
            manifest["schema_version"] != "pair-history-v1"
            or manifest["registry_version"] != registry_version
            or pd.Timestamp(manifest["end"]).year > 2023
            or set(manifest["pairs"]) != pairs
        ):
            raise ValueError("Pair-history registry, roster or development period differs")
        required = {
            "prices.parquet",
            "snapshots.parquet",
            "crossings.parquet",
            *manifest["pairs"].values(),
        }
        if not required <= manifest["files"].keys() or any(
            not confined_path(root, name).is_file() for name in required
        ):
            raise ValueError("Incomplete pair-history export")
        return cls(root, manifest)

    def _read(self, name: str, filters: list[Any]) -> pd.DataFrame:
        path = confined_path(self.root, name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.manifest["files"][name]:
            raise ValueError("Pair-history checksum differs")
        return pd.read_parquet(path, filters=filters)

    def read(self, pair_id: str) -> PairSeries:
        if pair_id not in self.manifest["pairs"]:
            raise ValueError("Pair is outside the pinned history roster")
        state = self._read(self.manifest["pairs"][pair_id], [("pair_id", "=", pair_id)])
        prices = self._read("prices.parquet", [("ticker", "in", pair_id.split("__"))])
        snapshots = self._read("snapshots.parquet", [("pair_id", "=", pair_id)])
        crossings = self._read("crossings.parquet", [("pair_id", "=", pair_id)])
        for frame, column in (
            (state, "trading_date"),
            (prices, "trading_date"),
            (snapshots, "estimation_date"),
            (crossings, "event_date"),
        ):
            dates = pd.to_datetime(frame[column])
            if dates.gt(pd.Timestamp(self.manifest["end"])).any():
                raise ValueError("Final-test rows in development pair history")
        if state.empty or prices.ticker.nunique() != 2:
            raise ValueError("Incomplete history for a pinned pair")
        return PairSeries(pair_id, state, prices, snapshots, crossings)
