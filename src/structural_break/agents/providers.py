"""Budgeted Phase 5 providers, separate from the frozen SEC catalyst extractor.

Gemma receives an explicit schema in its prompt. Flash-Lite uses JSON structured
output. Strict contract/citation/semantic validation remains the graph's job;
schema-constrained generation is not evidence of semantic accuracy.
"""

import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol

from structural_break.agents.budgets import DurableAttemptJournal, fingerprint
from structural_break.agents.prompts import ROLES
from structural_break.intelligence.extraction import ProviderFailure

ADAPTER_VERSION = "phase5-google-role-provider-v1"
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/"
_ADVOCATE_ROLES = frozenset(ROLES[:4])
Transport = Callable[[str, dict[str, Any], dict[str, str], float], Mapping[str, Any]]


class AgentProvider(Protocol):
    @property
    def mode(self) -> Literal["mock", "live"]: ...

    @property
    def identity(self) -> dict[str, object]: ...

    @property
    def calls(self) -> int: ...

    def identity_for(self, role: str) -> dict[str, object]: ...

    def generate(
        self, role: str, prompt: str, output_schema: dict[str, object]
    ) -> dict[str, object]: ...


def _environment_key() -> str | None:
    return os.environ.get("SB_LLM_API_KEY") or os.environ.get("GEMINI_API_KEY")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _no_constant(value: str) -> Any:
    raise ValueError("Non-finite JSON number")


def _reject_nonfinite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite JSON number")
    if isinstance(value, dict):
        for child in value.values():
            _reject_nonfinite(child)
    elif isinstance(value, list):
        for child in value:
            _reject_nonfinite(child)


def _strict_json(text: str) -> dict[str, object]:
    decoded: object = json.loads(
        text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constant
    )
    if not isinstance(decoded, dict):
        raise ValueError("Expected a JSON object")
    # 1e1000 overflows Python float without passing through parse_constant.
    _reject_nonfinite(decoded)
    return decoded


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the credential header away from the fixed API endpoint."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise ProviderFailure("PROVIDER_REDIRECT_REJECTED", retriable=False)


def _http_transport(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":"), allow_nan=False).encode(),
        headers=headers,
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(256_001)
    if len(raw) > 256_000:
        raise ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE", retriable=False)
    try:
        return _strict_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise ProviderFailure("INVALID_PROVIDER_RESPONSE", retriable=False) from None


