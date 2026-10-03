"""Daily market source adapters and trailing-only curated transformations.

Adjusted Yahoo closes are frozen, retrospectively adjusted vendor history. They
are not a vintage point-in-time corporate-action feed. Missing observations are
never repaired here, including when calculating returns and rolling volatility.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from io import BytesIO
from time import sleep
from urllib.parse import quote

import exchange_calendars as xcals
import numpy as np
import pandas as pd

PRICE_FIELDS = ("open", "high", "low", "close", "adj_close", "volume")
ACTION_FIELDS = ("dividends", "stock_splits")
LINEAGE_FIELDS = (
    "source_snapshot_id",
    "data_snapshot_id",
    "raw_file_path",
    "sha256",
    "source_url",
    "retrieved_at_utc",
    "source_provider",
    "library_version",
)
YAHOO_FIELDS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "stock_splits",
}
VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
Downloader = Callable[..., pd.DataFrame | None]


def session_schedule(start: date, end: date) -> pd.DataFrame:
    """XNYS session date, open and actual close, including holidays/early closes."""
    if start > end:
        raise ValueError("Market start must not follow end")
    calendar = xcals.get_calendar(
        "XNYS", start=start - timedelta(days=10), end=end + timedelta(days=10)
    )
    schedule = calendar.schedule
    schedule = schedule.loc[
        (schedule.index >= pd.Timestamp(start)) & (schedule.index <= pd.Timestamp(end))
    ].copy()
    return pd.DataFrame(
        {
            "trading_date": schedule.index.date,
            "session_open": pd.to_datetime(schedule["open"].to_numpy(), utc=True),
            "data_available_at": pd.to_datetime(schedule["close"].to_numpy(), utc=True),
        }
    )


def download_market(
    tickers: tuple[str, ...],
    start: date,
    end: date,
    *,
    downloader: Downloader | None = None,
    attempts: int = 3,
    sleeper: Callable[[float], None] = sleep,
) -> dict[str, pd.DataFrame]:
    """Download one complete batch; bound retries and reject silent empty symbols.

    Bounds are inclusive to callers. Yahoo's exclusive end is the following day.
    The injected downloader permits CI to test the exact request without sockets.
    """
    if not tickers or len(set(tickers)) != len(tickers):
        raise ValueError("Requested market tickers must be nonempty and unique")
    if start > end or not 1 <= attempts <= 5:
        raise ValueError("Invalid date bounds or retry count")
    if downloader is None:
        import yfinance

        downloader = yfinance.download
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            batch = downloader(
                list(tickers),
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=True,
                repair=False,
                prepost=False,
                threads=False,
                group_by="ticker",
                keepna=True,
                progress=False,
                multi_level_index=True,
                timeout=30,
            )
            if batch is None or batch.empty:
                raise ValueError("Yahoo returned an empty market batch")
            retrieved = datetime.now(UTC)
            result: dict[str, pd.DataFrame] = {}
            for ticker in tickers:
                if isinstance(batch.columns, pd.MultiIndex):
                    ticker_levels = [
                        level
                        for level in range(batch.columns.nlevels)
                        if ticker in batch.columns.get_level_values(level)
                    ]
                    if len(ticker_levels) != 1:
                        raise ValueError(f"Yahoo did not return unambiguous data for {ticker}")
                    raw = pd.DataFrame(batch.xs(ticker, axis=1, level=ticker_levels[0])).copy()
                elif len(tickers) == 1:
                    raw = batch.copy()
                else:
                    raise ValueError("Yahoo multi-symbol data is missing its ticker column level")
                missing = set(YAHOO_FIELDS) - set(raw.columns)
                if missing:
                    raise ValueError(f"Yahoo fields missing for {ticker}: {sorted(missing)}")
                raw = raw.rename(columns=YAHOO_FIELDS).loc[:, [*PRICE_FIELDS, *ACTION_FIELDS]]
                if raw.loc[:, list(PRICE_FIELDS)].isna().all(axis=None):
                    raise ValueError(f"Yahoo returned no price observations for {ticker}")
                if not isinstance(raw.index, pd.DatetimeIndex):
                    raise ValueError(f"Yahoo returned a non-date index for {ticker}")
                # Daily Yahoo indexes represent the local exchange date. Do not
                # convert midnight to UTC and inadvertently change that date.
                raw.insert(0, "trading_date", raw.index.date)
                raw.insert(0, "ticker", ticker)
                raw = raw.reset_index(drop=True)
                dates = raw["trading_date"]
                raw = raw.loc[(dates >= start) & (dates <= end)].reset_index(drop=True)
                if raw.empty:
                    raise ValueError(f"Yahoo returned no requested dates for {ticker}")
                raw["retrieved_at_utc"] = retrieved
                raw["source_provider"] = "YAHOO_YFINANCE"
                raw["library_version"] = version("yfinance")
                raw["source_url"] = (
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}"
                )
                result[ticker] = raw
            return result
        except Exception as exc:
            error = exc
            if attempt + 1 < attempts:
                sleeper(float(min(2**attempt, 8)))
    raise RuntimeError(f"Yahoo market batch failed after {attempts} attempts: {error}") from error


def _require_columns(frame: pd.DataFrame, fields: Sequence[str]) -> None:
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"Required market columns missing: {sorted(missing)}")


def _row_flags(frame: pd.DataFrame, sessions: set[date]) -> pd.Series:
    flags: list[str] = []
    for values in frame.to_dict("records"):
        problems: list[str] = []
        prices = np.array([values[field] for field in PRICE_FIELDS[:-1]], dtype=float)
        if not np.isfinite(prices).all():
            problems.append("MISSING_OR_NONFINITE_PRICE")
        elif (prices <= 0).any():
            problems.append("NONPOSITIVE_PRICE")
        if np.isfinite(prices[:4]).all() and (
            values["low"] > values["high"]
            or not values["low"] <= values["open"] <= values["high"]
            or not values["low"] <= values["close"] <= values["high"]
        ):
            problems.append("OHLC_INCONSISTENT")
        if not np.isfinite(values["volume"]) or values["volume"] < 0:
            problems.append("INVALID_VOLUME")
        elif values["volume"] == 0:
            problems.append("ZERO_VOLUME")
        if values["trading_date"] not in sessions:
            problems.append("NON_SESSION")
        flags.append("|".join(problems) if problems else "OK")
    return pd.Series(flags, index=frame.index, dtype="string")


def normalize_prices(raw: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Preserve observations and lineage; calculate returns only across adjacent sessions."""
    if not raw:
        raise ValueError("Cannot normalize an empty price collection")
    outputs: list[pd.DataFrame] = []
    for ticker, source in sorted(raw.items()):
        _require_columns(source, ("ticker", "trading_date", *PRICE_FIELDS, *ACTION_FIELDS))
        if source.empty:
            raise ValueError(f"Empty market frame: {ticker}")
        frame = source.copy()
        if not frame["ticker"].eq(ticker).all():
            raise ValueError(f"Raw ticker key disagrees with frame: {ticker}")
        frame["trading_date"] = pd.to_datetime(frame["trading_date"], errors="raise").dt.date
        if frame.duplicated(["ticker", "trading_date"]).any():
            raise ValueError(f"Duplicate market keys: {ticker}")
        monotonic = frame["trading_date"].is_monotonic_increasing
        frame = frame.sort_values("trading_date").reset_index(drop=True)
        for column in (*PRICE_FIELDS, *ACTION_FIELDS):
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
        schedule = session_schedule(frame["trading_date"].min(), frame["trading_date"].max())
        sessions = set(schedule["trading_date"])
        frame["security_id"] = f"US:{ticker}"
        frame["quality_flag"] = _row_flags(frame, sessions)
        if not monotonic:
            frame["quality_flag"] = (
                frame["quality_flag"]
                .map(lambda flag: "NON_MONOTONIC" if flag == "OK" else f"NON_MONOTONIC|{flag}")
                .astype("string")
            )
        frame = frame.merge(schedule[["trading_date", "data_available_at"]], how="left")
        index = pd.Index(schedule["trading_date"], name="trading_date")
        adjusted = frame.set_index("trading_date")["adj_close"].reindex(index)
        adjusted = adjusted.where(np.isfinite(adjusted) & (adjusted > 0))
        log_return = pd.Series(
            np.log(adjusted.to_numpy() / adjusted.shift(1).to_numpy()), index=index
        )
        frame["daily_log_return"] = frame["trading_date"].map(log_return)
        frame["dollar_volume"] = frame["close"] * frame["volume"]
        for column in LINEAGE_FIELDS:
            if column in frame and column == "retrieved_at_utc":
                timestamps = frame[column].map(pd.Timestamp)
                if timestamps.map(lambda value: value.tzinfo is None).any():
                    raise ValueError("Source retrieval timestamps must include a timezone")
                frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
        outputs.append(frame)
    return pd.concat(outputs, ignore_index=True)


