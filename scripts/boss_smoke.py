"""End-to-end BOSS smoke script.

Drives the full BOSS data path (recruiter → job → candidate →
message → re-engagement scan/run) against a temporary SQLite database
without touching any real Android device. Used as:

* a CI gate so a regression in any repository / orchestrator surfaces
  before deployment;
* a quick local sanity check after editing any of the BOSS modules.

Exit code is ``0`` on success and ``1`` on failure. The summary is
printed to stdout in a human-readable single line.

Usage::

    uv run scripts/boss_smoke.py [--db-path PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from boss_automation.database.candidate_repository import CandidateRepository  # noqa: E402
from boss_automation.database.conversation_repository import ConversationRepository  # noqa: E402
from boss_automation.database.followup_attempts_repository import (  # noqa: E402
    FollowupAttemptsRepository,
)
from boss_automation.database.job_repository import JobRepository  # noqa: E402
from boss_automation.database.message_repository import MessageRepository  # noqa: E402
from boss_automation.database.recruiter_repository import RecruiterRepository  # noqa: E402
from boss_automation.parsers.candidate_card_parser import CandidateCard  # noqa: E402
from boss_automation.parsers.job_list_parser import Job, JobStatus  # noqa: E402
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile  # noqa: E402
from boss_automation.services.reengagement.detector import find_eligible  # noqa: E402
from boss_automation.services.reengagement.orchestrator import (  # noqa: E402
    ReengagementKind,
    ReengagementOrchestrator,
    ReengagementSettings,
)


@dataclass(frozen=True, slots=True)
class SmokeSummary:
    recruiters: int
    jobs: int
    candidates: int
    eligible: int
    attempts: int
    outcome: str
    ok: bool


async def _always_safe(_boss_candidate_id: str) -> bool:
    return False


def run_smoke(*, db_path: str) -> SmokeSummary:
    """Execute the full happy path. Returns a :class:`SmokeSummary`."""
    now = datetime.now(tz=UTC)

    recruiter_repo = RecruiterRepository(db_path)
    rid = recruiter_repo.upsert(
        "SMOKE-DEVICE",
        RecruiterProfile(name="Smoke Recruiter", company="Smoke Co", position="HR"),
    )

    job_repo = JobRepository(db_path)
    job_repo.upsert(
        rid,
        Job(
            boss_job_id="SMOKE-J1",
            title="Smoke Test Engineer",
            status=JobStatus.OPEN,
            salary_min=20,
            salary_max=40,
            location="远程",
            education=None,
            experience=None,
        ),
    )

    cand_repo = CandidateRepository(db_path)
    cand_id = cand_repo.upsert_from_card(
        rid,
        CandidateCard(
            boss_candidate_id="SMOKE-CAND",
            name="Smoke 候选人",
            age=None,
            gender=None,
            education=None,
            experience_years=None,
            current_company=None,
            current_position=None,
        ),
    )
    cand_repo.set_status(rid, "SMOKE-CAND", "greeted")

    conv_repo = ConversationRepository(db_path)
    conv_id = conv_repo.upsert(recruiter_id=rid, candidate_id=cand_id)

    msg_repo = MessageRepository(db_path)
    msg_repo.insert(
        conversation_id=conv_id,
        direction="out",
        content_type="text",
        text="Smoke greeting",
        sent_at=now - timedelta(days=4),
        sent_by="auto",
    )

    eligible = find_eligible(
        db_path=db_path,
        recruiter_id=rid,
        silent_for_days=3,
        cooldown_days=7,
        now=now,
    )
    if not eligible:
        return SmokeSummary(
            recruiters=1,
            jobs=1,
            candidates=1,
            eligible=0,
            attempts=0,
            outcome="no_eligible",
            ok=False,
        )

    orchestrator = ReengagementOrchestrator(
        attempts_repo=FollowupAttemptsRepository(db_path),
        message_repo=msg_repo,
        dispatcher=None,
        is_blacklisted=_always_safe,
        settings=ReengagementSettings(silent_for_days=3, cooldown_days=7, daily_cap=10),
        clock=lambda: now,
    )
    outcome = asyncio.run(orchestrator.run_one(eligible=eligible[0]))

    ok = outcome.kind == ReengagementKind.DRY_RUN and outcome.attempt_id is not None
    return SmokeSummary(
        recruiters=1,
        jobs=1,
        candidates=1,
        eligible=len(eligible),
        attempts=1 if outcome.attempt_id else 0,
        outcome=outcome.kind.value,
        ok=ok,
    )


def format_summary(summary: SmokeSummary) -> str:
    label = "BOSS smoke OK" if summary.ok else "BOSS smoke FAIL"
    return (
        f"{label} "
        f"(recruiters={summary.recruiters}, "
        f"jobs={summary.jobs}, "
        f"candidates={summary.candidates}, "
        f"eligible={summary.eligible}, "
        f"attempts={summary.attempts}, "
        f"outcome={summary.outcome})"
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BOSS Zhipin pivot smoke test")
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="SQLite path; default is a fresh tempfile (auto-deleted).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    if args.db_path:
        summary = run_smoke(db_path=args.db_path)
    else:
        with tempfile.TemporaryDirectory(prefix="boss_smoke_") as td:
            summary = run_smoke(db_path=str(Path(td) / "smoke.db"))
    print(format_summary(summary))
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
