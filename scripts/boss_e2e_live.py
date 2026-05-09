"""Live E2E test for BOSS Zhipin automation on a real device.

Drives the full flow:
  1. Launch BOSS app → verify login
  2. Read recruiter profile
  3. Navigate to chat → list conversations with unread counts
  4. Dispatch one reply to the first unread conversation (dry-run first)
  5. If confirmed, send the actual reply
  6. Navigate to candidate recommendation feed → parse candidate cards
  7. Execute one greet attempt (dry-run)

Usage:
    BOSS_DEVICE_SERIAL=10AE9P1DTT002LE python scripts/boss_e2e_live.py [--send-reply] [--send-greet]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname)-5s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("droidrun").setLevel(logging.WARNING)
logging.getLogger("pydantic").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("boss-e2e-live")

from boss_automation.core.config import get_default_db_path
from boss_automation.database.candidate_repository import CandidateRepository
from boss_automation.database.conversation_repository import ConversationRepository
from boss_automation.database.message_repository import MessageRepository
from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.database.template_repository import TemplateRepository
from boss_automation.parsers.candidate_card_parser import parse_candidate_feed
from boss_automation.parsers.greet_state_detector import GreetState, detect_greet_state
from boss_automation.parsers.message_list_parser import parse_message_list
from boss_automation.parsers.recruiter_profile_parser import (
    LoginState,
    detect_login_state,
    extract_recruiter_profile,
)
from boss_automation.services.boss_app_service import BossAppService
from boss_automation.services.droidrun_adapter import DroidRunAdapter
from boss_automation.services.greet.greet_executor import (
    GreetExecutor,
    GreetOutcome,
    OutcomeKind,
)
from boss_automation.services.greet.quota_guard import GreetQuota, QuotaGuard
from boss_automation.services.greet.schedule import GreetSchedule, is_within_window, weekday_mask_for
from boss_automation.services.reply_dispatcher import DispatchKind, ReplyDispatcher
from boss_automation.services.template_engine import render_template

SERIAL = os.environ.get("BOSS_DEVICE_SERIAL", "10AE9P1DTT002LE")
DB_PATH = os.environ.get("BOSS_DB_PATH", str(get_default_db_path()))


async def _always_safe(_id: str) -> bool:
    return False


async def _press_back(adb: DroidRunAdapter) -> None:
    """Press BACK via adb shell (not in AdbPort protocol)."""
    import asyncio as _aio

    proc = await asyncio.create_subprocess_exec(
        "adb",
        "-s",
        SERIAL,
        "shell",
        "input",
        "keyevent",
        "4",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def _navigate_to_tab(adb: DroidRunAdapter, tab_name: str) -> bool:
    """Navigate to a bottom tab, handling the case where we might be in
    a detail page (press back first)."""
    for attempt in range(2):
        tapped = await adb.tap_by_text(tab_name)
        if tapped:
            return True
        # Maybe we're in a detail page, press back first
        await _press_back(adb)
        await asyncio.sleep(1.5)
    return False


def _log_separator(title: str) -> None:
    logger.info("=" * 60)
    logger.info("  %s", title)
    logger.info("=" * 60)


async def run_full_e2e(*, send_reply: bool = False, send_greet: bool = False) -> dict:
    results: dict = {"steps": {}, "start_time": time.time()}
    adb = DroidRunAdapter(serial=SERIAL, use_tcp=False, droidrun_port=8080)

    # ── Step 1: Launch & Login ──────────────────────────────────────
    _log_separator("STEP 1: Launch BOSS & verify login")
    service = BossAppService(adb)

    logger.info("Launching BOSS app on device %s ...", SERIAL)
    await service.launch()
    await asyncio.sleep(6)

    state = await service.detect_login_state()
    logger.info("Login state: %s", state.value)

    # On some devices the splash screen takes a moment longer,
    # or we may be on a detail page (no tab bar visible)
    if state != LoginState.LOGGED_IN:
        for retry in range(3):
            logger.info("Login state not detected, pressing BACK and retrying (attempt %d)...", retry + 1)
            await _press_back(adb)
            await asyncio.sleep(2)
            state = await service.detect_login_state()
            logger.info("Login state after retry: %s", state.value)
            if state == LoginState.LOGGED_IN:
                break

    results["steps"]["login_state"] = state.value

    if state != LoginState.LOGGED_IN:
        logger.error("ABORT: Device is not logged in!")
        results["error"] = "not_logged_in"
        return results

    profile = await service.get_recruiter_profile()
    if profile:
        logger.info("Recruiter: %s | Company: %s | Position: %s", profile.name, profile.company, profile.position)
        results["steps"]["recruiter"] = {
            "name": profile.name,
            "company": profile.company,
            "position": profile.position,
        }

    # Persist recruiter to DB
    recruiter_repo = RecruiterRepository(DB_PATH)
    recruiter_id = recruiter_repo.upsert(SERIAL, profile)
    logger.info("Recruiter persisted: id=%d", recruiter_id)
    results["steps"]["recruiter_id"] = recruiter_id

    # Navigate to 消息 tab (get_recruiter_profile may have switched to 我的 tab)
    logger.info("Navigating to 消息 tab...")
    await adb.tap_by_text("消息")
    await asyncio.sleep(2)

    # ── Step 2: Check chat page ─────────────────────────────────────
    _log_separator("STEP 2: Read chat page (messages list)")
    tree, _ = await adb.get_state()
    rows = parse_message_list(tree)
    logger.info("Found %d conversation rows", len(rows))

    unread_count_total = 0
    unread_rows = []
    for i, row in enumerate(rows):
        marker = " <<< UNREAD" if row.unread_count > 0 else ""
        logger.info(
            "  [%d] %s | unread=%d | last=%s%s",
            i,
            row.candidate_name,
            row.unread_count,
            (row.last_message_text or "")[:50],
            marker,
        )
        unread_count_total += row.unread_count
        if row.unread_count > 0:
            unread_rows.append(row)

    results["steps"]["conversations"] = {
        "total": len(rows),
        "unread_total": unread_count_total,
        "unread_conversations": len(unread_rows),
    }
    logger.info(
        "Summary: %d conversations, %d total unread, %d with unread", len(rows), unread_count_total, len(unread_rows)
    )

    # ── Step 3: Reply to unread (dry-run or real) ───────────────────
    if unread_rows:
        _log_separator("STEP 3: Reply to first unread conversation")
        target = unread_rows[0]
        logger.info(
            "Target: %s (id=%s, unread=%d)", target.candidate_name, target.boss_candidate_id, target.unread_count
        )

        template_repo = TemplateRepository(DB_PATH)

        def template_provider(scenario: str) -> str:
            record = template_repo.get_default(scenario)
            if record:
                return record.content
            rows = template_repo.list_by_scenario(scenario)
            if rows:
                return rows[0].content
            return "您好 {name}，看到您的简历很感兴趣，请问方便聊聊吗？"

        dispatcher = ReplyDispatcher(
            adb=adb,
            template_provider=template_provider,
            ai_client=None,
        )

        dry_run = not send_reply
        logger.info("Dispatching reply (dry_run=%s) ...", dry_run)
        try:
            outcome = await dispatcher.dispatch_one(
                is_blacklisted=_always_safe,
                dry_run=dry_run,
            )
            logger.info("Reply outcome: %s", outcome.kind.value)
            logger.info("  candidate_id: %s", outcome.boss_candidate_id)
            logger.info("  candidate_name: %s", outcome.candidate_name)
            logger.info("  text_sent: %s", (outcome.text_sent or "")[:100])
            if outcome.template_warnings:
                for w in outcome.template_warnings:
                    logger.warning("  template warning: %s", w)

            results["steps"]["reply"] = {
                "outcome": outcome.kind.value,
                "candidate_id": outcome.boss_candidate_id,
                "candidate_name": outcome.candidate_name,
                "text": outcome.text_sent,
                "dry_run": dry_run,
            }

            if outcome.kind in (DispatchKind.SENT_TEMPLATE, DispatchKind.SENT_AI):
                logger.info("REPLY SENT SUCCESSFULLY!")
        except Exception as exc:
            logger.error("Reply dispatch failed: %s", exc, exc_info=True)
            results["steps"]["reply"] = {"error": str(exc)}

        # Navigate back to message list after reply
        logger.info("Navigating back to 消息 tab...")
        await _navigate_to_tab(adb, "消息")
        await asyncio.sleep(2)
    else:
        logger.info("No unread conversations to reply to")
        results["steps"]["reply"] = {"outcome": "skipped_no_unread"}

    # ── Step 4: Navigate to candidate feed for greet ────────────────
    _log_separator("STEP 4: Navigate to candidate recommendation feed (牛人 tab)")

    # The bottom tab bar uses "牛人" for the recommendation/candidate tab
    tab_tapped = await _navigate_to_tab(adb, "牛人")
    logger.info("Tapped 牛人 tab: %s", tab_tapped)
    await asyncio.sleep(3)

    feed_tree, _ = await adb.get_state()
    cards = parse_candidate_feed(feed_tree)
    logger.info("Found %d candidate cards on feed", len(cards))

    for i, card in enumerate(cards[:8]):
        logger.info(
            "  [%d] id=%s name=%s age=%s edu=%s exp=%s pos=%s @ %s",
            i,
            card.boss_candidate_id,
            card.name,
            card.age or "?",
            card.education or "?",
            card.experience_years or "?",
            card.current_position or "?",
            card.current_company or "?",
        )

    results["steps"]["candidates"] = {
        "total": len(cards),
        "top3": [{"name": c.name, "id": c.boss_candidate_id, "position": c.current_position} for c in cards[:3]],
    }

    # ── Step 5: Execute one greet attempt ───────────────────────────
    if cards:
        _log_separator("STEP 5: Execute greet attempt")
        now = time.localtime()
        weekday = now.tm_wday
        schedule = GreetSchedule(
            weekday_mask=weekday_mask_for([0, 1, 2, 3, 4, 5, 6]),
            start_minute=0,
            end_minute=1439,
            timezone="Asia/Shanghai",
        )

        now_utc = datetime.now(tz=UTC)
        if not is_within_window(schedule, now_utc):
            logger.warning("Outside greet time window!")

        quota_guard = QuotaGuard(GreetQuota(per_day=80, per_hour=15, per_job=None))
        candidate_repo = CandidateRepository(DB_PATH)

        events: list[str] = []

        def on_progress(event) -> None:
            msg = f"[GREET] stage={event.stage}"
            if event.boss_candidate_id:
                msg += f" candidate={event.boss_candidate_id}"
            if event.detail:
                msg += f" detail={event.detail}"
            events.append(msg)
            logger.info(msg)

        executor = GreetExecutor(
            adb=adb,
            candidate_repo=candidate_repo,
            recruiter_id=recruiter_id,
            schedule=schedule,
            quota_guard=quota_guard,
            is_blacklisted=_always_safe,
        )

        # We need to be on the feed page for the executor
        # Navigate back to candidate feed first
        await _navigate_to_tab(adb, "牛人")
        await asyncio.sleep(2)

        logger.info("Starting greet execution...")
        try:
            outcome = await executor.execute_one(progress=on_progress)
            logger.info("Greet outcome: %s", outcome.kind.value)
            logger.info("  candidate_id: %s", outcome.boss_candidate_id)
            logger.info("  candidate_name: %s", outcome.candidate_name)
            logger.info("  detail: %s", outcome.detail)
            results["steps"]["greet"] = {
                "outcome": outcome.kind.value,
                "candidate_id": outcome.boss_candidate_id,
                "candidate_name": outcome.candidate_name,
                "detail": outcome.detail,
                "events": events,
            }

            if outcome.kind == OutcomeKind.SENT:
                logger.info("GREET SENT SUCCESSFULLY to %s!", outcome.candidate_name)
        except Exception as exc:
            logger.error("Greet execution failed: %s", exc, exc_info=True)
            results["steps"]["greet"] = {"error": str(exc), "events": events}
    else:
        logger.info("No candidate cards found on feed")
        results["steps"]["greet"] = {"outcome": "skipped_no_candidates"}

    # ── Step 6: Navigate back to chat page ──────────────────────────
    _log_separator("STEP 6: Return to chat page and final state")
    await _navigate_to_tab(adb, "消息")
    await asyncio.sleep(2)
    final_tree, _ = await adb.get_state()
    final_rows = parse_message_list(final_tree)
    logger.info("Final state: %d conversations listed", len(final_rows))
    for i, row in enumerate(final_rows[:5]):
        logger.info("  [%d] %s | unread=%d", i, row.candidate_name, row.unread_count)
    results["steps"]["final_state"] = {"conversations": len(final_rows)}

    results["elapsed"] = time.time() - results["start_time"]
    _log_separator("E2E COMPLETE")
    logger.info("Total elapsed: %.1fs", results["elapsed"])
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="BOSS Zhipin live E2E test")
    parser.add_argument("--send-reply", action="store_true", help="Actually send reply (default: dry-run)")
    parser.add_argument("--send-greet", action="store_true", help="Actually send greet (default: parse only)")
    args = parser.parse_args()

    logger.info("Starting live E2E test")
    logger.info("  Device: %s", SERIAL)
    logger.info("  DB: %s", DB_PATH)
    logger.info("  send_reply: %s", args.send_reply)
    logger.info("  send_greet: %s", args.send_greet)

    results = asyncio.run(run_full_e2e(send_reply=args.send_reply, send_greet=args.send_greet))

    # Summary
    print("\n" + "=" * 60)
    print("  E2E TEST SUMMARY")
    print("=" * 60)
    steps = results.get("steps", {})
    for step_name, step_data in steps.items():
        if isinstance(step_data, dict):
            print(f"  {step_name}: {step_data}")
        else:
            print(f"  {step_name}: {step_data}")
    elapsed = results.get("elapsed", 0)
    print(f"  Total time: {elapsed:.1f}s")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