def normalize_actions(prices: pd.DataFrame) -> pd.DataFrame:
    """One typed row per dividend/split; preserve source lineage on event rows."""
    _require_columns(prices, ("security_id", "ticker", "trading_date", *ACTION_FIELDS))
    base = ["security_id", "ticker", "trading_date", "data_available_at", "quality_flag"]
    base.extend(column for column in LINEAGE_FIELDS if column in prices)
    events: list[pd.DataFrame] = []
    for field, action_type in (("dividends", "DIVIDEND"), ("stock_splits", "STOCK_SPLIT")):
        mask = prices[field].notna() & prices[field].ne(0)
        event = prices.loc[mask, base].copy()
        event["action_type"] = pd.Series(action_type, index=event.index, dtype="string")
        event["action_value"] = prices.loc[mask, field].astype("float64")
        events.append(event)
    return (
        pd.concat(events, ignore_index=True)
        .sort_values(["ticker", "trading_date", "action_type"])
        .reset_index(drop=True)
    )


def normalize_vix(body: bytes, start: date, end: date) -> pd.DataFrame:
    """Normalize official CSV without filling, interpolation or dropping invalid rows."""
    frame = pd.read_csv(BytesIO(body))
    frame.columns = frame.columns.str.strip().str.upper()
    _require_columns(frame, ("DATE", "OPEN", "HIGH", "LOW", "CLOSE"))
    frame = frame.rename(
        columns={
            "DATE": "trading_date",
            "OPEN": "vix_open",
            "HIGH": "vix_high",
            "LOW": "vix_low",
            "CLOSE": "vix_close",
        }
    )
    frame["trading_date"] = pd.to_datetime(
        frame["trading_date"], format="%m/%d/%Y", errors="raise"
    ).dt.date
    frame = frame.loc[frame["trading_date"].between(start, end)].copy()
    if frame.empty:
        raise ValueError("Cboe VIX CSV has no requested dates")
    if frame["trading_date"].duplicated().any():
        raise ValueError("Duplicate Cboe VIX dates")
    monotonic = frame["trading_date"].is_monotonic_increasing
    frame = frame.sort_values("trading_date").reset_index(drop=True)
    fields = ("vix_open", "vix_high", "vix_low", "vix_close")
    for field in fields:
        frame[field] = pd.to_numeric(frame[field], errors="raise").astype("float64")
    valid = pd.Series(
        np.isfinite(frame.loc[:, list(fields)].to_numpy()).all(axis=1), index=frame.index
    )
    valid &= frame.loc[:, list(fields)].gt(0).all(axis=1)
    valid &= frame["vix_low"].le(frame["vix_high"])
    valid &= frame["vix_open"].between(frame["vix_low"], frame["vix_high"])
    valid &= frame["vix_close"].between(frame["vix_low"], frame["vix_high"])
    frame["quality_flag"] = pd.Series(np.where(valid, "OK", "INVALID_VIX"), dtype="string")
    if not monotonic:
        frame["quality_flag"] = frame["quality_flag"].replace("OK", "NON_MONOTONIC")
    frame["source_provider"] = "CBOE"
    frame["source_url"] = VIX_URL
    # The official daily close is calculated after the equity market close.
    # This is a conservative observation-time proxy, not a claim about when
    # the downloadable historical CSV was published. Previous-session context
    # avoids admitting that same-day value at the equity closing cutoff.
    frame["vix_observed_at_utc"] = (
        pd.to_datetime(frame["trading_date"].astype(str) + " 16:16:00")
        .dt.tz_localize("America/New_York")
        .dt.tz_convert("UTC")
    )
    return frame