def _valid_int(value: int, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _bounded_float(value: float, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise ProviderFailure("INVALID_AGENT_ROLE", retriable=False)


class GeminiAgentProvider:
    """Free-tier, exact shared call budgets with no SDK retries or model fallback.

    One transport attempt is one charged call, even if it times out or fails. The
    entire instance serializes attempts so concurrent advocates share pacing and
    counters. Counts are invocation-local, not assertions about project quotas or
    durable accounting for failed requests from previous runs. Authentication is
    global; rate/quota/model/request failures latch the affected model. The graph
    must fail closed if any required role cannot produce a valid report.
    """

    mode: Literal["live"] = "live"

    def __init__(
        self,
        *,
        advocate_model: str = "gemma-4-26b-a4b-it",
        reviewer_model: str = "gemini-3.1-flash-lite",
        max_calls: int = 60,
        advocate_max_calls: int = 40,
        reviewer_max_calls: int = 20,
        timeout_seconds: float = 60,
        max_retries: int = 1,
        advocate_min_interval_seconds: float = 32,
        reviewer_min_interval_seconds: float = 5,
        max_prompt_chars: int = 64_000,
        max_output_tokens: int = 2400,
        max_response_chars: int = 24_000,
        transport: Transport | None = None,
        credential: Callable[[], str | None] | None = None,
        attempt_journal: DurableAttemptJournal | None = None,
    ) -> None:
        if not re.fullmatch(r"gemma-[a-z0-9.-]+", advocate_model):
            raise ValueError("A pinned Gemma advocate model is required")
        if not re.fullmatch(r"gemini-[a-z0-9.-]*flash-lite[a-z0-9.-]*", reviewer_model):
            raise ValueError("A pinned Gemini Flash-Lite reviewer model is required")
        if (
            not _valid_int(max_calls, 1, 100_000)
            or not _valid_int(advocate_max_calls, 0, 100_000)
            or not _valid_int(reviewer_max_calls, 0, 100_000)
            or not _valid_int(max_retries, 0, 2)
            or not _bounded_float(timeout_seconds, 0.1, 300)
            or not _bounded_float(advocate_min_interval_seconds, 0, 300)
            or not _bounded_float(reviewer_min_interval_seconds, 0, 300)
            or not _valid_int(max_prompt_chars, 1, 64_000)
            or not _valid_int(max_output_tokens, 128, 4096)
            or not _valid_int(max_response_chars, 1, 32_000)
        ):
            raise ValueError("Invalid agent provider limits")
        self.advocate_model = advocate_model
        self.reviewer_model = reviewer_model
        self.max_calls = max_calls
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = max_retries
        self.max_prompt_chars = max_prompt_chars
        self.max_output_tokens = max_output_tokens
        self.max_response_chars = max_response_chars
        self._caps = {advocate_model: advocate_max_calls, reviewer_model: reviewer_max_calls}
        self._intervals = {
            advocate_model: float(advocate_min_interval_seconds),
            reviewer_model: float(reviewer_min_interval_seconds),
        }
        self._transport = transport or _http_transport
        self._credential = credential or _environment_key
        self._attempt_journal = attempt_journal
        self._lock = threading.Lock()
        self._calls = 0
        self._model_calls = {advocate_model: 0, reviewer_model: 0}
        self._last_call = {advocate_model: float("-inf"), reviewer_model: float("-inf")}
        self._blocked_models: dict[str, str] = {}
        self._global_block: str | None = None

    @property
    def identity(self) -> dict[str, object]:
        # Counters and credentials never enter identity: it is stable throughout a run.
        return {
            "adapter_version": ADAPTER_VERSION,
            "provider": "google-generative-language",
            "mode": self.mode,
            "advocate_model": self.advocate_model,
            "reviewer_model": self.reviewer_model,
            "max_calls": self.max_calls,
            "model_call_caps": dict(self._caps),
            "model_min_intervals": dict(self._intervals),
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "max_prompt_chars": self.max_prompt_chars,
            "max_output_tokens": self.max_output_tokens,
            "max_response_chars": self.max_response_chars,
            "temperature": 0,
            "candidate_count": 1,
            "gemma_thinking": "minimal",
            "reviewer_calls_per_complete_event": 2,
            "tools": False,
            "fallback": False,
            "durable_budget": (
                self._attempt_journal.identity if self._attempt_journal is not None else None
            ),
        }

    def identity_for(self, role: str) -> dict[str, object]:
        _check_role(role)
        return {**self.identity, "role": role, "model": self._model_for(role)}

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    @property
    def calls_by_model(self) -> dict[str, int]:
        with self._lock:
            return dict(self._model_calls)

    def _model_for(self, role: str) -> str:
        return self.advocate_model if role in _ADVOCATE_ROLES else self.reviewer_model

    def _request(
        self, role: str, prompt: str, output_schema: dict[str, object]
    ) -> tuple[str, dict[str, Any]]:
        _check_role(role)
        try:
            if not isinstance(prompt, str) or not prompt or not isinstance(output_schema, dict):
                raise ValueError("Invalid prompt/schema")
            if output_schema.get("type") != "object":
                raise ValueError("Response schema must describe an object")
            schema_json = json.dumps(
                output_schema, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (ValueError, TypeError, RecursionError):
            raise ProviderFailure("INVALID_AGENT_PROVIDER_REQUEST", retriable=False) from None
        model = self._model_for(role)
        complete_prompt = f"{prompt}\nREQUIRED JSON SCHEMA\n{schema_json}"
        if len(complete_prompt) > self.max_prompt_chars:
            raise ProviderFailure("AGENT_PROMPT_BOUNDS_EXCEEDED", retriable=False)
        generation: dict[str, Any] = {
            "temperature": 0,
            "candidateCount": 1,
            "maxOutputTokens": self.max_output_tokens,
        }
        if role in _ADVOCATE_ROLES:
            if model.startswith("gemma-4-"):
                generation["thinkingConfig"] = {"thinkingLevel": "minimal"}
        else:
            generation["responseMimeType"] = "application/json"
            generation["responseJsonSchema"] = output_schema
        return model, {
            "contents": [{"role": "user", "parts": [{"text": complete_prompt}]}],
            "generationConfig": generation,
        }

    def _decode(self, response: Mapping[str, Any]) -> dict[str, object]:
        try:
            candidates = response.get("candidates")
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise ValueError("Expected one response candidate")
            candidate = candidates[0]
            if candidate.get("finishReason") != "STOP":
                raise ProviderFailure("INCOMPLETE_PROVIDER_RESPONSE", retriable=False)
            parts = candidate["content"]["parts"]
            if (
                not isinstance(parts, list)
                or not 1 <= len(parts) <= 4
                or any(
                    not isinstance(part, dict)
                    or set(part) not in ({"text"}, {"text", "thought"})
                    or not isinstance(part.get("text"), str)
                    or len(part["text"]) > self.max_response_chars
                    or ("thought" in part and part["thought"] is not True)
                    for part in parts
                )
            ):
                raise ValueError("Invalid response protocol parts")
            final_parts = [part for part in parts if "thought" not in part]
            if len(final_parts) != 1:
                raise ValueError("Expected exactly one final text part")
            return _strict_json(final_parts[0]["text"])
        except ProviderFailure:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError):
            raise ProviderFailure("INVALID_PROVIDER_RESPONSE", retriable=False) from None

    def _transport_failure(self, error: Exception, model: str) -> ProviderFailure:
        code = getattr(error, "code", None) or getattr(error, "status_code", None)
        if code in {401, 403}:
            self._global_block = "PROVIDER_AUTHENTICATION_FAILED"
            return ProviderFailure(self._global_block, retriable=False)
        permanent_reasons = {
            429: "PROVIDER_QUOTA_OR_RATE_LIMIT",
            404: "PROVIDER_MODEL_UNAVAILABLE",
            400: "PROVIDER_REQUEST_REJECTED",
        }
        reason = permanent_reasons.get(code) if isinstance(code, int) else None
        if reason is not None:
            self._blocked_models[model] = reason
            return ProviderFailure(reason, retriable=False)
        if isinstance(error, ProviderFailure):
            # Only the adapter's own bounded transport codes are allowed through.
            if error.reason in {
                "PROVIDER_RESPONSE_TOO_LARGE",
                "INVALID_PROVIDER_RESPONSE",
                "PROVIDER_REDIRECT_REJECTED",
            }:
                return ProviderFailure(error.reason, retriable=False)
        if isinstance(error, TimeoutError) or isinstance(
            getattr(error, "reason", None), TimeoutError
        ):
            return ProviderFailure("PROVIDER_TIMEOUT")
        return ProviderFailure("PROVIDER_UNAVAILABLE")

    def generate(
        self, role: str, prompt: str, output_schema: dict[str, object]
    ) -> dict[str, object]:
        model, payload = self._request(role, prompt, output_schema)
        with self._lock:
            for attempt in range(self.max_retries + 1):
                if self._global_block is not None:
                    raise ProviderFailure(self._global_block, retriable=False)
                if model in self._blocked_models:
                    raise ProviderFailure(self._blocked_models[model], retriable=False)
                if self._calls >= self.max_calls or self._model_calls[model] >= self._caps[model]:
                    raise ProviderFailure("REQUEST_BUDGET_EXHAUSTED", retriable=False)
                try:
                    key = self._credential()
                except Exception:
                    key = None
                if not isinstance(key, str) or not key.strip():
                    self._global_block = "PROVIDER_AUTHENTICATION_FAILED"
                    raise ProviderFailure(self._global_block, retriable=False)
                delay = max(
                    0.0, self._intervals[model] - (time.monotonic() - self._last_call[model])
                )
                if delay:
                    time.sleep(delay)
                if self._attempt_journal is not None:
                    self._attempt_journal.reserve(
                        model=model,
                        role=role,
                        request_sha256=fingerprint(
                            {"role": role, "model": model, "payload": payload}
                        ),
                    )
                self._last_call[model] = time.monotonic()
                self._calls += 1
                self._model_calls[model] += 1
                try:
                    response = self._transport(
                        _ENDPOINT + model + ":generateContent",
                        payload,
                        {"Content-Type": "application/json", "x-goog-api-key": key},
                        self.timeout_seconds,
                    )
                except Exception as error:
                    failure = self._transport_failure(error, model)
                    if failure.retriable and attempt < self.max_retries:
                        continue
                    raise failure from None
                return self._decode(response)
        raise AssertionError("Bounded provider loop must return or raise")


class ScriptedProvider:
    """Deterministic fixture outputs for engineering checks, never model evaluation.

    Identity binds the full supplied role script so changing mock results cannot
    reuse a previous cache. Responses are copied and all requests are counted.
    """

    mode: Literal["mock"] = "mock"

    def __init__(
        self,
        responses: Mapping[str, dict[str, object]],
        *,
        max_calls: int = 100,
        attempt_journal: DurableAttemptJournal | None = None,
    ) -> None:
        if not _valid_int(max_calls, 1, 100_000) or set(responses) - set(ROLES):
            raise ValueError("Invalid scripted provider roles or budget")
        try:
            raw = json.dumps(responses, sort_keys=True, separators=(",", ":"), allow_nan=False)
            parsed = _strict_json(raw)
            if any(not isinstance(value, dict) for value in parsed.values()):
                raise ValueError("Each scripted role needs an object")
        except (ValueError, TypeError, RecursionError):
            raise ValueError("Scripted responses must be finite JSON objects") from None
        self._responses = parsed
        self._script_sha256 = hashlib.sha256(raw.encode()).hexdigest()
        self.max_calls = max_calls
        self._attempt_journal = attempt_journal
        self._calls = 0
        self._roles: list[str] = []
        self._lock = threading.Lock()

    @property
    def identity(self) -> dict[str, object]:
        return {
            "provider": "scripted-fixture",
            "adapter_version": "phase5-scripted-provider-v1",
            "mode": self.mode,
            "script_sha256": self._script_sha256,
            "max_calls": self.max_calls,
            "quality_evidence": False,
            "durable_budget": (
                self._attempt_journal.identity if self._attempt_journal is not None else None
            ),
        }

    def identity_for(self, role: str) -> dict[str, object]:
        _check_role(role)
        return {**self.identity, "role": role, "model": "scripted-fixture"}

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    @property
    def called_roles(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._roles)

    def generate(
        self, role: str, prompt: str, output_schema: dict[str, object]
    ) -> dict[str, object]:
        _check_role(role)
        if not isinstance(prompt, str) or not prompt or output_schema.get("type") != "object":
            raise ProviderFailure("INVALID_AGENT_PROVIDER_REQUEST", retriable=False)
        with self._lock:
            if self._calls >= self.max_calls:
                raise ProviderFailure("REQUEST_BUDGET_EXHAUSTED", retriable=False)
            if self._attempt_journal is not None:
                self._attempt_journal.reserve(
                    model="scripted-fixture",
                    role=role,
                    request_sha256=fingerprint(
                        {"role": role, "prompt": prompt, "schema": output_schema}
                    ),
                )
            self._calls += 1
            self._roles.append(role)
            if role not in self._responses:
                raise ProviderFailure("MOCK_RESPONSE_UNAVAILABLE", retriable=False)
            return _strict_json(json.dumps(self._responses[role], allow_nan=False))
