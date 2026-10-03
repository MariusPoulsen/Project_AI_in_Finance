from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from structural_break.data.market import (
    build_market_context,
    download_market,
    normalize_actions,
    normalize_prices,
    normalize_vix,
    session_schedule,
    validate_market,
    validate_market_context,
    validate_vix,
)


def raw_prices(ticker, dates, closes=None):
    closes = np.asarray(closes if closes is not None else np.arange(len(dates)) + 100, dtype=float)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "trading_date": dates,
            "open": closes,
            "high": closes + 1,
            "low": closes - 1,
            "close": closes,
            "adj_close": closes,
            "volume": 1000.0,
            "dividends": 0.0,
            "stock_splits": 0.0,
            "source_snapshot_id": "yahoo_fixture",
            "data_snapshot_id": "snap_fixture",
            "raw_file_path": f"data/raw/yahoo/prices/{ticker}/fixture.parquet",
            "sha256": "a" * 64,
            "source_url": f"https://example.invalid/{ticker}",
            "retrieved_at_utc": datetime(2026, 10, 1, tzinfo=UTC),
            "source_provider": "YAHOO_YFINANCE",
            "library_version": "fixture",
        }
    )


def yahoo_batch(tickers, dates):
    frames = {}
    for ticker in tickers:
        frame = raw_prices(ticker, dates)
        frame = frame.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "adj_close": "Adj Close",
                "volume": "Volume",
                "dividends": "Dividends",
                "stock_splits": "Stock Splits",
            }
        )
        frame = frame[
            ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
        ]
        frame.index = pd.DatetimeIndex(dates)
        frames[ticker] = frame
    return pd.concat(frames, axis=1)


def test_yahoo_contract_keeps_raw_fields_and_inclusive_end():
    calls = []
    dates = [date(2023, 11, 22), date(2023, 11, 24)]

    def download(tickers, **kwargs):
        calls.append((tickers, kwargs))
        return yahoo_batch(tickers, dates)

    result = download_market(("KO", "SPY"), dates[0], dates[-1], downloader=download)
    tickers, kwargs = calls[0]
    assert tickers == ["KO", "SPY"]
    assert kwargs["start"] == "2023-11-22"
    assert kwargs["end"] == "2023-11-25"
    assert kwargs["auto_adjust"] is False
    assert kwargs["actions"] is True
    assert kwargs["repair"] is False
    assert kwargs["prepost"] is False
    assert kwargs["threads"] is False
    assert kwargs["interval"] == "1d"
    assert kwargs["keepna"] is True
    assert result["KO"]["trading_date"].tolist() == dates
    assert result["KO"]["retrieved_at_utc"].dt.tz == UTC
    assert result["SPY"]["library_version"].notna().all()
    assert "stock_splits" in result["KO"]


def test_yahoo_retries_silent_partial_batch_and_never_returns_empty_symbol():
    calls = []

    def download(tickers, **kwargs):
        calls.append(kwargs)
        return yahoo_batch(["KO"], [date(2023, 11, 22)])

    with pytest.raises(RuntimeError, match="after 2 attempts"):
        download_market(
            ("KO", "SPY"),
            date(2023, 11, 22),
            date(2023, 11, 24),
            downloader=download,
            attempts=2,
            sleeper=lambda seconds: None,
        )
    assert len(calls) == 2


def test_yahoo_field_first_columns_and_local_date():
    dates = [date(2023, 11, 22)]
    frame = yahoo_batch(["KO", "SPY"], dates).swaplevel(0, 1, axis=1)
    frame.index = frame.index.tz_localize("America/New_York")
    result = download_market(
        ("KO", "SPY"), dates[0], dates[0], downloader=lambda *args, **kwargs: frame
    )
    assert result["KO"]["trading_date"].tolist() == dates


def test_calendar_holidays_half_days_and_dst_are_actual_utc_closes():
    schedule = session_schedule(date(2023, 11, 22), date(2023, 11, 27))
    assert schedule["trading_date"].tolist() == [
        date(2023, 11, 22),
        date(2023, 11, 24),
        date(2023, 11, 27),
    ]
    assert schedule.loc[1, "data_available_at"] == pd.Timestamp("2023-11-24T18:00:00Z")
    assert session_schedule(date(2023, 7, 3), date(2023, 7, 3)).iloc[0][
        "data_available_at"
    ] == pd.Timestamp("2023-07-03T17:00:00Z")


