# Design — 0006 Reengagement

## Lifecycle

```
scan(detector)
  └─► eligible candidates  (silent_for_days >= threshold,
                           we sent last,
                           not blacklisted at scan time,
                           cooldown elapsed,
                           no pending attempt)

run_one(orchestrator)
  ├─► quota.allow()  → if no, return SKIPPED_QUOTA
  ├─► repo.append_pending(candidate_id, conversation_id)
  ├─► repo.cancel_if_candidate_replied(...)
  │     (mid-flight: if they replied since scan, mark cancelled)
  ├─► is_blacklisted(candidate_id)?  (real-time DB read)
  │     yes → repo.mark_cancelled('blacklisted'); return SKIPPED_BLACKLISTED
  ├─► dispatcher.dispatch_one()  (re-uses M4 reply path)
  ├─► repo.mark_sent(attempt_id)  on success
  └─► repo.mark_failed(attempt_id, reason) on dispatch error
```

## Detector contract

```python
@dataclass(frozen=True)
class EligibleCandidate:
    recruiter_id: int
    candidate_id: int
    conversation_id: int
    boss_candidate_id: str
    last_outbound_at_iso: str
    silent_for_seconds: int

def find_eligible(
    *,
    db_path: str,
    recruiter_id: int,
    silent_for_days: int,
    cooldown_days: int,
    now: datetime,
) -> list[EligibleCandidate]: ...
```

Pure SQL over `conversations` + `messages` + `followup_attempts_v2`;
no UI, no ADB.

## Orchestrator contract

```python
@dataclass(frozen=True)
class ReengagementOutcome:
    kind: ReengagementKind  # SENT | SKIPPED_* | FAILED
    candidate_id: int | None
    boss_candidate_id: str | None
    attempt_id: int | None
    detail: str | None

class ReengagementOrchestrator:
    def __init__(
        self,
        *,
        adb: AdbPort | None,
        dispatcher: ReplyDispatcher | None,
        attempts_repo: FollowupAttemptsRepository,
        message_repo: MessageRepository,
        is_blacklisted: Callable[[str], Awaitable[bool]],
        clock: Callable[[], datetime] = ...,
    ) -> None: ...

    async def run_one(
        self,
        *,
        recruiter_id: int,
        eligible: EligibleCandidate,
    ) -> ReengagementOutcome: ...
```

`adb` and `dispatcher` are optional so unit tests can pass `None`
and exercise the cancellation paths without UI work. When both are
provided, a SENT path drives a real (or fake) dispatch.

## Repository

`followup_attempts_v2` already has:

```
id, candidate_id, conversation_id, scheduled_at, sent_at,
template_id, status, reason, created_at, updated_at
```

Operations:

- `append_pending(candidate_id, conversation_id, scheduled_at) -> int`
- `mark_sent(attempt_id, sent_at)` — also refuses double-send.
- `mark_cancelled(attempt_id, reason)`
- `mark_failed(attempt_id, reason)`
- `latest_for_candidate(candidate_id) -> AttemptRecord | None`
- `count_sent_in_range(recruiter_id, since, until)` — for daily cap.

## Risks

- Race between scan and run: detector saw candidate as silent, but
  candidate replied moments before send. The "cancel if candidate
  replied" check immediately before dispatch closes that gap.
- Duplicate SENT rows under retry: `attempt.status` transitions are
  one-shot; `mark_sent` raises if already sent.
- Blacklist drift: per AGENTS.md guardrail, `is_blacklisted` is
  called immediately before dispatch and must use a real-time DB
  read, not a cache.
