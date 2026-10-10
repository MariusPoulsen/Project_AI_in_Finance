"""HTTP failure, pacing, identity and redirect checks without live requests."""

import http.client
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

import pytest

from structural_break.data.http import HttpClient, SafeRedirect, SourceError, validate_url

SEC_URL = "https://data.sec.gov/submissions/CIK0000021344.json"
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
CBOE_API_URL = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
TEST_AGENT = "Example Project tests@example.invalid"


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.delays.append(duration)
        self.now += duration


class FakeResponse:
    def __init__(
        self,
        body: bytes = b"source bytes",
        status: int = 200,
        url: str = SEC_URL,
        *,
        read_error: Exception | None = None,
        exit_error: Exception | None = None,
    ):
        self.body = body
        self.status = status
        self.url = url
        self.read_error = read_error
        self.exit_error = exit_error
        self.read_calls = 0
        self.exit_calls = 0

    def read(self) -> bytes:
        self.read_calls += 1
        if self.read_error is not None:
            raise self.read_error
        return self.body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        self.exit_calls += 1
        if self.exit_error is not None:
            raise self.exit_error
        return None


class FakeOpener:
    def __init__(self, outcomes: list[FakeResponse | Exception], clock: FakeClock) -> None:
        self.outcomes = iter(outcomes)
        self.clock = clock
        self.calls: list[tuple[urllib.request.Request, float, float]] = []

    def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout, self.clock.now))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client_with_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[FakeResponse | Exception],
    *,
    agent: str | None = TEST_AGENT,
    **options: Any,
) -> tuple[HttpClient, FakeOpener, FakeClock]:
    clock = FakeClock()
    opener = FakeOpener(outcomes, clock)
    monkeypatch.setattr("structural_break.data.http.time.monotonic", clock.monotonic)
    monkeypatch.setattr(urllib.request, "build_opener", lambda _: opener)
    client = HttpClient(agent, sleeper=clock.sleep, **options)
    return client, opener, clock


@pytest.mark.parametrize(
    "url",
    [
        SEC_URL,
        "https://www.sec.gov/files/company_tickers.json",
        CBOE_URL,
        CBOE_API_URL,
        "https://data.gdeltproject.org/gdeltv3/gal/file.json.gz",
        "https://data.sec.gov:443/submissions/CIK0000021344.json",
    ],
)
def test_approved_public_https_urls_are_allowed(url: str) -> None:
    validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://data.sec.gov/submissions/file.json",
        "https://example.invalid/file.json",
        "https://data.sec.gov.example.invalid/file.json",
        "https://localhost/file.json",
        "https://127.0.0.1/file.json",
        "https://user:password@data.sec.gov/file.json",
        "https://user@data.sec.gov/file.json",
        "https://data.sec.gov:8443/file.json",
        "file:///tmp/source.json",
    ],
)
def test_unapproved_or_credentialed_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize("agent", [None, "", "Example Project", "bad-contact@invalid"])
def test_sec_contact_is_required_before_any_request(
    monkeypatch: pytest.MonkeyPatch, agent: str | None
) -> None:
    client, opener, clock = client_with_outcomes(monkeypatch, [], agent=agent)
    with pytest.raises(ValueError, match="SB_SEC_USER_AGENT"):
        client.get(SEC_URL)
    assert not opener.calls
    assert not clock.delays