def test_missing_session_breaks_return_without_filling_prices():
    dates = [date(2023, 11, 20), date(2023, 11, 22), date(2023, 11, 24)]
    prices = normalize_prices({"KO": raw_prices("KO", dates, [100, 110, 121])})
    assert len(prices) == 3
    assert date(2023, 11, 21) not in set(prices["trading_date"])
    assert prices["daily_log_return"].isna().tolist() == [True, True, False]
    assert prices.loc[2, "daily_log_return"] == pytest.approx(np.log(1.1))
    assert prices.loc[2, "dollar_volume"] == 121000
    assert prices["sha256"].eq("a" * 64).all()
    findings = validate_market(prices, date(2023, 11, 20), date(2023, 11, 24))
    assert [row["affected_rows"] for row in findings if row["check"] == "missing_sessions"] == [1]


def test_nan_or_nonpositive_adjusted_prices_never_create_infinite_returns():
    dates = session_schedule(date(2023, 11, 20), date(2023, 11, 27))["trading_date"]
    frame = raw_prices("KO", dates, [100, 101, 102, 103, 104])
    frame.loc[1, "adj_close"] = np.nan
    frame.loc[3, "adj_close"] = 0
    prices = normalize_prices({"KO": frame})
    assert prices["daily_log_return"].isna().all()
    assert "MISSING_OR_NONFINITE_PRICE" in prices.loc[1, "quality_flag"]
    assert "NONPOSITIVE_PRICE" in prices.loc[3, "quality_flag"]


def test_duplicates_rejected_and_input_order_reviewed():
    dates = [date(2023, 11, 21), date(2023, 11, 20)]
    raw = raw_prices("KO", dates)
    prices = normalize_prices({"KO": raw})
    assert prices["trading_date"].tolist() == sorted(dates)
    assert prices["quality_flag"].eq("NON_MONOTONIC").all()
    assert "monotonic_dates" in {
        f["check"] for f in validate_market(prices, date(2023, 11, 20), date(2023, 11, 21))
    }
    with pytest.raises(ValueError, match="Duplicate market keys"):
        normalize_prices({"KO": pd.concat([raw, raw.iloc[:1]])})


def test_actions_are_event_rows_and_empty_frame_remains_typed():
    frame = raw_prices("KO", [date(2023, 11, 20), date(2023, 11, 21)])
    empty = normalize_actions(normalize_prices({"KO": frame}))
    assert empty.empty
    assert str(empty["action_type"].dtype) == "string"
    assert str(empty["action_value"].dtype) == "float64"
    assert str(empty["data_available_at"].dtype) == "datetime64[ns, UTC]"
    frame.loc[1, "dividends"] = 0.25
    frame.loc[1, "stock_splits"] = 2
    actions = normalize_actions(normalize_prices({"KO": frame}))
    assert actions["action_type"].tolist() == ["DIVIDEND", "STOCK_SPLIT"]
    assert actions["action_value"].tolist() == [0.25, 2.0]
    assert actions["raw_file_path"].eq(frame.iloc[0]["raw_file_path"]).all()


def test_naive_source_timestamp_is_rejected_without_guessing_its_timezone():
    frame = raw_prices("KO", [date(2023, 11, 20)])
    frame["retrieved_at_utc"] = datetime(2026, 10, 1)
    with pytest.raises(ValueError, match="must include a timezone"):
        normalize_prices({"KO": frame})


def test_unexplained_price_jump_is_reviewed_and_recorded_split_is_auditable():
    dates = [date(2023, 11, 20), date(2023, 11, 21)]
    frame = raw_prices("KO", dates, [100, 50])
    findings = validate_market(normalize_prices({"KO": frame}), dates[0], dates[-1])
    assert "unexplained_price_jump" in {row["check"] for row in findings}
    frame.loc[1, "stock_splits"] = 2
    findings = validate_market(normalize_prices({"KO": frame}), dates[0], dates[-1])
    assert "unexplained_price_jump" not in {row["check"] for row in findings}


