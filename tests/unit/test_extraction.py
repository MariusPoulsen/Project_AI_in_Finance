"""No-network extraction checks use grounded, explicitly synthetic evidence."""

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from structural_break.config.paths import ProjectPaths
from structural_break.intelligence.evidence import (
    build_evidence_pack,
    cache_filing,
    parse_documents,
    select_event_filings,
)
from structural_break.intelligence.extraction import (
    CatalystResponse,
    LiteLLMProvider,
    ProviderFailure,
    extract_pack,
    validate_stored_extraction,
)
from structural_break.intelligence.fixtures import MockProvider, make_evidence_fixture


def pack(*, complete: bool = True, empty: bool = False) -> dict[str, Any]:
    text = "Quarterly earnings and revenue increased substantially."
    return {
        "event_id": "event_1",
        "pair_id": "KO__PEP",
        "event_timestamp": "2022-03-10T21:00:00+00:00",
        "evidence_cutoff": "2022-03-10T21:00:00+00:00",
        "policy_version": "test-v1",
        "coverage": {leg: {"status": "COMPLETE" if complete else "UNKNOWN"} for leg in ("A", "B")},
        "chunks": []
        if empty
        else [
            {
                "chunk_id": "chunk_1",
                "leg": "A",
                "filing_id": "filing_1",
                "security_id": "KO",
                "acceptance_datetime_utc": "2022-03-08T21:00:00+00:00",
                "chunk_text": text,
                "source_url": "https://www.sec.gov/Archives/example.html",
                "sha256": "raw-file-sha",
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        ],
    }


def response() -> dict[str, Any]:
    return {
        "event_type": "EARNINGS",
        "affected_leg": "A",
        "direction": "POSITIVE",
        "materiality": "MEDIUM",
        "relationship_relevance": "INDIRECT",
        "extraction_confidence": 0.8,
        "citations": [
            {
                "chunk_id": "chunk_1",
                "leg": "A",
                "quote": "Quarterly earnings and revenue increased substantially.",
            }
        ],
    }


def run(tmp_path: Path, evidence: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return extract_pack(
        evidence or pack(),
        lambda _: response(),
        tmp_path,
        "mock-test",
        "synthetic-test",
        synthetic=True,
        **kwargs,
    )


def test_grounded_extraction_cache_and_derived_fields(tmp_path: Path) -> None:
    calls = []

    def provider(request: dict[str, Any]) -> dict[str, Any]:
        calls.append(request)
        return response()

    one = extract_pack(pack(), provider, tmp_path, "mock", "synthetic", synthetic=True)
    two = extract_pack(pack(), provider, tmp_path, "mock", "synthetic", synthetic=True)
    assert one == two
    assert len(calls) == 1
    assert one["status"] == "SUCCESS"
    assert one["source_count"] == 1
    assert one["document_recency_days"] == 2
    assert one["one_sided_event"] is True
    assert one["evidence_ids"] == ["chunk_1"]
    assert one["synthetic"] is True
    assert not any(name in json.dumps(calls) for name in ("y_revert_success", "raw_probability"))


@pytest.mark.parametrize(
    "empty,complete,expected", [(True, True, "NONE"), (True, False, "UNKNOWN")]
)
def test_empty_complete_none_vs_empty_missing_unknown(
    tmp_path: Path,
    empty: bool,
    complete: bool,
    expected: str,
) -> None:
    def never(_: dict[str, Any]) -> str:
        pytest.fail("Empty evidence must not call provider")

    output = extract_pack(pack(empty=empty, complete=complete), never, tmp_path, "mock", "test")
    assert output["status"] == expected
    assert output["evidence_available"] is complete


def test_partial_coverage_never_none_and_one_sided_not_invented(tmp_path: Path) -> None:
    unknown = {
        "event_type": "NONE",
        "affected_leg": "NONE",
        "direction": "UNKNOWN",
        "materiality": "UNKNOWN",
        "relationship_relevance": "NONE",
        "extraction_confidence": 0.9,
        "citations": [],
    }
    output = extract_pack(pack(complete=False), lambda _: unknown, tmp_path, "mock", "test")
    assert output["status"] == "UNKNOWN"
    other = run(tmp_path, pack(complete=False))
    assert other["status"] == "SUCCESS"
    assert other["one_sided_event"] is False


@pytest.mark.parametrize("mutation", ["future", "cutoff", "naive", "duplicate", "checksum"])
def test_bad_pack_rejected_before_provider(tmp_path: Path, mutation: str) -> None:
    source = pack()
    if mutation == "future":
        source["chunks"][0]["acceptance_datetime_utc"] = "2022-03-11T21:00:00+00:00"
    elif mutation == "cutoff":
        source["evidence_cutoff"] = "2022-03-11T21:00:00+00:00"
    elif mutation == "naive":
        source["event_timestamp"] = "2022-03-10T21:00:00"
    elif mutation == "duplicate":
        source["chunks"].append(source["chunks"][0].copy())
    else:
        source["chunks"][0]["chunk_text"] += " Changed"
    with pytest.raises(ValueError):
        run(tmp_path, source)


@pytest.mark.parametrize(
    "mutation",
    [
        "invented_id",
        "invented_quote",
        "wrong_leg",
        "wrong_category",
        "extra_field",
        "unknown_confidence",
    ],
)
def test_invalid_or_ungrounded_provider_retained_unknown(tmp_path: Path, mutation: str) -> None:
    payload = response()
    if mutation == "invented_id":
        payload["citations"][0]["chunk_id"] = "invented"
    elif mutation == "invented_quote":
        payload["citations"][0]["quote"] = "Company is acquiring a bank tomorrow."
    elif mutation == "wrong_leg":
        payload["citations"][0]["leg"] = "B"
    elif mutation == "wrong_category":
        payload["event_type"] = "LITIGATION"
    elif mutation == "unknown_confidence":
        payload.update(event_type="UNKNOWN", affected_leg="UNKNOWN", citations=[])
    else:
        payload["future_return"] = 0.4
    output = extract_pack(pack(), lambda _: payload, tmp_path, "mock", "test")
    assert output["status"] == "UNKNOWN"
    assert output["evidence_ids"] == []
    assert "INVALID_OR_UNGROUNDED_PROVIDER_RESPONSE" in output["reason_codes"]


def test_each_affected_leg_requires_evidence(tmp_path: Path) -> None:
    payload = response()
    payload["affected_leg"] = "BOTH"
    output = extract_pack(pack(), lambda _: payload, tmp_path, "mock", "test")
    assert output["status"] == "UNKNOWN"


def test_provider_timeout_and_bounded_retry(tmp_path: Path) -> None:
    calls = []

    def slow(_: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        time.sleep(0.05)
        return response()

    output = extract_pack(
        pack(), slow, tmp_path, "mock", "test", timeout_seconds=0.001, max_retries=1
    )
    assert output["status"] == "UNKNOWN"
    assert "PROVIDER_TIMEOUT" in output["reason_codes"]
    assert len(calls) == 2


def test_failed_cache_retry_is_redacted_and_later_success_reused(tmp_path: Path) -> None:
    def bad(_: dict[str, Any]) -> str:
        raise RuntimeError("secret-API-key-123 payload")

    failed = extract_pack(pack(), bad, tmp_path, "mock", "test", max_retries=0)
    assert failed["status"] == "UNKNOWN"
    successful = extract_pack(pack(), lambda _: response(), tmp_path, "mock", "test")
    assert successful["status"] == "SUCCESS"
    assert failed["extraction_id"] != successful["extraction_id"]
    assert "secret-API" not in "".join(path.read_text() for path in tmp_path.rglob("*.json"))


def test_cache_tamper_rejected(tmp_path: Path) -> None:
    run(tmp_path)
    path = next(tmp_path.rglob("extraction.json"))
    payload = json.loads(path.read_text())
    payload["source_count"] = 999
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="checksum/derived"):
        run(tmp_path)


def test_cache_identity_changes_with_provider_model_prompt_config_evidence(tmp_path: Path) -> None:
    outputs = [run(tmp_path)]
    outputs.append(extract_pack(pack(), lambda _: response(), tmp_path, "other", "test"))
    outputs.append(extract_pack(pack(), lambda _: response(), tmp_path, "mock", "other"))
    outputs.append(run(tmp_path, prompt_version="different"))
    outputs.append(run(tmp_path, provider_config={"max_tokens": 500}))
    changed = pack()
    changed["chunks"][0]["source_url"] += "?new-source"
    outputs.append(run(tmp_path, changed))
    assert len({output["cache_identity"] for output in outputs}) == len(outputs)


def test_prompt_strips_arbitrary_target_fields(tmp_path: Path) -> None:
    evidence = pack()
    evidence.update(y_revert_success=1, raw_probability=0.9, future_outcome="CONVERGED")
    evidence["chunks"][0]["future_outcome"] = "STOPPED"
    captured = []
    extract_pack(
        evidence, lambda request: captured.append(request) or response(), tmp_path, "mock", "test"
    )
    prompt = json.dumps(captured)
    assert "y_revert_success" not in prompt and "future_outcome" not in prompt


def test_credentials_cannot_enter_cache_config(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="credentials"):
        run(tmp_path, provider_config={"api_key": "secret"})


def test_adapter_schema_pacing_budget_and_redacted_quota(tmp_path: Path) -> None:
    requests = []

    def completion(**kwargs: Any) -> Any:
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response())))]
        )

    provider = LiteLLMProvider(
        "configured/model", min_interval_seconds=0, max_calls=1, completion=completion
    )
    output = extract_pack(pack(), provider, tmp_path, "configured", "configured/model")
    assert output["status"] == "SUCCESS"
    assert provider.calls == 1
    assert requests[0]["num_retries"] == 0
    assert requests[0]["response_format"]["json_schema"]["strict"] is True
    with pytest.raises(ProviderFailure, match="REQUEST_BUDGET_EXHAUSTED"):
        provider({})


