"""Tests for routers/boss_templates.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

project_root = backend_dir.parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from routers import boss_templates  # noqa: E402


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "boss_templates.db")


@pytest.fixture()
def app(db_path: str) -> FastAPI:
    boss_templates.set_db_path_provider(lambda: db_path)
    fastapi_app = FastAPI()
    fastapi_app.include_router(boss_templates.router)
    yield fastapi_app
    boss_templates.reset_db_path_provider()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_list_returns_empty_initially(client: TestClient) -> None:
    response = client.get("/api/boss/templates/?scenario=reply")
    assert response.status_code == 200
    assert response.json() == {"templates": []}


def test_create_then_list_then_get(client: TestClient) -> None:
    payload = {
        "name": "default-reply",
        "scenario": "reply",
        "content": "您好 {name}",
        "is_default": True,
    }
    create_resp = client.post("/api/boss/templates/", json=payload)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["id"] > 0
    assert created["name"] == "default-reply"

    list_resp = client.get("/api/boss/templates/?scenario=reply")
    assert list_resp.status_code == 200
    rows = list_resp.json()["templates"]
    assert len(rows) == 1
    assert rows[0]["is_default"] is True

    get_resp = client.get(f"/api/boss/templates/{created['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["content"] == "您好 {name}"


def test_create_with_invalid_scenario_400(client: TestClient) -> None:
    response = client.post(
        "/api/boss/templates/",
        json={"name": "x", "scenario": "bogus", "content": "y"},
    )
    assert response.status_code == 422 or response.status_code == 400


def test_update_changes_content(client: TestClient) -> None:
    created = client.post(
        "/api/boss/templates/",
        json={"name": "x", "scenario": "reply", "content": "old"},
    ).json()
    update_resp = client.put(
        f"/api/boss/templates/{created['id']}",
        json={"content": "new", "is_default": True},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["content"] == "new"
    assert update_resp.json()["is_default"] is True


def test_update_unknown_id_returns_404(client: TestClient) -> None:
    response = client.put(
        "/api/boss/templates/9999",
        json={"content": "x"},
    )
    assert response.status_code == 404


def test_delete_removes_template(client: TestClient) -> None:
    created = client.post(
        "/api/boss/templates/",
        json={"name": "x", "scenario": "reply", "content": "y"},
    ).json()
    delete_resp = client.delete(f"/api/boss/templates/{created['id']}")
    assert delete_resp.status_code == 204
    get_resp = client.get(f"/api/boss/templates/{created['id']}")
    assert get_resp.status_code == 404


def test_render_preview(client: TestClient) -> None:
    response = client.post(
        "/api/boss/templates/preview",
        json={
            "content": "你好 {name}{?company:，{company}}",
            "context": {"name": "李雷", "company": "ByteDance"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "你好 李雷，ByteDance"
    assert body["warnings"] == []


def test_render_preview_collects_warnings(client: TestClient) -> None:
    response = client.post(
        "/api/boss/templates/preview",
        json={"content": "Hi {name} {missing}", "context": {"name": "x"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert "{missing}" in body["text"]
    assert body["warnings"] == ["missing"]
