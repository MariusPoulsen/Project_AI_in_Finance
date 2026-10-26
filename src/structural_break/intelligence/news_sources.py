"""GDELT and TickerTick company headlines for the position monitor (Decisions 116, 116a).

Both adapters return the FNSPID headline table (``intelligence.headlines``): the same
company-specific title test and the same conservative availability rule, so the monitor
reads every source the same way. Nothing after the development end is requested or read
while the final test is locked (``periods.check_end``).

- **GDELT DOC 2.0** (free, no key): one article-list query per company and calendar week
  for the company's name variants, English sources, up to 250 articles; the stamp is
  GDELT's ``seendate`` (UTC). Raw answers are cached; requests are spaced by at least
  ``GDELT_SPACING`` seconds as GDELT asks.
- **TickerTick** bulk files (free): one JSON story a line with ``tickers_direct`` and a UNIX
  timestamp, converted to US Eastern time. Only stories inside the requested window are kept.
"""

from __future__ import annotations

import bz2
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break import periods
from structural_break.agents.debate import name_variants
from structural_break.intelligence.headlines import _matcher

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_RAW = Path("data/external/gdelt/raw")
GDELT_SPACING = 6.0
GDELT_MAX = 250
USER_AGENT = "Mozilla/5.0 (academic research; pairs-trading news monitor)"
COLUMNS = [
    "ticker",
    "security_id",
    "stamp",
    "title",
    "summary",
    "publisher",
    "url",
    "source",
    "specific",
]


def _table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=COLUMNS)
    frame["stamp"] = pd.to_datetime(frame["stamp"])
    frame["date"] = frame["stamp"].dt.normalize()
    seconds = (frame["stamp"] - frame["date"]).dt.total_seconds()
    frame["same_day"] = (seconds > 0) & (seconds <= 15 * 3600)
    return frame.drop_duplicates(["ticker", "title", "date"]).reset_index(drop=True)


def gdelt_query(issuer_name: str) -> str:
    variants = [v for v in name_variants(issuer_name) if len(v) >= 3]
    phrases = " OR ".join(f'"{v}"' for v in variants)
    return (
        f"({phrases}) sourcelang:english" if len(variants) > 1 else f"{phrases} sourcelang:english"
    )


