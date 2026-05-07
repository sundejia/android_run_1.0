# Design — 0007 Ops Hardening

## Monitoring summary contract

```python
class RecruiterSummary(BaseModel):
    recruiter_id: int
    device_serial: str
    name: str | None
    jobs_by_status: dict[str, int]
    candidates_by_status: dict[str, int]
    greet_attempts_last_24h: dict[str, int]      # sent / cancelled / failed
    reengagement_attempts_last_24h: dict[str, int]
    silent_candidates_eligible: int

class MonitoringSummaryResponse(BaseModel):
    generated_at_iso: str
    recruiters: list[RecruiterSummary]
```

The endpoint runs four read-only SQL queries per recruiter and zero
writes. It does not call into device code so it's safe to poll from
the dashboard at 5-second intervals.

## Smoke script outline

```text
1. Create a temp SQLite DB.
2. Apply BOSS schema (ensure_schema).
3. Upsert one recruiter, one job, one candidate.
4. Insert one outbound message dated 4 days ago.
5. Run SilentCandidateDetector → assert 1 row.
6. Drive ReengagementOrchestrator with no dispatcher → expect DRY_RUN
   and one cancelled attempt row.
7. Print "BOSS smoke OK (recruiters=1, jobs=1, candidates=1, attempts=1)"
   and exit 0.
```

The script is a thin wrapper around the same modules the API uses,
so a regression here implies a regression in the public contract.

## Dashboard view

Single `BossDashboardView.vue` page that:

- Polls the summary endpoint on mount + every 30s while active.
- Shows one card per recruiter with the four counters as small
  stats blocks plus a "立即扫描" button that calls the existing
  reengagement scan endpoint.
- Renders a coloured chip for jobs_by_status and candidates_by_status.

This is intentionally read-only: any write action (start sync,
update settings) lives in the existing per-feature views.

## Risks

- Counting per-recruiter requires a JOIN through `candidates` for
  the attempts tables. We add a covering index in code (idempotent)
  if performance becomes an issue, but at hundreds of attempts/day
  the unindexed query is fine.
- The 24-hour window is a rolling clock window, not a calendar day.
  Documented explicitly in the API response.
