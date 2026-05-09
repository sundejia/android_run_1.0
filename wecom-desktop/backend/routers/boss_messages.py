"""REST routes for the BOSS message-reply feature.

* ``GET /recruiters/{recruiter_id}/conversations`` — list conversations
  persisted for one recruiter (used by the desktop chat list panel).
* ``GET /conversations/{conversation_id}`` — full message history for
  one conversation (used by the chat detail pane).
* ``POST /dispatch`` — drive the BOSS app one step: parse messages
  list → tap unread → render template / call AI → send → persist.

Mounted only when ``BOSS_FEATURES_ENABLED`` is truthy.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.core.config import get_default_db_path  # noqa: E402
from boss_automation.database.candidate_repository import (  # noqa: E402
    CandidateRepository,
)
from boss_automation.database.conversation_repository import (  # noqa: E402
    ConversationRecord,
    ConversationRepository,
)
from boss_automation.database.message_repository import (  # noqa: E402
    MessageRecord,
    MessageRepository,
)
from boss_automation.database.recruiter_repository import (  # noqa: E402
    RecruiterRepository,
)
from boss_automation.database.template_repository import (  # noqa: E402
    TemplateRepository,
)
from boss_automation.services.adb_port import AdbPort  # noqa: E402
from boss_automation.services.ai_reply_client import AiReplyClient  # noqa: E402
from boss_automation.services.reply_dispatcher import (  # noqa: E402
    DispatchKind,
    ReplyDispatcher,
)

router = APIRouter(prefix="/api/boss/messages", tags=["boss-messages"])

OutcomeLiteral = Literal[
    "sent_template",
    "sent_ai",
    "dry_run_ready",
    "skipped_no_unread",
    "skipped_blacklisted",
    "halted_unknown_ui",
]


# --------- Pydantic schemas ----------------------------------------


class ConversationModel(BaseModel):
    id: int
    recruiter_id: int
    candidate_id: int
    unread_count: int
    last_direction: str | None

    @classmethod
    def from_record(cls, record: ConversationRecord) -> ConversationModel:
        return cls(
            id=record.id,
            recruiter_id=record.recruiter_id,
            candidate_id=record.candidate_id,
            unread_count=record.unread_count,
            last_direction=record.last_direction,
        )


class ConversationsListResponse(BaseModel):
    recruiter_id: int
    conversations: list[ConversationModel] = Field(default_factory=list)


class MessageModel(BaseModel):
    id: int
    direction: str
    content_type: str
    text: str | None
    sent_at_iso: str
    sent_by: str | None
    template_id: int | None

    @classmethod
    def from_record(cls, record: MessageRecord) -> MessageModel:
        return cls(
            id=record.id,
            direction=record.direction,
            content_type=record.content_type,
            text=record.text,
            sent_at_iso=record.sent_at_iso,
            sent_by=record.sent_by,
            template_id=record.template_id,
        )


class MessagesListResponse(BaseModel):
    conversation_id: int
    messages: list[MessageModel] = Field(default_factory=list)


class DispatchRequest(BaseModel):
    device_serial: str
    dry_run: bool = True
    confirm_send: bool = False


class DispatchResponse(BaseModel):
    outcome: OutcomeLiteral
    boss_candidate_id: str | None = None
    candidate_name: str | None = None
    text_sent: str | None = None
    template_warnings: list[str] = Field(default_factory=list)


# --------- Dependency wiring ---------------------------------------


_DbPathProvider = Callable[[], str]
_AdbPortFactory = Callable[[str], AdbPort]
_AiClientProvider = Callable[[], AiReplyClient | None]
_BlacklistChecker = Callable[[str], Awaitable[bool]]


def _default_db_path() -> str:
    return str(get_default_db_path())


def _default_adb_factory(_serial: str) -> AdbPort:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="ADB port factory not wired (M6 will install device-manager wiring)",
    )


def _default_ai_provider() -> AiReplyClient | None:
    return None


async def _default_blacklist_check(_boss_candidate_id: str) -> bool:
    return False


_db_path_provider: _DbPathProvider = _default_db_path
_adb_factory: _AdbPortFactory = _default_adb_factory
_ai_provider: _AiClientProvider = _default_ai_provider
_blacklist_check: _BlacklistChecker = _default_blacklist_check


def set_db_path_provider(provider: _DbPathProvider) -> None:
    global _db_path_provider
    _db_path_provider = provider


def reset_db_path_provider() -> None:
    set_db_path_provider(_default_db_path)


def set_adb_port_factory(factory: _AdbPortFactory) -> None:
    global _adb_factory
    _adb_factory = factory


def reset_adb_port_factory() -> None:
    set_adb_port_factory(_default_adb_factory)


def set_ai_client_provider(provider: _AiClientProvider) -> None:
    global _ai_provider
    _ai_provider = provider


def reset_ai_client_provider() -> None:
    set_ai_client_provider(_default_ai_provider)


def set_blacklist_check(check: _BlacklistChecker) -> None:
    global _blacklist_check
    _blacklist_check = check


def reset_blacklist_check() -> None:
    set_blacklist_check(_default_blacklist_check)


def get_db_path() -> str:
    return _db_path_provider()


# --------- Routes --------------------------------------------------


@router.get(
    "/recruiters/{recruiter_id}/conversations",
    response_model=ConversationsListResponse,
)
def list_conversations(recruiter_id: int, db_path: str = Depends(get_db_path)) -> ConversationsListResponse:
    repo = ConversationRepository(db_path)
    rows = repo.list_for_recruiter(recruiter_id)
    return ConversationsListResponse(
        recruiter_id=recruiter_id,
        conversations=[ConversationModel.from_record(r) for r in rows],
    )


@router.get("/conversations/{conversation_id}", response_model=MessagesListResponse)
def list_messages(conversation_id: int, db_path: str = Depends(get_db_path)) -> MessagesListResponse:
    repo = MessageRepository(db_path)
    rows = repo.list_for_conversation(conversation_id)
    return MessagesListResponse(
        conversation_id=conversation_id,
        messages=[MessageModel.from_record(r) for r in rows],
    )


@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_one(body: DispatchRequest, db_path: str = Depends(get_db_path)) -> DispatchResponse:
    recruiter_repo = RecruiterRepository(db_path)
    recruiter = recruiter_repo.get_by_serial(body.device_serial)
    if recruiter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no recruiter bound to device {body.device_serial!r}",
        )

    template_repo = TemplateRepository(db_path)

    def template_provider(scenario: str) -> str:
        record = template_repo.get_default(scenario)
        if record is not None:
            return record.content
        rows = template_repo.list_by_scenario(scenario)
        if rows:
            return rows[0].content
        # Last-resort fallback so dispatch never crashes the operator.
        return "您好 {name}，看到您的简历，请问方便沟通吗？"

    adb = _adb_factory(body.device_serial)
    dispatcher = ReplyDispatcher(
        adb=adb,
        template_provider=template_provider,
        ai_client=_ai_provider(),
    )

    outcome = await dispatcher.dispatch_one(
        is_blacklisted=_blacklist_check,
        dry_run=body.dry_run or not body.confirm_send,
    )

    if outcome.kind in (DispatchKind.SENT_TEMPLATE, DispatchKind.SENT_AI):
        _persist_outbound_message(
            db_path=db_path,
            recruiter_id=recruiter.id,
            boss_candidate_id=outcome.boss_candidate_id,
            candidate_name=outcome.candidate_name,
            text=outcome.text_sent or "",
            sent_by="ai" if outcome.kind == DispatchKind.SENT_AI else "template",
        )

    return DispatchResponse(
        outcome=outcome.kind.value,  # type: ignore[arg-type]
        boss_candidate_id=outcome.boss_candidate_id,
        candidate_name=outcome.candidate_name,
        text_sent=outcome.text_sent,
        template_warnings=list(outcome.template_warnings),
    )


def _persist_outbound_message(
    *,
    db_path: str,
    recruiter_id: int,
    boss_candidate_id: str | None,
    candidate_name: str | None,
    text: str,
    sent_by: str,
) -> None:
    if not boss_candidate_id or not candidate_name:
        return
    candidate_repo = CandidateRepository(db_path)
    record = candidate_repo.get_by_boss_candidate_id(recruiter_id, boss_candidate_id)
    if record is None:
        # We have a candidate id but no row yet (the operator dispatched
        # before the recommendation feed populated). Insert a minimal
        # row using a synthesised CandidateCard.
        from boss_automation.parsers.candidate_card_parser import CandidateCard

        candidate_id = candidate_repo.upsert_from_card(
            recruiter_id,
            CandidateCard(
                boss_candidate_id=boss_candidate_id,
                name=candidate_name,
                age=None,
                gender=None,
                education=None,
                experience_years=None,
                current_company=None,
                current_position=None,
            ),
        )
    else:
        candidate_id = record.id

    conv_repo = ConversationRepository(db_path)
    conversation_id = conv_repo.upsert(
        recruiter_id=recruiter_id,
        candidate_id=candidate_id,
        last_direction="out",
    )

    MessageRepository(db_path).insert(
        conversation_id=conversation_id,
        direction="out",
        content_type="text",
        text=text,
        sent_at=datetime.now(tz=UTC),
        sent_by=sent_by,
    )


# --------- Feature flag --------------------------------------------


def boss_features_enabled() -> bool:
    raw = os.environ.get("BOSS_FEATURES_ENABLED", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


__all__ = [
    "router",
    "boss_features_enabled",
    "set_db_path_provider",
    "reset_db_path_provider",
    "set_adb_port_factory",
    "reset_adb_port_factory",
    "set_ai_client_provider",
    "reset_ai_client_provider",
    "set_blacklist_check",
    "reset_blacklist_check",
    "get_db_path",
    "ConversationModel",
    "ConversationsListResponse",
    "MessageModel",
    "MessagesListResponse",
    "DispatchRequest",
    "DispatchResponse",
]
