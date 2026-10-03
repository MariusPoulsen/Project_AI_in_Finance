"""Governed reference data from the fixed universe and an official SEC snapshot.

The project classifications are explicitly versioned research assumptions. They
are not a reconstructed historical GICS or listing-membership database. Unknown
lifecycle dates remain null; market-data coverage is checked by the ingestion job.
"""

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

import pandas as pd
import yaml
from pydantic import Field, model_validator

from structural_break.config.loader import UniqueKeyLoader
from structural_break.config.models import ProjectConfig, SettingsModel, Version

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
Ticker = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9.-]*$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class SecurityMetadata(SettingsModel):
    ticker: Ticker
    exchange: Literal["NYSE", "NASDAQ"]
    sector: NonEmpty
    sub_industry: NonEmpty
    sector_etf: Ticker
    active_from: date | None
    active_to: date | None
    domestic_sec_issuer: Literal[True]
    manual_review_status: Literal["APPROVED", "REJECTED"]
    notes: str = ""
    audit_source: str | None = None

    @model_validator(mode="after")
    def chronological_lifecycle(self) -> Self:
        if self.active_from and self.active_to and self.active_from > self.active_to:
            raise ValueError("Security active_from must not follow active_to")
        return self


class ReferenceMetadata(SettingsModel):
    version: Version
    universe_version: Version
    reviewed_at: datetime
    review_basis: NonEmpty
    classification_policy: Literal["static_project_research_classification"]
    classification_sources: tuple[NonEmpty, ...] = Field(min_length=1)
    sector_etfs: dict[NonEmpty, Ticker] = Field(min_length=1)
    securities: tuple[SecurityMetadata, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def reviewed_and_unique(self) -> Self:
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("Reference reviewed_at must include a timezone")
        tickers = [security.ticker for security in self.securities]
        if len(tickers) != len(set(tickers)):
            raise ValueError("Duplicate ticker in governed reference metadata")
        for security in self.securities:
            if self.sector_etfs.get(security.sector) != security.sector_etf:
                raise ValueError(f"Sector ETF mismatch for {security.ticker}")
        return self


def _load_metadata(config: ProjectConfig, metadata_path: Path) -> ReferenceMetadata:
    payload = yaml.load(metadata_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    metadata = ReferenceMetadata.model_validate(payload)
    if metadata.universe_version != config.universe.version:
        raise ValueError("Reference universe_version differs from configured pair universe")
    expected = {ticker for pair in config.universe.pairs for ticker in (pair.leg_a, pair.leg_b)}
    actual = {security.ticker for security in metadata.securities}
    if actual != expected:
        raise ValueError(
            f"Reference ticker coverage mismatch: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    rejected = [s.ticker for s in metadata.securities if s.manual_review_status != "APPROVED"]
    if rejected:
        raise ValueError(f"Reference tickers have not been approved: {sorted(rejected)}")
    by_ticker = {security.ticker: security for security in metadata.securities}
    for pair in config.universe.pairs:
        left, right = by_ticker[pair.leg_a], by_ticker[pair.leg_b]
        if (left.sector, left.sub_industry) != (right.sector, right.sub_industry):
            raise ValueError(f"Pair {pair.pair_id} has inconsistent economic metadata")
        if left.sub_industry != pair.peer_group:
            raise ValueError(f"Pair {pair.pair_id} differs from the approved peer group")
    return metadata


def required_tickers(config: ProjectConfig, metadata_path: Path) -> tuple[str, ...]:
    """Return governed equities plus SPY and the sector benchmarks actually used."""
    metadata = _load_metadata(config, metadata_path)
    return tuple(
        sorted(
            {security.ticker for security in metadata.securities}
            | {security.sector_etf for security in metadata.securities}
            | {"SPY"}
        )
    )


def _sec_identities(
    ticker_map: Mapping[str, object], requested: set[str]
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for record in ticker_map.values():
        if not isinstance(record, Mapping):
            raise ValueError("SEC ticker snapshot must contain mapping records")
        ticker = record.get("ticker")
        if not isinstance(ticker, str) or ticker not in requested:
            continue
        if ticker in result:
            raise ValueError(f"Ambiguous SEC ticker mapping for {ticker}")
        cik_value = record.get("cik_str")
        if isinstance(cik_value, bool) or not isinstance(cik_value, (str, int)):
            raise ValueError(f"Invalid SEC CIK for {ticker}")
        cik = str(cik_value)
        if not re.fullmatch(r"\d{1,10}", cik) or int(cik) <= 0:
            raise ValueError(f"Invalid SEC CIK for {ticker}")
        title = record.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Missing SEC issuer title for {ticker}")
        result[ticker] = (cik.zfill(10), title.strip())
    missing = requested - result.keys()
    if missing:
        raise ValueError(f"Missing exact SEC ticker mapping: {sorted(missing)}")
    # Distinct equity identities in this universe must not silently collapse.
    ciks = [identity[0] for identity in result.values()]
    if len(ciks) != len(set(ciks)):
        raise ValueError("Ambiguous SEC CIK shared by governed equity tickers")
    return result


def build_reference(
    config: ProjectConfig,
    metadata_path: Path,
    ticker_map: Mapping[str, object],
    *,
    source_snapshot_id: str,
    data_snapshot_id: str,
    raw_file_path: str,
    sha256: str,
    retrieved_at: datetime,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build security master, oriented pair universe and used-sector benchmark map.

    Only the fixed reviewed equity universe receives SEC issuer identities. ETFs
    are market benchmarks and are deliberately excluded from security_master.
    Mapping failures require reconciliation instead of heuristic issuer matching.
    """
    metadata = _load_metadata(config, metadata_path)
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone")
    if not all((source_snapshot_id, data_snapshot_id, raw_file_path)):
        raise ValueError("Reference snapshot identities and raw path are required")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Reference raw source requires a SHA-256 hex digest")
    by_ticker = {security.ticker: security for security in metadata.securities}
    identities = _sec_identities(ticker_map, set(by_ticker))
    reviewed_at = metadata.reviewed_at.astimezone(UTC)
    lineage: dict[str, object] = {
        "source": "sec",
        "source_url": SEC_TICKER_URL,
        "source_snapshot_id": source_snapshot_id,
        "data_snapshot_id": data_snapshot_id,
        "raw_file_path": raw_file_path,
        "sha256": sha256,
        "retrieved_at": retrieved_at.astimezone(UTC),
        "reference_version": metadata.version,
        "reference_file_path": f"configs/{metadata_path.name}",
        "reference_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        "reviewed_at": reviewed_at,
        "review_basis": metadata.review_basis,
        "classification_policy": metadata.classification_policy,
    }
    security_rows: list[dict[str, object]] = []
    for ticker, security in sorted(by_ticker.items()):
        cik, issuer_name = identities[ticker]
        security_rows.append(
            {
                **security.model_dump(),
                "security_id": f"US:{ticker}",
                "cik": cik,
                "name": issuer_name,
                "issuer_name": issuer_name,
                "lifecycle_status": "KNOWN" if security.active_from else "UNKNOWN",
                **lineage,
            }
        )
    pair_rows: list[dict[str, object]] = []
    for pair in config.universe.pairs:
        security = by_ticker[pair.leg_a]
        pair_rows.append(
            {
                "pair_id": pair.pair_id,
                "leg_a": pair.leg_a,
                "leg_b": pair.leg_b,
                "leg_a_security_id": f"US:{pair.leg_a}",
                "leg_b_security_id": f"US:{pair.leg_b}",
                "sector": security.sector,
                "sub_industry": security.sub_industry,
                "sector_etf": security.sector_etf,
                "peer_group": pair.peer_group,
                "economic_rationale": f"Both issuers are reviewed peers in {pair.peer_group}.",
                "enabled": True,
                "orientation": config.universe.orientation,
                "pair_version": config.universe.version,
                "manual_review_status": "APPROVED",
                "created_at": reviewed_at,
                "notes": "Fixed orientation and inclusion from canonical project decisions.",
                **lineage,
            }
        )
    used_sectors = sorted({security.sector for security in metadata.securities})
    sector_rows = [
        {
            "sector": sector,
            "sector_etf": metadata.sector_etfs[sector],
            "manual_review_status": "APPROVED",
            **lineage,
        }
        for sector in used_sectors
    ]
    return pd.DataFrame(security_rows), pd.DataFrame(pair_rows), pd.DataFrame(sector_rows)
