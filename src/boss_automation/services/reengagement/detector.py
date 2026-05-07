"""Pure SQL scan: find candidates eligible for re-engagement.

A candidate is **eligible** when:

1. Their conversation's most recent message is **outbound** (us).
2. That outbound message is older than ``silent_for_days``.
3. They are not in the ``blocked`` status (the orchestrator still
   re-checks the dedicated blacklist table at send time, per
   AGENTS.md guardrail).
4. The most recent ``followup_attempts_v2`` row with status ``sent``
   for that candidate is older than ``cooldown_days`` (or doesn't
   exist).

The detector does no UI work and does not write to the DB.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from boss_automation.database.schema import ensure_schema


@dataclass(frozen=True, slots=True)
class EligibleCandidate:
    recruiter_id: int
    candidate_id: int
    conversation_id: int
    boss_candidate_id: str
    last_outbound_at_iso: str
    silent_for_seconds: int


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def find_eligible(
    *,
    db_path: str | Path,
    recruiter_id: int,
    silent_for_days: int,
    cooldown_days: int,
    now: datetime,
) -> list[EligibleCandidate]:
    if silent_for_days < 0 or cooldown_days < 0:
        raise ValueError("silent_for_days and cooldown_days must be non-negative")

    ensure_schema(str(db_path))
    now_utc = _ensure_utc(now)
    silent_threshold_iso = (now_utc - _days(silent_for_days)).isoformat()
    cooldown_threshold_iso = (now_utc - _days(cooldown_days)).isoformat()

    sql = """
    WITH latest_out AS (
        SELECT conversation_id, MAX(sent_at) AS last_out_at
        FROM messages
        WHERE direction = 'out'
        GROUP BY conversation_id
    ),
    latest_in AS (
        SELECT conversation_id, MAX(sent_at) AS last_in_at
        FROM messages
        WHERE direction = 'in'
        GROUP BY conversation_id
    ),
    recent_attempts AS (
        SELECT candidate_id, MAX(sent_at) AS last_attempt_at
        FROM followup_attempts_v2
        WHERE status = 'sent'
        GROUP BY candidate_id
    )
    SELECT
        c.id            AS conversation_id,
        c.recruiter_id  AS recruiter_id,
        c.candidate_id  AS candidate_id,
        cand.boss_candidate_id AS boss_candidate_id,
        lo.last_out_at  AS last_out_at
    FROM conversations c
    JOIN candidates cand ON cand.id = c.candidate_id
    JOIN latest_out lo  ON lo.conversation_id = c.id
    LEFT JOIN latest_in li ON li.conversation_id = c.id
    LEFT JOIN recent_attempts ra ON ra.candidate_id = c.candidate_id
    WHERE c.recruiter_id = ?
      AND lo.last_out_at <= ?
      AND (li.last_in_at IS NULL OR li.last_in_at < lo.last_out_at)
      AND cand.status != 'blocked'
      AND (ra.last_attempt_at IS NULL OR ra.last_attempt_at < ?)
    ORDER BY lo.last_out_at ASC
    """

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            sql,
            (
                recruiter_id,
                silent_threshold_iso,
                cooldown_threshold_iso,
            ),
        ).fetchall()
    finally:
        conn.close()

    out: list[EligibleCandidate] = []
    for row in rows:
        last_out_iso = row["last_out_at"]
        silent_seconds = _silent_seconds(last_out_iso, now_utc)
        out.append(
            EligibleCandidate(
                recruiter_id=int(row["recruiter_id"]),
                candidate_id=int(row["candidate_id"]),
                conversation_id=int(row["conversation_id"]),
                boss_candidate_id=row["boss_candidate_id"],
                last_outbound_at_iso=last_out_iso,
                silent_for_seconds=silent_seconds,
            )
        )
    return out


def _days(n: int) -> _TimedeltaShim:
    # Tiny indirection so the SQL string above can be inspected without
    # constructing timedeltas at import time.
    from datetime import timedelta

    return timedelta(days=n)


def _silent_seconds(last_out_iso: str, now_utc: datetime) -> int:
    try:
        last = datetime.fromisoformat(last_out_iso)
    except ValueError:
        return 0
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    delta = now_utc - last
    return int(delta.total_seconds())


# Local alias so static type checkers don't complain about the dummy
# _TimedeltaShim name above. The actual return type is timedelta.
_TimedeltaShim = object
