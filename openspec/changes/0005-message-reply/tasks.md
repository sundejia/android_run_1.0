# Tasks - 0005 Message Reply

## Phase 1: Fixtures

- [x] messages_list/with_unread.json (mixed read/unread)
- [x] conversation_detail/text_only.json
- [x] conversation_detail/with_image.json
- [x] resume_view/full_resume.json

## Phase 2: Parsers

- [x] tests/unit/boss/parsers/test_message_list_parser.py + impl
- [x] tests/unit/boss/parsers/test_conversation_parser.py + impl
- [x] tests/unit/boss/parsers/test_resume_parser.py + impl

## Phase 3: Template Engine

- [x] tests/unit/boss/services/test_template_engine.py + impl

## Phase 4: AI Reply Client

- [x] tests/unit/boss/services/test_ai_reply_client.py + impl

## Phase 5: Repositories

- [x] tests/unit/boss/test_conversation_repository.py + impl
- [x] tests/unit/boss/test_message_repository.py + impl
- [x] tests/unit/boss/test_template_repository.py + impl

## Phase 6: Reply Dispatcher

- [x] tests/unit/boss/services/test_reply_dispatcher.py + impl

## Phase 7: Backend

- [x] routers/boss_templates.py + tests
- [x] routers/boss_messages.py + tests
- [x] Mount in main.py

## Phase 8: Frontend

- [x] bossApi.ts extended (templates + messages)
- [x] stores/bossTemplates.ts + spec
- [x] stores/bossMessages.ts + spec
- [x] views/boss/TemplatesView.vue + spec
- [x] views/boss/ConversationsView.vue + spec

## Verification

- 227 BOSS Python unit tests green (`uv run pytest tests/unit/boss`).
- 42 BOSS backend API tests green (`uv run pytest wecom-desktop/backend/tests/test_boss_*`).
- 90 desktop Vitest tests green (`npx vitest run` in `wecom-desktop`).
- `ruff check src/boss_automation tests/unit/boss wecom-desktop/backend/routers/boss_*.py` clean.
