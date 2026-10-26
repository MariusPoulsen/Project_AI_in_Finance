"""Builders for the book inputs that earlier lived in one-off commands and stage scripts.

Each command writes the same file the adopted book reads (Decision 110d), from the frozen
research workspace and the upstream pipeline outputs. ``verify`` rebuilds the fast inputs
into a scratch folder and compares them with the stored files. The full order, including the
module CLIs that build the upstream inputs, is printed by ``plan``. Nothing here reads
2024-2025 data: every builder stops at the workspace's development end or at 2023-12-31.

    python -m structural_break.pipeline.build_inputs plan
    python -m structural_break.pipeline.build_inputs features --sec-metadata <folder>
    python -m structural_break.pipeline.build_inputs verify --sec-metadata <folder>
"""

from __future__ import annotations

import argparse
import pickle
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE = Path("data/team")
OUTPUTS = Path("outputs")
BOOK = OUTPUTS / "p6_quant"
SIMULATION = OUTPUTS / "p6_improvement/walkforward/simulation_frozen_exit.parquet"
LONG_HORIZON = 41  # monitored closes: the 40-session time-stop cap plus one spare close

# Upstream inputs built by module CLIs, in order (python -m <module> ...).
PLAN = (
    (
        "walk-forward frame",
        "structural_break.pipeline.walkforward",
        "p6_improvement/walkforward/simulation_frozen_exit.parquet",
    ),
    (
        "SEC filing timing features",
        "structural_break.pipeline.sec_timing",
        "p6_sec_features/timing_features.parquet",
    ),
    (
        "recent 8-K news and tone features",
        "structural_break.pipeline.news_features",
        "news_v1/{windows,news_features,tone_features}.parquet",
    ),
    (
        "8-K headline tone",
        "structural_break.pipeline.headline_tone",
        "headline_v1/headline_tone.parquet",
    ),
    (
        "E3 news-exit results",
        "structural_break.pipeline.news_exit",
        "p6_sec_explore2/exits_*.parquet",
    ),
    (
        "forecast features",
        "structural_break.pipeline.build_inputs features",
        "p6_quant/features.parquet",
    ),
    ("OU features", "structural_break.pipeline.build_inputs ou", "p6_quant/ou_features.parquet"),
    (
        "R1 fresh-news events",
        "structural_break.pipeline.build_inputs r1",
        "p6_quant/r1_events.parquet",
    ),
    (
        "R0 selection scores",
        "structural_break.forecast.model_b_scores",
        "p6_boosting2/scores.parquet",
    ),
    (
        "bagged forecaster scores",
        "structural_break.forecast.harness run"
        " --specs B+rule+ou B+rule+ou+track --schemes recent:bag5",
        "p6_quant/scores__*__recent-bag5.parquet",
    ),
    ("trade requests and exit grid", "structural_break.book.trades build", "p6_quant/requests.pkl"),
    (
        "per-trade costs",
        "structural_break.pipeline.build_inputs costs",
        "p6_quant/cost_model_nets.parquet",
    ),
    (
        "residual-sleeve targets",
        "structural_break.pipeline.build_inputs residual-targets",
        "p6_quant/stage_q/targets_pca_continuous.npy",
    ),
    (
        "desk entry and monitor cases",
        "structural_break.agents.desk_runner build-entry / build-monitor",
        "p6_desk/*_inventory.parquet",
    ),
    (
        "41-session trade paths",
        "structural_break.pipeline.build_inputs long-paths",
        "p6_quant/requests_long.pkl",
    ),
)


def features(sec_metadata: Path, out: Path) -> Path:
    """Peer, state, track-record, earnings and momentum blocks (Decision 75)."""
    from structural_break.forecast import model_b
    from structural_break.pipeline import features as qf

    frame, _ = model_b.load_data(WORKSPACE, SIMULATION)
    filings = pd.read_parquet(
        sec_metadata / "filings.parquet",
        columns=["security_id", "form", "items", "acceptance_datetime_utc"],
    )
    pairs = pd.read_parquet(WORKSPACE / "universe/source_v1/pair_universe.parquet")
    prices = pd.read_parquet(
        WORKSPACE / "market/source_v1/prices.parquet",
        columns=["ticker", "trading_date", "adj_close"],
    )
    path = out / "features.parquet"
    qf.build_all(frame, WORKSPACE, filings, pairs, prices).to_parquet(path, index=False)
    return path


