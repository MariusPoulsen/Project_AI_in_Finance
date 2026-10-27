"""Second explore-then-confirm round: news exits, graded sizing, sharper entry news (DECISIONS 59).

Three families, each explored on 2006-2015 with one variant chosen per family
by bootstrap t-statistic, then confirmed once on 2016-2021 with a Holm
correction across the three families:

* E (exits): close an open trade at the next open when qualifying news arrives
  during it (E1-E4), or after 10 sessions (E5, Engelberg, Gao and
  Jagannathan). Entry, band, stop, costs and borrow are frozen; a research copy
  of the exit loop must reproduce the frozen simulator exactly without news.
* Z (sizing): scale each position by a weight in [0, 1] from news instead of
  skipping it (Z1 recent-news FinBERT tone, Z3 Gemma news type, Z4 headline
  tone).
* H (sharper entry evidence): skip using the FinBERT tone of each 8-K's
  press-release headline (one- and three-session windows, tone surprise
  against the company's own recent headlines) or abnormal 8-K volume.

All contrasts are paired per-candidate net-return differences under the frozen
Decision 36 policy on Baseline 0 and Baseline 1, with the calendar-month block
bootstrap of ``news_filters``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break import periods
from structural_break.backtest.historical import (
    HistoricalSources,
    PriceBook,
    build_historical_events,
)
from structural_break.backtest.production_policy import load_headline
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.book.long_exit import simulate_long
from structural_break.intelligence.timing import session_closes
from structural_break.pipeline import news_filters as ex
from structural_break.pipeline.sources import _chunks, _sources, _spec
from structural_break.storage.files import write_bytes

PLAN_VERSION = "p6-sec-explore2-v1"
EXPLORE, CONFIRM = (2006, 2015), (2016, 2021)
REPLICATE = (2022, 2023)  # DECISIONS 61: one test of the confirmed exit rule
FAMILIES = ("exit", "sizing", "entry")
EXITS = (
    "E1_mover_8k",
    "E2_mover_earnings",
    "E3_adverse_tone_either_leg",
    "E4_mover_negative_headline",
    "E5_timeout_10",
)
SIZING = ("Z1_recent_tone_weight", "Z3_news_type_weight", "Z4_headline_tone_weight")
ENTRY = (
    "H1_mover_neg_headline_1s",
    "H2_mover_net_headline_1s",
    "H3_mover_tone_surprise_3s",
    "H4_abnormal_8k_volume_5s",
    "H5_mover_neg_headline_3s",
)
POPULATIONS = ("B0", "B1")
NEWS_HORIZON = timedelta(days=45)
EMPTY = pd.DataFrame(
    {
        "accepted": pd.Series(dtype="datetime64[ns, UTC]"),
        "earnings": pd.Series(dtype=bool),
        "negative": pd.Series(dtype=float),
        "net": pd.Series(dtype=float),
    }
)


# --------------------------------------------------------------------------- #
# Headline index and entry evidence
# --------------------------------------------------------------------------- #


def headline_index(table: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rows = table.loc[
        :, ["security_id", "acceptance_datetime_utc", "earnings", "negative", "net"]
    ].copy()
    rows["accepted"] = pd.to_datetime(rows["acceptance_datetime_utc"], utc=True)
    return {
        str(key): group.sort_values("accepted").reset_index(drop=True)
        for key, group in rows.groupby("security_id")
    }


def _mover_security(frame: pd.DataFrame, pairs: pd.DataFrame) -> pd.Series:
    legs = frame.loc[:, ["pair_id"]].merge(
        pairs.loc[:, ["pair_id", "leg_a_security_id", "leg_b_security_id"]],
        on="pair_id",
        how="left",
    )
    a, b = (
        frame["abnormal_return_A_1d"].astype(float).to_numpy(),
        frame["abnormal_return_B_1d"].astype(float).to_numpy(),
    )
    mover = np.where(
        np.abs(a) >= np.abs(b),
        legs["leg_a_security_id"].to_numpy(),
        legs["leg_b_security_id"].to_numpy(),
    )
    return pd.Series(mover, index=frame.index).where(~(np.isnan(a) | np.isnan(b)))


def entry_evidence(
    frame: pd.DataFrame, pairs: pd.DataFrame, index: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """Headline-based evidence for the moving company before each signal close."""
    cutoffs = pd.DatetimeIndex(pd.to_datetime(frame["event_timestamp"], utc=True))
    closes = session_closes(date(2005, 10, 1), periods.data_end() + timedelta(days=31))
    position = closes.searchsorted(cutoffs, side="right") - 1
    starts = {k: closes[position - k] for k in (1, 3, 5)}
    movers = _mover_security(frame, pairs)
    empty = pd.DataFrame(columns=["accepted", "earnings", "negative", "net"])
    rows = []
    for i, security in enumerate(movers.to_numpy()):
        values: dict[str, float] = {}
        filings = index.get(security, empty) if isinstance(security, str) else empty
        before = filings.loc[filings["accepted"].le(cutoffs[i])] if len(filings) else filings
        for k in (1, 3, 5):
            window = before.loc[before["accepted"].gt(starts[k][i])] if len(before) else before
            if k == 5:
                values["h_count_5s"] = float(len(window))
                continue
            values[f"h_neg_{k}s"] = (
                float(window["negative"].max()) if window["negative"].notna().any() else np.nan
            )
            values[f"h_net_{k}s"] = (
                float(window["net"].min()) if window["net"].notna().any() else np.nan
            )
            if k == 3:
                history = before.loc[
                    before["accepted"].le(starts[3][i])
                    & before["accepted"].gt(cutoffs[i] - pd.Timedelta(days=365))
                ]
                known = history["net"].dropna()
                if len(known) >= 3 and window["net"].notna().any():
                    values["h_surprise_3s"] = float(window["net"].min() - known.mean())
                else:
                    values["h_surprise_3s"] = np.nan
        rows.append(values)
    return pd.DataFrame(rows, index=frame.index)


SKIPS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "H1_mover_neg_headline_1s": lambda f: f["h_neg_1s"].ge(0.2),
    "H2_mover_net_headline_1s": lambda f: f["h_net_1s"].lt(-0.1),
    "H3_mover_tone_surprise_3s": lambda f: f["h_surprise_3s"].lt(-0.2),
    "H4_abnormal_8k_volume_5s": lambda f: f["h_count_5s"].ge(2),
    "H5_mover_neg_headline_3s": lambda f: f["h_neg_3s"].ge(0.2),
}
WEIGHTS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "Z1_recent_tone_weight": lambda f: (
        (1 - 2 * f["mover_tone_negative"].astype(float)).clip(0, 1).fillna(1.0)
    ),
    "Z3_news_type_weight": lambda f: pd.Series(
        np.where(
            ex._is(f["mover_news_earnings"]),
            0.0,
            np.where(
                ex._is(f["mover_news_corporate"]) & ex._is(f["mover_news_material"]), 0.5, 1.0
            ),
        ),
        index=f.index,
    ),
    "Z4_headline_tone_weight": lambda f: (
        (1 - 2 * f["h_neg_3s"].astype(float)).clip(0, 1).fillna(1.0)
    ),
}


def _rows(frame: pd.DataFrame, population: str, span: tuple[int, int]) -> pd.DataFrame:
    year = pd.to_datetime(frame["event_date"]).dt.year
    keep = frame["frozen|status"].eq("COMPLETE") & year.between(*span)
    if population == "B1":
        keep &= frame["baseline1_eligible"].eq(True)
    return frame.loc[keep]


def _stats(difference: pd.Series, dates: pd.Series, extra: dict[str, Any]) -> dict[str, Any]:
    stamps = pd.to_datetime(dates)
    return (
        ex.bootstrap(difference.to_numpy(dtype=float), stamps.dt.strftime("%Y-%m").to_numpy())
        | extra
        | {
            "per_year_bps": {
                str(y): float(g.mean() * 1e4)
                for y, g in difference.groupby(stamps.dt.year.to_numpy())
            },
        }
    )


def entry_contrast(
    frame: pd.DataFrame, name: str, population: str, span: tuple[int, int]
) -> dict[str, Any]:
    data = _rows(frame, population, span)
    net = data["frozen|net"].astype(float)
    skip = SKIPS[name](data).fillna(False).astype(bool)
    return _stats(
        -(net * skip),
        data["event_date"],
        {
            "skipped_share": float(skip.mean()),
            "skipped_mean_net_bps": float(net[skip].mean() * 1e4) if skip.any() else None,
            "kept_mean_net_bps": float(net[~skip].mean() * 1e4) if (~skip).any() else None,
        },
    )


def sizing_contrast(
    frame: pd.DataFrame, name: str, population: str, span: tuple[int, int]
) -> dict[str, Any]:
    data = _rows(frame, population, span)
    net = data["frozen|net"].astype(float)
    weight = WEIGHTS[name](data).astype(float)
    reduced = weight.lt(1)
    return _stats(
        (weight - 1) * net,
        data["event_date"],
        {
            "reduced_share": float(reduced.mean()),
            "mean_weight": float(weight.mean()),
            "reduced_mean_net_bps": float(net[reduced].mean() * 1e4) if reduced.any() else None,
        },
    )


# --------------------------------------------------------------------------- #
# News exits
# --------------------------------------------------------------------------- #


def _times(rows: pd.DataFrame, start: datetime, mask: pd.Series | None = None) -> list[datetime]:
    """Availability times of rows accepted after ``start`` (within the news horizon)."""
    if rows.empty:
        return []
    keep = rows["accepted"].gt(start) & rows["accepted"].le(start + NEWS_HORIZON)
    if mask is not None:
        keep &= mask.fillna(False).astype(bool)
    return [moment.to_pydatetime() for moment in rows.loc[keep, "accepted"]]


def simulate_exits(
    sources: HistoricalSources,
    configs: Path,
    frame: pd.DataFrame,
    pairs: pd.DataFrame,
    index: dict[str, pd.DataFrame],
    periodic: dict[str, pd.DataFrame],
    span: tuple[int, int],
    say: Callable[[str], None],
) -> pd.DataFrame:
    headline = load_headline(configs)
    lookup = frame.set_index("event_id")

    def rows_for(security: str) -> pd.DataFrame:
        return index.get(security, EMPTY)

    legs = pairs.set_index("pair_id")
    development_end = sources.binding.development_end
    rows = []
    for start, end in _chunks(date(span[0], 1, 1), date(span[1], 12, 31)):
        spec = _spec(sources, start, end)
        events, _, _ = build_historical_events(sources, spec)
        say(f"exits: simulating {len(events)} events {start}..{end}")
        for event in events:
            request = event.request
            event_id = event.state.event_id
            if event_id not in lookup.index:
                continue
            info = lookup.loc[event_id]
            pair = legs.loc[request.pair_id]
            a, b = float(info["abnormal_return_A_1d"]), float(info["abnormal_return_B_1d"])
            securities = {"a": str(pair["leg_a_security_id"]), "b": str(pair["leg_b_security_id"])}
            long_leg = "b" if request.signal_z > 0 else "a"
            short_leg = "a" if long_leg == "b" else "b"
            signal = request.signal_at
            long_rows, short_rows = rows_for(securities[long_leg]), rows_for(securities[short_leg])
            news: dict[str, list[datetime]] = {
                "E1_mover_8k": [],
                "E2_mover_earnings": [],
                "E3_adverse_tone_either_leg": _times(long_rows, signal, long_rows["net"].le(-0.1))
                + _times(short_rows, signal, short_rows["net"].ge(0.1)),
                "E4_mover_negative_headline": [],
            }
            if not (np.isnan(a) or np.isnan(b)):
                mover = securities["a" if abs(a) >= abs(b) else "b"]
                mover_rows = rows_for(mover)
                periodic_rows = periodic.get(mover, EMPTY)
                news["E1_mover_8k"] = _times(mover_rows, signal)
                news["E2_mover_earnings"] = _times(
                    mover_rows, signal, mover_rows["earnings"].astype(bool)
                ) + _times(periodic_rows, signal)
                news["E4_mover_negative_headline"] = _times(
                    mover_rows, signal, mover_rows["negative"].ge(0.2)
                )
            frozen = simulate_pair_trade(request, headline)
            row: dict[str, Any] = {
                "event_id": event_id,
                "event_date": request.sessions[0].session_date,
                "frozen_status": frozen.status,
                "frozen_net": frozen.net_return,
            }
            copy = simulate_long(request, request.sessions, request.prices, headline, 20)
            row["copy_status"], row["copy_net"] = copy["status"], copy["net"]
            for name, moments in news.items():
                result = simulate_long(
                    request, request.sessions, request.prices, headline, 20, moments
                )
                row[f"{name}|status"], row[f"{name}|net"] = result["status"], result["net"]
                row[f"{name}|reason"] = result["reason"]
            result = simulate_long(request, request.sessions, request.prices, headline, 10)
            row["E5_timeout_10|status"], row["E5_timeout_10|net"] = result["status"], result["net"]
            row["E5_timeout_10|reason"] = result["reason"]
            rows.append(row)
        del events
    _ = (PriceBook, development_end)
    out = pd.DataFrame(rows)
    mismatch = out["copy_status"].ne(out["frozen_status"]) | (
        out["frozen_net"].astype(float) - out["copy_net"].astype(float)
    ).abs().gt(1e-12)
    if mismatch.any():
        raise ValueError(
            f"Exit copy differs from the frozen simulator on {int(mismatch.sum())} events"
        )
    return out


def exit_contrast(
    exits: pd.DataFrame, frame: pd.DataFrame, name: str, population: str, span: tuple[int, int]
) -> dict[str, Any]:
    data = exits.merge(frame.loc[:, ["event_id", "baseline1_eligible"]], on="event_id", how="left")
    year = pd.to_datetime(data["event_date"]).dt.year
    keep = (
        year.between(*span)
        & data["frozen_status"].eq("COMPLETE")
        & data[f"{name}|status"].eq("COMPLETE")
    )
    if population == "B1":
        keep &= data["baseline1_eligible"].eq(True)
    data = data.loc[keep]
    difference = data[f"{name}|net"].astype(float) - data["frozen_net"].astype(float)
    reasons = data[f"{name}|reason"].value_counts().to_dict()
    return _stats(
        difference,
        data["event_date"],
        {
            "exit_reasons": reasons,
            "news_exit_share": float(data[f"{name}|reason"].eq("NEWS_EXIT").mean()),
        },
    )


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #


def _load(
    args: argparse.Namespace,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    frame, _ = ex.load(args.workspace_root, args.features, args.simulation)
    pairs = pd.read_parquet(args.workspace_root / "universe/source_v1/pair_universe.parquet")
    table = pd.read_parquet(args.headlines)
    index = headline_index(table)
    frame = pd.concat([frame, entry_evidence(frame, pairs, index)], axis=1)
    filings = pd.read_parquet(
        args.sec_metadata / "filings.parquet",
        columns=["security_id", "form", "acceptance_datetime_utc"],
    )
    periodic_rows = filings.loc[filings["form"].isin(["10-Q", "10-K", "10-Q/A", "10-K/A"])].copy()
    periodic_rows["accepted"] = pd.to_datetime(periodic_rows["acceptance_datetime_utc"], utc=True)
    periodic = {
        str(k): g.sort_values("accepted").reset_index(drop=True)
        for k, g in periodic_rows.groupby("security_id")
    }
    return frame, pairs, index, periodic


def _variants() -> list[tuple[str, str, str]]:
    rows = [("exit", pop, name) for name in EXITS for pop in POPULATIONS]
    rows += [("sizing", pop, name) for name in SIZING for pop in POPULATIONS]
    rows += [("entry", pop, name) for name in ENTRY for pop in POPULATIONS]
    return rows


def _evaluate(
    family: str,
    name: str,
    population: str,
    frame: pd.DataFrame,
    exits: pd.DataFrame | None,
    span: tuple[int, int],
) -> dict[str, Any]:
    if family == "exit":
        assert exits is not None
        return exit_contrast(exits, frame, name, population, span)
    if family == "sizing":
        return sizing_contrast(frame, name, population, span)
    return entry_contrast(frame, name, population, span)


CHOICES_MARKER = "### 59a. "
RESULTS_MARKER = "## 60. "


def record_choices(output: Path, decisions: Path) -> bool:
    """Append the fixed stage-1 choices to DECISIONS (once), before stage 2 runs."""
    text = decisions.read_text(encoding="utf-8")
    if CHOICES_MARKER in text:
        return False
    raw = (output / "choices.json").read_bytes()
    choices = json.loads(raw)
    explored = json.loads((output / "exploration.json").read_bytes())["variants"]
    positive = sum(1 for row in explored if (row.get("estimate") or 0) > 0)
    lines = [
        "",
        f"{CHOICES_MARKER}Round-2 exploration choices, fixed before confirmation",
        "",
        f"Recorded {date.today().isoformat()} automatically by `scripts/round2_watcher.ps1`",
        "immediately after stage 1 and before stage 2 ran; the commit containing this",
        "record precedes the confirmation run. Stage 1 explored "
        f"{len(explored)} variants on 2006–2015, {positive} with a positive estimate.",
        f"`outputs/news_exit/choices.json` SHA-256 `{hashlib.sha256(raw).hexdigest()}`.",
        "",
        "| Family | Variant | Population | Exploration estimate | t |",
        "|---|---|---|---|---|",
    ]
    for family in FAMILIES:
        choice = choices[family]
        lines.append(
            f"| {family} | {choice['name']} | {choice['population']} | "
            f"{choice['explore_estimate_bps']:+.2f} bps per candidate | {choice['explore_t']:.2f} |"
        )
    _append(decisions, text, lines)
    return True


def _append(decisions: Path, text: str, lines: list[str]) -> None:
    newline = chr(10)
    decisions.write_text(
        text.rstrip(newline) + newline + newline.join(lines) + newline, encoding="utf-8"
    )


def record_results(output: Path, decisions: Path) -> bool:
    """Append the factual stage-2 results to DECISIONS (once)."""
    text = decisions.read_text(encoding="utf-8")
    if RESULTS_MARKER in text:
        return False
    result = json.loads((output / "confirmation.json").read_bytes())
    rows = result["families"]
    passed = [family for family, row in rows.items() if row["passes"]]
    lines = [
        "",
        f"{RESULTS_MARKER}Round-2 confirmation result",
        "",
        f"Recorded {date.today().isoformat()} automatically by `scripts/round2_watcher.ps1`",
        "after the one-time Decision 59 stage 2 on 2016–2021",
        f"(`outputs/news_exit/confirmation.json`, choices `{result['choices_sha256'][:8]}…`).",
        "",
        "| Family | Variant | Population | 2016–2021 difference | 95 % interval "
        "| One-sided p | Holm p | Years positive | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for family in FAMILIES:
        row = rows[family]
        low, high = row["interval_95_bps"]
        lines.append(
            f"| {family} | {row['name']} | {row['population']} | {row['estimate_bps']:+.2f} bps | "
            f"[{low:+.2f}, {high:+.2f}] | {row['p_one_sided']:.3f} | {row['p_holm']:.3f} | "
            f"{row['years_positive']} of 6 | {'**Passes**' if row['passes'] else 'Fails'} |"
        )
    verdict = (
        f"**Passing:** {', '.join(passed)}. A passing family becomes a candidate for a "
        "separately versioned policy with a new freeze proposal and replaces nothing "
        "without the owner's final-test unlock decision."
        if passed
        else "**No family passes the pre-registered rule; none is adopted.**"
    )
    lines += ["", verdict, "The Decision 36–42 freeze and the 2024–2025 lock are unchanged."]
    _append(decisions, text, lines)
    return True


# The adopted 8-K news exit (Decisions 59-62) and its stored per-event results.
EXIT = "E3_adverse_tone_either_leg"


def load_exits(output: Path) -> pd.DataFrame:
    parts = [
        pd.read_parquet(output / f"exits_{name}.parquet")
        for name in ("explore", "confirm", "replicate")
    ]
    exits = pd.concat(parts, ignore_index=True)
    if exits["event_id"].duplicated().any():
        raise ValueError("Exit simulations overlap")
    return exits.loc[
        :, ["event_id", "frozen_status", "frozen_net", f"{EXIT}|status", f"{EXIT}|net"]
    ]


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("explore", "confirm", "replicate", "record-choices", "record-results")
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--configs-dir", type=Path, default=Path("configs"))
    parser.add_argument("--features", type=Path, action="append", required=True)
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--headlines", type=Path, required=True)
    parser.add_argument("--sec-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, default=Path("docs/DECISIONS.md"))
    args = parser.parse_args(arguments)
    if args.stage == "record-choices":
        print(json.dumps({"recorded": record_choices(args.output_dir, args.decisions)}))
        return
    if args.stage == "record-results":
        print(json.dumps({"recorded": record_results(args.output_dir, args.decisions)}))
        return

    def say(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    frame, pairs, index, periodic = _load(args)
    sources = _sources(args.workspace_root)
    out = args.output_dir
    span = EXPLORE if args.stage == "explore" else CONFIRM
    cache = out / f"exits_{args.stage}.parquet"
    if args.stage == "explore":
        if cache.exists():
            exits = pd.read_parquet(cache)
        else:
            exits = simulate_exits(
                sources, args.configs_dir, frame, pairs, index, periodic, span, say
            )
            out.mkdir(parents=True, exist_ok=True)
            exits.to_parquet(cache, index=False)
        results = []
        for family, population, name in _variants():
            say(f"explore {family} {population} {name}")
            stats = _evaluate(family, name, population, frame, exits, span)
            results.append({"family": family, "population": population, "name": name, **stats})
        choices = {}
        for family in FAMILIES:
            pool = [r for r in results if r["family"] == family and r.get("estimate") is not None]
            positive = [r for r in pool if r["estimate"] > 0]
            best = max(positive or pool, key=lambda r: r["t"])
            choices[family] = {
                "name": best["name"],
                "population": best["population"],
                "explore_t": best["t"],
                "explore_estimate_bps": best["estimate_bps"],
            }
        body = {
            "plan_version": PLAN_VERSION,
            "years": EXPLORE,
            "variants": results,
            "choices": choices,
            "run_date": date.today().isoformat(),
        }
        write_bytes(
            out / "exploration.json",
            (json.dumps(body, indent=2, sort_keys=True, default=str) + "\n").encode(),
        )
        raw = (json.dumps(choices, indent=2, sort_keys=True) + "\n").encode()
        write_bytes(out / "choices.json", raw)
        print(json.dumps({"choices": choices, "choices_sha256": hashlib.sha256(raw).hexdigest()}))
        return
    if args.stage == "replicate":
        exits = simulate_exits(
            sources, args.configs_dir, frame, pairs, index, periodic, REPLICATE, say
        )
        exits.to_parquet(out / "exits_replicate.parquet", index=False)
        name = "E3_adverse_tone_either_leg"
        stats = exit_contrast(exits, frame, name, "B0", REPLICATE)
        both = exits["frozen_status"].eq("COMPLETE") & exits[f"{name}|status"].eq("COMPLETE")
        stats |= {
            "frozen_mean_net_bps": float(exits.loc[both, "frozen_net"].mean() * 1e4),
            "rule_mean_net_bps": float(exits.loc[both, f"{name}|net"].mean() * 1e4),
            "passes": bool(stats["estimate"] > 0 and stats["p_one_sided"] < ex.ALPHA),
            "years": REPLICATE,
            "run_date": date.today().isoformat(),
        }
        text = json.dumps(stats, indent=2, sort_keys=True, default=str) + chr(10)
        write_bytes(out / "replication.json", text.encode())
        print(json.dumps({k: stats[k] for k in ("passes", "estimate_bps", "p_one_sided")}))
        return
    raw = (out / "choices.json").read_bytes()
    choices = json.loads(raw)
    confirmed_exits: pd.DataFrame | None = None
    if choices["exit"]:
        confirmed_exits = simulate_exits(
            sources, args.configs_dir, frame, pairs, index, periodic, span, say
        )
        confirmed_exits.to_parquet(cache, index=False)
    rows = {}
    for family, choice in choices.items():
        stats = _evaluate(
            family, choice["name"], choice["population"], frame, confirmed_exits, span
        )
        years = stats.get("per_year_bps", {})
        rows[family] = {**choice, **stats, "years_positive": sum(v > 0 for v in years.values())}
    order = sorted(rows, key=lambda f: rows[f]["p_one_sided"])
    running = 0.0
    for rank, family in enumerate(order):
        running = min(1.0, max(running, (len(order) - rank) * rows[family]["p_one_sided"]))
        rows[family]["p_holm"] = running
        rows[family]["passes"] = bool(
            running < ex.ALPHA
            and rows[family]["estimate"] > 0
            and rows[family]["years_positive"] >= ex.MIN_CONFIRM_YEARS
        )
    body = {
        "plan_version": PLAN_VERSION,
        "years": CONFIRM,
        "families": rows,
        "choices_sha256": hashlib.sha256(raw).hexdigest(),
        "run_date": date.today().isoformat(),
    }
    write_bytes(
        out / "confirmation.json",
        (json.dumps(body, indent=2, sort_keys=True, default=str) + "\n").encode(),
    )
    print(
        json.dumps(
            {
                f: {"passes": r["passes"], "estimate_bps": r["estimate_bps"], "p_holm": r["p_holm"]}
                for f, r in rows.items()
            }
        )
    )


if __name__ == "__main__":
    main()
