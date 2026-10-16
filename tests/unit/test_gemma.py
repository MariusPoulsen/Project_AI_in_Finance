"""No-network checks of guarded Gemma extraction and retained UNKNOWN failures."""

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from structural_break.intelligence.extraction import (
    CatalystResponse,
    ProviderFailure,
    extract_pack,
)
from structural_break.intelligence.gemma import GemmaProvider


def pack() -> dict[str, Any]:
    return {
        "event_id": "event_1",
        "pair_id": "KO__PEP",
        "event_timestamp": "2022-03-10T21:00:00+00:00",
        "evidence_cutoff": "2022-03-10T21:00:00+00:00",
        "policy_version": "synthetic-gemma-test",
        "coverage": {leg: {"status": "COMPLETE"} for leg in ("A", "B")},
        "chunks": [
            {
                "chunk_id": "chunk_1",
                "leg": "A",
                "filing_id": "filing_1",
                "security_id": "KO",
                "acceptance_datetime_utc": "2022-03-08T21:00:00+00:00",
                "chunk_text": "Quarterly earnings and revenue increased substantially.",
                "source_url": "https://www.sec.gov/Archives/synthetic.html",
            }
        ],
    }


def payload() -> dict[str, Any]:
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


def envelope(content: str) -> dict[str, Any]:
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}]}


def request() -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": "Extract from source evidence only."},
            {"role": "user", "content": json.dumps(pack())},
        ],
        "response_schema": CatalystResponse.model_json_schema(),
        "timeout_seconds": 20,
        "provider_config": {"max_tokens": 1500},
    }


@pytest.fixture(autouse=True)
def isolated_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    monkeypatch.delenv("SB_LLM_API_KEY", raising=False)


def test_one_user_turn_no_native_schema_tools_or_secret_prompt(tmp_path: Path) -> None:
    calls = []

    def transport(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return envelope(json.dumps(payload()))

    provider = GemmaProvider("gemini/gemma-4-31b-it", min_interval_seconds=0, transport=transport)
    output = extract_pack(pack(), provider, tmp_path, "gemma", "gemma-4-31b-it", synthetic=True)
    assert output["status"] == "SUCCESS" and output["evidence_ids"] == ["chunk_1"]
    url, body, headers, timeout = calls[0]
    assert url.endswith("/models/gemma-4-31b-it:generateContent")
    assert "synthetic-test-key" not in url and "?" not in url
    assert headers["x-goog-api-key"] == "synthetic-test-key"
    assert "synthetic-test-key" not in json.dumps(body)
    assert list(body) == ["contents", "generationConfig"]
    assert len(body["contents"]) == 1 and body["contents"][0]["role"] == "user"
    prompt = body["contents"][0]["parts"][0]["text"]
    assert "REQUIRED JSON SCHEMA" in prompt and "untrusted" in prompt.lower()
    assert body["generationConfig"] == {
        "temperature": 0,
        "candidateCount": 1,
        "maxOutputTokens": 1600,
        "thinkingConfig": {"thinkingLevel": "minimal"},
    }
    assert timeout == 60 and provider.calls == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "fence",
        "prose",
        "duplicate",
        "nan",
        "string_number",
        "wrong_quote",
        "wrong_leg",
        "extra_field",
        "array",
    ],
)
def test_invalid_or_ungrounded_text_retained_unknown(tmp_path: Path, mutation: str) -> None:
    data = payload()
    if mutation == "string_number":
        data["extraction_confidence"] = "0.8"
    elif mutation == "wrong_quote":
        data["citations"][0]["quote"] = "Invented acquisition of a bank."
    elif mutation == "wrong_leg":
        data["citations"][0]["leg"] = "B"
    elif mutation == "extra_field":
        data["future_return"] = 0.9
    content = json.dumps(data)
    if mutation == "fence":
        content = "```json\n" + content + "\n```"
    elif mutation == "prose":
        content = "The answer is " + content
    elif mutation == "duplicate":
        content = content[:-1] + ', "event_type":"EARNINGS"}'
    elif mutation == "nan":
        content = content.replace("0.8", "NaN")
    elif mutation == "array":
        content = "[" + content + "]"
    provider = GemmaProvider(
        "gemma-4-31b-it", min_interval_seconds=0, transport=lambda *_: envelope(content)
    )
    output = extract_pack(pack(), provider, tmp_path, "gemma", "gemma-4-31b-it", max_retries=0)
    assert output["status"] == "UNKNOWN"
    assert output["reason_codes"] == ["INVALID_OR_UNGROUNDED_PROVIDER_RESPONSE"]
    assert output["evidence_ids"] == []