def test_success_keeps_source_bytes_and_records_utc_retrieval(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body = b'{"raw": "unchanged"}\r\n'
    client, opener, clock = client_with_outcomes(monkeypatch, [FakeResponse(body)], timeout=12)
    before = datetime.now(UTC)
    response = client.get(SEC_URL)
    assert response.body == body
    assert response.url == SEC_URL
    assert response.status_code == 200
    assert before <= response.retrieved_at <= datetime.now(UTC)
    assert response.retrieved_at.tzinfo == UTC
    request, timeout, _ = opener.calls[0]
    assert request.get_header("User-agent") == TEST_AGENT
    assert request.get_header("Accept-encoding") == "identity"
    assert timeout == 12
    assert not clock.delays
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_non_sec_source_needs_no_contact_and_uses_project_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, opener, clock = client_with_outcomes(
        monkeypatch, [FakeResponse(url=CBOE_URL)], agent=None
    )
    assert client.get(CBOE_URL).body == b"source bytes"
    assert opener.calls[0][0].get_header("User-agent") == (
        "Project_AI_in_Finance/0.1 research-ingestion"
    )
    assert not clock.delays


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_http_error_has_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    error = urllib.error.HTTPError(SEC_URL, status, "temporary", {}, None)
    client, opener, clock = client_with_outcomes(
        monkeypatch, [error, error, FakeResponse()], attempts=3
    )
    assert client.get(SEC_URL).status_code == 200
    assert len(opener.calls) == 3
    assert clock.delays == [1, 2]


@pytest.mark.parametrize("error", [TimeoutError(), urllib.error.URLError("unavailable")])
def test_transport_failure_retries_and_stops_at_configured_attempt_count(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    client, opener, clock = client_with_outcomes(monkeypatch, [error] * 3, attempts=3)
    with pytest.raises(SourceError) as caught:
        client.get(SEC_URL)
    assert len(opener.calls) == 3
    assert clock.delays == [1, 2]
    assert caught.value.status_code is None
    assert TEST_AGENT not in str(caught.value)


_DROPPED_CONNECTION_ERRORS = [
    pytest.param(http.client.RemoteDisconnected("peer closed"), id="remote-disconnected"),
    pytest.param(ConnectionResetError("peer reset"), id="connection-reset"),
    pytest.param(ConnectionAbortedError("connection aborted"), id="connection-aborted"),
    pytest.param(BrokenPipeError("broken pipe"), id="broken-pipe"),
    pytest.param(http.client.IncompleteRead(b"partial", 100), id="incomplete-read"),
]


def transport_outcome(error: Exception, stage: str) -> FakeResponse | Exception:
    if stage == "open":
        return error
    if stage == "read":
        return FakeResponse(read_error=error)
    return FakeResponse(exit_error=error)


@pytest.mark.parametrize("error", _DROPPED_CONNECTION_ERRORS)
@pytest.mark.parametrize("stage", ["open", "read", "close"])
def test_dropped_response_retries_without_returning_partial_bytes(
    monkeypatch: pytest.MonkeyPatch, error: Exception, stage: str
) -> None:
    dropped = transport_outcome(error, stage)
    complete = FakeResponse(b"complete source bytes")
    client, opener, clock = client_with_outcomes(monkeypatch, [dropped, complete])
    response = client.get(SEC_URL)
    assert response.body == b"complete source bytes"
    assert response.url == SEC_URL and response.status_code == 200
    assert len(opener.calls) == 2
    assert clock.delays == [1]
    assert all(call[0].get_header("User-agent") == TEST_AGENT for call in opener.calls)
    assert all(call[0].get_header("Accept-encoding") == "identity" for call in opener.calls)
    assert complete.exit_calls == 1
    if isinstance(dropped, FakeResponse):
        assert dropped.exit_calls == 1


@pytest.mark.parametrize("error", _DROPPED_CONNECTION_ERRORS)
@pytest.mark.parametrize("stage", ["open", "read", "close"])
def test_dropped_response_exhausts_only_existing_attempt_budget(
    monkeypatch: pytest.MonkeyPatch, error: Exception, stage: str
) -> None:
    outcomes = [transport_outcome(error, stage) for _ in range(3)]
    client, opener, clock = client_with_outcomes(monkeypatch, outcomes, attempts=3)
    with pytest.raises(SourceError) as caught:
        client.get(SEC_URL)
    assert len(opener.calls) == 3
    assert clock.delays == [1, 2]
    assert caught.value.url == SEC_URL
    assert caught.value.status_code == (None if stage == "open" else 200)
    assert TEST_AGENT not in str(caught.value)
    assert b"partial".decode() not in str(caught.value)
    for outcome in outcomes:
        if isinstance(outcome, FakeResponse):
            assert outcome.exit_calls == 1


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("not a transport failure"),
        ValueError("invalid source"),
        http.client.BadStatusLine("malformed response"),
    ],
)
@pytest.mark.parametrize("stage", ["open", "read"])
def test_nontransient_response_failure_is_never_retried(
    monkeypatch: pytest.MonkeyPatch, error: Exception, stage: str
) -> None:
    failed = transport_outcome(error, stage)
    client, opener, clock = client_with_outcomes(monkeypatch, [failed])
    with pytest.raises(type(error)):
        client.get(SEC_URL)
    assert len(opener.calls) == 1
    assert not clock.delays
    if isinstance(failed, FakeResponse):
        assert failed.exit_calls == 1


