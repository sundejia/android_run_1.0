"""Tests for ReviewClient (upload + analyze with idempotency)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wecom_automation.services.review.client import (
    ReviewClient,
    ReviewSubmissionError,
)


class _FakeClientResponse:
    def __init__(self, status: int, json_body: dict | None = None, text: str = "") -> None:
        self.status = status
        self._json = json_body or {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self):
        return self._json

    async def text(self):
        return self._text


class _FakeAiohttpSession:
    def __init__(self, queued: list) -> None:
        self.queued = list(queued)
        self.calls: list[tuple[str, str, object]] = []

    def post(self, url, *, data=None, json=None, **kwargs):
        self.calls.append((url, "post", data or json))
        if not self.queued:
            return _FakeClientResponse(200, {"ok": True})
        nxt = self.queued.pop(0)
        return nxt

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_submit_uploads_and_then_triggers_analyze(tmp_path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    upload_resp = _FakeClientResponse(
        200,
        {
            "success": True,
            "results": [
                {
                    "status": "success",
                    "metadata": {"image_id": "img-99"},
                }
            ],
        },
    )
    analyze_resp = _FakeClientResponse(200, {"image_id": "img-99", "model": "qwen3-vl"})
    session = _FakeAiohttpSession([upload_resp, analyze_resp])

    client = ReviewClient(
        rating_server_url="http://127.0.0.1:8080",
        session_factory=lambda: session,
    )

    result = await client.submit(
        image_path=str(img),
        message_id=42,
    )

    assert result.image_id == "img-99"
    assert len(session.calls) == 2
    upload_call_url = session.calls[0][0]
    analyze_call_url = session.calls[1][0]
    assert "/api/v1/upload" in upload_call_url
    assert "/api/v1/ai/analyze/img-99" in analyze_call_url


@pytest.mark.asyncio
async def test_submit_raises_on_upload_failure(tmp_path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    upload_resp = _FakeClientResponse(500, {}, text="server boom")
    session = _FakeAiohttpSession([upload_resp])
    client = ReviewClient(
        rating_server_url="http://127.0.0.1:8080",
        session_factory=lambda: session,
    )

    with pytest.raises(ReviewSubmissionError):
        await client.submit(image_path=str(img), message_id=42)


@pytest.mark.asyncio
async def test_submit_uses_correlation_id_in_analyze(tmp_path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"a")

    upload_resp = _FakeClientResponse(
        200,
        {
            "success": True,
            "results": [
                {
                    "status": "success",
                    "metadata": {"image_id": "img-99"},
                }
            ],
        },
    )
    analyze_resp = _FakeClientResponse(200, {"image_id": "img-99"})
    session = _FakeAiohttpSession([upload_resp, analyze_resp])

    client = ReviewClient(
        rating_server_url="http://127.0.0.1:8080",
        session_factory=lambda: session,
    )

    await client.submit(image_path=str(img), message_id=12345)

    analyze_payload = session.calls[1][2]
    assert analyze_payload == {"correlation_id": "12345"}


@pytest.mark.asyncio
async def test_submit_skips_when_image_missing(tmp_path) -> None:
    client = ReviewClient(
        rating_server_url="http://127.0.0.1:8080",
        session_factory=lambda: _FakeAiohttpSession([]),
    )
    with pytest.raises(ReviewSubmissionError):
        await client.submit(image_path=str(tmp_path / "missing.png"), message_id=1)
