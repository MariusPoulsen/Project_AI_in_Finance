"""Independent free-source market capture for the outcome-blind research-v2 freeze.

No 2024--2025 prices or outcomes enter this collection. Source gaps and identity
floors are retained in a coverage audit; neither listing dates nor delisting
coverage are inferred from Yahoo's first/last available observations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from time import sleep
from typing import Any

import numpy as np
import pandas as pd

from structural_break.config.paths import confined_path
from structural_break.data.http import FetchedResponse, HttpClient
from structural_break.data.market import (
    VIX_URL,
    Downloader,
    build_market_context,
    download_market,
    normalize_prices,
    normalize_vix,
    session_schedule,
)
from structural_break.research.universe import (
    json_bytes,
    parquet_bytes,
    verify_universe_freeze,
)
from structural_break.storage.files import sha256_file, write_bytes

Progress = Callable[[dict[str, Any]], None]


def _date(value: Any) -> date | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value).date()


def _raw_market(
    directory: Path,
    ticker: str,
    start: date,
    end: date,
    downloader: Downloader | None,
    attempts: int,
    sleeper: Callable[[float], None],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    filename = f"raw/{ticker}.parquet"
    metadata_path = directory / f"raw/{ticker}.source.json"
    request = {"ticker": ticker, "start": start.isoformat(), "end": end.isoformat()}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_bytes())
        if metadata.get("request") != request or metadata.get("file") != filename:
            raise ValueError("Cached market request disagrees with this capture")
        body = (directory / filename).read_bytes()
        if hashlib.sha256(body).hexdigest() != metadata["sha256"]:
            raise ValueError("Cached raw market bytes failed checksum verification")
        return pd.read_parquet(BytesIO(body)), metadata
    raw = download_market(
        (ticker,), start, end, downloader=downloader, attempts=attempts, sleeper=sleeper
    )[ticker]
    body = parquet_bytes(raw)
    digest = hashlib.sha256(body).hexdigest()
    metadata = {
        "request": request,
        "file": filename,
        "sha256": digest,
        "source_snapshot_id": "yahoo_" + digest[:24],
        "source_url": str(raw.iloc[0]["source_url"]),
        "retrieved_at_utc": pd.Timestamp(raw.iloc[0]["retrieved_at_utc"]).isoformat(),
        "source_provider": "YAHOO_YFINANCE",
        "library_version": str(raw.iloc[0]["library_version"]),
    }
    write_bytes(directory / filename, body)
    write_bytes(metadata_path, json_bytes(metadata))
    return raw, metadata


def collect_market(
    frozen_universe_dir: Path,
    output_dir: Path,
    start: date = date(2004, 1, 1),
    end: date = date(2023, 12, 31),
    *,
    tickers: Sequence[str] | None = None,
    downloader: Downloader | None = None,
    get: Callable[[str], FetchedResponse] | None = None,
    attempts: int = 3,
    min_interval_seconds: float = 1.0,
    sleeper: Callable[[float], None] = sleep,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Capture each issuer independently and publish engine-compatible tables.

    An explicit ticker subset supports an outcome-blind bounded source dry run.
    All required benchmarks are collected for that subset. Failed issuer sources
    exclude affected pairs with a reason, and never select on relationship fit or
    reversion outcomes. Raw successes are hash-verified on an interrupted retry.
    A finished capture is immutable; changing inputs requires a new directory.
    """
    if start >= end or end > date(2023, 12, 31):
        raise ValueError("Research-v2 development collection must end by 2023-12-31")
    if not 1 <= attempts <= 5 or not 0 <= min_interval_seconds <= 60:
        raise ValueError("Invalid bounded market source policy")
    freeze = verify_universe_freeze(frozen_universe_dir)
    securities = pd.read_parquet(frozen_universe_dir / "security_master.parquet")
    pairs = pd.read_parquet(frozen_universe_dir / "pair_universe.parquet")
    selected = tuple(sorted(tickers if tickers is not None else securities["ticker"].tolist()))
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("Market capture requires a nonempty unique issuer selection")
    if set(selected) - set(securities["ticker"]):
        raise ValueError("Market selection includes an issuer outside the frozen universe")
    securities = securities.loc[securities["ticker"].isin(selected)].copy()
    sectors = tuple(sorted(set(securities["sector_etf"])))
    requested = tuple(sorted(set(selected) | set(sectors) | {"SPY"}))
    inputs = {
        "universe_freeze_id": freeze["freeze_id"],
        "universe_manifest_sha256": sha256_file(frozen_universe_dir / "manifest.json"),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "selected_issuers": list(selected),
        "market_code_sha256": sha256_file(Path(__file__)),
        "normalization_code_sha256": sha256_file(Path(__file__).parents[1] / "data/market.py"),
    }
    if (output_dir / "manifest.json").exists():
        manifest = verify_market_capture(output_dir, frozen_universe_dir)
        if manifest["inputs"] != inputs:
            raise ValueError("Market directory already binds another source capture")
        return manifest
    raw_frames: dict[str, pd.DataFrame] = {}
    sources: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    bounds: list[dict[str, Any]] = []
    security_by_ticker = securities.set_index("ticker").to_dict("index")
    for index, ticker in enumerate(requested):
        rule = security_by_ticker.get(ticker, {})
        floor, ceiling = (
            _date(rule.get("identity_valid_from")),
            _date(rule.get("identity_valid_to")),
        )
        lower = max(start, floor) if floor else start
        upper = min(end, ceiling) if ceiling else end
        bounds.append(
            {
                "ticker": ticker,
                "requested_start": lower.isoformat(),
                "requested_end": upper.isoformat(),
                "identity_floor": floor.isoformat() if floor else None,
                "identity_ceiling": ceiling.isoformat() if ceiling else None,
            }
        )
        try:
            if lower >= upper:
                raise ValueError("Reviewed identity has no usable development date range")
            raw, source = _raw_market(
                output_dir, ticker, lower, upper, downloader, attempts, sleeper
            )
            raw = raw.copy()
            raw["source_snapshot_id"] = source["source_snapshot_id"]
            raw["raw_file_path"] = source["file"]
            raw["sha256"] = source["sha256"]
            raw_frames[ticker] = raw
            sources.append(source)
            status = "OK"
        except (RuntimeError, ValueError) as exc:
            # Existing corrupt caches are failures, never silently redownloaded
            # under an immutable identity. Their exclusions remain auditable.
            if (output_dir / f"raw/{ticker}.source.json").exists():
                raise ValueError(f"Frozen raw cache failed integrity checks for {ticker}") from exc
            failures.append(
                {"ticker": ticker, "reason": "MARKET_SOURCE_FAILED", "detail": str(exc)}
            )
            status = "FAILED"
        if progress:
            progress(
                {
                    "ticker": ticker,
                    "status": status,
                    "completed": index + 1,
                    "total": len(requested),
                }
            )
        if index + 1 < len(requested) and min_interval_seconds:
            sleeper(min_interval_seconds)
    benchmark_missing = (set(sectors) | {"SPY"}) - raw_frames.keys()
    if benchmark_missing:
        raise ValueError(f"Required benchmark source failed: {sorted(benchmark_missing)}")
    if get is None:
        get = HttpClient(None, attempts=attempts).get
    vix_file = output_dir / "raw/VIX_History.csv"
    vix_metadata_file = output_dir / "raw/VIX_History.source.json"
    if vix_metadata_file.exists():
        vix_metadata = json.loads(vix_metadata_file.read_bytes())
        body = vix_file.read_bytes()
        if hashlib.sha256(body).hexdigest() != vix_metadata["sha256"]:
            raise ValueError("Cached Cboe VIX bytes failed checksum verification")
    else:
        response = get(VIX_URL)
        if response.status_code != 200 or response.url != VIX_URL or not response.body:
            raise ValueError(
                "Cboe VIX capture did not return the required successful public source"
            )
        body = response.body
        digest = hashlib.sha256(body).hexdigest()
        vix_metadata = {
            "file": "raw/VIX_History.csv",
            "sha256": digest,
            "source_snapshot_id": "cboe_" + digest[:24],
            "source_url": VIX_URL,
            "retrieved_at_utc": response.retrieved_at.isoformat(),
            "source_provider": "CBOE",
            "library_version": "official_csv",
        }
        write_bytes(vix_file, body)
        write_bytes(vix_metadata_file, json_bytes(vix_metadata))
    sources.append(vix_metadata)
    source_identity = {"inputs": inputs, "sources": sources, "failures": list(failures)}
    snapshot_id = "market_" + hashlib.sha256(json_bytes(source_identity)).hexdigest()[:24]
    for raw in raw_frames.values():
        raw["data_snapshot_id"] = snapshot_id
    prices = normalize_prices(raw_frames)
    # Preserve non-session originals, but engine inputs require an actual session
    # timestamp. Invalid in-session rows remain flagged and are never filled.
    non_session_count = int(prices["data_available_at"].isna().sum())
    prices = prices.loc[prices["data_available_at"].notna()].reset_index(drop=True)
    vix = normalize_vix(body, start, end)
    for key in ("source_snapshot_id", "sha256", "source_url", "source_provider", "library_version"):
        vix[key] = vix_metadata[key]
    vix["raw_file_path"] = vix_metadata["file"]
    vix["data_snapshot_id"] = snapshot_id
    vix["retrieved_at_utc"] = pd.to_datetime(vix_metadata["retrieved_at_utc"], utc=True)
    context = build_market_context(prices, vix, sectors)
    coverage = coverage_report(prices, securities, start, end)
    usable = {row["ticker"] for row in coverage if row["usable_observation_count"] > 0}
    for ticker in set(selected) - usable:
        if ticker not in {failure["ticker"] for failure in failures}:
            failures.append({"ticker": ticker, "reason": "NO_USABLE_IN_SESSION_PRICE"})
    included_pairs = pairs.loc[pairs["leg_a"].isin(usable) & pairs["leg_b"].isin(usable)].copy()
    pair_exclusions = [
        {"pair_id": row["pair_id"], "reason": "ISSUER_OUTSIDE_CAPTURE_OR_MISSING_SOURCE"}
        for row in pairs.loc[~pairs["pair_id"].isin(included_pairs["pair_id"])].to_dict("records")
    ]
    securities["market_coverage_status"] = np.where(
        securities["ticker"].isin(usable), "AVAILABLE", "MISSING"
    )
    files = {
        "prices.parquet": parquet_bytes(prices),
        "vix.parquet": parquet_bytes(vix),
        "market_context.parquet": parquet_bytes(context),
        "security_master.parquet": parquet_bytes(securities.reset_index(drop=True)),
        "pair_universe.parquet": parquet_bytes(included_pairs.reset_index(drop=True)),
        "coverage.json": json_bytes(coverage),
        "exclusions.json": json_bytes({"issuers": failures, "pairs": pair_exclusions}),
        "identity_bounds.json": json_bytes(bounds),
        "sources.json": json_bytes(sources),
    }
    for source in sources:
        filename = source["file"]
        files[filename] = (output_dir / filename).read_bytes()
        sidecar = filename.replace(".parquet", ".source.json").replace(".csv", ".source.json")
        files[sidecar] = (output_dir / sidecar).read_bytes()
    manifest = {
        "schema_version": "research-market-capture-v1",
        "data_snapshot_id": snapshot_id,
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "inputs": inputs,
        "source_identity": source_identity,
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
        "requested_issuer_count": len(selected),
        "available_issuer_count": len(usable),
        "included_pair_count": len(included_pairs),
        "price_rows": len(prices),
        "context_rows": len(context),
        "non_session_raw_rows_excluded": non_session_count,
        "vix_context_lag_sessions": 1,
        "final_test_prices_collected": False,
        "historical_adjustment_vintages_available": False,
        "listing_delisting_dates_inferred": False,
        "delisting_complete": False,
    }
    for filename, content in files.items():
        write_bytes(output_dir / filename, content)
    write_bytes(output_dir / "manifest.json", json_bytes(manifest))
    return verify_market_capture(output_dir, frozen_universe_dir)


