"""HTTP client for the BOSS recruiter AI reply service.

Wraps a transport (HTTP client abstraction) with:

- A simple in-process circuit breaker that opens after N consecutive
  failures and stays open for ``recovery_timeout_s`` seconds.
- A normalized result enum so the dispatcher can branch deterministically
  on success / timeout / HTTP error / empty reply / circuit open.

The transport is injected so unit tests can drive it without any real
network. The default transport (using ``httpx``) is intentionally
omitted from this module - it lives in ``ai_reply_transport.py`` to
keep this file pure.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

_DEFAULT_TIMEOUT_S: Final[float] = 10.0
_DEFAULT_FAILURE_THRESHOLD: Final[int] = 3
_DEFAULT_RECOVERY_TIMEOUT_S: Final[float] = 120.0


class AiReplyKind(StrEnum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    EMPTY = "empty"
    CIRCUIT_OPEN = "circuit_open"


@dataclass(frozen=True, slots=True)
class AiReplyResult:
    kind: AiReplyKind
    text: str | None
    detail: str | None = None


@runtime_checkable
class AiTransport(Protocol):
    async def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> dict[str, Any]: ...


class _MiniBreaker:
    """Local copy of the breaker behaviour the dispatcher needs.

    We intentionally do *not* import the wecom-desktop circuit breaker
    here to keep ``boss_automation`` independent of the desktop app
    package. The semantics are the same for the cases we use.
    """

    def __init__(self, failure_threshold: int, recovery_timeout_s: float) -> None:
        self._failure_threshold = max(1, failure_threshold)
        self._recovery_timeout_s = max(0.0, recovery_timeout_s)
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self._recovery_timeout_s:
            # Half-open window: allow one probe.
            return True
        return False

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._opened_at = time.monotonic()


class AiReplyClient:
    """Thin async client for the recruiter AI reply backend."""

    def __init__(
        self,
        endpoint: str,
        *,
        transport: AiTransport,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
        recovery_timeout_s: float = _DEFAULT_RECOVERY_TIMEOUT_S,
    ) -> None:
        if not endpoint:
            raise ValueError("endpoint must be a non-empty string")
        self._endpoint = endpoint
        self._transport = transport
        self._timeout_s = timeout_s
        self._breaker = _MiniBreaker(failure_threshold, recovery_timeout_s)

    @property
    def endpoint(self) -> str:
        return self._endpoint

    async def generate(
        self,
        *,
        candidate_name: str,
        resume_summary: str | None,
        last_message: str,
        timeout_s: float | None = None,
    ) -> AiReplyResult:
        if not self._breaker.allow():
            return AiReplyResult(
                kind=AiReplyKind.CIRCUIT_OPEN,
                text=None,
                detail="AI circuit open",
            )

        payload: dict[str, Any] = {
            "candidate_name": candidate_name,
            "resume_summary": resume_summary or "",
            "last_message": last_message,
            "scenario": "boss_reply",
        }
        try:
            response = await self._transport.post_json(
                self._endpoint,
                payload,
                timeout_s=timeout_s if timeout_s is not None else self._timeout_s,
            )
        except TimeoutError:
            self._breaker.record_failure()
            return AiReplyResult(kind=AiReplyKind.TIMEOUT, text=None, detail="timeout")
        except Exception as exc:  # noqa: BLE001
            self._breaker.record_failure()
            return AiReplyResult(kind=AiReplyKind.HTTP_ERROR, text=None, detail=str(exc))

        text = ""
        if isinstance(response, dict):
            raw = response.get("reply")
            if isinstance(raw, str):
                text = raw.strip()

        if not text:
            self._breaker.record_failure()
            return AiReplyResult(kind=AiReplyKind.EMPTY, text=None, detail="empty")

        self._breaker.record_success()
        return AiReplyResult(kind=AiReplyKind.SUCCESS, text=text, detail=None)
