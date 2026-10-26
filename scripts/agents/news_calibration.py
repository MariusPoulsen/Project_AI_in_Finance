"""Decision 116 (amended 116a, 116b): GDELT and TickerTick against FNSPID, 2023-01-01 to 06-30.

    python scripts/agents/news_calibration.py sample       # draw the 20 tickers (no requests)
    python scripts/agents/news_calibration.py tickertick   # extract the window from the bulk file
    python scripts/agents/news_calibration.py gdelt        # weekly queries, capped weeks by day
    python scripts/agents/news_calibration.py report       # score both sources and apply the rule

Raw answers are cached, so every step can be rerun. Outputs: outputs/news_calibration/.
"""

import json
import math
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from structural_break.intelligence import news_sources as ns
from structural_break.intelligence.headlines import _matcher, available_session

START, END = date(2023, 1, 1), date(2023, 6, 30)
SEED, PER_QUARTILE = 116, 5
TONE, JACCARD = 0.2, 0.5
OUT = Path("outputs/news_calibration")
WS = Path("data/team")
BULK = Path("data/external/tickertick/TickerTick-stock-news-dataset.2023-11-23.json.bz2")
WEEKS_2024_2025, TICKERS_ALL = 104, 250


def master() -> pd.DataFrame:
    return pd.read_parquet(WS / "universe/source_v1/security_master.parquet")


def sessions() -> pd.DatetimeIndex:
    days = pd.read_parquet(WS / "market/source_v1/prices.parquet", columns=["trading_date"])
    days = pd.DatetimeIndex(pd.to_datetime(days.trading_date.unique())).sort_values()
    return days[(days >= pd.Timestamp(START)) & (days <= pd.Timestamp(2023, 7, 7))]


def in_window(frame: pd.DataFrame) -> pd.DataFrame:
    keep = (frame.date >= pd.Timestamp(START)) & (frame.date <= pd.Timestamp(END))
    return frame[keep].reset_index(drop=True)


def fnspid(tickers: list[str]) -> pd.DataFrame:
    h = pd.read_parquet("data/external/fnspid/headlines.parquet")
    return in_window(h[h.ticker.isin(tickers)])


def sample() -> list[str]:
    m = master()
    h = fnspid(list(m.ticker))
    counts = h[h.specific].groupby("ticker").size().reindex(m.ticker, fill_value=0)
    quartile = pd.qcut(counts.rank(method="first"), 4, labels=False)
    picked = []
    for q in range(4):
        picked += list(counts[quartile == q].sample(PER_QUARTILE, random_state=SEED).index)
    OUT.mkdir(parents=True, exist_ok=True)
    record = {
        "seed": SEED,
        "window": [str(START), str(END)],
        "tickers": picked,
        "fnspid_specific_counts": {t: int(counts[t]) for t in picked},
    }
    (OUT / "sample.json").write_text(json.dumps(record, indent=1))
    return picked


def tickers() -> list[str]:
    return list(json.loads((OUT / "sample.json").read_text())["tickers"])


def run_tickertick() -> Path:
    return ns.tickertick_extract(BULK, tickers(), START, END, OUT / "tickertick_stories.parquet")


def run_gdelt() -> dict[str, dict[str, int]]:
    names = master().set_index("ticker")
    spacer = ns.Spacer()
    stats = {}
    for ticker in tickers():
        _, stats[ticker] = ns.gdelt_collect(
            ticker, names.loc[ticker].issuer_name, START, END, spacer=spacer
        )
        print(ticker, stats[ticker], flush=True)
    (OUT / "gdelt_stats.json").write_text(json.dumps(stats, indent=1))
    return stats


def gdelt_table() -> pd.DataFrame:
    names = master().set_index("ticker")
    frames = []
    for ticker in tickers():
        payloads, _ = ns.gdelt_collect(ticker, names.loc[ticker].issuer_name, START, END)
        frames.append(
            ns.gdelt_frame(
                payloads, ticker, names.loc[ticker].security_id, names.loc[ticker].issuer_name
            )
        )
    return in_window(pd.concat(frames, ignore_index=True))


def tone(titles: list[str]) -> dict[str, float]:
    from structural_break.intelligence.recent_tone import TONE_POLICY
    from structural_break.intelligence.sentiment import HuggingFaceFinBERT

    backend = HuggingFaceFinBERT(
        Path.home() / ".cache/huggingface/hub", TONE_POLICY, local_files_only=True
    )
    unique, out = list(dict.fromkeys(t[:400] for t in titles)), {}
    for start in range(0, len(unique), 256):
        batch = unique[start : start + 256]
        windows = [list(backend.token_ids(t))[: TONE_POLICY.max_tokens - 2] or [100] for t in batch]
        for text, p in zip(batch, backend.predict(windows), strict=True):
            out[text] = float(p["positive"] - p["negative"])
    return out