def coverage_report(
    prices: pd.DataFrame, securities: pd.DataFrame, start: date, end: date
) -> list[dict[str, Any]]:
    """Source availability audit; first/last dates do not infer legal lifecycle."""
    schedule = session_schedule(start, end)
    days = set(schedule["trading_date"])
    rows = []
    for security in securities.sort_values("ticker").to_dict("records"):
        ticker = security["ticker"]
        frame = prices.loc[prices["ticker"].eq(ticker)].copy()
        flag_ok = frame["quality_flag"].isin(("OK", "ZERO_VOLUME"))
        valid = frame.loc[flag_ok & np.isfinite(frame["adj_close"]) & frame["adj_close"].gt(0)]
        first = valid["trading_date"].min() if not valid.empty else None
        last = valid["trading_date"].max() if not valid.empty else None
        internal = {day for day in days if first is not None and first <= day <= last}
        observed = set(valid["trading_date"])
        identity_floor = _date(security.get("identity_valid_from"))
        rows.append(
            {
                "ticker": ticker,
                "security_id": security["security_id"],
                "source_first_usable_date": first.isoformat() if first else None,
                "source_last_usable_date": last.isoformat() if last else None,
                "observation_count": len(frame),
                "usable_observation_count": len(valid),
                "internal_missing_or_invalid_sessions": len(internal - observed),
                "full_requested_missing_or_invalid_sessions": len(days - observed),
                "observations_by_year": {
                    str(year): int(valid["trading_date"].map(lambda day: day.year).eq(year).sum())
                    for year in range(start.year, end.year + 1)
                },
                "quality_flags": {
                    str(key): int(value)
                    for key, value in frame["quality_flag"].value_counts().items()
                },
                "identity_valid_from": identity_floor.isoformat() if identity_floor else None,
                "legal_listing_date": None,
                "legal_delisting_date": None,
                "delisting_complete": False,
            }
        )
    return rows