@pytest.mark.parametrize("mutation", ["future", "oversize", "schema", "timeout", "override"])
def test_invalid_input_rejected_without_spending_calls(mutation: str) -> None:
    source = request()
    if mutation in {"future", "oversize"}:
        evidence = pack()
        if mutation == "future":
            evidence["chunks"][0]["acceptance_datetime_utc"] = "2023-03-08T21:00:00+00:00"
        else:
            evidence["chunks"][0]["chunk_text"] = "earnings " * 2000
        source["messages"][1]["content"] = json.dumps(evidence)
    elif mutation == "schema":
        source["response_schema"] = {"type": "object"}
    elif mutation == "timeout":
        source["timeout_seconds"] = float("nan")
    else:
        source["provider_config"]["api_key"] = "must-not-be-sent"
    provider = GemmaProvider(
        "gemma-4-31b-it",
        min_interval_seconds=0,
        transport=lambda *_: pytest.fail("Must not call API"),
    )
    with pytest.raises(ProviderFailure):
        provider(source)
    assert provider.calls == 0


@pytest.mark.parametrize(
    "code,reason",
    [
        (429, "PROVIDER_QUOTA_OR_RATE_LIMIT"),
        (401, "PROVIDER_AUTHENTICATION_FAILED"),
        (403, "PROVIDER_AUTHENTICATION_FAILED"),
        (404, "PROVIDER_MODEL_UNAVAILABLE"),
        (400, "PROVIDER_REQUEST_REJECTED"),
    ],
)
def test_permanent_failure_latches_and_exception_is_redacted(code: int, reason: str) -> None:
    class HTTPError(RuntimeError):
        status_code = code

    def transport(*_: Any) -> dict[str, Any]:
        raise HTTPError("real-secret-might-be-in-this-provider-exception")

    provider = GemmaProvider("gemma-4-31b-it", min_interval_seconds=0, transport=transport)
    for _ in range(2):
        with pytest.raises(ProviderFailure, match=reason) as failure:
            provider(request())
        assert failure.value.retriable is False
        assert "real-secret" not in str(failure.value)
    assert provider.calls == 1 and provider.blocked_reason == reason


def test_budget_is_atomic_across_threads() -> None:
    provider = GemmaProvider(
        "gemma-4-31b-it",
        min_interval_seconds=0,
        max_calls=1,
        transport=lambda *_: envelope(json.dumps(payload())),
    )
    results = []

    def call() -> None:
        try:
            results.append(provider(request()))
        except ProviderFailure as error:
            results.append(error.reason)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert len(results) == 2 and "REQUEST_BUDGET_EXHAUSTED" in results
    assert provider.calls == 1


def test_prompt_drops_targets_and_response_counts_are_locally_derived() -> None:
    source = request()
    evidence = pack()
    evidence["future_return"] = 0.9
    evidence["chunks"][0]["y_revert_success"] = 1
    source["messages"][1]["content"] = json.dumps(evidence)
    captured = []

    def transport(*args: Any) -> dict[str, Any]:
        captured.append(args[1])
        return envelope(json.dumps(payload()))

    GemmaProvider("gemma-4-31b-it", min_interval_seconds=0, transport=transport)(source)
    assert "future_return" not in json.dumps(captured)
    assert "y_revert_success" not in json.dumps(captured)


