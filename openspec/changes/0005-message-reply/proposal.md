# 0005 - Message Reply: Resume-Aware Template + AI Replies

## Why

Greeting candidates is only step one. The recruiter's bottleneck shifts
to the messages page: dozens of unread conversations per day, each
requiring a tailored response built from the candidate's resume + the
recruiter's templates + (optionally) AI. Doing this by hand burns the
recruiter's day.

M4 ships the read/reply loop: parse the messages list, classify each
conversation, fetch the candidate's resume/last message, pick a template
or call AI, send via the BOSS chat composer, and persist the message.

## What

Five new fixture sets, parsers, a template-rendering engine, an AI
reply client (re-uses the existing HTTP client + circuit breaker
pattern), a reply dispatcher with full send-safety, repositories for
conversations / messages / templates, REST routes for templates CRUD
and reply dispatch, plus a two-column conversation detail view and a
templates management view in the desktop app.

### Specifically

- Fixtures: messages_list (3 conversations, mixed unread states),
  conversation_detail (text + image messages), resume_view (full
  panel).
- Parsers:
  - `parsers/message_list_parser.py` extracts a list of
    `ConversationSummary(boss_candidate_id, name, last_text, unread)`.
  - `parsers/conversation_parser.py` extracts ordered `Message`
    records from the chat detail page.
  - `parsers/resume_parser.py` extracts a `ResumeSnapshot` from the
    候选人简历 view (current job, expected job, education, etc.).
- Services:
  - `services/message/template_engine.py` renders templates with
    `{name} {position} {company}` placeholders, supports
    conditional segments via simple `{?has_resume: ... }` syntax.
  - `services/message/ai_reply_client.py` is a thin async HTTP
    client with timeout + retry + circuit-breaker pattern.
  - `services/message/reply_dispatcher.py` orchestrates one reply:
    pick conversation → load resume → pick template OR call AI →
    blacklist re-check → send → persist (`messages` table).
- Repositories:
  - `database/conversation_repository.py`
  - `database/message_repository.py`
  - `database/greeting_template_repository.py`
- Backend:
  - `routers/boss_templates.py` (CRUD on `greeting_templates`).
  - `routers/boss_messages.py` (list conversations, dispatch one
    reply via injected ADB).
- Frontend:
  - `services/bossApi.ts` extended with templates + messages APIs.
  - Pinia stores `bossTemplates.ts`, `bossMessages.ts`.
  - `views/boss/TemplatesView.vue` for CRUD.
  - `views/boss/ConversationsView.vue` two-column layout.

## Out of Scope

- Image reply / file send (M5+).
- Multi-turn AI dialogue (M5).
- Real WebSocket push for new messages (M6).

## Success Criteria

- Parsers extract typed records from new fixtures with 100 % branch
  coverage on happy-path tests.
- Template engine handles missing fields, conditional segments, and
  unknown placeholders without raising.
- AI reply client surfaces a typed `AiReplyResult` (success / timeout
  / circuit_open / http_error / empty) for the dispatcher to handle.
- Reply dispatcher passes a 6-path test matrix: template_render /
  ai_success / ai_timeout / ai_empty_falls_back_to_template /
  blacklist_recheck / outside_window.
- Templates CRUD endpoints validate scenario enum and unique
  `(name, scenario)` constraint per M0 schema.
- Two-column ConversationsView renders messages and resume side by
  side with the boss-scope theme.
- Total BOSS unit tests >= 220, coverage stays >= 90 %.
