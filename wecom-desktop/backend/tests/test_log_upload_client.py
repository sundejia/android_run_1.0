from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from services.log_upload_client import LogUploadClient


class _DummyResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, data=None, files=None):
        self.post_calls.append(
            {
                "url": url,
                "data": data,
                "files": files,
            }
        )
        return _DummyResponse({
            "success": True,
            "data": {
                "success": True,
                "upload_id": "test-uuid",
                "filename": "sample.log",
                "stored_path": "/tmp/upload.bin",
                "size": 5,
                "checksum": "abc123",
                "message": "uploaded",
            },
        })


@pytest.mark.asyncio
async def test_log_upload_client_sends_person_name(monkeypatch, tmp_path):
    created_clients: list[_DummyAsyncClient] = []

    def _make_client(*args, **kwargs):
        client = _DummyAsyncClient(*args, **kwargs)
        created_clients.append(client)
        return client

    monkeypatch.setattr("services.log_upload_client.httpx.AsyncClient", _make_client)

    upload_file = tmp_path / "sample.log"
    upload_file.write_text("hello", encoding="utf-8")

    client = LogUploadClient(timeout_seconds=5.0)
    result = await client.upload_file(
        base_url="http://localhost:8085",
        device_id="device-123",
        hostname="host-a",
        person_name="张三",
        upload_kind="runtime-log",
        checksum="abc123",
        uploaded_at=datetime(2026, 3, 16, 12, 0, 0),
        file_path=upload_file,
    )

    assert result["success"] is True
    assert len(created_clients) == 1
    assert len(created_clients[0].post_calls) == 1

    payload = created_clients[0].post_calls[0]
    assert payload["url"] == "http://localhost:8085/api/android-logs/upload"
    assert payload["data"]["device_id"] == "device-123"
    assert payload["data"]["hostname"] == "host-a"
    assert payload["data"]["person_name"] == "张三"
    assert payload["data"]["upload_kind"] == "runtime-log"
    assert result["data"]["stored_path"] == "/tmp/upload.bin"