def _http(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310 (fixed https host)
        text = response.read().decode("utf-8", errors="replace")
    return dict(json.loads(text)) if text.strip().startswith("{") else {"articles": []}


class Spacer:
    """Keeps at least ``seconds`` between requests and backs off on HTTP 429."""

    def __init__(self, seconds: float = GDELT_SPACING, sleep: Callable[[float], None] = time.sleep):
        self.seconds, self.sleep, self.last = seconds, sleep, 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self.last
        if gap < self.seconds:
            self.sleep(self.seconds - gap)
        self.last = time.monotonic()


def gdelt_window(
    ticker: str,
    issuer_name: str,
    first: date,
    last: date,
    *,
    raw: Path = GDELT_RAW,
    spacer: Spacer | None = None,
    transport: Callable[[str], dict[str, Any]] = _http,
    retries: int = 4,
) -> dict[str, Any]:
    """GDELT's article list for one company and the days ``first`` to ``last`` (cached)."""
    periods.check_end(last)
    path = raw / ticker / f"{first:%Y%m%d}_{last:%Y%m%d}.json"
    if path.exists():
        return dict(json.loads(path.read_text(encoding="utf-8")))
    query = {
        "query": gdelt_query(issuer_name),
        "mode": "ArtList",
        "maxrecords": str(GDELT_MAX),
        "format": "json",
        "sort": "DateAsc",
        "startdatetime": f"{first:%Y%m%d}000000",
        "enddatetime": f"{last:%Y%m%d}235959",
    }
    url = f"{GDELT_URL}?{urllib.parse.urlencode(query)}"
    spacer = spacer or Spacer()
    for attempt in range(retries + 1):
        spacer.wait()
        try:
            payload = transport(url)
            break
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == retries:
                raise
            spacer.sleep(300.0 * (attempt + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def capped(payload: dict[str, Any]) -> bool:
    return len(payload.get("articles", [])) >= GDELT_MAX


def gdelt_collect(
    ticker: str,
    issuer_name: str,
    start: date,
    end: date,
    *,
    spacer: Spacer | None = None,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Weekly queries from the Monday on or before ``start`` to ``end``; a week that hits the
    250-article cap is re-queried day by day (Decision 116b). Returns the payloads used and
    counts of weeks, capped weeks and capped days."""
    spacer = spacer or Spacer()
    monday = start - timedelta(days=start.weekday())
    used, stats = [], {"weeks": 0, "capped_weeks": 0, "capped_days": 0, "weekly_only_articles": 0}
    while monday <= end:
        sunday = min(monday + timedelta(days=6), end)
        week = gdelt_window(ticker, issuer_name, monday, sunday, spacer=spacer, **kwargs)
        stats["weeks"] += 1
        stats["weekly_only_articles"] += len(week.get("articles", []))
        if capped(week):
            stats["capped_weeks"] += 1
            for offset in range((sunday - monday).days + 1):
                day = monday + timedelta(days=offset)
                daily = gdelt_window(ticker, issuer_name, day, day, spacer=spacer, **kwargs)
                stats["capped_days"] += int(capped(daily))
                used.append(daily)
        else:
            used.append(week)
        monday += timedelta(days=7)
    return used, stats


def gdelt_frame(
    payloads: Iterable[dict[str, Any]], ticker: str, security_id: str, issuer_name: str
) -> pd.DataFrame:
    matcher = _matcher(issuer_name, ticker)
    rows = []
    for payload in payloads:
        for item in payload.get("articles", []):
            title = str(item.get("title") or "").strip()
            stamp = pd.to_datetime(item.get("seendate"), format="%Y%m%dT%H%M%SZ", errors="coerce")
            if not title or pd.isna(stamp):
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "security_id": security_id,
                    "stamp": stamp,
                    "title": title,
                    "summary": "",
                    "publisher": str(item.get("domain") or ""),
                    "url": str(item.get("url") or ""),
                    "source": "gdelt",
                    "specific": bool(matcher.search(title)),
                }
            )
    return _table(rows)


def tickertick_extract(
    bulk: Path, tickers: Iterable[str], start: date, end: date, out: Path
) -> Path:
    """Stories in [start, end] (US Eastern) whose ``tickers_direct`` names one of ``tickers``."""
    periods.check_end(end)
    wanted = {t.lower(): t for t in tickers}
    first = pd.Timestamp(start, tz="America/New_York").timestamp()
    last = pd.Timestamp(end + timedelta(days=1), tz="America/New_York").timestamp()
    rows = []
    with bz2.open(bulk, "rt", encoding="utf-8") as stream:
        for line in stream:
            story = json.loads(line)
            stamp = float(story.get("unix_timestamp", 0))
            if not first <= stamp < last:
                continue
            for direct in story.get("tickers_direct") or []:
                if direct in wanted:
                    rows.append(
                        {
                            "ticker": wanted[direct],
                            "unix_timestamp": stamp,
                            "title": story.get("title", ""),
                            "url": story.get("url", ""),
                            "site": story.get("site", ""),
                        }
                    )
    frame = pd.DataFrame(rows, columns=["ticker", "unix_timestamp", "title", "url", "site"])
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    return out


def tickertick_frame(stories: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    names = master.set_index("ticker")
    rows = []
    for row in stories.itertuples(index=False):
        meta = names.loc[row.ticker]
        stamp = (
            pd.Timestamp(row.unix_timestamp, unit="s", tz="UTC")
            .tz_convert("America/New_York")
            .tz_localize(None)
        )
        title = str(row.title or "").strip()
        if not title:
            continue
        rows.append(
            {
                "ticker": row.ticker,
                "security_id": meta.security_id,
                "stamp": stamp,
                "title": title,
                "summary": "",
                "publisher": str(row.site or ""),
                "url": str(row.url or ""),
                "source": "tickertick",
                "specific": bool(_matcher(meta.issuer_name, row.ticker).search(title)),
            }
        )
    return _table(rows)


TICKERTICK_API = "https://api.tickertick.com/feed"
TICKERTICK_SPACING = 7.0  # 10 requests a minute per IP, with a margin


def tickertick_api(
    ticker: str,
    first: date,
    last: date,
    *,
    spacer: Spacer | None = None,
    transport: Callable[[str], dict[str, Any]] = _http,
    max_pages: int = 400,
) -> pd.DataFrame:
    """Live-API stories for ``ticker`` dated ``first`` to ``last`` (US Eastern), paging back
    from the newest story; stories after ``last`` are skipped unread beyond their timestamp.
    For months after the last bulk file (Decision 116c); refused while the final test is
    locked when ``last`` is a final-test date."""
    periods.check_end(last)
    spacer = spacer or Spacer(TICKERTICK_SPACING)
    lower = pd.Timestamp(first, tz="America/New_York")
    upper = pd.Timestamp(last + timedelta(days=1), tz="America/New_York")
    params: dict[str, Any] = {"q": f"tt:{ticker.lower()}", "n": 200}
    rows = []
    for _ in range(max_pages):
        spacer.wait()
        payload = transport(f"{TICKERTICK_API}?{urllib.parse.urlencode(params)}")
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
        oldest = pd.Timestamp(int(stories[-1]["time"]), unit="ms", tz="UTC")
        if oldest < lower:
            break
        params["last"] = payload.get("last_id") or stories[-1]["id"]
    return pd.DataFrame(rows, columns=["ticker", "unix_timestamp", "title", "url", "site"])