def test_quota_failure_does_not_retry(tmp_path: Path) -> None:
    calls = []

    def limited(_: dict[str, Any]) -> str:
        calls.append(1)
        raise ProviderFailure("PROVIDER_QUOTA_OR_RATE_LIMIT", retriable=False)

    output = extract_pack(pack(), limited, tmp_path, "mock", "test", max_retries=3)
    assert output["status"] == "UNKNOWN" and len(calls) == 1


def test_adapter_latches_quota_so_later_events_do_not_spend_calls(tmp_path: Path) -> None:
    class RateLimitError(RuntimeError):
        status_code = 429

    calls = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise RateLimitError("provider body could contain a credential")

    provider = LiteLLMProvider("configured/model", min_interval_seconds=0, completion=completion)
    one = extract_pack(pack(), provider, tmp_path, "configured", "configured/model")
    different = pack()
    different["event_id"] = "event2"
    two = extract_pack(different, provider, tmp_path, "configured", "configured/model")
    assert one["status"] == two["status"] == "UNKNOWN"
    assert provider.blocked_reason == "PROVIDER_QUOTA_OR_RATE_LIMIT"
    assert provider.calls == 1 and len(calls) == 1


def test_strict_json_schema_has_no_open_extra_fields() -> None:
    schema = CatalystResponse.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Citation"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "field",
    [
        "source_count",
        "document_recency_days",
        "evidence_available",
        "one_sided_event",
        "response_hash",
        "extraction_id",
        "evidence_hash",
    ],
)
def test_stored_extraction_reconstructs_all_source_metadata(tmp_path: Path, field: str) -> None:
    output = run(tmp_path)
    validate_stored_extraction(pack(), output)
    corrupted = output.copy()
    corrupted[field] = "changed" if isinstance(corrupted[field], str) else 99
    with pytest.raises(ValueError):
        validate_stored_extraction(pack(), corrupted)


