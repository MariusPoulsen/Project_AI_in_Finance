"""Outcome-blind economic-peer source freeze for the separate research-v2 study.

The roster is explicitly a current-survivor prototype. Current issuer mappings
and business classifications are not historical membership or delisting data.
No market returns, event labels or model scores are accepted by this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from io import BytesIO
from itertools import combinations
from pathlib import Path
from typing import Any, Literal, Self

import pandas as pd
import yaml
from pydantic import Field, model_validator

from structural_break.config.loader import UniqueKeyLoader
from structural_break.config.models import Pair, ProjectConfig, SettingsModel, Version
from structural_break.config.paths import confined_path
from structural_break.data.sec import normalize_cik
from structural_break.pairs.reference import Ticker
from structural_break.storage.files import sha256_file, write_bytes

SECTORS = {
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLK": "Information Technology",
    "XLU": "Utilities",
    "XLC": "Communication Services",
    "XLB": "Materials",
}


class BusinessPeerGroup(SettingsModel):
    name: str = Field(min_length=1)
    sector_etf: Ticker
    tickers: tuple[Ticker, ...] = Field(min_length=2)
    rationale: str = Field(min_length=10)

    @model_validator(mode="after")
    def valid_group(self) -> Self:
        if self.sector_etf not in SECTORS:
            raise ValueError("Business group requires a declared sector benchmark")
        if len(set(self.tickers)) != len(self.tickers):
            raise ValueError("Duplicate ticker in business peer group")
        return self


class IssuerIdentityRule(SettingsModel):
    identity_valid_from: date | None = None
    identity_valid_to: date | None = None
    historical_cik: str | None = None
    historical_cik_valid_to: date | None = None
    notes: str = Field(min_length=10)
    source_links: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_rule(self) -> Self:
        if self.identity_valid_from and self.identity_valid_to:
            if self.identity_valid_from > self.identity_valid_to:
                raise ValueError("Identity bounds must be chronological")
        if self.historical_cik is not None:
            if normalize_cik(self.historical_cik) != self.historical_cik:
                raise ValueError("Historical CIK requires ten digits")
            if self.historical_cik_valid_to is None:
                raise ValueError("Historical CIK override requires a validity endpoint")
        return self


class ResearchUniverse(SettingsModel):
    version: Version
    reviewed_at: datetime
    membership_policy: Literal["current_survivor_conditioned_prototype"]
    orientation_policy: Literal["original_or_ascending_frozen_security_id"]
    classification_policy: Literal["static_business_peer_groups"]
    domestic_reporting_policy: Literal["candidate_domestic_10k_10q_requires_source_check"]
    source_links: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    groups: tuple[BusinessPeerGroup, ...] = Field(min_length=1)
    issuer_rules: dict[Ticker, IssuerIdentityRule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_issuers(self) -> Self:
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("Roster reviewed_at must include a timezone")
        tickers = [ticker for group in self.groups for ticker in group.tickers]
        if len(tickers) != len(set(tickers)):
            raise ValueError("Each issuer must belong to exactly one business peer group")
        names = [group.name for group in self.groups]
        if len(names) != len(set(names)):
            raise ValueError("Business peer group names must be unique")
        if set(self.issuer_rules) - set(tickers):
            raise ValueError("Identity rules must refer to roster issuers")
        return self

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(sorted(ticker for group in self.groups for ticker in group.tickers))


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, indent=2, allow_nan=False).encode("utf-8")


def parquet_bytes(frame: pd.DataFrame) -> bytes:
    output = BytesIO()
    frame.to_parquet(output, index=False, compression="zstd")
    return output.getvalue()


def load_research_universe(path: Path) -> ResearchUniverse:
    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    return ResearchUniverse.model_validate(payload)


def expand_pairs(universe: ResearchUniverse, original_pairs: Sequence[Pair]) -> pd.DataFrame:
    """All within-group pairs, retaining exact original orientations and IDs.

    New orientation sorts the frozen ``US:TICKER`` security identities. This
    rule is chosen before prices, diagnostic tests and outcomes are examined.
    Existing orientation is never reversed to obtain a better relationship fit.
    """
    originals = {frozenset((pair.leg_a, pair.leg_b)): pair for pair in original_pairs}
    if len(originals) != len(original_pairs):
        raise ValueError("Original pairs contain duplicated or reversed identities")
    by_ticker = {ticker: group for group in universe.groups for ticker in group.tickers}
    for pair in original_pairs:
        if pair.leg_a not in by_ticker or pair.leg_b not in by_ticker:
            raise ValueError("Expanded roster must preserve every original pair issuer")
        if by_ticker[pair.leg_a] != by_ticker[pair.leg_b]:
            raise ValueError("An original pair must remain within one declared business group")
    rows: list[dict[str, Any]] = []
    for group in sorted(universe.groups, key=lambda value: value.name):
        for left, right in combinations(sorted(group.tickers), 2):
            original = originals.get(frozenset((left, right)))
            leg_a, leg_b = (original.leg_a, original.leg_b) if original else (left, right)
            floors = [
                rule.identity_valid_from
                for ticker in (leg_a, leg_b)
                if (rule := universe.issuer_rules.get(ticker)) is not None
                and rule.identity_valid_from is not None
            ]
            ceilings = [
                rule.identity_valid_to
                for ticker in (leg_a, leg_b)
                if (rule := universe.issuer_rules.get(ticker)) is not None
                and rule.identity_valid_to is not None
            ]
            rows.append(
                {
                    "pair_id": f"{leg_a}__{leg_b}",
                    "leg_a": leg_a,
                    "leg_b": leg_b,
                    "leg_a_security_id": f"US:{leg_a}",
                    "leg_b_security_id": f"US:{leg_b}",
                    "peer_group": original.peer_group if original else group.name,
                    "business_group": group.name,
                    "sector": SECTORS[group.sector_etf],
                    "sub_industry": group.name,
                    "sector_etf": group.sector_etf,
                    "economic_rationale": group.rationale,
                    "orientation": "leg_a_is_y",
                    "orientation_basis": "ORIGINAL_FROZEN" if original else "SECURITY_ID_ORDER",
                    "original_reference_pair": original is not None,
                    "pair_version": universe.version,
                    "enabled": True,
                    # Operational engine bounds describe reviewed continuity floors,
                    # not a comprehensive listing/delisting lifecycle service.
                    "active_from": max(floors) if floors else None,
                    "active_to": min(ceilings) if ceilings else None,
                    "membership_policy": universe.membership_policy,
                }
            )
    return pd.DataFrame(rows).sort_values("pair_id").reset_index(drop=True)


def _resolve_directory(
    body: bytes, tickers: tuple[str, ...]
) -> tuple[dict[str, tuple[str, str]], list[dict[str, str]]]:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("SEC ticker directory must contain an object")
    candidates: dict[str, list[tuple[str, str]]] = {ticker: [] for ticker in tickers}
    for entry in payload.values():
        if not isinstance(entry, dict):
            raise ValueError("SEC ticker directory record must be an object")
        ticker = entry.get("ticker")
        if ticker not in candidates:
            continue
        value = entry.get("cik_str")
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError(f"Invalid directory CIK: {ticker}")
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Invalid directory issuer name: {ticker}")
        candidates[ticker].append((normalize_cik(value), title.strip()))
    resolved: dict[str, tuple[str, str]] = {}
    exclusions: list[dict[str, str]] = []
    for ticker, entries in sorted(candidates.items()):
        if len(entries) != 1:
            exclusions.append({"ticker": ticker, "reason": "SEC_IDENTITY_MISSING_OR_AMBIGUOUS"})
        else:
            resolved[ticker] = entries[0]
    counts: dict[str, int] = {}
    for cik, _ in resolved.values():
        counts[cik] = counts.get(cik, 0) + 1
    for ticker, (cik, _) in list(resolved.items()):
        if counts[cik] > 1:
            exclusions.append({"ticker": ticker, "reason": "SHARED_ISSUER_CIK"})
            del resolved[ticker]
    return resolved, exclusions


def _security_frame(
    universe: ResearchUniverse,
    identities: dict[str, tuple[str, str]],
    freeze_id: str,
) -> pd.DataFrame:
    securities: list[dict[str, Any]] = []
    for group in universe.groups:
        for ticker in group.tickers:
            if ticker not in identities:
                continue
            directory_cik, issuer_name = identities[ticker]
            rule = universe.issuer_rules.get(ticker)
            cik = rule.historical_cik if rule and rule.historical_cik else directory_cik
            securities.append(
                {
                    "ticker": ticker,
                    "security_id": f"US:{ticker}",
                    "cik": cik,
                    "directory_cik": directory_cik,
                    "issuer_name": issuer_name,
                    "sector": SECTORS[group.sector_etf],
                    "sub_industry": group.name,
                    "business_group": group.name,
                    "sector_etf": group.sector_etf,
                    "identity_valid_from": rule.identity_valid_from if rule else None,
                    "identity_valid_to": rule.identity_valid_to if rule else None,
                    "historical_cik_valid_to": rule.historical_cik_valid_to if rule else None,
                    "identity_notes": rule.notes
                    if rule
                    else "Continuity not comprehensively audited",
                    "identity_source_links": list(rule.source_links) if rule else [],
                    "issuer_document_link": f"https://www.sec.gov/edgar/browse/?CIK={cik}&owner=exclude",
                    "submissions_link": f"https://data.sec.gov/submissions/CIK{cik}.json",
                    "domestic_reporting_status": "MANUAL_CANDIDATE_REQUIRES_SOURCE_CHECK",
                    "lifecycle_status": "INCOMPLETE_REVIEW",
                    "membership_policy": universe.membership_policy,
                    "universe_freeze_id": freeze_id,
                }
            )
    return pd.DataFrame(securities).sort_values("ticker").reset_index(drop=True)


def freeze_universe(
    universe_path: Path,
    original_config: ProjectConfig,
    sec_directory_bytes: bytes,
    output_dir: Path,
) -> dict[str, Any]:
    """Publish a hash-bound roster/CIK/orientation freeze before added labels.

    Output goes only to the explicit new directory. Missing directory identities
    exclude added candidates; losing an original reference issuer fails the gate.
    Unchanged reruns verify and reuse the immutable freeze.
    """
    universe = load_research_universe(universe_path)
    original_bytes = json_bytes(original_config.universe.model_dump(mode="json"))
    config_bytes = universe_path.read_bytes()
    inputs = {
        "roster_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "original_universe_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "sec_directory_sha256": hashlib.sha256(sec_directory_bytes).hexdigest(),
        "universe_code_sha256": sha256_file(Path(__file__)),
    }
    freeze_id = "universe_" + hashlib.sha256(json_bytes(inputs)).hexdigest()[:24]
    if (output_dir / "manifest.json").exists():
        manifest = verify_universe_freeze(output_dir)
        if manifest["inputs"] != inputs:
            raise ValueError("Output directory already binds another universe source freeze")
        return manifest
    identities, exclusions = _resolve_directory(sec_directory_bytes, universe.tickers)
    originals = {
        ticker for pair in original_config.universe.pairs for ticker in (pair.leg_a, pair.leg_b)
    }
    if originals - identities.keys():
        raise ValueError("An original issuer lacks an unambiguous SEC directory identity")
    security_frame = _security_frame(universe, identities, freeze_id)
    if not security_frame["cik"].is_unique:
        raise ValueError("Reviewed overrides cannot collapse distinct roster securities")
    pairs = expand_pairs(universe, original_config.universe.pairs)
    included = set(security_frame["ticker"])
    pairs = pairs.loc[pairs["leg_a"].isin(included) & pairs["leg_b"].isin(included)].copy()
    pairs["universe_freeze_id"] = freeze_id
    files = {
        "roster.yaml": config_bytes,
        "original_universe.json": original_bytes,
        "sec_directory.json": sec_directory_bytes,
        "security_master.parquet": parquet_bytes(security_frame),
        "pair_universe.parquet": parquet_bytes(pairs),
        "exclusions.json": json_bytes(exclusions),
    }
    manifest = {
        "schema_version": "research-universe-freeze-v1",
        "freeze_id": freeze_id,
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "inputs": inputs,
        "files": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()},
        "candidate_count": len(universe.tickers),
        "included_security_count": len(security_frame),
        "included_pair_count": len(pairs),
        "original_pair_count": len(original_config.universe.pairs),
        "outcome_blind": True,
        "historical_membership_reconstructed": False,
        "delisting_complete": False,
        "domestic_reporting_source_check_complete": False,
        "limitations": list(universe.limitations),
    }
    for name, body in files.items():
        write_bytes(output_dir / name, body)
    write_bytes(output_dir / "manifest.json", json_bytes(manifest))
    return verify_universe_freeze(output_dir)


def verify_universe_freeze(directory: Path) -> dict[str, Any]:
    """Verify hashes and regenerate identities/pairs before consuming the freeze."""
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "research-universe-freeze-v1"
    ):
        raise ValueError("Invalid universe freeze manifest")
    inputs = manifest["inputs"]
    expected_id = "universe_" + hashlib.sha256(json_bytes(inputs)).hexdigest()[:24]
    if manifest.get("freeze_id") != expected_id or manifest.get("outcome_blind") is not True:
        raise ValueError("Universe freeze identity or outcome-blind policy is invalid")
    required = {
        "roster.yaml",
        "original_universe.json",
        "sec_directory.json",
        "security_master.parquet",
        "pair_universe.parquet",
        "exclusions.json",
    }
    if set(manifest.get("files", {})) != required:
        raise ValueError("Universe freeze has an incomplete file inventory")
    bodies = {}
    for name, digest in manifest["files"].items():
        body = confined_path(directory, name).read_bytes()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError(f"Universe freeze file checksum differs: {name}")
        bodies[name] = body
    for filename, key in (
        ("roster.yaml", "roster_sha256"),
        ("original_universe.json", "original_universe_sha256"),
        ("sec_directory.json", "sec_directory_sha256"),
    ):
        if hashlib.sha256(bodies[filename]).hexdigest() != inputs[key]:
            raise ValueError("Universe source does not match its input freeze")
    universe = ResearchUniverse.model_validate(
        yaml.load(bodies["roster.yaml"], Loader=UniqueKeyLoader)
    )
    originals = tuple(
        Pair.model_validate(row) for row in json.loads(bodies["original_universe.json"])["pairs"]
    )
    security_frame = pd.read_parquet(BytesIO(bodies["security_master.parquet"]))
    pairs = pd.read_parquet(BytesIO(bodies["pair_universe.parquet"]))
    identities, exclusions = _resolve_directory(bodies["sec_directory.json"], universe.tickers)
    expected_tickers = set(identities)
    if set(security_frame["ticker"]) != expected_tickers or len(security_frame) != len(
        expected_tickers
    ):
        raise ValueError("Frozen security inventory disagrees with the SEC directory")
    if json.loads(bodies["exclusions.json"]) != exclusions:
        raise ValueError("Frozen identity exclusions disagree with their sources")
    expected_securities = _security_frame(universe, identities, manifest["freeze_id"])
    try:
        pd.testing.assert_frame_equal(expected_securities, security_frame, check_dtype=False)
    except AssertionError as exc:
        raise ValueError("Frozen issuer metadata disagrees with its reviewed sources") from exc
    expected = expand_pairs(universe, originals)
    expected = expected.loc[
        expected["leg_a"].isin(expected_tickers) & expected["leg_b"].isin(expected_tickers)
    ].copy()
    expected["universe_freeze_id"] = manifest["freeze_id"]
    try:
        pd.testing.assert_frame_equal(expected.reset_index(drop=True), pairs, check_dtype=False)
    except AssertionError as exc:
        raise ValueError("Frozen pair inventory or orientation disagrees with its sources") from exc
    if (
        len(security_frame) != manifest["included_security_count"]
        or len(pairs) != manifest["included_pair_count"]
    ):
        raise ValueError("Universe freeze counts disagree with verified data")
    return dict(manifest)