@pytest.mark.parametrize("change", ["truncated", "thought", "multiple", "empty"])
def test_nonfinal_or_multiple_answers_fail_closed(change: str) -> None:
    response = envelope(json.dumps(payload()))
    if change == "truncated":
        response["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif change == "thought":
        response["candidates"][0]["content"]["parts"][0]["thought"] = True
    elif change == "multiple":
        response["candidates"].append(response["candidates"][0])
    else:
        response["candidates"] = []
    provider = GemmaProvider(
        "gemma-4-31b-it", min_interval_seconds=0, transport=lambda *_: response
    )
    with pytest.raises(ProviderFailure):
        provider(request())


def test_marked_thought_wire_channel_is_not_interpreted_as_the_final_answer() -> None:
    response = envelope(json.dumps(payload()))
    response["candidates"][0]["content"]["parts"].insert(0, {"text": "", "thought": True})
    provider = GemmaProvider(
        "gemma-4-26b-a4b-it", min_interval_seconds=0, transport=lambda *_: response
    )
    assert provider(request()) == payload()


@pytest.mark.parametrize(
    "name",
    [
        "gemini-3.5-flash",
        "gemma-4-31b-it?key=secret",
        "gemma-4/other",
        "https://evil.example/gemma",
    ],
)
def test_only_specific_gemma_names_accepted(name: str) -> None:
    with pytest.raises(ValueError):
        GemmaProvider(name)


@pytest.mark.parametrize(
    "config",
    [
        {"max_tokens": True},
        {"max_tokens": 40},
        {"top_p": float("nan")},
        {"seed": -1},
        {"max_tokens": 500, "max_completion_tokens": 500},
    ],
)
def test_configuration_cannot_relax_guardrails(config: dict[str, Any]) -> None:
    source = request()
    source["provider_config"] = config
    provider = GemmaProvider(
        "gemma-4-31b-it",
        min_interval_seconds=0,
        transport=lambda *_: pytest.fail("Must not call API"),
    )
    with pytest.raises(ProviderFailure, match="INVALID_GEMMA_EXTRACTION_REQUEST"):
        provider(source)
    assert provider.calls == 0


def test_missing_environment_key_does_not_call_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY")
    provider = GemmaProvider(
        "gemma-4-31b-it",
        min_interval_seconds=0,
        transport=lambda *_: pytest.fail("Must not call API"),
    )
    with pytest.raises(ProviderFailure, match="PROVIDER_AUTHENTICATION_FAILED"):
        provider(request())
    assert provider.calls == 0


def test_credential_resolver_stays_out_of_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY")
    captured = []

    def transport(*args: Any) -> dict[str, Any]:
        captured.append(args)
        return envelope(json.dumps(payload()))

    provider = GemmaProvider(
        "gemma-4-31b-it",
        min_interval_seconds=0,
        transport=transport,
        credential=lambda: "separate-runtime-secret",
    )
    provider(request())
    assert captured[0][2]["x-goog-api-key"] == "separate-runtime-secret"
    assert "separate-runtime-secret" not in json.dumps(captured[0][1])


def test_config_mapping_is_explicit() -> None:
    source = request()
    source["provider_config"] = {"max_completion_tokens": 500, "top_p": 0.9, "seed": 2}
    captured = []

    def transport(*args: Any) -> dict[str, Any]:
        captured.append(args[1])
        return envelope(json.dumps(payload()))

    GemmaProvider("gemma-4-31b-it", min_interval_seconds=0, transport=transport)(source)
    assert captured[0]["generationConfig"] == {
        "temperature": 0,
        "candidateCount": 1,
        "maxOutputTokens": 500,
        "topP": 0.9,
        "seed": 2,
        "thinkingConfig": {"thinkingLevel": "minimal"},
    }