def test_http_fixture_actual_parser_retrieval_extraction_and_offline_cache(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path, tmp_path)
    events = pd.DataFrame(
        [
            {
                "event_id": "fixture0",
                "pair_id": "KO__PEP",
                "event_timestamp": "2022-01-10T21:00:00Z",
            },
            {
                "event_id": "fixture1",
                "pair_id": "KO__PEP",
                "event_timestamp": "2023-02-10T21:00:00Z",
            },
        ]
    )
    filing_index, get = make_evidence_fixture(events, paths)
    outputs = []
    provider = MockProvider()
    for event in events.to_dict("records"):
        selected, coverage = select_event_filings(event, filing_index, ["KO", "PEP"])
        documents = [
            document for filing in selected for document in cache_filing(paths, filing, get)
        ]
        chunks = parse_documents(documents)
        evidence = build_evidence_pack(event, selected, chunks, coverage)
        output = extract_pack(evidence, provider, paths.data / "cache", "mock-test", "mock-test")
        assert output["synthetic"] is True
        assert all(
            pd.Timestamp(chunk["acceptance_datetime_utc"]) <= pd.Timestamp(event["event_timestamp"])
            for chunk in evidence["chunks"]
        )
        outputs.append(output)
        for filing in selected:
            cache_filing(
                paths, filing, lambda _: pytest.fail("Offline cache must not fetch"), offline=True
            )
    assert outputs[0]["event_type"] == "UNKNOWN"
    assert outputs[1]["status"] == "SUCCESS"
