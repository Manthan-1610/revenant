"""Tests for the polite Archive client (revenant/exhume/archive.py)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from email.utils import format_datetime
from itertools import pairwise

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from revenant.exhume.archive import (
    DEFAULT_USER_AGENT,
    ArchiveClient,
    ArchiveError,
    RateLimiter,
    backoff_delay,
    make_client,
    parse_retry_after,
    user_agent,
)
from tests.exhume.conftest import FAKE_EPOCH, FakeClock

F6_SOURCE = (
    "https://web.archive.org/web/20131213000000id_/http://ichart.yahoo.com:80/table.csv"
    "?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv"
)
F6_TARGET = (
    "https://web.archive.org/web/20131213174436id_/http://ichart.yahoo.com/table.csv"
    "?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv"
)
PLAIN_URL = (
    "https://web.archive.org/web/20131213174436id_/http://ichart.yahoo.com:80/table.csv"
    "?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv"
)

Outcome = tuple[str, int, dict[str, str]]  # (kind, status, headers); kind "response" | "connect"


class Recorder:
    """MockTransport handler that records request starts on the FakeClock."""

    def __init__(self, clock: FakeClock, outcomes: list[Outcome] | None = None) -> None:
        self.clock = clock
        self.outcomes = list(outcomes or [])
        self.starts: list[float] = []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.starts.append(self.clock.monotonic())
        self.requests.append(request)
        if str(request.url) == F6_SOURCE:
            return httpx.Response(302, headers={"Location": F6_TARGET})
        kind, status, headers = self.outcomes.pop(0) if self.outcomes else ("response", 200, {})
        if kind == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(status, headers=headers, content=b"Date,Open\n")


def build(
    outcomes: list[Outcome] | None = None, ua: str = DEFAULT_USER_AGENT
) -> tuple[ArchiveClient, FakeClock, Recorder]:
    clock = FakeClock()
    recorder = Recorder(clock, outcomes)
    client = make_client(RateLimiter(clock), ua, transport=httpx.MockTransport(recorder))
    return ArchiveClient(client, clock), clock, recorder


# --- Property 4 ---------------------------------------------------------------------------

outcome_strategy: st.SearchStrategy[Outcome] = st.one_of(
    st.just(("response", 200, {})),
    st.just(("response", 404, {})),
    st.just(("response", 429, {})),
    st.integers(min_value=0, max_value=120).map(
        lambda s: ("response", 429, {"Retry-After": str(s)})
    ),
    st.sampled_from([500, 502, 503, 504]).map(lambda s: ("response", s, {})),
    st.just(("connect", 0, {})),
)


# Feature: exhume, Property 4: Rate limiter spacing
@settings(max_examples=100, deadline=None)
@given(
    calls=st.lists(st.booleans(), min_size=1, max_size=8),
    outcomes=st.lists(outcome_strategy, max_size=30),
)
def test_rate_limiter_spacing(calls: list[bool], outcomes: list[Outcome]) -> None:
    """**Validates: Requirements 6.1**"""
    archive, _clock, recorder = build(outcomes)
    for redirect in calls:
        try:
            archive.get(F6_SOURCE if redirect else PLAIN_URL)
        except ArchiveError:
            pass
    starts = recorder.starts
    assert len(starts) >= len(calls)
    for earlier, later in pairwise(starts):
        assert later - earlier >= 1.0


def test_redirect_hops_are_spaced() -> None:
    archive, _clock, recorder = build()
    response = archive.get(F6_SOURCE)
    assert response.status_code == 200
    assert [str(r.url) for r in recorder.requests] == [F6_SOURCE, F6_TARGET]
    assert recorder.starts[1] - recorder.starts[0] >= 1.0


# --- Retry and backoff --------------------------------------------------------------------


def test_backoff_delay_values() -> None:
    assert [backoff_delay(k, 0) for k in range(1, 5)] == [2, 4, 8, 16]
    assert backoff_delay(1, 30) == 30
    assert backoff_delay(1, 500) == 60
    assert backoff_delay(10, 0) == 60


def test_five_attempts_then_archive_error_with_backoff_sequence() -> None:
    archive, clock, recorder = build([("response", 503, {})] * 10)
    with pytest.raises(ArchiveError):
        archive.get(PLAIN_URL)
    assert len(recorder.requests) == 5
    assert clock.sleeps == [2, 4, 8, 16]


def test_connection_errors_are_retried() -> None:
    archive, clock, recorder = build([("connect", 0, {})] * 2)
    assert archive.get(PLAIN_URL).status_code == 200
    assert len(recorder.requests) == 3
    assert clock.sleeps == [2, 4]


def test_404_is_returned_after_one_attempt() -> None:
    archive, clock, recorder = build([("response", 404, {})])
    assert archive.get(PLAIN_URL).status_code == 404
    assert len(recorder.requests) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (lambda: "30", 30),
        (lambda: "120", 60),
        (lambda: format_datetime(FAKE_EPOCH + timedelta(seconds=45), usegmt=True), 45),
        (lambda: format_datetime(FAKE_EPOCH + timedelta(seconds=600), usegmt=True), 60),
    ],
)
def test_retry_after_is_honoured_and_capped(header: Callable[[], str], expected: float) -> None:
    archive, clock, recorder = build([("response", 429, {"Retry-After": header()})])
    assert archive.get(PLAIN_URL).status_code == 200
    assert len(recorder.requests) == 2
    assert clock.sleeps == [expected]


def test_parse_retry_after_edge_cases() -> None:
    assert parse_retry_after(None, FAKE_EPOCH) == 0
    assert parse_retry_after("soon", FAKE_EPOCH) == 0
    assert parse_retry_after("-5", FAKE_EPOCH) == 0
    past = format_datetime(FAKE_EPOCH - timedelta(seconds=10), usegmt=True)
    assert parse_retry_after(past, FAKE_EPOCH) == 0
    assert parse_retry_after(" 7 ", FAKE_EPOCH) == 7


# --- User-Agent ---------------------------------------------------------------------------


def test_single_default_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVENANT_USER_AGENT", raising=False)
    assert user_agent() == DEFAULT_USER_AGENT
    archive, _clock, recorder = build(ua=user_agent())
    archive.get(PLAIN_URL)
    assert recorder.requests[0].headers.get_list("User-Agent") == [DEFAULT_USER_AGENT]


def test_user_agent_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVENANT_USER_AGENT", "Revenant/0.1 (test)")
    assert user_agent() == "Revenant/0.1 (test)"
    archive, _clock, recorder = build(ua=user_agent())
    archive.get(F6_SOURCE)
    for request in recorder.requests:
        assert request.headers.get_list("User-Agent") == ["Revenant/0.1 (test)"]
