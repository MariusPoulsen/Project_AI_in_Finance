"""Where the data comes from, and the project's own data as downloads.

Every downloadable file is built from the verified results the app has already loaded (the
SHA-256 manifest of ``demo/results``), so a download always matches what the pages show.
Raw third-party data is described with its source, not redistributed.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from functools import partial
from typing import Any

import pandas as pd
import streamlit as st

from structural_break.app_bundle.features import feature_label
from structural_break.app_ui.results import BOOKS, MODELS, Results, period_label

SOURCES = [
    (
        "Daily stock prices",
        "Yahoo Finance",
        "Open, high, low, close, adjusted close and volume for the 250 stocks, and the VIX",
        "2004–2025",
    ),
    (
        "Company filings",
        "SEC EDGAR",
        "Filing metadata (form, items, acceptance time) and 8-K text, for filing timing, "
        "FinBERT tone and the 8-K news exit",
        "2004–2025",
    ),
    (
        "Company news headlines",
        "FNSPID (development) · TickerTick (final test)",
        "Company-specific headlines read by the agent desk's entry agents and position monitor",
        "2010–2023 · 2024–2025",
    ),
    (
        "Cash rate",
        "13-week US Treasury bill (Yahoo ^IRX)",
        "Interest earned on the book's cash; Sharpe ratios are measured in excess of it",
        "2004–2025",
    ),
    (
        "Language models",
        "Gemma (Google AI Studio, free tier) · FinBERT",
        "The agent desk's assessments and the tone of filings and headlines",
        "Run once per case",
    ),
]
LINKS = {
    "Yahoo Finance": "https://finance.yahoo.com",
    "SEC EDGAR": "https://www.sec.gov/edgar",
    "FNSPID": "https://huggingface.co/datasets/Zihan1004/FNSPID",
    "TickerTick": "https://github.com/hczhu/TickerTick-API",
}
PROBABILITIES = {
    "p_model_a": "model_a",
    "p_r0": "r0",
    "p_bag5": "bag5",
    "p_track": "track",
    "p_full": "full",
}
EXIT_REASONS = {
    "CONVERGENCE": "Take profit",
    "TIMEOUT": "Time stop",
    "NEWS_EXIT": "8-K news exit",
    "MONITOR": "Monitor exit",
}


def _period(year: int) -> str:
    if year <= 2017:
        return "selection (2010–2017)"
    return "holdout (2018–2023)" if year <= 2023 else "final test (2024–2025)"


def events(results: Results) -> pd.DataFrame:
    forecasts = results.tables["forecasts"]
    trades = results.tables["trades"].set_index("event_id")
    table = pd.DataFrame(
        {
            "event_id": forecasts["event_id"],
            "date": forecasts["event_date"].dt.date,
            "period": forecasts["year"].astype(int).map(_period),
            "pair": forecasts["pair_id"],
            "stock_a": forecasts["leg_a"],
            "stock_b": forecasts["leg_b"],
            "business_group": forecasts["business_group"],
            "spread_z": forecasts["z_signed"].round(4),
            "reverted": forecasts["y"].where(forecasts["labelled"]),
        }
    )
    for column, model in PROBABILITIES.items():
        if column in forecasts:
            table[f"p_revert_{model}"] = forecasts[column].round(6)
    table["r0_top20"] = forecasts["r0_top20"].astype(bool)
    table["traded_by_adopted_book"] = forecasts["traded"].astype(bool)
    table["trade_exit"] = table["event_id"].map(trades["exit_reason"]).map(EXIT_REASONS)
    table["trade_gross_return"] = table["event_id"].map(trades["gross_return"]).round(6)
    return table


def event_features(results: Results) -> pd.DataFrame | None:
    inputs = results.tables.get("diagnostic_inputs")
    if inputs is None:
        return None
    dates = results.tables["forecasts"].set_index("event_id")["event_date"].dt.date
    out = inputs.copy()
    out.insert(1, "date", out["event_id"].map(dates))
    return out.round(6)


def trades(results: Results) -> pd.DataFrame:
    table = results.tables["trades"].copy()
    table["exit_reason"] = table["exit_reason"].map(EXIT_REASONS).fillna(table["exit_reason"])
    for column in ("entry_date", "exit_date"):
        table[column] = pd.to_datetime(table[column]).dt.date
    return table.rename(
        columns={"leg_a": "stock_a", "leg_b": "stock_b", "long_leg": "long_stock"}
    ).round(6)


def book_values(results: Results) -> pd.DataFrame:
    daily = results.tables["books_daily"].copy()
    daily["session_date"] = daily["session_date"].dt.date
    return daily.rename(columns={key: f"value_{key}" for key in BOOKS}).round(6)


def forecaster_metrics(results: Results) -> pd.DataFrame:
    metrics = results.metrics()
    return metrics.assign(model=metrics["model"].map(MODELS).fillna(metrics["label"]))[
        ["model", "period", "roc_auc", "pr_auc", "log_loss", "brier", "base_rate", "n"]
    ].round(6)


def book_metrics(results: Results) -> pd.DataFrame:
    stats = results.book_stats()
    stats["period"] = stats["period"].map(period_label)
    return stats.drop(columns=["book"]).rename(columns={"label": "book"}).round(6)


def news_coverage(results: Results) -> pd.DataFrame:
    return results.tables["news"].rename(columns={"tickers": "tickers_with_news"})


DATASETS: list[tuple[str, str, str, Callable[[Results], pd.DataFrame | None]]] = [
    (
        "events.csv",
        "Events and forecasts",
        "Every scored divergence 2010–2025: pair, date, spread, whether it reverted, each "
        "forecaster's walk-forward probability and the adopted book's trade",
        events,
    ),
    (
        "event_features.csv",
        "Model inputs per event",
        "The quantitative, SEC and tone inputs of every event, as the forecasters saw them",
        event_features,
    ),
    (
        "trades.csv",
        "Adopted book trades",
        "Every trade: entry and exit date, exit reason, size and gross return",
        trades,
    ),
    (
        "book_values.csv",
        "Daily book values",
        "Daily value (start 1.0, with cash interest) of the adopted book and its variants",
        book_values,
    ),
    (
        "forecaster_metrics.csv",
        "Forecaster metrics",
        "ROC AUC, PR AUC, log loss and Brier by model and period",
        forecaster_metrics,
    ),
    (
        "book_metrics.csv",
        "Book metrics",
        "Sharpe, CAGR, drawdown, volatility, turnover and costs by book and period",
        book_metrics,
    ),
    (
        "news_coverage.csv",
        "News coverage",
        "Company-specific headlines per month and source",
        news_coverage,
    ),
]
COLUMNS = {
    "event_id": "Identifier of the divergence event",
    "date": "Event date: the session close at which |z| first crossed 2",
    "period": "Selection 2010–2017, holdout 2018–2023 or final test 2024–2025",
    "pair": "Business-peer pair (stock A__stock B)",
    "stock_a": "First stock of the pair",
    "stock_b": "Second stock of the pair",
    "business_group": "Business group of the pair",
    "spread_z": "Signed z-score of the pair's spread at the event",
    "reverted": "1 if |z| returned to ≤ 0.5 within 20 sessions before reaching 3; empty if "
    "the outcome could not be labelled",
    "p_revert_model_a": "Model A walk-forward probability of reverting",
    "p_revert_r0": "Original Model B (R0) walk-forward probability",
    "p_revert_bag5": "B+rule+ou, bagged (pre-registered) walk-forward probability",
    "p_revert_track": "B+rule+ou+track, bagged walk-forward probability",
    "p_revert_full": "Full model (bagged + agent desk) probability; only where the agents "
    "read the event",
    "r0_top20": "In R0's top 20 % of its year (the selection before the book's filters)",
    "traded_by_adopted_book": "The adopted book entered a trade on this event",
    "trade_exit": "How the trade ended",
    "trade_gross_return": "Trade return before costs, close to close, as a share of gross notional",
    "entry_date": "Entry at the signal close",
    "exit_date": "Exit at the close",
    "long_stock": "The stock held long",
    "sessions": "Trading sessions held",
    "exit_reason": "Take profit, time stop, 8-K news exit or monitor exit",
    "size_nav": "Position size as a share of the book's value",
    "gross_return": "Trade return before costs",
    "session_date": "Trading day",
    "value_adopted": "Adopted book (R0 selection, monitor exit)",
    "value_no_monitor": "Same book without the monitor exit",
    "value_bag5": "Same book with the best forecaster's selection",
    "value_full": "Same book with the full model's selection",
    "model": "Forecaster",
    "roc_auc": "Area under the ROC curve (higher is better)",
    "pr_auc": "Area under the precision-recall curve (higher is better)",
    "log_loss": "Log loss of the calibrated probability (lower is better)",
    "brier": "Brier score (lower is better)",
    "base_rate": "Share of events that reverted",
    "n": "Labelled events",
    "book": "Book",
    "sharpe": "Annualised Sharpe ratio in excess of cash",
    "cagr": "Compound annual return in excess of cash",
    "cagr_with_cash": "Compound annual return including cash interest",
    "max_drawdown": "Largest fall from a previous peak",
    "volatility": "Annualised volatility",
    "turnover": "Traded value per year as a multiple of the book",
    "cost": "Trading costs per year as a share of the book",
    "source": "News source",
    "month": "Calendar month",
    "headlines": "Company-specific headlines in the month",
    "tickers_with_news": "Stocks with at least one headline in the month",
}
README = """Structural-break detector: data downloads

