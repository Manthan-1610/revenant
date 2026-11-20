"""Polite HTTP access to the Internet Archive: User-Agent, rate limiting and retries."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol

import httpx

from revenant.exhume.content import is_offline_page

DEFAULT_USER_AGENT = "Revenant/0.1 (+https://github.com/Manthan-1610/revenant)"
MAX_ATTEMPTS = 5
MAX_BACKOFF = 60.0
TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)


class ArchiveError(Exception):
    """An Archive request still failed after the Retry_Policy stopped."""


class Clock(Protocol):
    """Source of monotonic time, UTC time and sleep; tests inject a fake."""

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def now_utc(self) -> datetime: ...


class SystemClock:
    """The real Clock, backed by `time` and `datetime`."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def now_utc(self) -> datetime:
        return datetime.now(UTC)


def user_agent() -> str:
    """Return the configured User-Agent: env `REVENANT_USER_AGENT` or the default."""
    return os.environ.get("REVENANT_USER_AGENT") or DEFAULT_USER_AGENT


class RateLimiter:
    """Keeps at least `min_interval` seconds between the starts of any two requests."""

    def __init__(self, clock: Clock, min_interval: float = 1.0) -> None:
        self._clock = clock
        self._min_interval = min_interval
        self._last_start: float | None = None

    def on_request(self, request: httpx.Request) -> None:
        """httpx request event hook; fires once per attempt and per redirect hop."""
        if self._last_start is not None:
            wait = self._last_start + self._min_interval - self._clock.monotonic()
            if wait > 0:
                self._clock.sleep(wait)
        self._last_start = self._clock.monotonic()


def make_client(
    limiter: RateLimiter, ua: str, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """Build the sync httpx client used for every Archive request."""
    return httpx.Client(
        headers={"User-Agent": ua},
        follow_redirects=True,
        timeout=TIMEOUT,
        event_hooks={"request": [limiter.on_request]},
        transport=transport,
    )


def parse_retry_after(value: str | None, now: datetime) -> float:
    """Seconds to wait from a `Retry-After` value (integer seconds or HTTP date), else 0."""
    if value is None:
        return 0.0
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return 0.0
    if when is None:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def backoff_delay(attempt: int, retry_after: float) -> float:
    """Wait after attempt `attempt` (1-based): min(60, max(2 * 2**(attempt-1), retry_after))."""
    return min(MAX_BACKOFF, max(2.0 * 2 ** (attempt - 1), retry_after))


def _retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


class ArchiveClient:
    """Sends Archive requests one at a time and applies the Retry_Policy."""

    def __init__(self, client: httpx.Client, clock: Clock) -> None:
        self._client = client
        self._clock = clock

    def get(self, url: str, params: list[tuple[str, str]] | None = None) -> httpx.Response:
        """GET with up to 5 attempts; returns any non-retryable response, including 4xx.

        Connection errors, timeouts, 429, 5xx and Offline pages (any status) are retried.
        """
        last_problem = "no attempt made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            retry_after = 0.0
            try:
                response = self._client.get(url, params=params)
            except (httpx.TooManyRedirects, httpx.DecodingError) as exc:
                # Not TransportErrors and not transient: fail now, with no retry or sleep.
                raise ArchiveError(f"GET {url} failed: {type(exc).__name__}: {exc}") from exc
            except httpx.TransportError as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
            else:
                if is_offline_page(response.headers.get("content-type"), response.content):
                    # F9: the outage page can come with any status, including 200.
                    last_problem = f"Offline page (HTTP {response.status_code})"
                elif not _retryable_status(response.status_code):
                    return response
                else:
                    last_problem = f"HTTP {response.status_code}"
                retry_after = parse_retry_after(
                    response.headers.get("Retry-After"), self._clock.now_utc()
                )
            if attempt < MAX_ATTEMPTS:
                self._clock.sleep(backoff_delay(attempt, retry_after))
        raise ArchiveError(f"GET {url} failed after {MAX_ATTEMPTS} attempts: {last_problem}")