def words(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def measures(
    frame: pd.DataFrame, days: pd.DatetimeIndex, scores: dict[str, float], names: list[str]
) -> dict:
    spec = frame[frame.specific].copy()
    spec["session"] = available_session(spec, days)
    spec = spec.dropna(subset=["session"])
    spec["net"] = spec.title.str[:400].map(scores)
    toned = spec[spec.net.abs() >= TONE]
    window_days = days[(days >= pd.Timestamp(START)) & (days <= pd.Timestamp(END))]
    weeks = pd.Series(window_days).dt.strftime("%G-%V").unique()
    covered = spec.assign(week=spec.session.dt.strftime("%G-%V")).groupby("ticker").week.nunique()
    seconds = (frame.stamp - frame.date).dt.total_seconds()
    return {
        "headlines": int(len(frame)),
        "company_specific": int(len(spec)),
        "toned_sessions": int(toned[["ticker", "session"]].drop_duplicates().shape[0]),
        "coverage_ticker_weeks": float(
            covered.reindex(names, fill_value=0).sum() / (len(names) * len(weeks))
        ),
        "per_ticker_specific": {
            t: int(n) for t, n in spec.groupby("ticker").size().reindex(names, fill_value=0).items()
        },
        "share_with_time_of_day": float((seconds > 0).mean()) if len(frame) else math.nan,
    }


def overlap(fn: pd.DataFrame, other: pd.DataFrame) -> float:
    fn, other = fn[fn.specific], other[other.specific]
    by_ticker = {t: g for t, g in other.groupby("ticker")}
    matched = 0
    for row in fn.itertuples(index=False):
        g = by_ticker.get(row.ticker)
        if g is None:
            continue
        a = words(row.title)
        near = g[(g.date - row.date).abs() <= pd.Timedelta(days=1)]
        if any(len(a & words(t)) / max(len(a | words(t)), 1) >= JACCARD for t in near.title):
            matched += 1
    return matched / len(fn) if len(fn) else math.nan


def compare(candidate: dict, reference: dict, names: list[str]) -> dict:
    ratios = [
        candidate["per_ticker_specific"][t] / reference["per_ticker_specific"][t]
        for t in names
        if reference["per_ticker_specific"][t] > 0
    ]
    toned = (
        candidate["toned_sessions"] / reference["toned_sessions"]
        if reference["toned_sessions"]
        else math.nan
    )
    coverage = (
        candidate["coverage_ticker_weeks"] / reference["coverage_ticker_weeks"]
        if reference["coverage_ticker_weeks"]
        else math.nan
    )
    return {
        "toned_session_ratio": toned,
        "coverage_ratio": coverage,
        "median_volume_ratio": float(np.median(ratios)) if ratios else math.nan,
        "passes_rule": bool(0.67 <= toned <= 1.5 and coverage >= 0.8),
    }


def report() -> dict:
    names, m = tickers(), master()
    fn = fnspid(names)
    lookup = m.set_index("ticker")
    fn["specific"] = [
        bool(_matcher(lookup.loc[t].issuer_name, t).search(x)) for t, x in zip(fn.ticker, fn.title)
    ]
    tt = in_window(ns.tickertick_frame(pd.read_parquet(OUT / "tickertick_stories.parquet"), m))
    # Decision 116c: GDELT counts only if its run completed (gdelt_stats.json exists).
    gdelt_ok = (OUT / "gdelt_stats.json").exists()
    gd = gdelt_table() if gdelt_ok else tt.iloc[0:0]
    days = sessions()
    scores = tone([*fn[fn.specific].title, *tt[tt.specific].title, *gd[gd.specific].title])
    ref = measures(fn, days, scores, names)
    result = {
        "decision": "DECISIONS 116 (116a, 116b, 116c)",
        "window": [str(START), str(END)],
        "tickers": names,
        "fnspid": ref,
        "sources": {},
    }
    for label, frame in (("gdelt", gd), ("tickertick", tt)) if gdelt_ok else (("tickertick", tt),):
        own = measures(frame, days, scores, names)
        result["sources"][label] = {**own, **compare(own, ref, names), "overlap_fnspid_matched": overlap(fn, frame)}
    tt_ok = result["sources"]["tickertick"]["passes_rule"]
    if gdelt_ok:
        stats = json.loads((OUT / "gdelt_stats.json").read_text())
        queries = sum(s["weeks"] + 7 * s["capped_weeks"] for s in stats.values())
        g = result["sources"]["gdelt"]
        g["capped_week_share"] = sum(s["capped_weeks"] for s in stats.values()) / sum(s["weeks"] for s in stats.values())
        g["capture_queries_2024_2025"] = int(queries / (len(names) * max(s["weeks"] for s in stats.values()))
                                             * TICKERS_ALL * WEEKS_2024_2025)
        gd_ok = g["passes_rule"]
        if gd_ok or not tt_ok:
            choice = "GDELT" + ("" if gd_ok else " (with reported limitation)")
        else:
            choice = "TickerTick (bulk to May 2025, live API after)"
    else:
        result["gdelt"] = "infeasible under Decision 116c (rate-limited); not measured"
        choice = "TickerTick (bulk to May 2025, live API after)" + ("" if tt_ok else ", with reported limitation")
    result["final_test_source"] = choice
    (OUT / "report.json").write_text(json.dumps(result, indent=1, default=str))
    return result


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "report"
    if command == "sample":
        print(json.dumps(sample()))
    elif command == "tickertick":
        print(run_tickertick())
    elif command == "gdelt":
        run_gdelt()
    else:
        out = report()
        print(
            json.dumps(
                {k: v for k, v in out.items() if k != "fnspid"}
                | {
                    "fnspid": {k: v for k, v in out["fnspid"].items() if k != "per_ticker_specific"}
                },
                indent=1,
                default=str,
            )
        )
