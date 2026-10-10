"""SEC evidence boundaries and failure semantics, with no external requests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from structural_break.config.paths import ProjectPaths
from structural_break.data.http import FetchedResponse, SourceError
from structural_break.intelligence.evidence import (
    CHUNK_COLUMNS,
    EvidencePolicy,
    build_evidence_pack,
    cache_filing,
    parse_documents,
    select_event_filings,
)

CUTOFF = datetime(2022, 4, 1, 20, tzinfo=UTC)
RETRIEVED = datetime(2026, 10, 3, 10, tzinfo=UTC)


def event(**extra: Any) -> dict[str, object]:
    return {
        "event_id": "evt_fixture",
        "pair_id": "KO__PEP",
        "event_timestamp": CUTOFF,
        "evidence_cutoff": CUTOFF,
        **extra,
    }


def filing(
    sequence: int, security: str = "sec_KO", form: str = "8-K", days: int = 3, **extra: Any
) -> dict[str, object]:
    cik = "0000021344" if security == "sec_KO" else "0000077476"
    return {
        "filing_id": f"{cik}-22-{sequence:06d}",
        "cik": cik,
        "security_id": security,
        "form": form,
        "acceptance_datetime_utc": CUTOFF - timedelta(days=days),
        "point_in_time_eligible": True,
        "report_date": "2021-12-31",
        "primary_document": "primary.htm",
        **extra,
    }


def select(rows: list[dict[str, object]], **kwargs: Any) -> Any:
    return select_event_filings(event(), pd.DataFrame(rows), ["sec_KO", "sec_PEP"], **kwargs)


def get_fixture(calls: list[str], failures: set[str] | None = None) -> Any:
    def get(url: str) -> FetchedResponse:
        calls.append(url)
        name = url.rsplit("/", 1)[-1]
        if failures and name in failures:
            raise SourceError(url, 403)
        if name == "index.json":
            body = json.dumps(
                {"directory": {"item": [{"name": "primary.htm"}, {"name": "ex99.htm"}]}}
            ).encode()
        elif name == "primary.htm":
            body = (
                b"<html><head><style>hidden style</style></head><body>"
                b"<h2>Item 2.02 Results of Operations</h2><p>Earnings declined.</p>"
                b"<script>future profits invented</script></body></html>"
            )
        elif name == "ex99.htm":
            body = b"<html><p>Guidance raised and revenue increased.</p></html>"
        else:
            body = (
                b"<DOCUMENT>\n<TYPE>8-K\n<SEQUENCE>1\n<FILENAME>primary.htm\n"
                b"<TEXT><p>Primary embedded earnings text.</p></TEXT>\n</DOCUMENT>\n"
                b"<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>ex99.htm\n"
                b"<TEXT><p>Guidance raised and revenue increased.</p></TEXT>\n</DOCUMENT>"
            )
        return FetchedResponse(body, url, 200, RETRIEVED)

    return get


def test_selection_admissibility_precedes_latest_and_amendment_logic() -> None:
    rows = [
        filing(1, days=30),
        filing(2, days=31),
        filing(3, days=-1),
        filing(4, form="10-Q", days=70),
        filing(5, form="10-K", days=200),
        filing(6, form="10-Q/A", days=20),
        filing(7, form="10-Q/A", days=-2),
        filing(8, form="10-Q/A", days=10, report_date="2021-09-30"),
        filing(9, security="sec_PEP", form="10-K", days=250),
    ]
    chosen, coverage = select(rows)
    assert {row["filing_id"] for row in chosen} == {
        rows[index]["filing_id"] for index in (0, 3, 5, 8)
    }
    assert coverage["A"]["periodic_extended"] is False
    assert coverage["B"]["periodic_extended"] is True
    assert next(row for row in chosen if row["form"] == "10-Q/A")["is_amendment"] is True


def test_missing_acceptance_and_ineligible_source_do_not_become_none() -> None:
    chosen, coverage = select(
        [
            filing(1, acceptance_datetime_utc=None),
            filing(2, point_in_time_eligible=False),
            filing(3, security="sec_PEP", form="10-K", days=401),
        ]
    )
    assert not chosen
    assert coverage["A"]["status"] == coverage["B"]["status"] == "UNKNOWN"
    assert coverage["A"]["missing_acceptance_count"] == 1


def test_identity_window_prevents_successor_cik_retroactive_evidence() -> None:
    chosen, _ = select(
        [filing(1, identity_valid_from="2026-07-01"), filing(2, identity_valid_to="2026-07-01")]
    )
    assert [row["filing_id"] for row in chosen] == [filing(2)["filing_id"]]


@pytest.mark.parametrize(
    "field,value",
    [("event_timestamp", "2022-04-01"), ("evidence_cutoff", CUTOFF + timedelta(seconds=1))],
)
def test_naive_or_future_event_cutoff_is_blocking(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        select_event_filings(
            event(**{field: value}), pd.DataFrame([filing(1)]), ["sec_KO", "sec_PEP"]
        )


def test_duplicate_accession_rejected_before_selection() -> None:
    with pytest.raises(ValueError, match="unique"):
        select([filing(1), filing(1)])


def test_cache_primary_submission_exhibits_and_repeat_without_requests(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])
    calls: list[str] = []
    documents = cache_filing(paths, chosen[0], get_fixture(calls))
    assert len(calls) == 4
    assert {row["document_type"] for row in documents} == {"INDEX", "8-K", "SUBMISSION", "EX-99.1"}
    assert all(row["status"] == "DOWNLOADED" for row in documents)
    repeated = cache_filing(paths, chosen[0], get_fixture(calls), offline=True)
    assert documents == repeated
    assert len(calls) == 4
    for row in documents:
        raw = paths.workspace_root / str(row["raw_file_path"])
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == row["sha256"]
        assert raw.with_name(raw.name + ".response.json").is_file()


def test_cache_mutated_raw_bytes_fail_instead_of_recapture(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])
    calls: list[str] = []
    documents = cache_filing(paths, chosen[0], get_fixture(calls))
    Path(str(documents[1]["local_path"])).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        cache_filing(paths, chosen[0], get_fixture(calls))
    assert len(calls) == 4


def _cache_folder(paths: ProjectPaths, selected: dict[str, object]) -> Path:
    return paths.data_path(f"raw/sec/filings/{selected['cik']}/{selected['filing_id']}")


def _response_snapshot(folder: Path) -> dict[Path, tuple[bytes, int]]:
    return {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in folder.rglob("*")
        if path.is_file() and path.name != "response_manifest.json"
    }


@pytest.mark.parametrize("interrupt_at", ["submission", "exhibit"])
def test_interrupted_cache_fetches_only_missing_documents_and_preserves_receipts(
    paths: ProjectPaths, interrupt_at: str
) -> None:
    chosen, _ = select([filing(1)])
    selected = chosen[0]
    missing_name = (
        str(selected["filing_id"]) + ".txt" if interrupt_at == "submission" else "ex99.htm"
    )
    initial_calls: list[str] = []
    initial = get_fixture(initial_calls)

    def interrupted(url: str) -> FetchedResponse:
        if url.endswith("/" + missing_name):
            raise RuntimeError("simulated process interruption")
        return initial(url)

    with pytest.raises(RuntimeError, match="interruption"):
        cache_filing(paths, selected, interrupted)
    folder = _cache_folder(paths, selected)
    assert not (folder / "response_manifest.json").exists()
    before = _response_snapshot(folder)
    assert len(before) == (4 if interrupt_at == "submission" else 6)
    resumed_calls: list[str] = []
    resumed = get_fixture(resumed_calls)

    def later_response(url: str) -> FetchedResponse:
        response = resumed(url)
        return FetchedResponse(response.body, response.url, 200, RETRIEVED + timedelta(days=1))

    documents = cache_filing(paths, selected, later_response)
    assert {url.rsplit("/", 1)[-1] for url in resumed_calls} == (
        {str(selected["filing_id"]) + ".txt", "ex99.htm"}
        if interrupt_at == "submission"
        else {"ex99.htm"}
    )
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items()
    )
    assert all(row["status"] == "DOWNLOADED" for row in documents)
    assert documents == cache_filing(paths, selected, get_fixture(resumed_calls), offline=True)
    assert len(resumed_calls) == (2 if interrupt_at == "submission" else 1)


def test_crash_before_manifest_recovers_every_pair_without_http_or_receipt_rewrites(
    paths: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    import structural_break.intelligence.evidence as evidence

    chosen, _ = select([filing(1)])
    original_write = evidence.write_bytes

    def crash_manifest(path: Path, content: bytes) -> Path:
        if path.name == "response_manifest.json":
            raise RuntimeError("simulated manifest interruption")
        return original_write(path, content)

    monkeypatch.setattr(evidence, "write_bytes", crash_manifest)
    with pytest.raises(RuntimeError, match="manifest interruption"):
        cache_filing(paths, chosen[0], get_fixture([]))
    folder = _cache_folder(paths, chosen[0])
    before = _response_snapshot(folder)
    assert len(before) == 8

    def manifest_only(path: Path, content: bytes) -> Path:
        assert path.name == "response_manifest.json", "Existing response must not be rewritten"
        return original_write(path, content)

    def forbidden_http(url: str) -> FetchedResponse:
        pytest.fail(f"Completed response was refetched: {url}")

    monkeypatch.setattr(evidence, "write_bytes", manifest_only)
    documents = cache_filing(paths, chosen[0], forbidden_http)
    assert all(row["retrieved_at_utc"] == RETRIEVED.isoformat() for row in documents)
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items()
    )
    assert cache_filing(paths, chosen[0], forbidden_http, offline=True) == documents


@pytest.mark.parametrize("failure_kind", ["request", "body", "empty"])
def test_partial_failed_receipt_stays_failed_until_explicit_new_attempt(
    paths: ProjectPaths, failure_kind: str
) -> None:
    chosen, _ = select([filing(1)])
    selected = chosen[0]
    initial = get_fixture([])

    def interrupted(url: str) -> FetchedResponse:
        if url.endswith("/" + str(selected["filing_id"]) + ".txt"):
            raise RuntimeError("simulated process interruption")
        if url.endswith("/primary.htm"):
            if failure_kind == "request":
                raise SourceError(url, 403)
            return FetchedResponse(
                b"Access denied" if failure_kind == "body" else b"",
                url,
                403 if failure_kind == "body" else 200,
                RETRIEVED,
            )
        return initial(url)

    with pytest.raises(RuntimeError, match="interruption"):
        cache_filing(paths, selected, interrupted)
    before = _response_snapshot(_cache_folder(paths, selected))
    resumed_calls: list[str] = []
    resumed = cache_filing(paths, selected, get_fixture(resumed_calls))
    primary = next(row for row in resumed if row["document_type"] == "8-K")
    assert primary["status"] == "FAILED"
    assert primary["http_status"] == (200 if failure_kind == "empty" else 403)
    assert not any(url.endswith("/primary.htm") for url in resumed_calls)
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items()
    )
    if failure_kind == "request":
        assert primary["retrieved_at_utc"] is None and primary["sha256"] is None
    else:
        assert primary["retrieved_at_utc"] == RETRIEVED.isoformat()
        assert primary["sha256"] is not None
    retried = cache_filing(paths, selected, get_fixture([]), attempt_id="explicit_recovery")
    assert all(row["status"] == "DOWNLOADED" for row in retried)
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items()
    )
    assert cache_filing(paths, selected, get_fixture([]), offline=True) == resumed


def test_body_without_sidecar_fails_closed_before_http_after_crash(
    paths: ProjectPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    import structural_break.intelligence.evidence as evidence

    chosen, _ = select([filing(1)])
    original_write = evidence.write_bytes

    def crash_sidecar(path: Path, content: bytes) -> Path:
        if path.name == "primary_document.html.response.json":
            raise RuntimeError("simulated sidecar interruption")
        return original_write(path, content)

    monkeypatch.setattr(evidence, "write_bytes", crash_sidecar)
    with pytest.raises(RuntimeError, match="sidecar interruption"):
        cache_filing(paths, chosen[0], get_fixture([]))
    monkeypatch.setattr(evidence, "write_bytes", original_write)
    before = _response_snapshot(_cache_folder(paths, chosen[0]))
    calls: list[str] = []
    with pytest.raises(ValueError, match="no complete response metadata"):
        cache_filing(paths, chosen[0], get_fixture(calls))
    assert not calls
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://www.sec.gov/Archives/wrong.htm"),
        ("raw_file_path", "data/raw/sec/foreign.htm"),
        ("document_type", "10-K"),
        ("document_filename", "foreign.htm"),
        ("retrieved_at_utc", "2020-01-01T00:00:00+00:00"),
        ("retrieved_at_utc", "2026-10-03"),
        ("retrieved_at_utc", None),
        ("response_url", "https://example.com/foreign.htm"),
        ("status", "FAILED"),
        ("status", "MISSING"),
        ("http_status", 403),
        ("http_status", True),
        ("sha256", None),
        ("sha256", "0" * 64),
    ],
)
def test_partial_sidecar_tampering_is_blocking_without_refetch(
    paths: ProjectPaths, field: str, value: object
) -> None:
    chosen, _ = select([filing(1)])
    documents = cache_filing(paths, chosen[0], get_fixture([]))
    folder = _cache_folder(paths, chosen[0])
    (folder / "response_manifest.json").unlink()
    primary = Path(str(documents[1]["local_path"]))
    sidecar = primary.with_name(primary.name + ".response.json")
    receipt = json.loads(sidecar.read_bytes())
    receipt[field] = value
    sidecar.write_text(json.dumps(receipt))
    before = _response_snapshot(folder)
    calls: list[str] = []
    with pytest.raises(ValueError):
        cache_filing(paths, chosen[0], get_fixture(calls))
    assert not calls
    assert not (folder / "response_manifest.json").exists()
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items()
    )


@pytest.mark.parametrize("damage", ["body", "missing_body", "malformed", "missing_field"])
def test_partial_cache_incomplete_or_corrupt_receipt_is_not_replaced(
    paths: ProjectPaths, damage: str
) -> None:
    chosen, _ = select([filing(1)])
    documents = cache_filing(paths, chosen[0], get_fixture([]))
    folder = _cache_folder(paths, chosen[0])
    (folder / "response_manifest.json").unlink()
    primary = Path(str(documents[1]["local_path"]))
    sidecar = primary.with_name(primary.name + ".response.json")
    if damage == "body":
        primary.write_bytes(b"mutated SEC response")
    elif damage == "missing_body":
        primary.unlink()
    elif damage == "malformed":
        sidecar.write_bytes(b"{not json")
    else:
        receipt = json.loads(sidecar.read_bytes())
        del receipt["retrieved_at_utc"]
        sidecar.write_text(json.dumps(receipt))
    before = _response_snapshot(folder)
    calls: list[str] = []
    with pytest.raises(ValueError):
        cache_filing(paths, chosen[0], get_fixture(calls))
    assert not calls
    assert all(
        (path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items()
    )


def test_offline_partial_cache_remains_missing_and_read_only(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])
    cache_filing(paths, chosen[0], get_fixture([]))
    folder = _cache_folder(paths, chosen[0])
    (folder / "response_manifest.json").unlink()
    before = _response_snapshot(folder)
    calls: list[str] = []
    documents = cache_filing(paths, chosen[0], get_fixture(calls), offline=True)
    assert not calls and {row["status"] for row in documents} == {"MISSING"}
    assert all(row["error_reason"] == "OFFLINE_CACHE_MISS" for row in documents)
    assert not (folder / "response_manifest.json").exists()
    assert _response_snapshot(folder) == before


def test_cache_mutated_metadata_is_blocking(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])
    docs = cache_filing(paths, chosen[0], get_fixture([]))
    path = Path(str(docs[1]["local_path"]))
    path.with_name(path.name + ".response.json").write_text("{}")
    with pytest.raises(ValueError, match="metadata mismatch"):
        cache_filing(paths, chosen[0], get_fixture([]))


def test_offline_missing_cache_has_explicit_status_and_no_network(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])
    calls: list[str] = []
    documents = cache_filing(paths, chosen[0], get_fixture(calls), offline=True)
    assert not calls
    assert {row["status"] for row in documents} == {"MISSING"}
    assert all(row["error_reason"] == "OFFLINE_CACHE_MISS" for row in documents)
    assert not (paths.data / "raw/sec/filings").exists()


def test_explicit_retry_preserves_failed_original_cache(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])
    first = cache_filing(paths, chosen[0], get_fixture([], {"primary.htm"}))
    assert any(row["status"] == "FAILED" for row in first)
    original = paths.data_path(
        f"raw/sec/filings/{chosen[0]['cik']}/{chosen[0]['filing_id']}/response_manifest.json"
    )
    original_bytes = original.read_bytes()
    repaired = cache_filing(paths, chosen[0], get_fixture([]), attempt_id="retry_fixture")
    assert all(row["status"] == "DOWNLOADED" for row in repaired)
    assert all("attempts/retry_fixture/" in row["raw_file_path"] for row in repaired)
    assert original.read_bytes() == original_bytes
    assert cache_filing(paths, chosen[0], get_fixture([]), offline=True) == first
    assert (
        cache_filing(paths, chosen[0], get_fixture([]), offline=True, attempt_id="retry_fixture")
        == repaired
    )


def test_submission_failure_still_downloads_index_named_ex99(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])
    calls: list[str] = []
    complete_name = str(chosen[0]["filing_id"]) + ".txt"
    docs = cache_filing(paths, chosen[0], get_fixture(calls, {complete_name}))
    assert any(url.endswith("ex99.htm") for url in calls)
    chunks = parse_documents(docs)
    assert "FAILED" in set(chunks["status"])
    assert any(
        row["document_type"] == "EX-99" and row["status"] == "OK"
        for row in chunks.to_dict("records")
    )


def test_http_error_body_and_status_are_retained(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])

    def denied(url: str) -> FetchedResponse:
        return FetchedResponse(b"Access denied", url, 403, RETRIEVED)

    docs = cache_filing(paths, chosen[0], denied)
    assert all(row["status"] == "FAILED" and row["http_status"] == 403 for row in docs)
    assert all(
        (paths.workspace_root / row["raw_file_path"]).read_bytes() == b"Access denied"
        for row in docs
    )


def test_parsing_excludes_scripts_and_preserves_section_raw_and_text_hashes(
    paths: ProjectPaths,
) -> None:
    chosen, _ = select([filing(1)])
    documents = cache_filing(paths, chosen[0], get_fixture([]))
    chunks = parse_documents(documents)
    assert set(chunks["status"]) == {"OK"}
    assert chunks["chunk_id"].is_unique
    assert not chunks["chunk_text"].str.contains("hidden style|invented").any()
    assert "Item 2.02 Results of Operations" in set(chunks["section_label"])
    assert set(chunks["document_type"]) == {"8-K", "EX-99.1"}
    for row in chunks.to_dict("records"):
        assert row["text_sha256"] == hashlib.sha256(row["chunk_text"].encode()).hexdigest()
    pd.testing.assert_frame_equal(chunks, parse_documents(documents))


def _primary_exhibit_alias(
    paths: ProjectPaths,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]], list[dict[str, object]]]:
    chosen, coverage = select([filing(1)])
    original = get_fixture([])

    def get(url: str) -> FetchedResponse:
        if url.endswith("/index.json"):
            body = b'{"directory":{"item":[{"name":"primary.htm"}]}}'
        elif url.endswith(".txt"):
            body = (
                b"<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>1\n<FILENAME>primary.htm\n"
                b"<TEXT><p>Earnings declined.</p></TEXT>\n</DOCUMENT>"
            )
        else:
            return original(url)
        return FetchedResponse(body, url, 200, RETRIEVED)

    return chosen, coverage, cache_filing(paths, chosen[0], get)


def test_primary_exhibit_alias_counts_once_with_original_ids_and_all_raw_captures(
    paths: ProjectPaths,
) -> None:
    chosen, coverage, documents = _primary_exhibit_alias(paths)
    folder = _cache_folder(paths, chosen[0])
    snapshot = _response_snapshot(folder)
    manifest = (folder / "response_manifest.json").read_bytes()
    assert len(documents) == 4 and len(snapshot) == 8
    assert all(row["status"] == "DOWNLOADED" for row in documents)
    primary_only = [row for row in documents if row["document_type"] != "EX-99.1"]
    baseline = parse_documents(primary_only)
    chunks = parse_documents(documents)
    pd.testing.assert_frame_equal(chunks, baseline)
    pd.testing.assert_frame_equal(chunks, parse_documents(list(reversed(documents))))
    assert chunks["chunk_id"].is_unique and set(chunks["document_type"]) == {"8-K"}
    assert build_evidence_pack(event(), chosen, chunks, coverage) == build_evidence_pack(
        event(), chosen, baseline, coverage
    )
    assert _response_snapshot(folder) == snapshot
    assert (folder / "response_manifest.json").read_bytes() == manifest
    assert len(json.loads(manifest)["documents"]) == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("security_id", "sec_PEP"),
        ("cik", "0000077476"),
        ("leg", "B"),
        ("form", "10-Q"),
        ("acceptance_datetime_utc", CUTOFF.isoformat()),
        ("source_url", "https://www.sec.gov/Archives/edgar/data/foreign.htm"),
        ("sha256", "0" * 64),
        ("raw_file_path", None),
        ("document_type", "8-K"),
    ],
)
def test_primary_exhibit_alias_conflicting_identity_fails_closed(
    paths: ProjectPaths, field: str, value: object
) -> None:
    _, _, documents = _primary_exhibit_alias(paths)
    alias = next(row for row in documents if row["document_type"] == "EX-99.1")
    alias[field] = value
    with pytest.raises(ValueError, match="Conflicting SEC document aliases"):
        parse_documents(documents)


@pytest.mark.parametrize("update_claimed_hash", [False, True])
def test_primary_exhibit_alias_changed_body_cannot_be_hidden_by_canonical_primary(
    paths: ProjectPaths, update_claimed_hash: bool
) -> None:
    _, _, documents = _primary_exhibit_alias(paths)
    alias = next(row for row in documents if row["document_type"] == "EX-99.1")
    raw_path = Path(str(alias["local_path"]))
    body = b"<p>Conflicting exhibit content.</p>"
    raw_path.write_bytes(body)
    if update_claimed_hash:
        alias["sha256"] = hashlib.sha256(body).hexdigest()
    with pytest.raises(ValueError, match="Conflicting SEC document aliases|changed before parsing"):
        parse_documents(documents)


def test_pack_still_rejects_duplicate_chunk_ids(paths: ProjectPaths) -> None:
    chosen, coverage, documents = _primary_exhibit_alias(paths)
    chunks = parse_documents(documents)
    duplicated = pd.concat([chunks, chunks.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="unique stable IDs"):
        build_evidence_pack(event(), chosen, duplicated, coverage)


def test_complete_submission_recovers_embedded_exhibit_and_retains_failure(
    paths: ProjectPaths,
) -> None:
    chosen, _ = select([filing(1)])
    documents = cache_filing(paths, chosen[0], get_fixture([], {"ex99.htm"}))
    chunks = parse_documents(documents)
    assert "FAILED" in set(chunks["status"])
    recovered = chunks.loc[chunks["status"].eq("OK") & chunks["document_type"].eq("EX-99.1")]
    assert len(recovered) == 1
    assert recovered.iloc[0]["raw_file_path"].endswith("complete_submission.txt")
    assert recovered.iloc[0]["source_url"].endswith(".txt")


def make_pack(paths: ProjectPaths, **kwargs: Any) -> tuple[dict[str, object], pd.DataFrame]:
    chosen, coverage = select([filing(1, form="10-Q"), filing(2, security="sec_PEP", form="10-Q")])
    documents = [doc for row in chosen for doc in cache_filing(paths, row, get_fixture([]))]
    chunks = parse_documents(documents)
    return build_evidence_pack(
        event(y=1, outcome="CONVERGED"), chosen, chunks, coverage, **kwargs
    ), chunks


def test_pack_bounded_balanced_stable_and_no_outcomes(paths: ProjectPaths) -> None:
    policy = EvidencePolicy(chunk_chars=200, max_chunks_per_leg=1, max_total_chars=400)
    pack, chunks = make_pack(paths, policy=policy)
    assert pack["coverage_status"] == "COMPLETE"
    assert {row["leg"] for row in pack["chunks"]} == {"A", "B"}
    assert pack["total_chars"] <= 400
    assert "outcome" not in pack and "y" not in pack
    chosen, coverage = select([filing(1, form="10-Q"), filing(2, security="sec_PEP", form="10-Q")])
    repeated = build_evidence_pack(
        event(), chosen, chunks.sample(frac=1, random_state=3), coverage, policy
    )
    assert pack == repeated


def test_pack_future_documents_cannot_win_lexical_rank(paths: ProjectPaths) -> None:
    pack, chunks = make_pack(paths)
    chosen, coverage = select([filing(1, form="10-Q"), filing(2, security="sec_PEP", form="10-Q")])
    future = chunks.iloc[[0]].copy()
    future["acceptance_datetime_utc"] = CUTOFF + timedelta(seconds=1)
    future["chunk_text"] = "earnings guidance acquisition " * 500
    future["chunk_id"] = "future_chunk"
    enlarged = pd.concat([chunks, future], ignore_index=True)
    assert build_evidence_pack(event(), chosen, enlarged, coverage) == pack


def test_pack_tampered_text_is_blocking(paths: ProjectPaths) -> None:
    _, chunks = make_pack(paths)
    chosen, coverage = select([filing(1, form="10-Q"), filing(2, security="sec_PEP", form="10-Q")])
    chunks.loc[0, "chunk_text"] = "invented acquisition"
    with pytest.raises(ValueError, match="text hash"):
        build_evidence_pack(event(), chosen, chunks, coverage)


def test_selected_future_filing_is_a_leakage_failure(paths: ProjectPaths) -> None:
    _, chunks = make_pack(paths)
    chosen, coverage = select([filing(1, form="10-Q"), filing(2, security="sec_PEP", form="10-Q")])
    chosen[0]["acceptance_datetime_utc"] = CUTOFF + timedelta(seconds=1)
    with pytest.raises(ValueError, match="follows the evidence cutoff"):
        build_evidence_pack(event(), chosen, chunks, coverage)


def test_pack_rejects_stale_coverage_from_another_source_set(paths: ProjectPaths) -> None:
    _, chunks = make_pack(paths)
    chosen, coverage = select([filing(1, form="10-Q"), filing(2, security="sec_PEP", form="10-Q")])
    coverage["A"]["selected_filing_ids"] = []
    with pytest.raises(ValueError, match="coverage identity"):
        build_evidence_pack(event(), chosen, chunks, coverage)


def test_document_cannot_be_downloaded_before_claimed_acceptance(paths: ProjectPaths) -> None:
    chosen, _ = select([filing(1)])

    def prematurely_retrieved(url: str) -> FetchedResponse:
        return FetchedResponse(b"{}", url, 200, CUTOFF - timedelta(days=10))

    with pytest.raises(ValueError, match="acceptance cannot follow"):
        cache_filing(paths, chosen[0], prematurely_retrieved)


def test_failed_documents_remain_unknown_and_never_remove_event(paths: ProjectPaths) -> None:
    chosen, coverage = select([filing(1, form="10-Q"), filing(2, security="sec_PEP", form="10-Q")])
    documents = [
        doc for row in chosen for doc in cache_filing(paths, row, get_fixture([]), offline=True)
    ]
    pack = build_evidence_pack(event(), chosen, parse_documents(documents), coverage)
    assert pack["event_id"] == "evt_fixture"
    assert pack["coverage_status"] == "UNKNOWN"
    assert not pack["chunks"]
    assert len(pack["selected_filing_ids"]) == 2


def test_empty_index_output_can_build_unknown_pack() -> None:
    index = pd.DataFrame(columns=["security_id", "filing_id", "form", "acceptance_datetime_utc"])
    chosen, coverage = select_event_filings(event(), index, ["sec_KO", "sec_PEP"])
    pack = build_evidence_pack(event(), chosen, pd.DataFrame(columns=CHUNK_COLUMNS), coverage)
    assert pack["coverage_status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"recent_8k_days": 0},
        {"periodic_extension_days": 100},
        {"chunk_chars": 199},
        {"max_chunks_per_leg": 0},
        {"max_total_chars": 100},
    ],
)
def test_invalid_evidence_policy_is_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        EvidencePolicy(**kwargs)