def test_vix_preserves_invalid_values_missing_dates_and_source():
    body = (
        b"DATE,OPEN,HIGH,LOW,CLOSE\n"
        b"11/20/2023,13,14,12,13.5\n11/22/2023,14,15,13,14.5\n"
        b"11/24/2023,13,14,12,0\n"
    )
    vix = normalize_vix(body, date(2023, 11, 20), date(2023, 11, 24))
    assert len(vix) == 3
    assert date(2023, 11, 21) not in set(vix["trading_date"])
    assert vix.iloc[-1]["vix_close"] == 0
    assert vix.iloc[-1]["quality_flag"] == "INVALID_VIX"
    assert vix.iloc[0]["vix_observed_at_utc"] == pd.Timestamp("2023-11-20T21:16:00Z")
    assert vix["source_provider"].eq("CBOE").all()
    findings = validate_vix(vix, date(2023, 11, 20), date(2023, 11, 24))
    assert "vix_price_validity" in {row["check"] for row in findings}
    assert "missing_sessions" in {row["check"] for row in findings}


def test_context_uses_exact_previous_session_vix_and_never_fills_gap():
    dates = session_schedule(date(2023, 11, 20), date(2023, 11, 27))["trading_date"]
    prices = normalize_prices({ticker: raw_prices(ticker, dates) for ticker in ["SPY", "XLP"]})
    vix = normalize_vix(
        b"DATE,OPEN,HIGH,LOW,CLOSE\n11/20/2023,13,14,12,13.5\n"
        b"11/22/2023,14,15,13,14.5\n11/24/2023,15,16,14,15.5\n",
        date(2023, 11, 20),
        date(2023, 11, 27),
    )
    vix["source_snapshot_id"] = "cboe_fixture"
    vix["sha256"] = "b" * 64
    context = build_market_context(prices, vix, ["XLP"])
    assert context["vix_close"].isna().tolist() == [True, False, True, False, False]
    assert context.iloc[3]["vix_close"] == 14.5  # Friday uses Wednesday across holiday.
    assert context.iloc[3]["vix_observation_date"] == date(2023, 11, 22)
    assert context.iloc[3]["spy_sha256"] == "a" * 64
    assert context.iloc[3]["sector_sha256"] == "a" * 64
    assert context.iloc[3]["vix_sha256"] == "b" * 64
    assert context["market_realised_vol_20d"].isna().all()
    assert not [f for f in validate_market_context(context) if f["severity"] == "FAIL"]


@pytest.mark.parametrize("values", ["20,15,13,14", "14,12,13,14", "14,15,13,20"])
def test_vix_impossible_ohlc_ranges_are_blocking(values):
    vix = normalize_vix(
        f"DATE,OPEN,HIGH,LOW,CLOSE\n11/20/2023,{values}\n".encode(),
        date(2023, 11, 20),
        date(2023, 11, 20),
    )
    assert vix.iloc[0]["quality_flag"] == "INVALID_VIX"
    findings = validate_vix(vix, date(2023, 11, 20), date(2023, 11, 20))
    assert any(f["check"] == "vix_ohlc_consistency" and f["severity"] == "FAIL" for f in findings)


def test_duplicate_vix_dates_are_rejected_without_silent_deduplication():
    body = b"DATE,OPEN,HIGH,LOW,CLOSE\n11/20/2023,14,15,13,14\n11/20/2023,15,16,14,15\n"
    with pytest.raises(ValueError, match="Duplicate Cboe VIX dates"):
        normalize_vix(body, date(2023, 11, 20), date(2023, 11, 20))


def test_context_quality_rejects_stale_vix_and_missing_observation_timestamp():
    dates = [date(2023, 11, 20), date(2023, 11, 21), date(2023, 11, 22)]
    prices = normalize_prices({ticker: raw_prices(ticker, dates) for ticker in ["SPY", "XLP"]})
    vix = normalize_vix(
        b"DATE,OPEN,HIGH,LOW,CLOSE\n11/20/2023,13,14,12,13.5\n11/21/2023,14,15,13,14.5\n",
        dates[0],
        dates[-1],
    )
    context = build_market_context(prices, vix, ["XLP"])
    context.loc[2, "vix_observation_date"] = date(2023, 11, 20)
    findings = validate_market_context(context)
    assert any(f["check"] == "vix_lag" and f["severity"] == "FAIL" for f in findings)
    context = context.drop(columns="vix_observed_at_utc")
    findings = validate_market_context(context)
    assert any(f["check"] == "vix_cutoff" and f["severity"] == "FAIL" for f in findings)