def ou(out: Path) -> Path:
    """Ornstein-Uhlenbeck block (Decision 85)."""
    from structural_break.forecast import model_b
    from structural_break.pipeline import ou_features

    frame, _ = model_b.load_data(WORKSPACE, SIMULATION)
    path = out / "ou_features.parquet"
    ou_features.build(frame, WORKSPACE).to_parquet(path, index=False)
    return path


def r1(out: Path) -> Path:
    """Events skipped by the R1 fresh-news filter (Decision 82a)."""
    from structural_break.pipeline import news_filters as ex

    inputs = [
        OUTPUTS / "p6_sec_features/timing_features.parquet",
        OUTPUTS / "news_v1/news_features.parquet",
        OUTPUTS / "news_v1/tone_features.parquet",
    ]
    frame, _ = ex.load(WORKSPACE, inputs, SIMULATION)
    flagged = ex.FILTERS["R1_fresh_news_filter"][1](frame).fillna(False).astype(bool)
    path = out / "r1_events.parquet"
    frame.loc[flagged, ["event_id"]].to_parquet(path, index=False)
    return path


def costs(out: Path) -> Path:
    """Per-stock trading costs at $1m, $10m and $100m under the frozen exit (Decision 95)."""
    from structural_break.backtest.production_policy import load_headline
    from structural_break.book import costs as qc
    from structural_break.book import trades as qt

    headline = load_headline(Path("configs"))
    with open(BOOK / "requests.pkl", "rb") as handle:
        cache = pickle.load(handle)
    prices = pd.read_parquet(
        WORKSPACE / "market/source_v1/prices.parquet",
        columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"],
    )
    table = qc.lookup(qc.stock_inputs(prices))
    rows = []
    for event_id, (request, frozen, moments) in cache.items():
        row: dict[str, object] = {"event_id": event_id}
        status, net, _, _ = qt.exit_loop(request, frozen, headline, 1.0, 5.0, 20, moments)
        row["flat_net"] = net if status == "COMPLETE" else np.nan
        for label, capital in (("1m", 1e6), ("10m", 1e7), ("100m", 1e8)):
            rate = qc.trade_rate_bps(table, request, frozen, capital)
            row[f"rate_{label}"] = rate
            if rate is not None and status == "COMPLETE":
                priced, net2, _, _ = qt.exit_loop(
                    request, frozen, headline, 1.0, 5.0, 20, moments, cost_bps=rate
                )
                row[f"net_{label}"] = net2 if priced == "COMPLETE" else np.nan
            else:
                row[f"net_{label}"] = np.nan
        rows.append(row)
    path = out / "cost_model_nets.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def residual_targets(out: Path) -> Path:
    """Continuous PCA residual-reversal target weights (Decisions 101, 104)."""
    from structural_break.book import residual_sleeve as pr
    from structural_break.pipeline.sources import _sources

    sectors = _sources(WORKSPACE).security_sectors()
    prices = pd.read_parquet(
        WORKSPACE / "market/source_v1/prices.parquet",
        columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"],
    )
    panels = pr.load_panels(prices, sectors)
    start = int(np.searchsorted(panels.dates, pd.Timestamp("2009-06-01")))
    s, kappa, beta = pr.signals(panels, "pca", start)
    path = out / "stage_q" / "targets_pca_continuous.npy"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, pr.targets(panels, s, kappa, beta, "continuous"))
    return path


