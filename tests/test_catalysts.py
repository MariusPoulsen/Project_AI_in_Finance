import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from structural_break.intelligence import catalysts as cv
from structural_break.pipeline import catalysts as cc

A_TEXT = (
    "The company announced an agreement to acquire Widget Corp for $2 billion. "
    "The acquisition is expected to close next year."
)
B_TEXT = "Quarterly revenue increased 4% compared with the prior year. Net income rose."


def _chunk(leg: str, text: str, number: int) -> dict[str, Any]:
    return {
        "chunk_id": f"chunk_{leg}{number}",
        "filing_id": f"filing-{leg}",
        "security_id": f"US:{leg}",
        "leg": leg,
        "form": "8-K",
        "acceptance_datetime_utc": "2015-03-01T15:00:00+00:00",
        "section_label": "ITEM 8.01",
        "chunk_text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _pack(event_id: str = "e1", complete: bool = True) -> dict[str, Any]:
    status = "COMPLETE" if complete else "PARTIAL"
    return {
        "event_id": event_id,
        "pair_id": "A__B",
        "event_timestamp": "2015-03-02T21:00:00+00:00",
        "evidence_cutoff": "2015-03-02T21:00:00+00:00",
        "coverage": {
            "A": {"status": status, "security_id": "US:A"},
            "B": {"status": status, "security_id": "US:B"},
        },
        "chunks": [_chunk("A", A_TEXT, 1), _chunk("B", B_TEXT, 1)],
    }


def _ok(text: str, tokens: int = 1000) -> tuple[int, Any]:
    return 200, {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": ""}, {"text": text}]}}
        ],
        "usageMetadata": {"promptTokenCount": tokens, "candidatesTokenCount": 40},
    }