def build_market_context(
    prices: pd.DataFrame, vix: pd.DataFrame, sector_etfs: Sequence[str]
) -> pd.DataFrame:
    """Build session/sector context; volatility uses 20 consecutive trailing returns.

    Market/sector volatility is annualized sample standard deviation of log
    returns. VIX uses exactly the prior XNYS session; a missing prior observation
    stays missing. Historical CSV publication timing is an acknowledged proxy.
    """
    _require_columns(prices, ("ticker", "trading_date", "adj_close", "daily_log_return"))
    _require_columns(vix, ("trading_date", "vix_close"))
    if prices.empty or not sector_etfs:
        raise ValueError("Context needs price observations and at least one sector ETF")
    schedule = session_schedule(prices["trading_date"].min(), prices["trading_date"].max())
    if vix["trading_date"].duplicated().any():
        raise ValueError("Duplicate VIX context keys")
    index = pd.Index(schedule["trading_date"], name="trading_date")

    def benchmark(ticker: str, prefix: str) -> pd.DataFrame:
        frame = prices.loc[prices["ticker"].eq(ticker)].copy()
        if frame["trading_date"].duplicated().any():
            raise ValueError(f"Duplicate benchmark dates: {ticker}")
        frame = frame.set_index("trading_date").reindex(index)
        volatility = frame["daily_log_return"].rolling(20, min_periods=20).std() * np.sqrt(252)
        columns = ["adj_close", "daily_log_return"]
        if "quality_flag" in frame:
            columns.append("quality_flag")
        columns.extend(column for column in LINEAGE_FIELDS if column in frame)
        frame = frame.loc[:, columns].rename(
            columns={
                "adj_close": f"{prefix}_adj_close",
                "daily_log_return": f"{prefix}_return",
                "quality_flag": f"{prefix}_quality_flag",
                **{column: f"{prefix}_{column}" for column in LINEAGE_FIELDS},
            }
        )
        frame[f"{'market' if prefix == 'spy' else 'sector'}_realised_vol_20d"] = volatility
        return frame.reset_index()

    spy = benchmark("SPY", "spy")
    vix_columns = ["trading_date", *[str(name) for name in vix if str(name).startswith("vix_")]]
    vix_columns.extend(column for column in LINEAGE_FIELDS if column in vix)
    if "quality_flag" in vix:
        vix_columns.append("quality_flag")
    vix_data = vix.loc[:, vix_columns].rename(
        columns={
            **{column: f"vix_{column}" for column in LINEAGE_FIELDS},
            "quality_flag": "vix_quality_flag",
        }
    )
    vix_data = vix_data.rename(columns={"trading_date": "vix_observation_date"})
    expanded = session_schedule(
        prices["trading_date"].min() - timedelta(days=10), prices["trading_date"].max()
    )
    previous = expanded.set_index("trading_date").index.to_series().shift(1)
    outputs: list[pd.DataFrame] = []
    for ticker in sorted(set(sector_etfs)):
        context = schedule[["trading_date", "data_available_at"]].merge(spy, how="left")
        context = context.merge(benchmark(ticker, "sector"), on="trading_date", how="left")
        context["vix_observation_date"] = context["trading_date"].map(previous)
        context = context.merge(vix_data, on="vix_observation_date", how="left")
        context["vix_context_lag_sessions"] = 1
        context["sector_etf"] = ticker
        context["sector_etf_adj_close"] = context.pop("sector_adj_close")
        for name in ("data_snapshot_id",):
            if name in prices:
                values = prices[name].dropna().unique()
                if len(values) != 1:
                    raise ValueError("Context inputs must belong to one data snapshot")
                context[name] = values[0]
        complete = (
            context[["spy_adj_close", "sector_etf_adj_close", "vix_close"]].notna().all(axis=1)
        )
        context["quality_flag"] = pd.Series(
            np.where(complete, "OK", "MISSING_BENCHMARK"), dtype="string"
        )
        for column in ("spy_quality_flag", "sector_quality_flag", "vix_quality_flag"):
            if column in context:
                warning = context[column].eq("ZERO_VOLUME")
                context.loc[warning & context["quality_flag"].eq("OK"), "quality_flag"] = (
                    "WARNING_BENCHMARK"
                )
                invalid = context[column].notna() & context[column].ne("OK") & ~warning
                context.loc[invalid, "quality_flag"] = "INVALID_BENCHMARK"
        outputs.append(context)
    return pd.concat(outputs, ignore_index=True)


