"""Read-only results export for the research app (``demo/results/``): Goal 1 and Goal 2.

Run from a checkout whose ``outputs/`` holds the forecasters, the book inputs and the agent
desk: the development checkout gives 2010-2023, the final-test checkout 2010-2025.

    python scripts/export_results.py

Writes the headline forecasters' walk-forward probabilities per event, their ROC and
calibration curves and metrics by period, the daily value and statistics of the four books
(Decision 119), the adopted book's trade ledger, agent-desk and news statistics and, when it
exists, the final-test report. ``manifest.json`` lists every file with its SHA-256; the app
refuses files that do not match.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.metrics import roc_curve

from structural_break import periods
from structural_break.agents import desk_runner as desk
from structural_break.book import residual_sleeve as book
from structural_break.forecast import harness
from structural_break.pipeline.sources import _sources

WS = Path("data/team")
OUT = Path("demo/results")
FORECASTERS = {
    "r0": ("Original Model B (R0)", "scores__B__d45"),
    "bag5": ("B+rule+ou, bagged (pre-registered Goal 1 model)", "scores__B+rule+ou__recent-bag5"),
    "track": ("B+rule+ou+track, bagged (best observed)", "scores__B+rule+ou+track__recent-bag5"),
}
BOOKS = {
    "adopted": ("Adopted book (R0 selection, monitor exit)", "R0", True),
    "no_monitor": ("Same book without the monitor exit", "R0", False),
    "bag5": ("Best forecaster's selection (bagged B+rule+ou)", "B+rule+ou__recent-bag5", True),
    "full": ("Full model's selection (bagged + agent desk)", "FULL", True),
}
PERIODS = {
    "2010–2017": ((2010, 2017), "selection"),
    "2018–2023": ((2018, 2023), "holdout"),
    "2024–2025": ((2024, 2025), "final test"),
}


def _periods_with(years: pd.Series) -> dict[str, tuple[int, int]]:
    present = set(years.dropna().astype(int))
    return {k: y for k, (y, _) in PERIODS.items() if present & set(range(y[0], y[1] + 1))}


def forecasts() -> pd.DataFrame:
    args = harness.parser().parse_args(["summary"])
    frame, _, exits = harness.load(args)
    table: pd.DataFrame | None = None
    for key, (_, name) in FORECASTERS.items():
        scored = harness.attach(
            pd.read_parquet(Path("outputs/book") / f"{name}.parquet"), frame, exits
        )
        if table is None:
            table = scored[
                ["event_id", "event_date", "year", "labelled", "y_revert_success"]
            ].copy()
            table["r0_top20"] = scored["top20"].to_numpy()
        part = scored.set_index("event_id")
        table[f"p_{key}"] = table.event_id.map(part["probability"])
        table[f"raw_{key}"] = table.event_id.map(part["raw"])
    assert table is not None
    version = _sources(WS).binding.evaluation.version
    inputs = pd.read_parquet(
        WS / "artifacts/research" / version / "model_inputs.parquet",
        columns=["event_id", "pair_id", "z_signed"],
    ).drop_duplicates("event_id")
    pairs = pd.read_parquet(WS / "universe/source_v1/pair_universe.parquet")
    table = table.merge(inputs, on="event_id", how="left").merge(
        pairs[["pair_id", "leg_a", "leg_b", "business_group"]], on="pair_id", how="left"
    )
    full, _ = desk.full_model(WS)
    full = full.dropna(subset=["p_base", "p_agent"]).drop_duplicates("event_id")
    table = table.merge(
        full[["event_id", "p_base", "p_agent"]].rename(
            columns={"p_base": "p_full_base", "p_agent": "p_full"}
        ),
        on="event_id",
        how="left",
    )
    table["event_date"] = pd.to_datetime(table["event_date"])
    return table.rename(columns={"y_revert_success": "y"})


def _curve_rows(
    model: str, period: str, y: np.ndarray, raw: np.ndarray, p: np.ndarray
) -> list[dict[str, Any]]:
    rows = []
    fpr, tpr, _ = roc_curve(y, raw)
    pick = np.unique(np.linspace(0, len(fpr) - 1, min(len(fpr), 200)).astype(int))
    rows += [
        {"model": model, "period": period, "kind": "roc", "x": float(a), "y": float(b), "n": 0}
        for a, b in zip(fpr[pick], tpr[pick], strict=True)
    ]
    bins = pd.qcut(pd.Series(p).rank(method="first"), 10, labels=False)
    for _, group in pd.DataFrame({"p": p, "y": y, "bin": bins}).groupby("bin"):
        rows.append(
            {
                "model": model,
                "period": period,
                "kind": "calibration",
                "x": float(group.p.mean()),
                "y": float(group.y.mean()),
                "n": int(len(group)),
            }
        )
    return rows


def _metrics(y: np.ndarray, raw: np.ndarray, p: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    clipped = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "roc_auc": float(roc_auc_score(y, raw)),
        "pr_auc": float(average_precision_score(y, raw)),
        "log_loss": float(-np.mean(y * np.log(clipped) + (1 - y) * np.log(1 - clipped))),
        "brier": float(np.mean((p - y) ** 2)),
        "base_rate": float(y.mean()),
        "n": int(len(y)),
    }


def goal1(table: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    curves: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    labelled = table[table.labelled & table.y.notna()]
    for period, years in _periods_with(labelled.year).items():
        part = labelled[labelled.year.between(*years)]
        y = part.y.to_numpy(float)
        for key, (label, _) in FORECASTERS.items():
            raw, p = part[f"raw_{key}"].to_numpy(float), part[f"p_{key}"].to_numpy(float)
            curves += _curve_rows(key, period, y, raw, p)
            metrics.append({"model": key, "label": label, "period": period, **_metrics(y, raw, p)})
        region = part.dropna(subset=["p_full", "p_full_base"])
        if len(region) and region.y.nunique() == 2:
            y_r = region.y.to_numpy(float)
            for key, column, label in (
                ("full_base", "p_full_base", "Desk region: bagged B+rule+ou alone"),
                ("full", "p_full", "Desk region: full model (bagged + agent desk)"),
            ):
                p = region[column].to_numpy(float)
                curves += _curve_rows(key, period, y_r, p, p)
                metrics.append(
                    {"model": key, "label": label, "period": period, **_metrics(y_r, p, p)}
                )
    reference = pd.read_csv("outputs/book/goal1_table.csv")
    row = reference[reference.model.str.startswith("Model A")].iloc[0]
    for period, tag in (("2010–2017", "2010-17"), ("2018–2023", "2018-23")):
        metrics.append(
            {
                "model": "model_a",
                "label": "Model A (prices only)",
                "period": period,
                "roc_auc": float(row[f"AUC {tag}"]),
                "pr_auc": float(row[f"PR {tag}"]),
                "log_loss": float(row[f"LL {tag}"]),
                "brier": float(row[f"Brier {tag}"]),
                "base_rate": float("nan"),
                "n": 0,
            }
        )
    return pd.DataFrame(curves), metrics


def monitor_exits() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for record in pd.read_parquet(desk.OUTPUT / "monitor_inventory.parquet").to_dict("records"):
        result = desk.load_result(desk.OUTPUT, "monitor", record["file"])
        if result and result["scores"]:
            checks.append(
                {
                    **cast(dict[str, Any], record),
                    **{k: result["scores"][k] for k in ("adverse", "persistence")},
                }
            )
    hit = pd.DataFrame(checks).query("adverse >= 5 and persistence >= 5")
    return dict(hit.sort_values("session").groupby("event_id").session.first().dt.date.to_dict())


def books(exits: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    sectors = _sources(WS).security_sectors()
    prices = pd.read_parquet(
        WS / "market/source_v1/prices.parquet",
        columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"],
    )
    end = pd.Timestamp(prices.trading_date.max())
    panels = book.load_panels(prices, sectors)
    rf = book.tbill(Path("data/external/irx_13w_tbill.csv"))
    w = np.load("outputs/book/residual_targets_pca.npy") * 0.25
    _, chosen_full = desk.full_model(WS)
    daily: pd.DataFrame | None = None
    stats: dict[str, Any] = {}
    for key, (label, selector, monitor) in BOOKS.items():
        legs = desk.desk_book(
            WS,
            {},
            set(),
            exits if monitor else {},
            selector,
            chosen_full if selector == "FULL" else None,
        )
        b = book.run_book(
            panels,
            w,
            legs,
            pd.Timestamp("2010-01-01"),
            end,
            capital=1e7,
            rf=rf,
            speed=0.10,
            vol_target=0.04,
            vol_window=60,
            timing="close",
            max_gross=2.0,
        )
        if daily is None:
            daily = pd.DataFrame({"session_date": pd.to_datetime(b.session_date)})
        daily[key] = (1 + b.daily_return.to_numpy()).cumprod()
        stats[key] = {"label": label, "periods": {}}
        years = pd.Series(pd.to_datetime(b.session_date).dt.year)
        spans = {**_periods_with(years), "2010–2023": (2010, 2023)}
        if years.max() >= 2025:
            spans["2010–2025"] = (2010, 2025)
        for period, (y0, y1) in spans.items():
            s, c = book.stats(b, y0, y1), book.stats(b, y0, y1, cash=True)
            stats[key]["periods"][period] = {
                "sharpe": s["sharpe"],
                "cagr": s["cagr"],
                "cagr_with_cash": c["cagr"],
                "max_drawdown": s["maxdd"],
                "volatility": s["vol"],
                "turnover": s["turnover"],
                "cost": s["cost"],
            }
        print(key, {p: round(v["sharpe"], 3) for p, v in stats[key]["periods"].items()}, flush=True)
    assert daily is not None
    return daily, stats


def _price(frame: pd.DataFrame, day: pd.Timestamp, ticker: str) -> float:
    return float(cast(float, frame.at[day, ticker]))


def ledger(exits: dict[str, Any]) -> pd.DataFrame:
    """The adopted book's trades: entry and exit at the close, exit reason, gross return."""
    allocations, results, cache = desk.design_trades(WS, "R0")
    prices = pd.read_parquet(
        WS / "market/source_v1/prices.parquet",
        columns=["ticker", "trading_date", "close", "adj_close"],
    )
    prices["trading_date"] = pd.to_datetime(prices.trading_date)
    close = prices.pivot_table(index="trading_date", columns="ticker", values="close")
    adj = prices.pivot_table(index="trading_date", columns="ticker", values="adj_close")
    rows = []
    for event_id, fraction in allocations.items():
        result = results[event_id]
        if result.exit is None or result.position is None:
            continue
        request = cache[event_id][0]
        days = [x.session_date for x in request.sessions]
        trigger = days[days.index(result.exit.session_date) - 1]
        monitor = event_id in exits and exits[event_id] < trigger
        exit_day = exits[event_id] if monitor else trigger
        a, b = str(request.leg_a), str(request.leg_b)
        t0, t1 = pd.Timestamp(days[0]), pd.Timestamp(exit_day)
        wa = float(result.position.units_a) * _price(close, t0, a)
        wb = float(result.position.units_b) * _price(close, t0, b)
        ra = _price(adj, t1, a) / _price(adj, t0, a) - 1
        rb = _price(adj, t1, b) / _price(adj, t0, b) - 1
        cause = result.trigger.reason if result.trigger is not None else result.reason
        reason = "MONITOR" if monitor else str(getattr(cause, "value", cause))
        rows.append(
            {
                "event_id": event_id,
                "pair_id": result.pair_id,
                "leg_a": a,
                "leg_b": b,
                "long_leg": a if result.position.units_a > 0 else b,
                "entry_date": t0,
                "exit_date": t1,
                "sessions": int(sum(t0 < pd.Timestamp(d) <= t1 for d in days)),
                "exit_reason": reason,
                "size_nav": float(fraction),
                "gross_return": float((wa * ra + wb * rb) / (abs(wa) + abs(wb))),
            }
        )
    return pd.DataFrame(rows).sort_values("entry_date").reset_index(drop=True)