def long_paths(out: Path) -> Path:
    """41-session paths for the half-life time stop (Decision 111), checked against the cache."""
    from structural_break.backtest import historical
    from structural_break.backtest.historical import PriceBook
    from structural_break.book import portfolio as qp
    from structural_break.pipeline.sources import _sources, _spec

    sources = _sources(WORKSPACE)
    spec = _spec(sources, date(2006, 1, 1), date(2023, 12, 31))
    end = sources.binding.development_end
    book = PriceBook.build(sources.prices(date(2005, 11, 1), end), spec)
    cache = qp.load_cache(BOOK / "requests.pkl")
    wanted = set(pd.read_parquet(OUTPUTS / "p6_desk/entry_inventory.parquet").event_id)
    long_cache, mismatches = {}, 0
    for event_id in sorted(wanted):
        request, frozen, moments = cache[event_id]
        sessions = historical._sessions(request.sessions[0].session_date, LONG_HORIZON, end)
        bars = book.pair_bars(request.leg_a, request.leg_b, sessions)
        n = len(request.sessions)
        if tuple(sessions[:n]) != tuple(request.sessions) or tuple(bars[:n]) != tuple(
            request.prices
        ):
            mismatches += 1
            continue
        long_cache[event_id] = (
            request.model_copy(update={"sessions": sessions, "prices": bars}),
            frozen,
            moments,
        )
    if mismatches:
        raise SystemExit(f"{mismatches} rebuilt paths differ from the cached ones; not writing")
    path = out / "requests_long.pkl"
    with open(path, "wb") as handle:
        pickle.dump(long_cache, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return path


def _same_frame(new: Path, old: Path) -> str:
    a, b = pd.read_parquet(new), pd.read_parquet(old)
    missing = [c for c in a.columns if c not in b.columns]
    if missing:
        return f"columns not in the stored file: {missing}"
    b = b.loc[:, list(a.columns)]
    key = "event_id" if "event_id" in a.columns else None
    if key:
        a, b = a.sort_values(key).reset_index(drop=True), b.sort_values(key).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(a, b, check_dtype=False)
    except AssertionError as error:
        return str(error).splitlines()[0]
    return "identical"


def verify(sec_metadata: Path) -> dict[str, str]:
    """Rebuild the fast inputs in a scratch folder and compare them with the stored files."""
    report = {}
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch)
        report["features"] = _same_frame(features(sec_metadata, out), BOOK / "features.parquet")
        report["ou"] = _same_frame(ou(out), BOOK / "ou_features.parquet")
        report["r1"] = _same_frame(r1(out), BOOK / "r1_events.parquet")
        report["costs"] = _same_frame(costs(out), BOOK / "cost_model_nets.parquet")
        new = np.load(residual_targets(out))
        old = np.load(BOOK / "stage_q/targets_pca_continuous.npy")
        report["residual-targets"] = (
            "identical" if np.array_equal(new, old, equal_nan=True) else "DIFFERENT"
        )
    for name, verdict in report.items():
        print(f"{name:18s} {verdict}")
    return report


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "features",
            "ou",
            "r1",
            "costs",
            "residual-targets",
            "long-paths",
            "verify",
        ),
    )
    parser.add_argument(
        "--sec-metadata", type=Path, help="folder with the SEC filings.parquet (features, verify)"
    )
    parser.add_argument("--output", type=Path, default=BOOK)
    args = parser.parse_args(arguments)
    if args.command == "plan":
        for number, (name, module, output) in enumerate(PLAN, start=1):
            print(f"{number:2d}. {name:36s} python -m {module}\n    -> outputs/{output}")
        return
    if args.command in ("features", "verify") and args.sec_metadata is None:
        parser.error("--sec-metadata is required for features and verify")
    if args.command == "verify":
        verify(args.sec_metadata)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    build = {
        "features": lambda: features(args.sec_metadata, args.output),
        "ou": lambda: ou(args.output),
        "r1": lambda: r1(args.output),
        "costs": lambda: costs(args.output),
        "residual-targets": lambda: residual_targets(args.output),
        "long-paths": lambda: long_paths(args.output),
    }
    print(f"wrote {build[args.command]()}")


if __name__ == "__main__":
    main()