def validate_market(
    prices: pd.DataFrame,
    start: date,
    end: date,
    *,
    expected_tickers: Sequence[str] = (),
    benchmark_tickers: Sequence[str] = (),
    max_source_age_days: int = 30,
    max_missing_session_fraction: float = 0.0,
    as_of: datetime | None = None,
) -> list[dict[str, object]]:
    """Blocking price/calendar/timestamp QA; warnings never modify observations."""
    _require_columns(prices, ("ticker", "trading_date", *PRICE_FIELDS))
    if not 0 <= max_missing_session_fraction <= 1:
        raise ValueError("Missing-session tolerance must be between zero and one")
    schedule = session_schedule(start, end)
    sessions = set(schedule["trading_date"])
    findings: list[dict[str, object]] = []

    def add(check: str, rows: int, message: str, severity: str = "FAIL") -> None:
        if rows:
            findings.append(
                {
                    "dataset": "market.prices_daily",
                    "check": check,
                    "severity": severity,
                    "affected_rows": int(rows),
                    "message": message,
                }
            )

    add(
        "duplicate_keys",
        int(prices.duplicated(["ticker", "trading_date"]).sum()),
        "Ticker/trading_date must be unique",
    )
    numeric = prices.loc[:, list(PRICE_FIELDS)].to_numpy(dtype=float)
    add(
        "finite_prices",
        int((~np.isfinite(numeric[:, :5])).any(axis=1).sum()),
        "OHLC and adjusted closes must be present and finite",
    )
    add(
        "positive_prices",
        int((numeric[:, :5] <= 0).any(axis=1).sum()),
        "OHLC and adjusted closes must be positive",
    )
    impossible = prices["low"].gt(prices["high"])
    impossible |= ~prices["open"].between(prices["low"], prices["high"])
    impossible |= ~prices["close"].between(prices["low"], prices["high"])
    add("ohlc_consistency", int(impossible.sum()), "OHLC prices violate their daily range")
    add(
        "valid_volume",
        int((~np.isfinite(numeric[:, 5]) | (numeric[:, 5] < 0)).sum()),
        "Volume must be finite and nonnegative",
    )
    add("zero_volume", int(prices["volume"].eq(0).sum()), "Zero volume needs review", "WARN")
    for column in ACTION_FIELDS:
        if column in prices:
            actions = prices[column].to_numpy(dtype=float)
            add(
                "valid_corporate_actions",
                int((~np.isfinite(actions) | (actions < 0)).sum()),
                f"{column} must be finite and nonnegative",
            )
    add(
        "calendar_alignment",
        int((~prices["trading_date"].isin(sessions)).sum()),
        "Market rows must be XNYS sessions within requested bounds",
    )
    tickers = tuple(expected_tickers) or tuple(str(ticker) for ticker in prices["ticker"].unique())
    for ticker in tickers:
        frame = prices.loc[prices["ticker"].eq(ticker)]
        missing = len(sessions - set(frame["trading_date"]))
        severity = "FAIL" if missing > len(sessions) * max_missing_session_fraction else "WARN"
        add(
            "missing_sessions",
            missing,
            f"{ticker} is missing requested sessions; no prices were filled",
            severity,
        )
        if not frame["trading_date"].is_monotonic_increasing or (
            "quality_flag" in frame and frame["quality_flag"].str.contains("NON_MONOTONIC").any()
        ):
            add("monotonic_dates", len(frame), f"{ticker} source dates must increase")
        if all(column in frame for column in ACTION_FIELDS):
            ordered = frame.sort_values("trading_date")
            raw_jump = (ordered["close"] / ordered["close"].shift(1) - 1).abs().gt(0.4)
            action_recorded = ordered["dividends"].gt(0) | ordered["stock_splits"].gt(0)
            add(
                "unexplained_price_jump",
                int((raw_jump & ~action_recorded).sum()),
                f"{ticker} raw close moved over 40% without a split/dividend; review vendor data",
                "WARN",
            )
    for ticker in benchmark_tickers:
        frame = prices.loc[prices["ticker"].eq(ticker)]
        add(
            "benchmark_alignment",
            len(sessions - set(frame["trading_date"])),
            f"Required benchmark {ticker} lacks full session coverage",
        )
    if "data_available_at" in prices:
        closes = schedule.set_index("trading_date")["data_available_at"]
        expected = prices["trading_date"].map(closes)
        actual = pd.to_datetime(prices["data_available_at"], utc=True, errors="coerce")
        add(
            "market_timestamp",
            int((actual.isna() | actual.ne(expected)).sum()),
            "Market availability must equal the actual UTC XNYS close",
        )
    if "retrieved_at_utc" in prices:
        retrieved = pd.to_datetime(prices["retrieved_at_utc"], utc=True, errors="coerce")
        now = pd.Timestamp(as_of or datetime.now(UTC))
        add(
            "retrieval_timestamp",
            int((retrieved.isna() | (retrieved > now)).sum()),
            "Source retrieval timestamps must be valid and not in the future",
        )
        stale = retrieved < now - pd.Timedelta(days=max_source_age_days)
        add(
            "source_freshness",
            int(stale.sum()),
            "Frozen snapshot retrieval is older than the freshness threshold",
            "WARN",
        )
    return findings


