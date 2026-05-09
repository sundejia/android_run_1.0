"""TDD tests for boss_automation/services/reply_dispatcher.py.

The dispatcher walks the BOSS app:

  messages list -> tap one unread row -> chat detail -> tap resume
  -> resume view -> render template / call AI -> back to chat ->
  type text -> tap send -> persist message.

All ADB interactions are mocked through ``FakeAdbPort``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from boss_automation.services.adb_port import AdbPort  # noqa: F401  (used as type)
from boss_automation.services.ai_reply_client import (
    AiReplyKind,
    AiReplyResult,
)
from boss_automation.services.reply_dispatcher import (
    DispatchKind,
    DispatchOutcome,
    ReplyDispatcher,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _load(rel: str) -> dict[str, Any]:
    data = json.loads((FIXTURE_ROOT / rel).read_text(encoding="utf-8"))
    return data["ui_tree"]


class FakeAdbPort:
    """Plays back a programmed sequence of UI trees per `get_state`
    call. Records all writes (tap_by_text / type_text / start_app /
    swipe) so tests can assert side effects."""

    def __init__(self, trees: Sequence[dict[str, Any]]) -> None:
        self._trees = list(trees)
        self._idx = 0
        self.start_app_calls: list[str] = []
        self.tap_text_calls: list[str] = []
        self.type_text_calls: list[str] = []
        self.swipe_calls: list[tuple[int, int, int, int, int]] = []

    async def start_app(self, package_name: str) -> None:
        self.start_app_calls.append(package_name)

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not self._trees:
            return {}, []
        tree = self._trees[min(self._idx, len(self._trees) - 1)]
        self._idx += 1
        return tree, []

    async def tap_by_text(self, text: str) -> bool:
        self.tap_text_calls.append(text)
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipe_calls.append((x1, y1, x2, y2, duration_ms))

    async def type_text(self, text: str) -> bool:
        self.type_text_calls.append(text)
        return True


# ---------------------------------------------------------------------------
# Helper template provider — synchronous, deterministic.
# ---------------------------------------------------------------------------


def _default_template_provider(_scenario: str) -> str:
    return "您好 {name}，看到您简历，方便聊聊吗？"


@pytest.mark.asyncio
async def test_dispatches_template_reply_when_no_ai_configured() -> None:
    adb = FakeAdbPort(
        [
            _load("messages_list/with_unread.json"),
            _load("conversation_detail/text_only.json"),
            _load("resume_view/full_resume.json"),
        ]
    )
    dispatcher = ReplyDispatcher(
        adb=adb,
        template_provider=_default_template_provider,
        ai_client=None,
    )
    outcome = await dispatcher.dispatch_one()
    assert isinstance(outcome, DispatchOutcome)
    assert outcome.kind == DispatchKind.SENT_TEMPLATE
    assert outcome.boss_candidate_id == "CAND20260507A"
    assert outcome.text_sent is not None
    assert "李雷" in outcome.text_sent
    assert adb.tap_text_calls[0] == "李雷"  # tapped the unread conversation
    assert any("发送" in c for c in adb.tap_text_calls)
    assert outcome.text_sent in adb.type_text_calls


@pytest.mark.asyncio
async def test_uses_ai_reply_when_available() -> None:
    adb = FakeAdbPort(
        [
            _load("messages_list/with_unread.json"),
            _load("conversation_detail/text_only.json"),
            _load("resume_view/full_resume.json"),
        ]
    )

    class FakeAi:
        async def generate(
            self,
            *,
            candidate_name: str,
            resume_summary: str | None,
            last_message: str,
            timeout_s: float | None = None,
        ) -> AiReplyResult:
            return AiReplyResult(
                kind=AiReplyKind.SUCCESS,
                text=f"AI回复给{candidate_name}",
                detail=None,
            )

    dispatcher = ReplyDispatcher(
        adb=adb,
        template_provider=_default_template_provider,
        ai_client=FakeAi(),
    )
    outcome = await dispatcher.dispatch_one()
    assert outcome.kind == DispatchKind.SENT_AI
    assert outcome.text_sent == "AI回复给李雷"


@pytest.mark.asyncio
async def test_falls_back_to_template_when_ai_returns_failure() -> None:
    adb = FakeAdbPort(
        [
            _load("messages_list/with_unread.json"),
            _load("conversation_detail/text_only.json"),
            _load("resume_view/full_resume.json"),
        ]
    )

    class FakeAiTimeout:
        async def generate(self, **_: Any) -> AiReplyResult:
            return AiReplyResult(kind=AiReplyKind.TIMEOUT, text=None, detail="t")

    dispatcher = ReplyDispatcher(
        adb=adb,
        template_provider=_default_template_provider,
        ai_client=FakeAiTimeout(),
    )
    outcome = await dispatcher.dispatch_one()
    assert outcome.kind == DispatchKind.SENT_TEMPLATE
    assert outcome.text_sent is not None


@pytest.mark.asyncio
async def test_skips_when_no_unread_conversation() -> None:
    # Build a message list that has zero unread (use the second row,
    # which has no badge in our fixture).
    no_unread_tree = {
        "children": [
            {
                "resourceId": "com.hpbr.bosszhipin:id/conversation_list_recycler",
                "children": [
                    {
                        "resourceId": "com.hpbr.bosszhipin:id/conversation_row_root",
                        "children": [
                            {
                                "resourceId": "com.hpbr.bosszhipin:id/tv_conversation_name",
                                "text": "韩梅梅",
                            },
                            {
                                "resourceId": "com.hpbr.bosszhipin:id/tv_conversation_id_badge",
                                "text": "ID:CAND20260507B",
                            },
                        ],
                    }
                ],
            }
        ]
    }
    adb = FakeAdbPort([no_unread_tree])
    dispatcher = ReplyDispatcher(
        adb=adb,
        template_provider=_default_template_provider,
        ai_client=None,
    )
    outcome = await dispatcher.dispatch_one()
    assert outcome.kind == DispatchKind.SKIPPED_NO_UNREAD
    assert adb.type_text_calls == []


@pytest.mark.asyncio
async def test_blacklisted_candidate_is_cancelled_before_send() -> None:
    adb = FakeAdbPort(
        [
            _load("messages_list/with_unread.json"),
            _load("conversation_detail/text_only.json"),
            _load("resume_view/full_resume.json"),
        ]
    )

    async def is_blacklisted(boss_candidate_id: str) -> bool:
        assert boss_candidate_id == "CAND20260507A"
        return True

    dispatcher = ReplyDispatcher(
        adb=adb,
        template_provider=_default_template_provider,
        ai_client=None,
    )
    outcome = await dispatcher.dispatch_one(is_blacklisted=is_blacklisted)
    assert outcome.kind == DispatchKind.SKIPPED_BLACKLISTED
    assert adb.type_text_calls == []
    assert "发送" not in adb.tap_text_calls


@pytest.mark.asyncio
async def test_blacklist_check_callback_signature() -> None:
    """Callback must be awaitable (Awaitable[bool])."""
    adb = FakeAdbPort([_load("messages_list/with_unread.json")])

    received: list[str] = []

    async def cb(cid: str) -> bool:
        received.append(cid)
        return False

    cb_typed: Callable[[str], Awaitable[bool]] = cb
    dispatcher = ReplyDispatcher(
        adb=FakeAdbPort(
            [
                _load("messages_list/with_unread.json"),
                _load("conversation_detail/text_only.json"),
                _load("resume_view/full_resume.json"),
            ]
        ),
        template_provider=_default_template_provider,
        ai_client=None,
    )
    outcome = await dispatcher.dispatch_one(is_blacklisted=cb_typed)
    assert outcome.kind == DispatchKind.SENT_TEMPLATE
    assert received == ["CAND20260507A", "CAND20260507A"]
    _ = adb  # keep reference (unused)


@pytest.mark.asyncio
async def test_dry_run_prepares_reply_without_sending() -> None:
    adb = FakeAdbPort(
        [
            _load("messages_list/with_unread.json"),
            _load("conversation_detail/text_only.json"),
            _load("resume_view/full_resume.json"),
        ]
    )
    dispatcher = ReplyDispatcher(
        adb=adb,
        template_provider=_default_template_provider,
        ai_client=None,
    )

    outcome = await dispatcher.dispatch_one(dry_run=True)

    assert outcome.kind == DispatchKind.DRY_RUN_READY
    assert outcome.text_sent is not None
    assert adb.type_text_calls == []
    assert "发送" not in adb.tap_text_calls
