"""Tests for routers/boss_messages.py."""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

project_root = backend_dir.parent.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

from boss_automation.database.candidate_repository import CandidateRepository  # noqa: E402
from boss_automation.database.conversation_repository import ConversationRepository  # noqa: E402
from boss_automation.database.message_repository import MessageRepository  # noqa: E402
from boss_automation.database.recruiter_repository import RecruiterRepository  # noqa: E402
from boss_automation.database.template_repository import TemplateRepository  # noqa: E402
from boss_automation.parsers.candidate_card_parser import CandidateCard  # noqa: E402
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile  # noqa: E402
from routers import boss_messages  # noqa: E402

FIXTURE_ROOT = project_root / "tests" / "fixtures" / "boss"


def _tree(rel: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / rel).read_text(encoding="utf-8"))["ui_tree"]


class _FakeAdbPort:
    def __init__(self, trees: Sequence[dict[str, Any]]) -> None:
        self._trees = list(trees)
        self._idx = 0
        self.tap_text_calls: list[str] = []
        self.type_text_calls: list[str] = []

    async def start_app(self, package_name: str) -> None: ...

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._idx >= len(self._trees):
            tree = self._trees[-1] if self._trees else {}
        else:
            tree = self._trees[self._idx]
            self._idx += 1
        return copy.deepcopy(tree), []

    async def tap_by_text(self, text: str) -> bool:
        self.tap_text_calls.append(text)
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None: ...

    async def type_text(self, text: str) -> bool:
        self.type_text_calls.append(text)
        return True


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "boss_messages.db")


@pytest.fixture()
def recruiter_id(db_path: str) -> int:
    return RecruiterRepository(db_path).upsert("EMU-1", RecruiterProfile(name="Recr", company="Co", position="HR"))


@pytest.fixture()
def seeded_conversation(db_path: str, recruiter_id: int) -> int:
    cand_id = CandidateRepository(db_path).upsert_from_card(
        recruiter_id,
        CandidateCard(
            boss_candidate_id="CAND20260507A",
            name="李雷",
            age=28,
            gender=None,
            education=None,
            experience_years=None,
            current_company=None,
            current_position=None,
        ),
    )
    return ConversationRepository(db_path).upsert(
        recruiter_id=recruiter_id,
        candidate_id=cand_id,
        unread_count=2,
        last_direction="in",
    )


@pytest.fixture()
def app(db_path: str) -> FastAPI:
    boss_messages.set_db_path_provider(lambda: db_path)
    fastapi_app = FastAPI()
    fastapi_app.include_router(boss_messages.router)
    yield fastapi_app
    boss_messages.reset_db_path_provider()
    boss_messages.reset_adb_port_factory()


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_list_conversations_returns_seeded_rows(
    client: TestClient,
    seeded_conversation: int,
    recruiter_id: int,
) -> None:
    response = client.get(f"/api/boss/messages/recruiters/{recruiter_id}/conversations")
    assert response.status_code == 200
    body = response.json()
    assert body["recruiter_id"] == recruiter_id
    assert len(body["conversations"]) == 1
    assert body["conversations"][0]["id"] == seeded_conversation
    assert body["conversations"][0]["unread_count"] == 2


def test_list_messages_returns_persisted_history(
    client: TestClient,
    db_path: str,
    seeded_conversation: int,
) -> None:
    repo = MessageRepository(db_path)
    repo.insert(
        conversation_id=seeded_conversation,
        direction="in",
        content_type="text",
        text="您好",
        sent_at=datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC),
        sent_by="manual",
    )
    response = client.get(f"/api/boss/messages/conversations/{seeded_conversation}")
    assert response.status_code == 200
    rows = response.json()["messages"]
    assert len(rows) == 1
    assert rows[0]["text"] == "您好"
    assert rows[0]["direction"] == "in"


def test_dispatch_returns_503_when_no_adb_factory(
    client: TestClient,
    seeded_conversation: int,
    recruiter_id: int,
) -> None:
    response = client.post(
        "/api/boss/messages/dispatch",
        json={"device_serial": "EMU-1"},
    )
    assert response.status_code == 503


def test_dispatch_defaults_to_dry_run_without_persisting_message(
    client: TestClient,
    db_path: str,
    seeded_conversation: int,
    recruiter_id: int,
) -> None:
    TemplateRepository(db_path).insert(
        name="default-reply",
        scenario="reply",
        content="您好 {name}，我们职位在招",
        is_default=True,
    )

    fake_adb = _FakeAdbPort(
        [
            _tree("messages_list/with_unread.json"),
            _tree("conversation_detail/text_only.json"),
            _tree("resume_view/full_resume.json"),
        ]
    )
    boss_messages.set_adb_port_factory(lambda _serial: fake_adb)

    response = client.post(
        "/api/boss/messages/dispatch",
        json={"device_serial": "EMU-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "dry_run_ready"
    assert body["text_sent"] is not None
    assert fake_adb.type_text_calls == []
    assert "发送" not in fake_adb.tap_text_calls
    assert MessageRepository(db_path).list_for_conversation(seeded_conversation) == []


def test_dispatch_uses_template_and_persists_message(
    client: TestClient,
    db_path: str,
    seeded_conversation: int,
    recruiter_id: int,
) -> None:
    TemplateRepository(db_path).insert(
        name="default-reply",
        scenario="reply",
        content="您好 {name}，我们职位在招",
        is_default=True,
    )

    fake_adb = _FakeAdbPort(
        [
            _tree("messages_list/with_unread.json"),
            _tree("conversation_detail/text_only.json"),
            _tree("resume_view/full_resume.json"),
        ]
    )
    boss_messages.set_adb_port_factory(lambda _serial: fake_adb)

    response = client.post(
        "/api/boss/messages/dispatch",
        json={"device_serial": "EMU-1", "dry_run": False, "confirm_send": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "sent_template"
    assert body["boss_candidate_id"] == "CAND20260507A"
    assert body["text_sent"] is not None
    assert "李雷" in body["text_sent"]

    # Persisted into messages table.
    persisted = MessageRepository(db_path).list_for_conversation(seeded_conversation)
    assert any(m.direction == "out" and m.text == body["text_sent"] for m in persisted)
