# Remote WeCom Chatbot SQLite Recovery (2026-05-01)

## Scope

Operational incident and recovery on a standalone deployment of the **WeCom chatbot** FastAPI app under `/root/brain/wecom_chat` on host `8.136.11.129`. This repository (`android_run_1.0`) does not contain that application source tree; this document records facts observed during recovery so future ops and debugging stay aligned.

Public HTTP on port `80` serves the default nginx welcome page. The chatbot API listens on **`8000`** (`uvicorn main:app --host 0.0.0.0 --port 8000`).

## Symptoms

- Users saw the generic fallback copy: “抱歉，我现在遇到了一些技术问题，请稍后再试。如有紧急事务，请联系人工客服。”
- Application logs showed repeated `sqlite3.DatabaseError: database disk image is malformed` on reads/writes against `messages`, `ai_usage_logs`, `message_flow_logs`, etc.

## Root cause

Primary SQLite database file **`./data/chatbot.db`** (configured via `.env` as `DB_URL=sqlite+aiosqlite:///./data/chatbot.db`) was **structurally corrupted**. `PRAGMA quick_check` / `integrity_check` reported btree/page errors (not merely a transient lock).

That corruption broke session persistence and usage logging; agents still attempted LLM calls but downstream SQLAlchemy sessions failed when flushing usage rows, which surfaced as agent-level failures and the same fallback message.

## Secondary issue after “clean backup” swap

A verified-good snapshot at **`data/BACKUP/chatbot.db`** (`integrity_check = ok`) was older than production. After replacing the corrupt file with that backup:

- **Database integrity** was restored.
- **`ai_providers` rows** in the old snapshot did not match the **current encryption material** in `.env`, so API keys could not be decrypted (`Invalid encrypted API key`). That caused provider health checks and chat to fail until provider rows were reconciled with the configuration that matches the running secret.

## Recovery steps performed

1. Stop `uvicorn` on port `8000` so nothing writes during file operations.
2. Full backup of the corrupt database and WAL/SHM under  
   `data/recovery_backups/<timestamp>/` with checksum manifest (for rollback and optional `.recover` later).
3. Confirm `data/BACKUP/chatbot.db` passes **`PRAGMA integrity_check`** before use.
4. Replace active `data/chatbot.db`; archive prior `-wal`/`-shm` beside the backup (avoid WAL mismatch).
5. Copy **`ai_providers`** (and related provider metadata) from the **archived corrupt** database into the new active DB **using read-only access** to the corrupt file (`immutable=1`) so encrypted blobs remain consistent with runtime decryption.
6. Restart `uvicorn`, verify `/health` and a `/chat` probe.

## Post-recovery verification

- `GET /health` reported **`healthy`** with `workflow: true`, `memory_sqlite: true`.
- Sample `POST /chat` returned a normal model reply (not the fallback string).
- **DeepSeek** and **Doubao** rows in `ai_providers`: both **`is_active = 1`**, **`fallback_strategy = AUTO_FALLBACK`**, **`fallback_provider_id`** pointing to each other (mutual fallback).
- Post-restart log slice: **no** new `database disk image is malformed` lines.

## Redis note

The stack warned that Redis on `localhost:6379` was unavailable; the service continued with **SQLite-only** conversation memory. Redis is optional for this recovery outcome.

## Data-loss trade-off

Replacing the corrupt file with `data/BACKUP/chatbot.db` rolls application state back to that backup’s timeline. The corrupt DB remains under `data/recovery_backups/` for forensic recovery or `sqlite3 .recover` if newer business data must be salvaged.

## References (in-repo)

- Provider fallback chain logic: `ProviderManager.chat_with_fallback` and `AUTO_FALLBACK` handling in the chatbot codebase (when synced into this monorepo).
- Project documentation index: [docs/INDEX.md](../INDEX.md).