def verify_market_capture(directory: Path, universe_directory: Path) -> dict[str, Any]:
    """Verify every immutable input/output byte and the development-only boundary."""
    freeze = verify_universe_freeze(universe_directory)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "research-market-capture-v1"
    ):
        raise ValueError("Invalid research market capture manifest")
    inputs = manifest["inputs"]
    if inputs["universe_freeze_id"] != freeze["freeze_id"] or inputs[
        "universe_manifest_sha256"
    ] != sha256_file(universe_directory / "manifest.json"):
        raise ValueError("Market capture belongs to a different universe freeze")
    if (
        date.fromisoformat(inputs["end"]) > date(2023, 12, 31)
        or manifest.get("final_test_prices_collected") is not False
    ):
        raise ValueError("Market capture violates the final-test lock")
    expected_id = (
        "market_" + hashlib.sha256(json_bytes(manifest["source_identity"])).hexdigest()[:24]
    )
    if (
        manifest["data_snapshot_id"] != expected_id
        or manifest["source_identity"]["inputs"] != inputs
    ):
        raise ValueError("Market source identity disagrees with its manifest")
    bodies = {}
    for filename, digest in manifest["files"].items():
        body = confined_path(directory, filename).read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError(f"Market capture file checksum differs: {filename}")
        bodies[filename] = body
    required = {
        "prices.parquet",
        "market_context.parquet",
        "security_master.parquet",
        "pair_universe.parquet",
        "vix.parquet",
        "coverage.json",
        "exclusions.json",
        "identity_bounds.json",
        "sources.json",
    }
    if not required.issubset(bodies):
        raise ValueError("Market capture has an incomplete curated file inventory")
    prices = pd.read_parquet(BytesIO(bodies["prices.parquet"]))
    dates = pd.to_datetime(prices["trading_date"]).dt.date
    if not dates.between(
        date.fromisoformat(inputs["start"]), date.fromisoformat(inputs["end"])
    ).all():
        raise ValueError("Market capture contains prices outside the frozen development range")
    if (
        len(prices) != manifest["price_rows"]
        or not prices["data_snapshot_id"].eq(expected_id).all()
    ):
        raise ValueError("Market curated prices mix data identities or disagree with counts")
    for source in manifest["source_identity"]["sources"]:
        if (
            source["file"] not in bodies
            or hashlib.sha256(bodies[source["file"]]).hexdigest() != source["sha256"]
        ):
            raise ValueError("Market raw source disagrees with its source lineage")
    return dict(manifest)
