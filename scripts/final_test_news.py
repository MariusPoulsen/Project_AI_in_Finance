"""Final-test company headlines (Decision 116d plan, after the owner's unlock, Decision 120).

    python scripts/final_test_news.py bulk     # Jan 2024 to 25 May 2025, 2025-05-26 bulk file
    python scripts/final_test_news.py anchor   # a story id dated just after 2025-12-31
    python scripts/final_test_news.py api      # 26 May to 31 Dec 2025, live API, resumable
    python scripts/final_test_news.py frame    # data/external/news_final/headlines.parquet

The live API pages back from the newest story. Its ``last`` parameter accepts any story id,
also one returned for another ticker, so every ticker starts from one story dated just after
the window (the anchor) instead of paging back from today. Query, spacing and the row schema
are those of ``news_sources.tickertick_api``.
"""

import json
import sys
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break import periods
from structural_break.intelligence import news_sources as ns

WS = Path("data/team")
BULK = Path("data/external/tickertick/TickerTick-stock-news-dataset.2025-05-26.json.bz2")
OUT = Path("data/external/tickertick/final")
API_FIRST, API_LAST = date(2025, 5, 26), date(2025, 12, 31)
BULK_FIRST, BULK_LAST = date(2024, 1, 1), date(2025, 5, 25)
ANCHOR_TICKER = "duk"  # a ticker with few stories, so the anchor needs few requests


def master() -> pd.DataFrame:
    return pd.read_parquet(WS / "universe/source_v1/security_master.parquet")


def bulk() -> None:
    ns.tickertick_extract(BULK, list(master().ticker), BULK_FIRST, BULK_LAST, OUT / "bulk.parquet")
    print("bulk", len(pd.read_parquet(OUT / "bulk.parquet")), "stories")


def _feed(params: dict[str, object], spacer: ns.Spacer) -> dict[str, Any]:
    spacer.wait()
    for attempt in range(6):
        try:
            return ns._http(f"{ns.TICKERTICK_API}?{urllib.parse.urlencode(params)}")
        except Exception as error:  # noqa: BLE001 (blocked for 30 s on a burst; retry)
            print("retry", attempt, error, flush=True)
            spacer.sleep(35 * (attempt + 1))
    raise RuntimeError("TickerTick did not answer")


def anchor() -> None:
    spacer = ns.Spacer(ns.TICKERTICK_SPACING)
    upper = pd.Timestamp(API_LAST, tz="America/New_York") + pd.Timedelta(days=1)
    params: dict[str, object] = {"q": f"tt:{ANCHOR_TICKER}", "n": 200}
    best: tuple[str, str] | None = None
    for _ in range(100):
        stories = _feed(params, spacer).get("stories", [])
        if not stories:
            break
        for story in stories:
            stamp = pd.Timestamp(int(story["time"]), unit="ms", tz="UTC")
            if stamp >= upper:
                best = (str(story["id"]), str(stamp))
            elif best is not None:
                OUT.mkdir(parents=True, exist_ok=True)
                (OUT / "anchor.json").write_text(json.dumps({"id": best[0], "time": best[1]}))
                print("anchor", best)
                return
        params["last"] = stories[-1]["id"]
    raise RuntimeError("no anchor found")


def api() -> None:
    periods.check_end(API_LAST)
    start = json.loads((OUT / "anchor.json").read_text())["id"]
    spacer = ns.Spacer(ns.TICKERTICK_SPACING)
    lower = pd.Timestamp(API_FIRST, tz="America/New_York")
    upper = pd.Timestamp(API_LAST, tz="America/New_York") + pd.Timedelta(days=1)
    folder = OUT / "api"
    folder.mkdir(parents=True, exist_ok=True)
    tickers = sorted(master().ticker)
    for n, ticker in enumerate(tickers, 1):
        target = folder / f"{ticker}.parquet"
        if target.exists():
            continue
        params: dict[str, object] = {"q": f"tt:{ticker.lower()}", "n": 200, "last": start}
        rows, pages = [], 0
        while True:
            payload = _feed(params, spacer)
            pages += 1
            stories = payload.get("stories", [])
            if not stories:
                break
            for story in stories:
                stamp = pd.Timestamp(int(story["time"]), unit="ms", tz="UTC").tz_convert(
                    "America/New_York"
                )
                if lower <= stamp < upper:
                    rows.append(
                        {
                            "ticker": ticker,
                            "unix_timestamp": stamp.timestamp(),
                            "title": story.get("title", ""),
                            "url": story.get("url", ""),
                            "site": story.get("site", ""),
                        }
                    )
            if pd.Timestamp(int(stories[-1]["time"]), unit="ms", tz="UTC") < lower:
                break
            params["last"] = payload.get("last_id") or stories[-1]["id"]
        frame = pd.DataFrame(rows, columns=["ticker", "unix_timestamp", "title", "url", "site"])
        frame.to_parquet(target, index=False)
        print(f"{n}/{len(tickers)} {ticker} {len(frame)} stories {pages} pages", flush=True)


def frame() -> None:
    parts = [pd.read_parquet(OUT / "bulk.parquet")]
    parts += [pd.read_parquet(p) for p in sorted((OUT / "api").glob("*.parquet"))]
    stories = pd.concat(parts, ignore_index=True)
    table = ns.tickertick_frame(stories, master())
    out = Path("data/external/news_final/headlines.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out, index=False)
    by_year = table.groupby(table.date.dt.year).agg(
        n=("title", "size"), specific=("specific", "sum")
    )
    print(out, len(table), "headlines\n", by_year.to_string())


if __name__ == "__main__":
    {"bulk": bulk, "anchor": anchor, "api": api, "frame": frame}[sys.argv[1]]()