def validate_market_context(context: pd.DataFrame) -> list[dict[str, object]]:
    """Check context keys and the equity-close cutoff, including lagged VIX."""
    _require_columns(
        context,
        (
            "trading_date",
            "sector_etf",
            "data_available_at",
            "spy_adj_close",
            "sector_etf_adj_close",
            "vix_close",
            "vix_observation_date",
        ),
    )
    findings: list[dict[str, object]] = []

    def add(check: str, rows: int, message: str, severity: str = "FAIL") -> None:
        if rows:
            findings.append(
                {
                    "dataset": "market.market_context_daily",
                    "check": check,
                    "severity": severity,
                    "affected_rows": int(rows),
                    "message": message,
                }
            )

    add(
        "duplicate_keys",
        int(context.duplicated(["trading_date", "sector_etf"]).sum()),
        "Context session/sector ETF keys must be unique",
    )
    if context.empty:
        add("empty_context", 1, "Market context must contain rows")
        return findings
    if "quality_flag" in context:
        add(
            "invalid_benchmark",
            int(context["quality_flag"].eq("INVALID_BENCHMARK").sum()),
            "Context references invalid market or VIX observations",
        )
        add(
            "warning_benchmark",
            int(context["quality_flag"].eq("WARNING_BENCHMARK").sum()),
            "Context references a benchmark observation with a nonblocking volume warning",
            "WARN",
        )
    schedule = session_schedule(context["trading_date"].min(), context["trading_date"].max())
    expected = context["trading_date"].map(schedule.set_index("trading_date")["data_available_at"])
    cutoff = pd.to_datetime(context["data_available_at"], utc=True, errors="coerce")
    add(
        "context_timestamp",
        int((cutoff.isna() | cutoff.ne(expected)).sum()),
        "Context timestamp must be the actual equity session close",
    )
    if "vix_observed_at_utc" in context:
        observed = pd.to_datetime(context["vix_observed_at_utc"], utc=True, errors="coerce")
        add(
            "vix_cutoff",
            int((context["vix_close"].notna() & (observed.isna() | observed.gt(cutoff))).sum()),
            "VIX observation must precede the context cutoff",
        )
    else:
        add(
            "vix_cutoff",
            int(context["vix_close"].notna().sum()),
            "Nonmissing VIX observations require an explicit observation timestamp",
        )
    expanded = session_schedule(
        context["trading_date"].min() - timedelta(days=10), context["trading_date"].max()
    )
    previous = expanded.set_index("trading_date").index.to_series().shift(1)
    expected_previous = context["trading_date"].map(previous)
    add(
        "vix_lag",
        int(
            (
                context["vix_close"].notna() & context["vix_observation_date"].ne(expected_previous)
            ).sum()
        ),
        "VIX context must use exactly the previous XNYS session observation",
    )
    for column in ("spy_adj_close", "sector_etf_adj_close", "vix_close"):
        add(
            "missing_benchmark",
            int(context[column].isna().sum()),
            f"Context lacks {column}; missing values must remain explicit",
            "WARN",
        )
    return findings