The project's own data: every scored divergence with each forecaster's walk-forward
probability, the model inputs, the adopted book's trades, the daily book values and all
metrics, for 2010-2025. The 2024-2025 final test was run once on the frozen design.

Raw third-party data (daily prices from Yahoo Finance, SEC EDGAR filings, FNSPID and TickerTick
headlines) is not included; it is available from its sources.

Files are UTF-8 CSV (with a byte-order mark for spreadsheet programs).
data_dictionary.csv explains every column.
Probabilities are walk-forward: each year is scored by a model fitted on earlier years only.
"""


def dictionary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, frame in frames.items():
        for column in frame.columns:
            description = COLUMNS.get(column)
            if description is None:
                description = f"Model input: {feature_label(column)}"
            rows.append({"file": name, "column": column, "description": description})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner="Packaging the ZIP…", max_entries=2)
def build(_results: Results, digest: str) -> dict[str, bytes]:
    """CSV bytes per file plus the data dictionary, README and one ZIP of everything."""
    del digest  # cache key: the results manifest
    frames = {}
    for name, _, _, make in DATASETS:
        frame = make(_results)
        if frame is not None:
            frames[name] = frame
    frames["data_dictionary.csv"] = dictionary(frames)
    files = {name: _csv(frame) for name, frame in frames.items()}
    files["README.txt"] = README.encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    files["structural_break_data.zip"] = buffer.getvalue()
    return files


def sources_table() -> str:
    """Markdown table of the sources (wraps long text, unlike a data frame), with links."""

    def linked(text: str) -> str:
        for name, url in LINKS.items():
            text = text.replace(name, f"[{name}]({url})", 1)
        return text

    rows = ["| Data | Source | What it is used for | Years |", "|---|---|---|---|"]
    for data, source, use, years in SOURCES:
        rows.append(f"| {data} | {linked(source)} | {use} | {years} |")
    return "\n".join(rows)


def _csv(frame: pd.DataFrame) -> bytes:
    # UTF-8 with a byte-order mark, so spreadsheet programs read the dashes and symbols.
    return frame.to_csv(index=False).encode("utf-8-sig")


@st.cache_data(show_spinner="Preparing the file…", max_entries=16)
def single(_results: Results, digest: str, name: str) -> bytes:
    """One dataset as CSV, built the first time someone asks for it."""
    del digest  # cache key: the results manifest
    make = next(make for file, _, _, make in DATASETS if file == name)
    frame = make(_results)
    if frame is None:
        raise ValueError(f"{name} is not in this deployment")
    return _csv(frame)


def _zip(results: Results, digest: str) -> bytes:
    return build(results, digest)["structural_break_data.zip"]


def render(results: Results | None) -> None:
    st.subheader("Data")
    st.markdown("**Where the data comes from**")
    st.markdown(sources_table())
    st.caption("Raw third-party data is not redistributed here; it is available from its sources.")
    if results is None:
        st.info("The project's results are not in this deployment.")
        return
    digest = str(results.manifest.get("files", {}).get("forecasts.parquet"))
    st.markdown("**Download the project's data**")
    # The files are built when a button is clicked, not when the page opens.
    st.download_button(
        "Download all (ZIP with README and data dictionary)",
        partial(_zip, results, digest),
        file_name="structural_break_data.zip",
        mime="application/zip",
        icon=":material/folder_zip:",
        type="primary",
        key="download_all",
        on_click="ignore",
    )
    for name, title, description, _ in DATASETS:
        if name == "event_features.csv" and "diagnostic_inputs" not in results.tables:
            continue
        left, right = st.columns([3, 1])
        left.markdown(f"**{title}** · {description}")
        right.download_button(
            name,
            partial(single, results, digest, name),
            file_name=name,
            mime="text/csv",
            icon=":material/download:",
            key=f"download_{name}",
            width="stretch",
            on_click="ignore",
        )
    st.caption(
        "Each pair's daily spread series can be downloaded on its Pair detail page. "
        "data_dictionary.csv (in the ZIP) explains every column. The ZIP takes a few seconds "
        "to prepare the first time."
    )


def footnote(results: Results | None) -> str | None:
    if results is None:
        return None
    manifest: dict[str, Any] = results.manifest
    generated = str(manifest.get("generated_at", ""))[:10]
    sha = str(manifest.get("freeze_manifest_sha256") or "")[:12]
    return (
        f"Reproducibility: results exported {generated} from code version "
        f"{manifest.get('commit')}; freeze manifest {sha}…"
    )