class FakeTransport:
    def __init__(self, replies: list[tuple[int, Any]]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def __call__(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float):
        assert headers["x-goog-api-key"] == "test-key"
        assert "test-key" not in json.dumps(payload) and "test-key" not in url
        self.prompts.append(payload["contents"][0]["parts"][0]["text"])
        return self.replies.pop(0)


def _client(replies: list[tuple[int, Any]], sleeps: list[float] | None = None) -> cv.ModelClient:
    log = sleeps if sleeps is not None else []
    return cv.ModelClient(
        cv.MODELS[0],
        credential=lambda: "test-key",
        transport=FakeTransport(replies),
        sleep=log.append,
        clock=lambda: 0.0 if not log else sum(log),
    )


M_AND_A = {
    "event_type": "M&A",
    "affected_leg": "A",
    "direction": "POSITIVE",
    "materiality": "HIGH",
    "relationship_relevance": "DIRECT",
    "extraction_confidence": 0.8,
    "citations": ["A1.1"],
}


def test_prompt_numbers_exact_sentences_and_hides_identifiers() -> None:
    view = cv.build_prompt(_pack())
    assert "(A1.1) The company announced an agreement" in view.prompt
    assert "chunk_A1" not in view.prompt and "text_sha256" not in view.prompt
    for chunk_id, leg, sentence in view.references.values():
        source = A_TEXT if leg == "A" else B_TEXT
        assert sentence in source and chunk_id == f"chunk_{leg}1"


def test_sentence_reference_resolves_to_exact_validated_citation() -> None:
    record = cv.extract_view(_client([_ok("```json\n" + json.dumps(M_AND_A) + "\n```")]), _pack())
    assert record["status"] == "SUCCESS" and record["reasons"] == []
    citation = record["response"]["citations"][0]
    assert citation["chunk_id"] == "chunk_A1" and citation["quote"] in A_TEXT


def test_invalid_answer_retries_once_with_the_specific_error() -> None:
    wrong = {**M_AND_A, "citations": ["B1.1"]}  # B sentence for an A catalyst
    transport_replies = [_ok(json.dumps(wrong)), _ok(json.dumps(M_AND_A))]
    client = _client(transport_replies)
    record = cv.extract_view(client, _pack())
    assert record["status"] == "SUCCESS"
    assert record["reasons"] == ["INVALID_OR_UNGROUNDED_PROVIDER_RESPONSE"]
    assert "previous answer was rejected" in client.transport.prompts[1]  # type: ignore[attr-defined]


def test_unknown_reference_and_prose_stay_unknown() -> None:
    record = cv.extract_view(
        _client([_ok(json.dumps({**M_AND_A, "citations": ["A9.9"]})), _ok("Sure! {}"), _ok("{}")]),
        _pack(),
    )
    assert record["status"] == "UNKNOWN" and record["response"] is None


def test_none_requires_complete_coverage() -> None:
    none = {
        "event_type": "NONE",
        "affected_leg": "NONE",
        "direction": "UNKNOWN",
        "materiality": "UNKNOWN",
        "relationship_relevance": "NONE",
        "extraction_confidence": 0.9,
        "citations": [],
    }
    assert cv.extract_view(_client([_ok(json.dumps(none))]), _pack())["status"] == "NONE"
    client = _client([_ok(json.dumps(none))] * 3)
    partial = cv.extract_view(client, _pack(complete=False))
    assert partial["status"] == "UNKNOWN" and len(partial["rejected_answers"]) == 2
    assert "REPEATED_REJECTED_ANSWER" in partial["reasons"] and "_signatures" not in partial
    prompts = client.transport.prompts  # type: ignore[attr-defined]
    assert "NONE is not allowed here" in prompts[0]
    assert "PRODUCT_OTHER|UNKNOWN" in prompts[0] and "A|B|BOTH|UNKNOWN" in prompts[0]
    assert "NONE is not allowed because coverage is incomplete" in prompts[1]


def test_minute_quota_waits_and_daily_quota_raises() -> None:
    minute = {
        "error": {"details": [{"violations": [{"quotaId": "PerMinute"}]}, {"retryDelay": "7s"}]}
    }
    sleeps: list[float] = []
    record = cv.extract_view(_client([(429, minute), _ok(json.dumps(M_AND_A))], sleeps), _pack())
    assert record["status"] == "SUCCESS" and 7.0 in sleeps
    day = {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerModel"}]}]}}
    with pytest.raises(cv.DailyQuotaExhausted):
        cv.extract_view(_client([(429, day)]), _pack())


def test_server_errors_back_off_then_leave_pack_unknown() -> None:
    sleeps: list[float] = []
    record = cv.extract_view(_client([(500, None)] * 7, sleeps), _pack())
    assert record["status"] == "UNKNOWN" and record["reasons"] == ["PROVIDER_UNAVAILABLE"]
    assert sleeps == list(cv.SERVER_RETRY_SECONDS)
    recovered = cv.extract_view(_client([(503, None), _ok(json.dumps(M_AND_A))]), _pack())
    assert recovered["status"] == "SUCCESS"


def test_token_pacing_waits_when_the_minute_budget_is_spent() -> None:
    sleeps: list[float] = []
    client = _client([_ok(json.dumps(M_AND_A), tokens=14_000)] * 2, sleeps)
    cv.extract_view(client, _pack())
    cv.extract_view(client, _pack())
    assert sleeps and sleeps[0] >= 1.0


def test_next_quota_reset_is_after_midnight_pacific() -> None:
    reset = cv.next_quota_reset(datetime(2026, 10, 17, 20, 0, tzinfo=UTC))
    assert reset == datetime(2026, 10, 18, 7, 5, tzinfo=UTC)


def test_prompt_states_category_terms_and_cue_retry_names_them() -> None:
    view = cv.build_prompt(_pack())
    assert "EARNINGS: earnings, revenue, net income" in view.prompt
    no_cue = {**M_AND_A, "event_type": "LITIGATION", "citations": ["A1.2"]}
    client = _client([_ok(json.dumps(no_cue)), _ok(json.dumps(M_AND_A))])
    record = cv.extract_view(client, _pack())
    assert record["status"] == "SUCCESS"
    retry = client.transport.prompts[1]  # type: ignore[attr-defined]
    assert "None of your cited sentences contains a LITIGATION term" in retry
    assert record["validation_errors"] == [
        "Supporting quotes lack a cue for the claimed catalyst category"
    ]


def test_corrections_cover_each_validation_error() -> None:
    assert "affected_leg must match" in cv.correction(
        "Every affected leg requires matching supporting citations", {}, True
    )
    assert "sentence IDs exactly" in cv.correction("Unknown sentence ID A9.9", {}, True)
    assert "Field rules" in cv.correction(
        "1 validation error for CatalystResponse Value error, NONE cannot invent", {}, True
    )


def test_concurrent_threads_share_one_token_budget() -> None:
    import threading

    client = cv.ModelClient(
        cv.MODELS[0],
        credential=lambda: "test-key",
        transport=lambda *args: _ok(json.dumps(M_AND_A), tokens=5000),
        sleep=lambda seconds: None,
    )
    booked: list[float] = []
    lock = threading.Lock()

    def reserve() -> None:
        entry = client._reserve(5000)
        with lock:
            booked.append(sum(item[1] for item in client.window))
        assert entry[1] == 5000

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert max(booked) <= cv.TOKEN_BUDGET and client.calls == 2


def test_records_from_an_older_adapter_are_redone() -> None:
    assert cc.needs_work({"adapter_version": "gemma-sentence-cite-v3", "status": "SUCCESS"})
    assert not cc.needs_work({"adapter_version": cv.ADAPTER_VERSION, "status": "SUCCESS"})


def test_server_errors_do_not_consume_the_token_budget() -> None:
    client = _client([(500, None), _ok(json.dumps(M_AND_A), tokens=3000)])
    cv.extract_view(client, _pack())
    assert sorted(entry[1] for entry in client.window) == [0.0, 3000.0]
    assert client.statuses == {500: 1, 200: 1}

