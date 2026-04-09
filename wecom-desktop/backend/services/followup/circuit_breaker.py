"""
AI Circuit Breaker

Prevents the system from repeatedly calling an unavailable AI service.
When consecutive failures exceed a threshold, the breaker "opens" and
short-circuits AI calls for a cooldown period, avoiding pointless retries
that cause the same customer chat to be entered/exited dozens of times.

State machine:
    CLOSED  -> (N consecutive failures) -> OPEN
    OPEN    -> (recovery_timeout elapsed) -> HALF_OPEN
    HALF_OPEN -> (success) -> CLOSED
    HALF_OPEN -> (failure) -> OPEN
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class AICircuitBreaker:
    """Circuit breaker for AI reply generation."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 120.0,
        half_open_max_calls: int = 1,
        logger: Any | None = None,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        self._logger = logger

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    # ------------------------------------------------------------------
    # Public query
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        self._maybe_transition_to_half_open()
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def allow_request(self) -> bool:
        """Return True if an AI request should be attempted."""
        self._maybe_transition_to_half_open()

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self._half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

        # OPEN
        return False

    # ------------------------------------------------------------------
    # Record outcomes
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        """Call after a successful AI response."""
        prev = self._state
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._half_open_calls = 0
        if prev != CircuitState.CLOSED and self._logger:
            self._logger.info(f"[CircuitBreaker] State {prev.value} -> closed (AI recovered)")

    def record_failure(self) -> None:
        """Call after a failed AI request (timeout, error, empty reply, etc.)."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._half_open_calls = 0
            if self._logger:
                self._logger.warning(
                    f"[CircuitBreaker] half_open -> open (probe failed, cooling down {self._recovery_timeout}s)"
                )
            return

        if self._state == CircuitState.CLOSED and self._consecutive_failures >= self._failure_threshold:
            self._state = CircuitState.OPEN
            if self._logger:
                self._logger.warning(
                    f"[CircuitBreaker] closed -> open "
                    f"(consecutive failures={self._consecutive_failures}, "
                    f"cooling down {self._recovery_timeout}s)"
                )

    def force_open(self) -> None:
        """Externally force the breaker open (e.g. health-check detected AI down)."""
        if self._state != CircuitState.OPEN:
            prev = self._state
            self._state = CircuitState.OPEN
            self._last_failure_time = time.monotonic()
            if self._logger:
                self._logger.warning(f"[CircuitBreaker] {prev.value} -> open (forced)")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maybe_transition_to_half_open(self) -> None:
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._last_failure_time
        if elapsed >= self._recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            if self._logger:
                self._logger.info(
                    f"[CircuitBreaker] open -> half_open (cooldown {self._recovery_timeout}s elapsed, probing)"
                )

    # ------------------------------------------------------------------
    # Serialisation helpers (for persistence across restarts)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "state": self._state.value,
            "consecutive_failures": self._consecutive_failures,
            "last_failure_time": self._last_failure_time,
            "half_open_calls": self._half_open_calls,
        }

    def load_from_dict(self, data: dict) -> None:
        self._state = CircuitState(data.get("state", "closed"))
        self._consecutive_failures = data.get("consecutive_failures", 0)
        self._last_failure_time = data.get("last_failure_time", 0.0)
        self._half_open_calls = data.get("half_open_calls", 0)
