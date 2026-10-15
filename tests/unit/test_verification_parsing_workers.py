"""Spawned parsing preserves exact frames and owns bounded process cleanup."""

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from structural_break.intelligence.evidence import EvidencePolicy, parse_documents
from structural_break.research.parsing_workers import VerificationParsingPool


def inventory(tmp_path: Path, index: int) -> list[dict[str, Any]]:
    path = tmp_path / f"raw-{index}.html"
    body = f"<html><h1>Item 7</h1><p>Earnings increased {index} percent.</p></html>".encode()
    path.write_bytes(body)
    return [
        {
            "filing_id": f"0000900000-22-{index:06d}",
            "security_id": "US:KO",
            "leg": "A",
            "cik": "0000900000",
            "form": "8-K",
            "is_amendment": False,
            "document_type": "8-K",
            "document_filename": f"raw-{index}.html",
            "acceptance_datetime_utc": "2022-03-08T21:30:00Z",
            "status": "DOWNLOADED",
            "source_url": f"https://www.sec.gov/Archives/edgar/data/9000000/raw-{index}.html",
            "raw_file_path": f"data/raw/sec/raw-{index}.html",
            "local_path": str(path),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    ]


def test_spawned_pool_preserves_exact_frames_limits_tasks_and_joins(tmp_path: Path) -> None:
    documents = [inventory(tmp_path, index) for index in (1, 2, 3)]
    expected = [parse_documents(rows, EvidencePolicy()) for rows in documents]
    pool = VerificationParsingPool()
    with pool:
        first = pool.submit(documents[0], EvidencePolicy())
        second = pool.submit(documents[1], EvidencePolicy())
        processes = list(pool._executor._processes.values())
        with pytest.raises(RuntimeError, match="at most two"):
            pool.submit(documents[2], EvidencePolicy())
        pd.testing.assert_frame_equal(pool.result(first), expected[0], check_exact=True)
        third = pool.submit(documents[2], EvidencePolicy())
        pd.testing.assert_frame_equal(pool.result(second), expected[1], check_exact=True)
        pd.testing.assert_frame_equal(pool.result(third), expected[2], check_exact=True)
        with pytest.raises(ValueError, match="does not belong"):
            pool.result(first)
    assert pool._closed and not pool._pending
    assert len(processes) == 2 and all(not process.is_alive() for process in processes)
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit(documents[0], EvidencePolicy())


@pytest.mark.parametrize("failure", ["worker_hash", "parent", "worker_alias"])
def test_pool_cancels_and_joins_on_worker_or_parent_failure(tmp_path: Path, failure: str) -> None:
    documents = inventory(tmp_path, 1)
    other = inventory(tmp_path, 2)
    if failure == "worker_hash":
        Path(documents[0]["local_path"]).write_bytes(b"changed after parent validation")
    elif failure == "worker_alias":
        documents.append(
            dict(documents[0], document_type="EX-99.1", raw_file_path="other", security_id="US:PEP")
        )
    pool = VerificationParsingPool()
    with pytest.raises((ValueError, RuntimeError), match="changed|Conflicting|parent failed"):
        with pool:
            first = pool.submit(documents, EvidencePolicy())
            pool.submit(other, EvidencePolicy())
            processes = list(pool._executor._processes.values())
            if failure == "parent":
                raise RuntimeError("parent failed")
            pool.result(first)
    assert pool._closed and not pool._pending
    assert len(processes) == 2 and all(not process.is_alive() for process in processes)


@pytest.mark.parametrize("workers", [0, 1, 3, True])
def test_pool_rejects_unbounded_or_unregistered_worker_counts(workers: int) -> None:
    with pytest.raises(ValueError, match="exactly two"):
        VerificationParsingPool(workers)
