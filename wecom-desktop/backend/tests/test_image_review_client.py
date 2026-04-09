from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import httpx

from services import image_review_client


TEST_IMAGE_DIR = Path(__file__).parent / ".tmp_image_review_client"
TEST_IMAGE_DIR.mkdir(exist_ok=True)


def _write_test_image(filename: str) -> Path:
    path = TEST_IMAGE_DIR / filename
    path.write_bytes(b"fake-image")
    return path


class _DummyResponse:
    def __init__(self, *, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _CompletedAsyncClient:
    def __init__(self, *args, **kwargs):
        self.get_calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, files=None, data=None):
        return _DummyResponse(
            status_code=200,
            payload={
                "results": [
                    {
                        "original_filename": "sample.jpg",
                        "status": "success",
                        "metadata": {"image_id": "img-1"},
                    }
                ]
            },
        )

    async def get(self, url):
        self.get_calls.append(url)
        if url.endswith("/api/v1/images/img-1/analysis"):
            return _DummyResponse(
                status_code=200,
                payload={
                    "score": 92.5,
                    "model": "demo-model",
                    "details": {"reason": "safe"},
                    "created_at": "2026-03-21T10:00:00+00:00",
                },
            )
        if url.endswith("/api/v1/images/img-1"):
            return _DummyResponse(status_code=200, payload={"ai_decision": "pass"})
        raise AssertionError(f"Unexpected GET URL: {url}")


class _TimeoutAsyncClient:
    def __init__(self, *args, **kwargs):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, files=None, data=None):
        return _DummyResponse(
            status_code=200,
            payload={
                "results": [
                    {
                        "original_filename": "sample.jpg",
                        "status": "success",
                        "metadata": {"image_id": "img-2"},
                    }
                ]
            },
        )

    async def get(self, url):
        if url.endswith("/api/v1/images/img-2"):
            return _DummyResponse(
                status_code=200,
                payload={
                    "ai_score": None,
                    "ai_decision": None,
                    "ai_analyzed_at": None,
                },
            )
        if url.endswith("/api/v1/images/img-2/analysis"):
            return _DummyResponse(status_code=404, payload={})
        raise AssertionError(f"Unexpected GET URL: {url}")


@pytest.fixture(autouse=True)
def clear_image_review_state():
    image_review_client._uploaded_paths.clear()
    image_review_client._inflight_uploads.clear()
    yield
    image_review_client._uploaded_paths.clear()
    image_review_client._inflight_uploads.clear()


@pytest.mark.asyncio
async def test_upload_image_for_review_persists_pending_and_completed(monkeypatch):
    image_file = _write_test_image("sample-completed.jpg")

    state_calls: list[dict] = []

    async def _capture_state(message_id, db_path, **kwargs):
        state_calls.append({"message_id": message_id, "db_path": db_path, **kwargs})

    monkeypatch.setattr(image_review_client, "_get_runtime_settings", lambda _: (True, "http://server", 40, False))
    monkeypatch.setattr(image_review_client, "_set_review_state", _capture_state)
    monkeypatch.setattr(httpx, "AsyncClient", _CompletedAsyncClient)

    result = await image_review_client.upload_image_for_review(
        image_file,
        local_message_id=123,
        db_path="test.db",
    )

    assert result is True
    assert [call["ai_review_status"] for call in state_calls] == [
        image_review_client.REVIEW_STATUS_PENDING,
        image_review_client.REVIEW_STATUS_COMPLETED,
    ]
    assert state_calls[-1]["review_external_id"] == "img-1"
    assert state_calls[-1]["ai_review_score"] == 92.5
    assert state_calls[-1]["ai_review_decision"] == "pass"


@pytest.mark.asyncio
async def test_upload_image_for_review_marks_timeout(monkeypatch):
    image_file = _write_test_image("sample-timeout.jpg")

    state_calls: list[dict] = []

    async def _capture_state(message_id, db_path, **kwargs):
        state_calls.append({"message_id": message_id, "db_path": db_path, **kwargs})

    async def _return_timeout(*args, **kwargs):
        return None

    monkeypatch.setattr(image_review_client, "_get_runtime_settings", lambda _: (True, "http://server", 1, False))
    monkeypatch.setattr(image_review_client, "_set_review_state", _capture_state)
    monkeypatch.setattr(image_review_client, "_poll_analysis_until_ready", _return_timeout)
    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutAsyncClient)

    result = await image_review_client.upload_image_for_review(
        image_file,
        local_message_id=456,
        db_path="test.db",
    )

    assert result is False
    assert state_calls[-1]["ai_review_status"] == image_review_client.REVIEW_STATUS_TIMEOUT
    assert state_calls[-1]["review_external_id"] == "img-2"
    assert "Timed out waiting for image review result after 1s" in state_calls[-1]["ai_review_error"]


@pytest.mark.asyncio
async def test_upload_image_for_review_returns_early_in_low_spec_mode(monkeypatch):
    image_file = _write_test_image("sample-low-spec.jpg")

    started = asyncio.Event()

    async def _slow_impl(**kwargs):
        started.set()
        await asyncio.sleep(0.01)
        return True

    monkeypatch.setattr(image_review_client, "_get_runtime_settings", lambda _: (True, "http://server", 40, True))
    monkeypatch.setattr(image_review_client, "_upload_image_for_review_impl", _slow_impl)

    result = await image_review_client.upload_image_for_review(image_file)

    assert result is True
    assert await asyncio.wait_for(started.wait(), timeout=0.1)