def test_zero_volume_benchmark_warns_without_upgrading_valid_prices_to_failure():
    dates = [date(2023, 11, 20), date(2023, 11, 21)]
    raw = {ticker: raw_prices(ticker, dates) for ticker in ["SPY", "XLP"]}
    raw["SPY"].loc[1, "volume"] = 0
    prices = normalize_prices(raw)
    vix = normalize_vix(
        b"DATE,OPEN,HIGH,LOW,CLOSE\n11/20/2023,13,14,12,13.5\n", dates[0], dates[-1]
    )
    context = build_market_context(prices, vix, ["XLP"])
    assert context.loc[1, "quality_flag"] == "WARNING_BENCHMARK"
    findings = validate_market_context(context)
    assert not any(f["severity"] == "FAIL" for f in findings)
    assert any(f["check"] == "warning_benchmark" and f["severity"] == "WARN" for f in findings)


def test_nonmonotonic_dates_are_flagged_even_when_every_row_has_volume_warning():
    dates = [date(2023, 11, 21), date(2023, 11, 20)]
    frame = raw_prices("KO", dates)
    frame["volume"] = 0
    prices = normalize_prices({"KO": frame})
    findings = validate_market(prices, min(dates), max(dates))
    assert any(f["check"] == "monotonic_dates" and f["severity"] == "FAIL" for f in findings)


def test_volatility_is_trailing_and_missing_return_restarts_twenty_session_window():
    dates = session_schedule(date(2023, 1, 3), date(2023, 3, 31))["trading_date"]
    close = 100 * np.exp(np.cumsum(np.sin(np.arange(len(dates))) / 100))
    raw = {ticker: raw_prices(ticker, dates, close) for ticker in ["SPY", "XLP"]}
    vix = pd.DataFrame({"trading_date": dates, "vix_close": 20.0})
    original = build_market_context(normalize_prices(raw), vix, ["XLP"])
    assert original["market_realised_vol_20d"].iloc[:20].isna().all()
    assert pd.notna(original["market_realised_vol_20d"].iloc[20])
    raw["SPY"].loc[30:, ["open", "high", "low", "close", "adj_close"]] *= 2
    changed = build_market_context(normalize_prices(raw), vix, ["XLP"])
    pd.testing.assert_series_equal(
        original["market_realised_vol_20d"].iloc[:30], changed["market_realised_vol_20d"].iloc[:30]
    )
    raw["SPY"] = raw["SPY"].drop(index=25)
    gaps = build_market_context(normalize_prices(raw), vix, ["XLP"])
    assert gaps["market_realised_vol_20d"].iloc[25:46].isna().all()
    assert pd.notna(gaps["market_realised_vol_20d"].iloc[46])


def test_quality_reports_duplicate_prices_calendar_volume_and_timestamp_errors():
    dates = [date(2023, 11, 20), date(2023, 11, 21)]
    prices = normalize_prices({"KO": raw_prices("KO", dates)})
    prices = pd.concat([prices, prices.iloc[:1]], ignore_index=True)
    prices.loc[0, "open"] = -1
    prices.loc[0, "volume"] = -1
    prices.loc[1, "trading_date"] = date(2023, 11, 23)
    prices.loc[1, "data_available_at"] = pd.Timestamp("2023-11-23T21:00:00Z")
    prices.loc[0, "retrieved_at_utc"] = pd.Timestamp("2030-01-01T00:00:00Z")
    findings = validate_market(
        prices,
        dates[0],
        dates[-1],
        expected_tickers=["KO"],
        benchmark_tickers=["SPY"],
        as_of=datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert {
        "duplicate_keys",
        "positive_prices",
        "ohlc_consistency",
        "valid_volume",
        "calendar_alignment",
        "missing_sessions",
        "benchmark_alignment",
        "market_timestamp",
        "retrieval_timestamp",
    }.issubset({f["check"] for f in findings})
