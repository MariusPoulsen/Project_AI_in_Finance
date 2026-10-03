"""Explicit synthetic public-source fixtures for the real offline ingestion job."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from structural_break.data.http import FetchedResponse
from structural_break.data.market import VIX_URL, YAHOO_FIELDS
from structural_break.data.sec import COMPANY_TICKERS_URL, SUBMISSIONS_BASE_URL


class FixtureSources:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        descriptor = json.loads((directory / "fixture.json").read_bytes())
        if descriptor["synthetic"] is not True:
            raise ValueError("Offline source fixture must explicitly identify itself as synthetic")
        self.start = date.fromisoformat(descriptor["start"])
        self.end = date.fromisoformat(descriptor["end"])
        self.retrieved_at = datetime.fromisoformat(descriptor["retrieved_at_utc"])
        self.submissions = json.loads((directory / "sec_submissions.json").read_bytes())

    def get(self, url: str) -> FetchedResponse:
        if url == COMPANY_TICKERS_URL:
            body = (self.directory / "company_tickers.json").read_bytes()
        elif url == VIX_URL:
            body = (self.directory / "vix.csv").read_bytes()
        elif url.startswith(SUBMISSIONS_BASE_URL):
            filename = urlparse(url).path.rsplit("/", 1)[-1]
            body = json.dumps(self.submissions[filename], sort_keys=True).encode()
        else:
            raise ValueError("Fixture request attempted a source absent from its frozen inventory")
        return FetchedResponse(body, url, 200, self.retrieved_at)

    def download(self, tickers: list[str], **kwargs: Any) -> pd.DataFrame:
        if (
            kwargs["start"] != self.start.isoformat()
            or not kwargs["actions"]
            or kwargs["auto_adjust"]
            or kwargs["repair"]
        ):
            raise ValueError("Fixture received a changed research retrieval contract")
        prices = pd.read_csv(self.directory / "market.csv", parse_dates=["trading_date"])
        frames = []
        reverse = {value: key for key, value in YAHOO_FIELDS.items()}
        for ticker in tickers:
            selected = prices.loc[prices["ticker"].eq(ticker)].set_index("trading_date")
            if selected.empty:
                raise ValueError("Requested symbol is absent from market fixture")
            selected = selected[list(reverse)].rename(columns=reverse)
            selected.columns = pd.MultiIndex.from_product([[ticker], selected.columns])
            frames.append(selected)
        return pd.concat(frames, axis=1)
