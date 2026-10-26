"""FNSPID company headlines with conservative point-in-time availability (DECISIONS 110).

FNSPID (Dong et al. 2024, CC BY-NC 4.0) labels times "UTC", but many Benzinga
stamps look like US Eastern time and many carry only a date (00:00:00). A
headline therefore counts at a session's close only when it is safe under
either reading:

- a stated time after midnight and at or before 15:00 on date D is available
  at the close of the first session on or after D;
- a date-only stamp, or a time after 15:00, is available at the close of the
  first session strictly after D.

Only company-specific headlines are kept as evidence: the title must name the
company (a spelling of its issuer name) or its ticker in an exchange
pattern. Generic lists ("71 Biggest Movers From Friday") are dropped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from structural_break.agents.debate import name_variants

HEADLINES_VERSION = "fnspid-headlines-v1"
COLUMNS = ["Date", "Article_title", "Stock_symbol", "Url", "Publisher"]


def _matcher(issuer_name: str, ticker: str) -> re.Pattern[str]:
    names = [re.escape(v) for v in name_variants(issuer_name)]
    exchange = rf"\b(?:NYSE|NASDAQ|Nasdaq|NYSE American)\s*:\s*{re.escape(ticker)}\b"
    body = "|".join(rf"(?<![A-Za-z0-9]){n}(?![A-Za-z0-9])" for n in names)
    return re.compile(rf"(?:{body})|{exchange}" if body else exchange, re.IGNORECASE)


def ingest(
    csvs: Path | list[Path], master: pd.DataFrame, out: Path, chunksize: int = 200_000
) -> pd.DataFrame:
    """Filter FNSPID files to the universe's tickers; one row per company headline.

    The Nasdaq file also carries an extractive summary; its first 300 characters
    are kept as ``summary`` (empty for Benzinga rows).
    """
    tickers = dict(zip(master["ticker"], master["security_id"], strict=True))
    names = dict(zip(master["ticker"], master["issuer_name"], strict=True))
    matchers = {t: _matcher(str(names[t]), t) for t in tickers}
    parts = []
    for csv in [csvs] if isinstance(csvs, Path) else csvs:
        header = pd.read_csv(csv, nrows=0).columns
        usecols = COLUMNS + [c for c in ("Article", "Lsa_summary") if c in header]
        for chunk in pd.read_csv(csv, usecols=usecols, chunksize=chunksize, dtype=str):
            chunk = chunk[chunk["Stock_symbol"].isin(tickers)].dropna(
                subset=["Date", "Article_title"]
            )
            if chunk.empty:
                continue
            stamp = pd.to_datetime(
                chunk["Date"].str.replace(" UTC", "", regex=False), errors="coerce"
            )
            summary = (
                chunk.get("Lsa_summary", pd.Series("", index=chunk.index)).fillna("").str[:300]
            )
            article = chunk.get("Article", pd.Series("", index=chunk.index)).fillna("")
            chunk = chunk.assign(stamp=stamp, summary=summary, article=article, source=csv.stem)
            parts.append(
                chunk.dropna(subset=["stamp"]).drop(
                    columns=["Lsa_summary", "Article"], errors="ignore"
                )
            )
    frame = pd.concat(parts, ignore_index=True)
    frame = frame.rename(
        columns={
            "Article_title": "title",
            "Stock_symbol": "ticker",
            "Url": "url",
            "Publisher": "publisher",
        }
    )
    frame["security_id"] = frame["ticker"].map(tickers)
    frame["specific"] = [
        bool(matchers[t].search(title))
        for t, title in zip(frame["ticker"], frame["title"], strict=True)
    ]
    frame["date"] = frame["stamp"].dt.normalize()
    seconds = (frame["stamp"] - frame["date"]).dt.total_seconds()
    frame["same_day"] = (seconds > 0) & (seconds <= 15 * 3600)
    frame = frame.drop_duplicates(["ticker", "title", "date"]).reset_index(drop=True)
    frame = frame.loc[
        :,
        [
            "ticker",
            "security_id",
            "stamp",
            "date",
            "same_day",
            "title",
            "summary",
            "article",
            "publisher",
            "url",
            "source",
            "specific",
        ],
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    # The full text lives in a separate compressed store; the working table stays small.
    frame.to_parquet(out.with_name("articles.parquet"), index=False, compression="zstd")
    frame = frame.drop(columns=["article"])
    frame.to_parquet(out, index=False, compression="zstd")
    return cast(pd.DataFrame, frame)


def manifest(
    sources: list[Path], urls: Mapping[str, str], outputs: list[Path], path: Path
) -> dict[str, object]:
    """Provenance of the compact store: source sizes and SHA-256 hashes, so the raw files can be dropped."""  # noqa: E501
    import hashlib
    import json

    def sha(file: Path) -> str:
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 24), b""):
                digest.update(block)
        return digest.hexdigest()

    record: dict[str, object] = {
        "version": HEADLINES_VERSION,
        "dataset": "FNSPID (Dong et al. 2024), CC BY-NC 4.0",
        "sources": [
            {"file": s.name, "url": urls[s.name], "bytes": s.stat().st_size, "sha256": sha(s)}
            for s in sources
        ],
        "outputs": [{"file": o.name, "bytes": o.stat().st_size, "sha256": sha(o)} for o in outputs],
    }
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def available_session(frame: pd.DataFrame, sessions: Iterable[pd.Timestamp]) -> pd.Series:
    """First session whose close may use each headline (see module rule)."""
    days = pd.DatetimeIndex(sorted(pd.Timestamp(d).normalize() for d in sessions))
    on_or_after = days.searchsorted(frame["date"].to_numpy(), side="left")
    strictly_after = days.searchsorted(frame["date"].to_numpy(), side="right")
    position = np.where(frame["same_day"].to_numpy(), on_or_after, strictly_after)
    valid = position < len(days)
    result = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    result[valid] = days[position[valid]]
    return result


def coverage(
    events: pd.DataFrame, headlines: pd.DataFrame, sessions: pd.DatetimeIndex, lookback: int = 3
) -> pd.DataFrame:
    """Per event: company-specific headline counts per leg in the last ``lookback`` sessions."""
    days = pd.DatetimeIndex(sorted(sessions))
    grouped: Mapping[str, pd.DataFrame] = {
        str(sec): g for sec, g in headlines[headlines["specific"]].groupby("security_id")
    }
    rows = []
    for event in events.itertuples(index=False):
        end = pd.Timestamp(cast(Any, event.event_date)).normalize()
        position = int(days.searchsorted(end))
        start = days[max(position - lookback + 1, 0)]
        counts = {}
        for leg, sec in (("a", event.leg_a_security_id), ("b", event.leg_b_security_id)):
            g = grouped.get(str(sec))
            counts[leg] = 0 if g is None else int(g["session"].between(start, end).sum())
        rows.append(
            {"event_id": event.event_id, "headlines_a": counts["a"], "headlines_b": counts["b"]}
        )
    return pd.DataFrame(rows)
