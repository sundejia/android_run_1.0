"""TDD tests for boss_automation/services/ai_reply_client.py."""

from __future__ import annotations

import pytest

from boss_automation.services.ai_reply_client import (
    AiReplyClient,
    AiReplyKind,
    AiReplyResult,
    AiTransport,
)


class _FakeTransport:
    """Pluggable AiTransport stub. Each call dequeues one programmed
    outcome; an outcome can be a return value or an Exception subclass
    that should be raised."""

    def __init__(self, outcomes: list) -> None:  # type: ignore[type-arg]
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def post_json(self, url: str, payload: dict, *, timeout_s: float) -> dict:
        self.calls.append({"url": url, "payload": payload, "timeout_s": timeout_s})
        if not self._outcomes:
            raise RuntimeError("no outcome programmed")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_success_returns_text() -> None:
    transport = _FakeTransport([{"reply": "您好，欢迎"}])
    client = AiReplyClient(
        endpoint="http://ai/reply",
        transport=transport,
    )
    result = await client.generate(
        candidate_name="李雷",
        resume_summary="Java",
        last_message="还在招吗？",
    )
    assert result == AiReplyResult(kind=AiReplyKind.SUCCESS, text="您好，欢迎", detail=None)
    assert transport.calls[0]["url"] == "http://ai/reply"


@pytest.mark.asyncio
async def test_empty_reply_classified_as_empty() -> None:
    transport = _FakeTransport([{"reply": "   "}])
    client = AiReplyClient("http://ai/reply", transport=transport)
    result = await client.generate(candidate_name="x", resume_summary=None, last_message="hi")
    assert result.kind == AiReplyKind.EMPTY
    assert result.text is None


@pytest.mark.asyncio
async def test_timeout_classified_as_timeout() -> None:
    transport = _FakeTransport([TimeoutError()])
    client = AiReplyClient("http://ai/reply", transport=transport)
    result = await client.generate(candidate_name="x", resume_summary=None, last_message="hi")
    assert result.kind == AiReplyKind.TIMEOUT


@pytest.mark.asyncio
async def test_http_error_classified_as_http_error() -> None:
    transport = _FakeTransport([RuntimeError("502 Bad Gateway")])
    client = AiReplyClient("http://ai/reply", transport=transport)
    result = await client.generate(candidate_name="x", resume_summary=None, last_message="hi")
    assert result.kind == AiReplyKind.HTTP_ERROR
    assert "502" in (result.detail or "")


@pytest.mark.asyncio
async def test_circuit_opens_after_three_consecutive_failures() -> None:
    transport = _FakeTransport(
        [
            TimeoutError(),
            TimeoutError(),
            TimeoutError(),
        ]
    )
    client = AiReplyClient(
        "http://ai/reply",
        transport=transport,
        failure_threshold=3,
        recovery_timeout_s=120.0,
    )
    for _ in range(3):
        await client.generate(candidate_name="x", resume_summary=None, last_message="hi")

    # 4th call must short-circuit, no transport call recorded for it.
    blocked = await client.generate(candidate_name="x", resume_summary=None, last_message="hi")
    assert blocked.kind == AiReplyKind.CIRCUIT_OPEN
    assert blocked.text is None
    assert len(transport.calls) == 3


def test_protocol_is_runtime_checkable() -> None:
    # The transport protocol must accept arbitrary objects with the
    # right method signature.
    class HasPost:
        async def post_json(self, url: str, payload: dict, *, timeout_s: float) -> dict:
            return {}

    assert isinstance(HasPost(), AiTransport)
