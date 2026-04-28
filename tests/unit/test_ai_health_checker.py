"""
Unit tests for PeriodicAIHealthChecker — severity-aware force_open behaviour.

Background (BUG-2026-04-27-circuit-breaker-skip-reply):
    The original implementation called `circuit_breaker.force_open()` on
    EVERY non-healthy probe result. In the field this caused a
    "health-check lockup": when the AI server was in edge-degradation
    (slow inference but real /chat requests still completed), each
    300s probe re-forced the breaker open for 120s, repeatedly skipping
    customer replies even though the service was effectively up.

The fix:
    1. Severity classification:
       - "unreachable"        -> force_open immediately (network is dead).
       - "service_down"       -> require N consecutive results before force_open.
       - "inference_error"    -> require N consecutive results before force_open.
       - "inference_timeout"  -> NEVER force_open (real requests still succeed
                                 in this state — false positive in the field).
       - "healthy"            -> reset the consecutive-unhealthy counter.
    2. The threshold N defaults to 2 (configurable).
    3. A healthy probe always resets the counter so a single recovery
       breaks the lockup chain.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2] / "wecom-desktop" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.ai_health_checker import PeriodicAIHealthChecker  # type: ignore[reportMissingImports]  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeCircuitBreaker:
    def __init__(self):
        self.force_open_calls = 0

    def force_open(self) -> None:
        self.force_open_calls += 1


class StubLogger:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def info(self, msg: str) -> None:
        self.messages.append(("info", msg))

    def warning(self, msg: str) -> None:
        self.messages.append(("warning", msg))

    def error(self, msg: str) -> None:
        self.messages.append(("error", msg))


def _build_result(status: str, **overrides: Any) -> dict[str, Any]:
    """Build a probe result dict matching what check_ai_health() returns."""
    base = {
        "ai_server_url": "http://example.test:8000",
        "network": "reachable",
        "http_service": "alive",
        "inference": "working",
        "diagnosis": None,
        "response_time_ms": 100.0,
        "status": status,
    }
    base.update(overrides)
    return base


def _make_checker(threshold: int = 2) -> tuple[PeriodicAIHealthChecker, FakeCircuitBreaker]:
    cb = FakeCircuitBreaker()
    checker = PeriodicAIHealthChecker(
        ai_server_url="http://example.test:8000",
        interval_seconds=300.0,
        circuit_breaker=cb,
        logger=StubLogger(),
        force_open_threshold=threshold,
    )
    return checker, cb


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------


def test_inference_timeout_never_forces_open_even_repeatedly():
    """inference_timeout means /chat is slow; real customer requests still
    complete in the field. Force-opening here causes the lockup described
    in BUG-2026-04-27."""
    checker, cb = _make_checker(threshold=2)

    for _ in range(5):
        checker._handle_probe_result(_build_result("inference_timeout", inference="timeout"))

    assert cb.force_open_calls == 0


def test_unreachable_forces_open_immediately():
    """If the host is unreachable at the network layer, fail fast."""
    checker, cb = _make_checker(threshold=2)

    checker._handle_probe_result(_build_result("unreachable", network="unreachable"))

    assert cb.force_open_calls == 1


def test_service_down_requires_n_consecutive_before_force_open():
    """A single transient service_down probe must not force the breaker
    open. Only after N consecutive failures do we decide the service is
    really down."""
    checker, cb = _make_checker(threshold=2)

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    assert cb.force_open_calls == 0, "First service_down must not force_open"

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    assert cb.force_open_calls == 1, "Second consecutive service_down should force_open"


def test_inference_error_requires_n_consecutive_before_force_open():
    checker, cb = _make_checker(threshold=2)

    checker._handle_probe_result(_build_result("inference_error", inference="error_500"))
    assert cb.force_open_calls == 0

    checker._handle_probe_result(_build_result("inference_error", inference="error_500"))
    assert cb.force_open_calls == 1


def test_healthy_resets_consecutive_counter():
    """A single healthy probe must reset the consecutive-unhealthy counter,
    so the next isolated unhealthy probe does not immediately trip force_open."""
    checker, cb = _make_checker(threshold=2)

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    checker._handle_probe_result(_build_result("healthy"))
    checker._handle_probe_result(_build_result("service_down", http_service="dead"))

    assert cb.force_open_calls == 0, (
        "Healthy probe between two service_down probes must reset the "
        "consecutive-unhealthy counter; otherwise the second service_down "
        "alone would trip force_open and re-introduce the lockup."
    )


def test_force_open_called_only_once_during_continuous_outage():
    """While the breaker is being held open by repeated probes, we should
    not flood the breaker with redundant force_open calls (the breaker
    itself ignores them, but the health checker shouldn't escalate either).
    Once force_open has been invoked we don't need to keep invoking it
    until the service recovers."""
    checker, cb = _make_checker(threshold=2)

    for _ in range(5):
        checker._handle_probe_result(_build_result("service_down", http_service="dead"))

    assert cb.force_open_calls == 1, (
        "force_open should only fire once per outage; subsequent unhealthy "
        "probes during the same outage must not re-fire it."
    )


def test_recovery_after_force_open_allows_future_force_open():
    """After force_open has fired and the service later recovers, a NEW
    outage must again be able to force_open after threshold consecutive
    failures."""
    checker, cb = _make_checker(threshold=2)

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    assert cb.force_open_calls == 1

    checker._handle_probe_result(_build_result("healthy"))

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    assert cb.force_open_calls == 2


def test_threshold_of_one_preserves_legacy_behaviour_for_severe_states():
    """Operators who want the old behaviour for service_down can pass
    threshold=1 explicitly."""
    checker, cb = _make_checker(threshold=1)

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    assert cb.force_open_calls == 1


def test_inference_timeout_with_threshold_one_still_does_not_force_open():
    """inference_timeout severity is hard-coded as warn-only, regardless
    of the consecutive-failure threshold."""
    checker, cb = _make_checker(threshold=1)

    for _ in range(3):
        checker._handle_probe_result(_build_result("inference_timeout", inference="timeout"))

    assert cb.force_open_calls == 0


# ---------------------------------------------------------------------------
# Backward-compatibility: constructor accepts the legacy positional/keyword
# signature without the new parameter.
# ---------------------------------------------------------------------------


def test_constructor_works_without_threshold_kwarg():
    """Existing call sites (realtime_reply_process.py) construct the checker
    without `force_open_threshold`. That must keep working with a sensible
    default."""
    cb = FakeCircuitBreaker()
    checker = PeriodicAIHealthChecker(
        ai_server_url="http://example.test:8000",
        interval_seconds=300.0,
        circuit_breaker=cb,
        logger=StubLogger(),
    )

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    assert cb.force_open_calls == 0, (
        "Default threshold must be >=2 so a single transient service_down doesn't trip force_open."
    )

    checker._handle_probe_result(_build_result("service_down", http_service="dead"))
    assert cb.force_open_calls == 1


# ---------------------------------------------------------------------------
# Integration-ish: ensure the periodic loop actually drives _handle_probe_result
# (we don't want the new logic to live only in a method nobody calls).
# ---------------------------------------------------------------------------


async def test_loop_invokes_handler_per_probe(monkeypatch):
    cb = FakeCircuitBreaker()
    checker = PeriodicAIHealthChecker(
        ai_server_url="http://example.test:8000",
        interval_seconds=0.01,
        circuit_breaker=cb,
        logger=StubLogger(),
        force_open_threshold=2,
    )

    results = iter(
        [
            _build_result("service_down", http_service="dead"),
            _build_result("service_down", http_service="dead"),
            _build_result("healthy"),
        ]
    )

    async def fake_check(_url: str, timeout: float = 10.0) -> dict[str, Any]:
        try:
            return next(results)
        except StopIteration:
            await asyncio.sleep(10)
            return _build_result("healthy")

    import services.ai_health_checker as mod  # type: ignore[reportMissingImports]

    monkeypatch.setattr(mod, "check_ai_health", fake_check)
    monkeypatch.setattr(mod, "record_ai_health", lambda **kwargs: None, raising=False)

    checker.start()
    await asyncio.sleep(0.2)
    checker.stop()
    try:
        await checker._task  # type: ignore[arg-type]
    except (asyncio.CancelledError, Exception):
        pass

    assert cb.force_open_calls == 1, (
        "After two consecutive service_down probes followed by a healthy "
        "probe, exactly one force_open should have been dispatched."
    )
