"""Shared test helpers for Exhume: a fake Clock that never really sleeps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

FAKE_EPOCH = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)


class FakeClock:
    """Clock whose `sleep` advances monotonic and UTC time instantly and records the sleep."""

    def __init__(self, start: datetime = FAKE_EPOCH) -> None:
        self._t = 0.0
        self._start = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if seconds > 0:
            self._t += seconds

    def now_utc(self) -> datetime:
        return self._start + timedelta(seconds=self._t)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()
