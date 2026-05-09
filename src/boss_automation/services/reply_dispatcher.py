"""High-level dispatcher that drives a single reply attempt.

Algorithm
---------
1. ``get_state`` on the messages list page; pick the first row with
   ``unread_count > 0``. If none → ``SKIPPED_NO_UNREAD``.
2. Tap that row by candidate name. ``get_state`` again to load the
   chat detail page.
3. Tap the resume hot-zone (``查看简历`` button by text). ``get_state``
   to load the resume view.
4. Build a context dict ``{name, age, position, company, ...}`` from
   the parsed resume, then either:
   - call the AI client (if configured & succeeds) → ``SENT_AI``;
   - otherwise render the configured template → ``SENT_TEMPLATE``.
5. Re-check the blacklist callback right before send. If now
   blacklisted → ``SKIPPED_BLACKLISTED``.
6. ``type_text`` then ``tap_by_text("发送")``.
7. Return a ``DispatchOutcome`` describing what happened.

The dispatcher does not write to the database; the caller (the API
router or queue worker) is responsible for ``MessageRepository.insert``
on success. This keeps the unit under test single-purpose and lets us
exercise the full happy / sad paths without DB setup.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from boss_automation.parsers.conversation_parser import (
    Direction,
    extract_chat_partner_id,
    parse_conversation_detail,
)
from boss_automation.parsers.message_list_parser import parse_message_list
from boss_automation.parsers.resume_parser import ResumeSnapshot, parse_resume
from boss_automation.services.adb_port import AdbPort
from boss_automation.services.ai_reply_client import AiReplyKind, AiReplyResult
from boss_automation.services.template_engine import render_template


class DispatchKind(StrEnum):
    SENT_TEMPLATE = "sent_template"
    SENT_AI = "sent_ai"
    DRY_RUN_READY = "dry_run_ready"
    SKIPPED_NO_UNREAD = "skipped_no_unread"
    SKIPPED_BLACKLISTED = "skipped_blacklisted"
    HALTED_UNKNOWN_UI = "halted_unknown_ui"


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    kind: DispatchKind
    boss_candidate_id: str | None
    candidate_name: str | None
    text_sent: str | None
    template_warnings: tuple[str, ...] = ()


@runtime_checkable
class AiClientLike(Protocol):
    async def generate(
        self,
        *,
        candidate_name: str,
        resume_summary: str | None,
        last_message: str,
        timeout_s: float | None = None,
    ) -> AiReplyResult: ...


TemplateProvider = Callable[[str], str]
"""Callable returning the template body for a given scenario.

Scenarios are: ``first_greet`` | ``reply`` | ``reengage``.
"""


class ReplyDispatcher:
    def __init__(
        self,
        *,
        adb: AdbPort,
        template_provider: TemplateProvider,
        ai_client: AiClientLike | None = None,
    ) -> None:
        self._adb = adb
        self._template_provider = template_provider
        self._ai_client = ai_client

    async def dispatch_one(
        self,
        *,
        is_blacklisted: Callable[[str], Awaitable[bool]] | None = None,
        dry_run: bool = False,
    ) -> DispatchOutcome:
        list_tree, _ = await self._adb.get_state()
        rows = parse_message_list(list_tree)
        target = next((r for r in rows if r.unread_count > 0), None)
        if target is None:
            return DispatchOutcome(
                kind=DispatchKind.SKIPPED_NO_UNREAD,
                boss_candidate_id=None,
                candidate_name=None,
                text_sent=None,
            )

        if is_blacklisted is not None and await is_blacklisted(target.boss_candidate_id):
            return DispatchOutcome(
                kind=DispatchKind.SKIPPED_BLACKLISTED,
                boss_candidate_id=target.boss_candidate_id,
                candidate_name=target.candidate_name,
                text_sent=None,
            )

        await self._adb.tap_by_text(target.candidate_name)
        chat_tree, _ = await self._adb.get_state()
        partner_id = extract_chat_partner_id(chat_tree) or target.boss_candidate_id
        messages = parse_conversation_detail(chat_tree)
        last_inbound = next(
            (m.text or "" for m in reversed(messages) if m.direction == Direction.IN),
            "",
        )

        # Best-effort: tap the resume affordance and parse it.
        await self._adb.tap_by_text("查看简历")
        resume_tree, _ = await self._adb.get_state()
        resume = parse_resume(resume_tree)

        context = _build_context(target.candidate_name, resume)
        rendered_text: str
        kind: DispatchKind
        warnings: tuple[str, ...] = ()

        ai_text = await self._maybe_ai_reply(
            candidate_name=target.candidate_name,
            resume=resume,
            last_message=last_inbound,
        )
        if ai_text is not None:
            rendered_text = ai_text
            kind = DispatchKind.SENT_AI
        else:
            template_body = self._template_provider("reply")
            rendered = render_template(template_body, context)
            rendered_text = rendered.text
            warnings = rendered.warnings
            kind = DispatchKind.SENT_TEMPLATE

        # Mid-flight safety re-check (AGENTS.md guardrail: never fail-open).
        if is_blacklisted is not None and await is_blacklisted(partner_id):
            return DispatchOutcome(
                kind=DispatchKind.SKIPPED_BLACKLISTED,
                boss_candidate_id=partner_id,
                candidate_name=target.candidate_name,
                text_sent=None,
            )

        if dry_run:
            return DispatchOutcome(
                kind=DispatchKind.DRY_RUN_READY,
                boss_candidate_id=partner_id,
                candidate_name=target.candidate_name,
                text_sent=rendered_text,
                template_warnings=warnings,
            )

        await self._adb.type_text(rendered_text)
        await self._adb.tap_by_text("发送")

        return DispatchOutcome(
            kind=kind,
            boss_candidate_id=partner_id,
            candidate_name=target.candidate_name,
            text_sent=rendered_text,
            template_warnings=warnings,
        )

    async def _maybe_ai_reply(
        self,
        *,
        candidate_name: str,
        resume: ResumeSnapshot | None,
        last_message: str,
    ) -> str | None:
        if self._ai_client is None:
            return None
        result = await self._ai_client.generate(
            candidate_name=candidate_name,
            resume_summary=(resume.summary if resume else None),
            last_message=last_message,
        )
        if result.kind == AiReplyKind.SUCCESS and result.text:
            return result.text
        return None


def _build_context(candidate_name: str, resume: ResumeSnapshot | None) -> dict[str, str | None]:
    if resume is None:
        return {"name": candidate_name}
    return {
        "name": resume.name or candidate_name,
        "position": resume.current_position,
        "company": resume.current_company,
        "education": resume.education,
        "expected_salary": resume.expected_salary,
        "expected_location": resume.expected_location,
        "summary": resume.summary,
    }
