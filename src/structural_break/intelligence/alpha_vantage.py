"""Alpha Vantage company headlines for the position monitor (Decisions 113, 116).

``fetch`` asks ``NEWS_SENTIMENT`` for one ticker and window and keeps the raw JSON, so a
window is requested once. Every request is reserved in a durable day counter first (the
free tier allows 25 a day), and any window ending after the development end is refused
while the final test is locked (``periods.check_end``). ``normalise`` turns a feed into the
FNSPID headline table, with the same company-specific test and availability rule, so the
monitor reads both sources the same way. The key is read from ``ALPHAVANTAGE_API_KEY``
(or a dotenv file) and never printed or stored.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break import periods
from structural_break.intelligence.headlines import _matcher

URL = "https://www.alphavantage.co/query"
DAILY_LIMIT = 25
PAGE = 1000
SOURCE = "alpha_vantage"
RAW = Path("data/external/alpha_vantage/raw")
COUNTER = Path("data/external/alpha_vantage/requests.json")

Transport = Callable[[str], dict[str, Any]]


class QuotaReached(RuntimeError):
    """The day's request allowance is used up, or the provider refused the call."""


def load_key(env_file: Path | None = None) -> str:
    if env_file is not None and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ALPHAVANTAGE_API_KEY" and value.strip():
                os.environ.setdefault("ALPHAVANTAGE_API_KEY", value.strip().strip("\"'"))
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not set")
    return key


def _http(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 (fixed https host)
        return dict(json.loads(response.read().decode("utf-8")))


def _reserve(counter: Path, limit: int) -> int:
    """Charge one request to today's (UTC) counter before it is sent; returns the count."""
    today = datetime.now(UTC).date().isoformat()
    counts = json.loads(counter.read_text()) if counter.exists() else {}
    if counts.get(today, 0) >= limit:
        raise QuotaReached(f"{limit} Alpha Vantage requests already used on {today}")
    counts[today] = counts.get(today, 0) + 1
    counter.parent.mkdir(parents=True, exist_ok=True)
    temporary = counter.with_suffix(".tmp")
    temporary.write_text(json.dumps(counts, indent=1))
    temporary.replace(counter)
    return int(counts[today])


def raw_path(ticker: str, start: date, end: date, raw: Path = RAW) -> Path:
    return raw / f"{ticker}_{start:%Y%m%d}_{end:%Y%m%d}.json"


def fetch(
    ticker: str,
    start: date,
    end: date,
    key: str,
    *,
    raw: Path = RAW,
    counter: Path = COUNTER,
    limit: int = DAILY_LIMIT,
    transport: Transport = _http,
) -> dict[str, Any]:
    """The raw feed for one ticker and window, from the cache or one request."""
    periods.check_end(end)
    path = raw_path(ticker, start, end, raw)
    if path.exists():
        return dict(json.loads(path.read_text(encoding="utf-8")))
    _reserve(counter, limit)
    query = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "time_from": f"{start:%Y%m%d}T0000",
        "time_to": f"{end:%Y%m%d}T2359",
        "sort": "EARLIEST",
        "limit": str(PAGE),
        "apikey": key,
    }
    payload = transport(f"{URL}?{urllib.parse.urlencode(query)}")
    if "feed" not in payload:
        # Rate-limit and error answers carry "Information", "Note" or "Error Message".
        message = next(
            (str(payload[k]) for k in ("Information", "Note", "Error Message") if k in payload), ""
        )
        raise QuotaReached(f"no feed for {ticker}: {message[:160]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def truncated(payload: dict[str, Any]) -> bool:
    return len(payload.get("feed", [])) >= PAGE


def normalise(
    payload: dict[str, Any], ticker: str, security_id: str, issuer_name: str
) -> pd.DataFrame:
    """One row per headline in the FNSPID table layout (``intelligence.headlines``)."""
    matcher = _matcher(issuer_name, ticker)
    rows = []
    for item in payload.get("feed", []):
        stamp = pd.to_datetime(item.get("time_published"), format="%Y%m%dT%H%M%S", errors="coerce")
        title = str(item.get("title") or "").strip()
        if pd.isna(stamp) or not title:
            continue
        relevance = next(
            (
                float(t.get("relevance_score", 0))
                for t in item.get("ticker_sentiment", [])
                if t.get("ticker") == ticker
            ),
            0.0,
        )
        rows.append(
            {
                "ticker": ticker,
                "security_id": security_id,
                "stamp": stamp,
                "title": title,
                "summary": str(item.get("summary") or "")[:300],
                "publisher": str(item.get("source") or ""),
                "url": str(item.get("url") or ""),
                "source": SOURCE,
                "relevance": relevance,
                "specific": bool(matcher.search(title)),
            }
        )
    frame = pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "security_id",
            "stamp",
            "title",
            "summary",
            "publisher",
            "url",
            "source",
            "relevance",
            "specific",
        ],
    )
    frame["date"] = frame["stamp"].dt.normalize()
    seconds = (frame["stamp"] - frame["date"]).dt.total_seconds()
    frame["same_day"] = (seconds > 0) & (seconds <= 15 * 3600)
    return frame.drop_duplicates(["ticker", "title", "date"]).reset_index(drop=True)
