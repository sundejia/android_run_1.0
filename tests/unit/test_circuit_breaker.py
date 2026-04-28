"""
Unit tests for AICircuitBreaker.

Covers BUG-2026-04-27-circuit-breaker-skip-reply regressions:
- force_open() must NOT reset the cooldown timer when the breaker is already
  OPEN (otherwise a periodic health check that keeps re-forcing the breaker
  open will starve the natural 120s recovery cycle and lock the system out
  of replying to customers indefinitely).
- The closed -> open -> half_open -> closed natural recovery cycle must work.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "wecom-desktop" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.followup.circuit_breaker import (  # type: ignore[reportMissingImports]  # noqa: E402
    AICircuitBreaker,
    CircuitState,
)

# ---------------------------------------------------------------------------
# Time control helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """Replaces time.monotonic() in the circuit_breaker module."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    import services.followup.circuit_breaker as cb_module  # type: ignore[reportMissingImports]

    clock = _FakeClock()
    monkeypatch.setattr(cb_module.time, "monotonic", clock)
    return clock


# ---------------------------------------------------------------------------
# Basic state transitions (sanity / regression baseline)
# ---------------------------------------------------------------------------


def test_starts_closed_and_allows_requests():
    cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=120.0)

    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_opens_after_consecutive_failures(fake_clock):
    cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=120.0)

    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_natural_recovery_cycle_closes_after_successful_probe(fake_clock):
    cb = AICircuitBreaker(failure_threshold=2, recovery_timeout=120.0)

    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    fake_clock.advance(120.0)

    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_half_open_failure_returns_to_open(fake_clock):
    cb = AICircuitBreaker(failure_threshold=2, recovery_timeout=60.0)

    cb.record_failure()
    cb.record_failure()
    fake_clock.advance(60.0)

    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    cb.record_failure()
    assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# REGRESSION: BUG-2026-04-27 — force_open lockup
# ---------------------------------------------------------------------------


def test_force_open_from_closed_starts_cooldown(fake_clock):
    """First force_open from CLOSED must start the 120s cooldown timer."""
    cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=120.0)

    fake_clock.advance(50.0)
    cb.force_open()

    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False

    fake_clock.advance(119.0)
    assert cb.state == CircuitState.OPEN

    fake_clock.advance(2.0)  # total 121s — past the cooldown
    assert cb.state == CircuitState.HALF_OPEN


def test_force_open_when_already_open_does_not_reset_cooldown(fake_clock):
    """REGRESSION: a subsequent force_open() while OPEN must not extend the
    cooldown. Otherwise a periodic health check that re-forces the breaker
    open every interval will starve the natural recovery cycle."""
    cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=120.0)

    cb.force_open()
    fake_clock.advance(60.0)

    cb.force_open()

    fake_clock.advance(60.0)  # 120s total since the FIRST force_open
    assert cb.state == CircuitState.HALF_OPEN, (
        "Re-forcing while OPEN must not reset the cooldown timer; otherwise the breaker is permanently locked open."
    )


def test_force_open_three_times_during_cooldown_does_not_extend_lockout(fake_clock):
    """Even repeated force_open calls (e.g. health checker firing every 5min)
    must not extend a single cooldown window."""
    cb = AICircuitBreaker(failure_threshold=3, recovery_timeout=120.0)

    cb.force_open()

    fake_clock.advance(40.0)
    cb.force_open()
    fake_clock.advance(40.0)
    cb.force_open()
    fake_clock.advance(41.0)

    assert cb.state == CircuitState.HALF_OPEN, (
        "Multiple force_open calls during the cooldown window must not delay the half_open transition (BUG-2026-04-27)."
    )