def news() -> list[dict[str, Any]]:
    rows = []
    for path, source in (
        (Path("data/external/fnspid/headlines.parquet"), "FNSPID"),
        (Path("data/external/news_final/headlines.parquet"), "TickerTick"),
    ):
        if not path.exists():
            continue
        h = pd.read_parquet(path, columns=["ticker", "date", "specific"])
        h = h[h.specific & h.date.dt.year.between(2010, periods.data_end().year)]
        if source == "FNSPID":
            h = h[h.date <= pd.Timestamp(periods.DEVELOPMENT_END)]
        for month, group in h.groupby(h.date.dt.to_period("M")):
            rows.append(
                {
                    "source": source,
                    "month": str(month),
                    "headlines": int(len(group)),
                    "tickers": int(group.ticker.nunique()),
                }
            )
    return rows


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    table = forecasts()
    curves, metrics = goal1(table)
    exits = monitor_exits()
    trades = ledger(exits)
    table["traded"] = table.event_id.isin(set(trades.event_id))
    daily, book_stats = books(exits)
    table.to_parquet(OUT / "forecasts.parquet", index=False)
    curves.to_parquet(OUT / "curves.parquet", index=False)
    daily.to_parquet(OUT / "books_daily.parquet", index=False)
    trades.to_parquet(OUT / "trades.parquet", index=False)
    pd.DataFrame(news()).to_parquet(OUT / "news.parquet", index=False)
    review = pd.read_csv("docs/agent_review/review_answers.csv", dtype=str, keep_default_na=False)
    answers = review["answer (Y/P/N)"].str.upper()
    summary = {
        "goal1": metrics,
        "books": book_stats,
        "trades": {
            "count": int(len(trades)),
            "by_reason": trades.exit_reason.value_counts().to_dict(),
        },
        "review": {
            "cases": int(review.review_id.nunique()),
            "claims": int(review.item.str.startswith("claim").sum()),
            "confirmed": int((answers == "Y").sum()),
            "partly": int((answers == "P").sum()),
            "rejected": int((answers == "N").sum()),
            "answered": int((answers != "").sum()),
            "rows": int(len(review)),
        },
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=float), encoding="utf-8"
    )
    report = Path("outputs/final_test/final_test_2024_2025.json")
    final = OUT / "final_test.json"
    if report.exists():
        final.write_bytes(report.read_bytes())
    elif final.exists():
        final.unlink()
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    files = sorted(p for p in OUT.iterdir() if p.name != "manifest.json")
    manifest = {
        "schema_version": "app-results-v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "event_years": [int(table.year.min()), int(table.year.max())],
        "final_test_included": bool(report.exists()),
        "unlock_record": periods.unlock_record(),
        "freeze_manifest_sha256": periods.manifest_sha256(),
        "files": {p.name: _sha(p) for p in files},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({sum(p.stat().st_size for p in OUT.iterdir()) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
