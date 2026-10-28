"""The headline results (Goal 1 forecasters, Goal 2 books, agent desk) from ``demo/results``.

Written by ``scripts/export_results.py``. Every file is checked against the SHA-256 in
``manifest.json`` before it is read; a missing or altered file means no results are shown.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

FOLDER = Path(__file__).resolve().parents[3] / "demo" / "results"
TABLES = ("forecasts", "curves", "books_daily", "trades", "news")

MODELS = {
    "model_a": "Model A (prices only)",
    "r0": "Original Model B (R0)",
    "bag5": "B+rule+ou, bagged",
    "track": "B+rule+ou+track, bagged",
    "full_base": "Desk region: bagged B+rule+ou alone",
    "full": "Desk region: full model (bagged + agent desk)",
}
MODEL_NOTES = {
    "model_a": "Prices and the relationship only; the plan's Model A (Decision 45).",
    "r0": "Model A's inputs plus SEC timing and tone, fixed XGBoost (Decision 45). "
    "Selects the adopted book's trades.",
    "bag5": "R0's inputs plus the rule blocks (peer, state, earnings, momentum) and the "
    "structural OU prior, five seeds bagged (Decision 86b). The pre-registered Goal 1 model.",
    "track": "The pre-registered model plus each pair's and stock's earlier reversion "
    "record (Decision 88b). Best observed, chosen after the fact.",
    "full_base": "The pre-registered model on the events the agent desk scored.",
    "full": "The pre-registered model plus the entry agents' scores (Decisions 110b–c, 119).",
}
BOOKS = {
    "adopted": "Adopted book (R0 selection, monitor exit)",
    "no_monitor": "Same book without the monitor exit",
    "bag5": "Best forecaster's selection",
    "full": "Full model's selection",
}
PERIOD_ROLES = {
    "2010–2017": "selection",
    "2018–2023": "holdout",
    "2024–2025": "final test",
    "2010–2023": "development",
    "2010–2025": "all years",
}


@dataclass(frozen=True)
class Results:
    manifest: dict[str, Any]
    summary: dict[str, Any]
    tables: dict[str, pd.DataFrame]
    final_test: dict[str, Any] | None = None
    periods: tuple[str, ...] = field(default_factory=tuple)

    @property
    def final_included(self) -> bool:
        return bool(self.manifest.get("final_test_included"))

    def metrics(self) -> pd.DataFrame:
        frame = pd.DataFrame(self.summary["goal1"])
        r0 = frame[frame["model"].eq("r0")].set_index("period")
        model_a = frame["model"].eq("model_a")
        for column in ("n", "base_rate"):
            frame.loc[model_a, column] = frame.loc[model_a, "period"].map(r0[column])
        return frame

    def book_stats(self) -> pd.DataFrame:
        rows = []
        for key, book in self.summary["books"].items():
            for period, values in book["periods"].items():
                rows.append(
                    {
                        "book": key,
                        "label": BOOKS.get(key, book["label"]),
                        "period": period,
                        **values,
                    }
                )
        return pd.DataFrame(rows)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@st.cache_resource(show_spinner=False, max_entries=2)
def _read(folder: str, digest: str) -> Results | None:
    del digest  # cache key: a changed manifest is a different set of results
    root = Path(folder)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    files: dict[str, str] = manifest["files"]
    for name, sha in files.items():
        if not (root / name).is_file() or _sha(root / name) != sha:
            return None
    tables = {name: pd.read_parquet(root / f"{name}.parquet") for name in TABLES}
    for name, column in (("forecasts", "event_date"), ("books_daily", "session_date")):
        tables[name][column] = pd.to_datetime(tables[name][column])
    for column in ("entry_date", "exit_date"):
        tables["trades"][column] = pd.to_datetime(tables["trades"][column])
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    final = root / "final_test.json"
    report = json.loads(final.read_text(encoding="utf-8")) if "final_test.json" in files else None
    present = tuple(dict.fromkeys(m["period"] for m in summary["goal1"]))
    return Results(manifest, summary, tables, report, present)


def load(folder: Path = FOLDER) -> Results | None:
    """The verified results, or None when they are missing or do not match the manifest."""
    manifest = folder / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        files: dict[str, str] = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        # Verified on every load, not only when first cached: a file changed afterwards
        # must not be served from the cache.
        for name, sha in files.items():
            if not (folder / name).is_file() or _sha(folder / name) != sha:
                return None
        return _read(str(folder.resolve()), _sha(manifest))
    except Exception:  # noqa: BLE001 - fail closed: no partial results
        return None


EXIT_LABELS = {
    "TAKE_PROFIT": "Take profit",
    "CONVERGED": "Take profit",
    "CONVERGENCE": "Take profit",
    "TIMEOUT": "Time stop",
    "TIME_STOP": "Time stop",
    "MONITOR": "Monitor exit",
    "NEWS_EXIT": "News exit",
}


def year_period(year: int) -> str:
    if year <= 2017:
        return "selection"
    return "holdout" if year <= 2023 else "final test"


def event_table(results: Results, pair_id: str | None = None) -> pd.DataFrame:
    """Every scored divergence with the headline probabilities and the adopted book's trade."""
    forecasts = results.tables["forecasts"]
    if pair_id is not None:
        forecasts = forecasts[forecasts["pair_id"].eq(pair_id)]
    trades = results.tables["trades"].set_index("event_id")
    rows = pd.DataFrame(
        {
            "event_id": forecasts["event_id"],
            "date": forecasts["event_date"],
            "year": forecasts["year"].astype(int),
            "pair": forecasts["pair_id"],
            "group": forecasts["business_group"],
            "period": forecasts["year"].astype(int).map(year_period),
            "z_at_event": forecasts["z_signed"].astype(float),
            "p_r0": forecasts["p_r0"].astype(float),
            "p_bag5": forecasts["p_bag5"].astype(float),
            "p_track": forecasts["p_track"].astype(float),
            "p_full": forecasts["p_full"].astype(float),
            "candidate": forecasts["r0_top20"].astype(bool),
            "traded": forecasts["traded"].astype(bool),
        }
    )
    labelled = forecasts["labelled"].astype(bool) & forecasts["y"].notna()
    rows["outcome"] = "Unlabelled"
    rows.loc[labelled & forecasts["y"].eq(1), "outcome"] = "Reverted"
    rows.loc[labelled & forecasts["y"].eq(0), "outcome"] = "Did not revert"
    rows["exit"] = (
        rows["event_id"]
        .map(trades["exit_reason"])
        .map(lambda r: EXIT_LABELS.get(r, r) if isinstance(r, str) else None)
    )
    rows["trade_bps"] = rows["event_id"].map(trades["gross_return"]) * 1e4
    return rows.sort_values(["date", "p_r0"], ascending=[False, False]).reset_index(drop=True)


def period_label(period: str) -> str:
    role = PERIOD_ROLES.get(period)
    return f"{period} ({role})" if role else period