@pytest.mark.parametrize("status", [401, 403, 404])
def test_permanent_status_is_not_retried_when_response_cleanup_disconnects(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    failed = FakeResponse(status=status, exit_error=http.client.RemoteDisconnected("peer closed"))
    client, opener, clock = client_with_outcomes(monkeypatch, [failed])
    with pytest.raises(SourceError) as caught:
        client.get(SEC_URL)
    assert caught.value.status_code == status
    assert len(opener.calls) == 1 and not clock.delays
    assert failed.read_calls == 0 and failed.exit_calls == 1


def test_rejected_redirect_is_not_retried_when_response_cleanup_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = FakeResponse(url=CBOE_URL, exit_error=http.client.RemoteDisconnected("peer closed"))
    client, opener, clock = client_with_outcomes(monkeypatch, [failed])
    with pytest.raises(ValueError, match="same public provider"):
        client.get(SEC_URL)
    assert len(opener.calls) == 1 and not clock.delays
    assert failed.read_calls == 0 and failed.exit_calls == 1


@pytest.mark.parametrize("status", [401, 403, 404])
def test_permanent_http_error_has_no_retry_or_identity_in_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    error = urllib.error.HTTPError(SEC_URL, status, "permanent", {}, None)
    client, opener, clock = client_with_outcomes(monkeypatch, [error], attempts=3)
    with pytest.raises(SourceError) as caught:
        client.get(SEC_URL)
    assert caught.value.status_code == status
    assert caught.value.url == SEC_URL
    assert len(opener.calls) == 1
    assert not clock.delays
    assert TEST_AGENT not in str(caught.value)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_returned_permanent_status_is_never_retried(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    client, opener, clock = client_with_outcomes(
        monkeypatch, [FakeResponse(status=status)], attempts=3
    )
    with pytest.raises(SourceError) as caught:
        client.get(SEC_URL)
    assert caught.value.status_code == status
    assert len(opener.calls) == 1
    assert not clock.delays


@pytest.mark.parametrize("status", [429, 503])
def test_returned_temporary_status_retries_until_success(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    client, opener, clock = client_with_outcomes(
        monkeypatch, [FakeResponse(status=status), FakeResponse()], attempts=3
    )
    assert client.get(SEC_URL).status_code == 200
    assert len(opener.calls) == 2
    assert clock.delays == [1]


def test_retry_exhaustion_preserves_final_http_status(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(SEC_URL, 503, "unavailable", {}, None)
    client, opener, clock = client_with_outcomes(monkeypatch, [error] * 5, attempts=5)
    with pytest.raises(SourceError) as caught:
        client.get(SEC_URL)
    assert caught.value.status_code == 503
    assert len(opener.calls) == 5
    assert clock.delays == [1, 2, 4, 8]


def test_empty_successful_body_is_never_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    client, opener, clock = client_with_outcomes(monkeypatch, [FakeResponse(b"")] * 3, attempts=3)
    with pytest.raises(SourceError) as caught:
        client.get(SEC_URL)
    assert caught.value.status_code == 200
    assert len(opener.calls) == 3
    assert clock.delays == [1, 2]


def test_sec_requests_observe_configured_rate_without_real_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, opener, clock = client_with_outcomes(
        monkeypatch, [FakeResponse()] * 3, sec_requests_per_second=2
    )
    for _ in range(3):
        client.get(SEC_URL)
    assert [call[2] for call in opener.calls] == [100, 100.5, 101]
    assert clock.delays == [0.5, 0.5]


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"timeout": -1},
        {"attempts": 0},
        {"attempts": 6},
        {"sec_requests_per_second": 0},
        {"sec_requests_per_second": 6},
    ],
)
def test_invalid_timeout_retry_count_or_sec_rate_is_rejected(options: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="Invalid timeout"):
        HttpClient(TEST_AGENT, **options)


def test_unsafe_response_url_rejects_unexpected_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, opener, _ = client_with_outcomes(
        monkeypatch, [FakeResponse(url="https://example.invalid/source.json")]
    )
    with pytest.raises(ValueError, match="approved public HTTPS"):
        client.get(SEC_URL)
    assert len(opener.calls) == 1


def test_safe_redirect_allows_sec_metadata_host_and_rejects_external_host() -> None:
    request = urllib.request.Request("https://www.sec.gov/files/source.json")
    handler = SafeRedirect()
    redirected = handler.redirect_request(request, None, 302, "found", {}, SEC_URL)
    assert redirected is not None and redirected.full_url == SEC_URL
    for unsafe in ("http://data.sec.gov/file.json", "https://example.invalid/file.json"):
        with pytest.raises(ValueError, match="approved public HTTPS"):
            handler.redirect_request(request, None, 302, "found", {}, unsafe)


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        (SEC_URL, CBOE_URL),
        (SEC_URL, "https://data.gdeltproject.org/source.json"),
        (CBOE_URL, SEC_URL),
        ("https://data.gdeltproject.org/source.json", SEC_URL),
        (CBOE_URL, "https://data.gdeltproject.org/source.json"),
        (CBOE_API_URL, SEC_URL),
        (SEC_URL, CBOE_API_URL),
    ],
)
def test_redirect_cannot_cross_provider_identity_boundary(source: str, destination: str) -> None:
    request = urllib.request.Request(source, headers={"User-Agent": TEST_AGENT})
    with pytest.raises(ValueError, match="same public provider"):
        SafeRedirect().redirect_request(request, None, 302, "found", {}, destination)