def validate_vix(vix: pd.DataFrame, start: date, end: date) -> list[dict[str, object]]:
    """Official VIX OHLC/date QA with its calendar distinct from equity sessions.

    Official weekday observations on equity holidays remain in the source and
    are reported for review. Equity context still joins exactly the prior XNYS
    session, so these observations cannot replace an equity-session VIX value.
    """
    fields = ["vix_open", "vix_high", "vix_low", "vix_close"]
    _require_columns(vix, ("trading_date", *fields))
    findings: list[dict[str, object]] = []

    def add(check: str, rows: int, message: str, severity: str = "FAIL") -> None:
        if rows:
            findings.append(
                {
                    "dataset": "market.vix_daily",
                    "check": check,
                    "severity": severity,
                    "affected_rows": int(rows),
                    "message": message,
                }
            )

    values = vix.loc[:, fields].to_numpy(dtype=float)
    add(
        "vix_price_validity",
        int((~np.isfinite(values) | (values <= 0)).any(axis=1).sum()),
        "VIX OHLC must be present, finite and positive",
    )
    impossible = vix["vix_low"].gt(vix["vix_high"])
    impossible |= ~vix["vix_open"].between(vix["vix_low"], vix["vix_high"])
    impossible |= ~vix["vix_close"].between(vix["vix_low"], vix["vix_high"])
    add("vix_ohlc_consistency", int(impossible.sum()), "VIX OHLC range is inconsistent")
    add("duplicate_keys", int(vix["trading_date"].duplicated().sum()), "VIX dates must be unique")
    schedule = session_schedule(start, end)
    sessions = set(schedule["trading_date"])
    in_bounds = vix["trading_date"].between(start, end)
    weekend = vix["trading_date"].map(lambda value: value.weekday() >= 5)
    add(
        "calendar_alignment",
        int((~in_bounds | weekend).sum()),
        "VIX rows must be weekdays within requested date bounds",
    )
    add(
        "non_equity_session",
        int((in_bounds & ~weekend & ~vix["trading_date"].isin(sessions)).sum()),
        "Official VIX weekday observations outside XNYS are retained in raw and excluded "
        "from equity context",
        "WARN",
    )
    add(
        "missing_sessions",
        len(sessions - set(vix["trading_date"])),
        "VIX requested session coverage is incomplete; values remain missing",
        "WARN",
    )
    if "quality_flag" in vix:
        add(
            "monotonic_dates",
            int(vix["quality_flag"].str.contains("NON_MONOTONIC").sum()),
            "VIX source dates must increase",
        )
    return findings
