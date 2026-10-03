"""Bounded public-source retrieval with explicit SEC identity and conservative pacing."""

import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

_SEC_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
_CBOE_HOSTS = frozenset({"cdn.cboe.com", "cdn-api.cboe.com"})
ALLOWED_HOSTS = _SEC_HOSTS | _CBOE_HOSTS | {"data.gdeltproject.org"}
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchedResponse:
    body: bytes
    url: str
    status_code: int
    retrieved_at: datetime


class SourceError(RuntimeError):
    def __init__(self, url: str, status_code: int | None = None) -> None:
        self.url = url
        self.status_code = status_code
        super().__init__(f"Public source retrieval failed: {url} (status={status_code})")


def validate_url(url: str) -> None:
    parts = urlparse(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in ALLOWED_HOSTS
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise ValueError("Source must be an approved public HTTPS endpoint")


def validate_redirect(source_url: str, destination_url: str) -> None:
    """Keep identity headers within one provider's official source hosts."""
    validate_url(source_url)
    validate_url(destination_url)
    source_host = urlparse(source_url).hostname
    destination_host = urlparse(destination_url).hostname
    if source_host != destination_host and not (
        (source_host in _SEC_HOSTS and destination_host in _SEC_HOSTS)
        or (source_host in _CBOE_HOSTS and destination_host in _CBOE_HOSTS)
    ):
        raise ValueError("Source redirects must remain within the same public provider")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_redirect(req.full_url, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


class HttpClient:
    def __init__(
        self,
        sec_user_agent: str | None,
        *,
        timeout: float = 30,
        attempts: int = 3,
        sec_requests_per_second: float = 2,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0 or not 1 <= attempts <= 5 or not 0 < sec_requests_per_second <= 5:
            raise ValueError("Invalid timeout, retry count or conservative SEC request rate")
        self.sec_user_agent = sec_user_agent
        self.timeout = timeout
        self.attempts = attempts
        self.interval = 1 / sec_requests_per_second
        self.sleeper = sleeper
        self.last_sec_request = 0.0
        self.opener = urllib.request.build_opener(SafeRedirect())

    def get(self, url: str) -> FetchedResponse:
        validate_url(url)
        is_sec = urlparse(url).hostname in _SEC_HOSTS
        agent = "Project_AI_in_Finance/0.1 research-ingestion"
        if is_sec:
            if not self.sec_user_agent or not re.search(
                r"[^\s@]+@[^\s@]+\.[^\s@]+", self.sec_user_agent
            ):
                raise ValueError("Set SB_SEC_USER_AGENT to project name and a real contact email")
            agent = self.sec_user_agent
        for attempt in range(self.attempts):
            if is_sec:
                delay = self.interval - (time.monotonic() - self.last_sec_request)
                if delay > 0:
                    self.sleeper(delay)
                self.last_sec_request = time.monotonic()
            request = urllib.request.Request(
                url, headers={"User-Agent": agent, "Accept-Encoding": "identity"}
            )
            status: int | None = None
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    status = response.status
                    validate_redirect(url, response.url)
                    body = response.read()
                    if status != 200 or not body:
                        raise SourceError(url, status)
                    return FetchedResponse(body, url, status, datetime.now(UTC))
            except urllib.error.HTTPError as error:
                status = error.code
                if status not in _RETRYABLE_HTTP_STATUSES:
                    raise SourceError(url, status) from None
            except SourceError as error:
                if error.status_code not in _RETRYABLE_HTTP_STATUSES | {200, None}:
                    raise
            except (urllib.error.URLError, TimeoutError):
                pass
            if attempt + 1 < self.attempts:
                self.sleeper(min(2**attempt, 8))
        raise SourceError(url, status)