def test_sec_redirect_preserves_declared_contact_within_official_hosts() -> None:
    request = urllib.request.Request(
        "https://www.sec.gov/files/source.json", headers={"User-Agent": TEST_AGENT}
    )
    redirect = SafeRedirect().redirect_request(request, None, 302, "found", {}, SEC_URL)
    assert redirect is not None
    assert redirect.get_header("User-agent") == TEST_AGENT


@pytest.mark.parametrize(
    ("source", "destination"), [(CBOE_URL, CBOE_API_URL), (CBOE_API_URL, CBOE_URL)]
)
def test_cboe_redirect_allows_both_official_cdn_hosts(source: str, destination: str) -> None:
    request = urllib.request.Request(source, headers={"User-Agent": "Example Project"})
    redirect = SafeRedirect().redirect_request(
        request, None, 307, "temporary redirect", {}, destination
    )
    assert redirect is not None
    assert redirect.full_url == destination
    assert redirect.get_header("User-agent") == "Example Project"


def test_cboe_source_preserves_original_url_after_official_cdn_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, opener, _ = client_with_outcomes(
        monkeypatch, [FakeResponse(url=CBOE_API_URL)], agent=None
    )
    response = client.get(CBOE_URL)
    assert response.url == CBOE_URL
    assert response.body == b"source bytes"
    assert len(opener.calls) == 1


@pytest.mark.parametrize(
    ("source", "destination", "agent"),
    [(SEC_URL, CBOE_URL, TEST_AGENT), (CBOE_URL, SEC_URL, None)],
)
def test_response_provider_is_checked_even_if_opener_bypasses_redirect_handler(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    destination: str,
    agent: str | None,
) -> None:
    client, opener, clock = client_with_outcomes(
        monkeypatch, [FakeResponse(url=destination)], agent=agent
    )
    with pytest.raises(ValueError, match="same public provider"):
        client.get(source)
    assert len(opener.calls) == 1
    assert not clock.delays
