"""
End-to-end verification for the contact_picker page-state validator fix.

Goal: prove on a *real* device that after the 2026-05-07 selectors+page_state
patch, the share flow no longer aborts at the contact_card_menu state check.

Flow (non-destructive — never taps "Send"):
  1. Enter the first chat in the Messages list.
  2. Tap the attach button.
  3. Run `_assert_page_state("attach_panel", ...)` and assert OK.
  4. Open the Contact Card menu (current page or swipe + page 2).
  5. Run `_assert_page_state("contact_picker", ...)` and assert OK.
       ← THIS is the exact assertion that was failing in production
  6. Press back twice to dismiss picker + attach panel.

Pre-conditions:
  - adb device connected, serial passed in --serial
  - DroidRun overlay running on the device
  - Port forward already set up:  adb forward tcp:8080 tcp:8080
  - WeCom open on Messages tab (or any private-chats list)

Usage:
    .venv/bin/python scripts/e2e_verify_contact_picker_state.py --serial 10AE9P1DTT002LE
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wecom_automation.core.config import Config  # noqa: E402
from wecom_automation.core.logging import get_logger, init_logging  # noqa: E402
from wecom_automation.services.contact_share.models import (  # noqa: E402
    ContactShareRequest,
)
from wecom_automation.services.contact_share.page_state import (  # noqa: E402
    PageStateValidator,
)
from wecom_automation.services.contact_share.service import ContactShareService  # noqa: E402
from wecom_automation.services.wecom_service import WeComService  # noqa: E402

init_logging(hostname="e2e-pickerstate", level="INFO", console=True)
logger = get_logger("e2e.contact_picker_state")


def _print(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def _enter_first_chat(wecom: WeComService) -> bool:
    """Tap the topmost customer row in the Messages list."""
    screen = await wecom.get_current_screen()
    if screen == "chat":
        _print("[setup] Already on chat screen.")
        return True

    if screen != "private_chats":
        _print(f"[setup] Current screen: {screen} — navigating to private_chats…")
        await wecom.ensure_on_private_chats()
        await asyncio.sleep(1.0)

    _, elements = await wecom.adb.get_ui_state(force=True)
    candidate = None
    for e in elements:
        rid = e.get("resourceId") or ""
        text = (e.get("text") or "").strip()
        # The Messages list rows have a "hzj" name TextView per the UI dump.
        if "hzj" in rid and text and text not in ("Messages", "Emails", "Doc", "Workspace", "Contacts"):
            candidate = e
            break
    if candidate is None:
        _print("[setup] Could not find a customer row — abort.")
        return False
    name = (candidate.get("text") or "").split("\n")[0]
    idx = candidate.get("index")
    _print(f"[setup] Entering chat: '{name}' (index={idx})")
    await wecom.adb.tap(int(idx))
    await asyncio.sleep(2.0)
    return (await wecom.get_current_screen()) == "chat"


async def _back_n(wecom: WeComService, n: int) -> None:
    for _ in range(n):
        try:
            await wecom.go_back()
        except Exception:
            pass
        await asyncio.sleep(0.5)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    config = Config().with_overrides(device_serial=args.serial, droidrun_port=args.port)
    wecom = WeComService(config)
    share = ContactShareService(wecom_service=wecom, db_path=":memory:")

    request = ContactShareRequest(
        device_serial=args.serial,
        customer_name="(e2e-probe)",
        contact_name="(none)",
        send_message_before_share=False,
        pre_share_message_text="",
        assume_current_chat=True,
    )

    failures: list[str] = []
    completed_steps: list[str] = []

    try:
        _print("=" * 70)
        _print(" E2E: contact_picker page-state validator fix verification")
        _print("=" * 70)

        if not await _enter_first_chat(wecom):
            failures.append("could not enter chat")
            return 1
        completed_steps.append("entered_chat")

        _print("\n[1/3] Tap attach button…")
        if not await share._tap_attach_button(device_serial=args.serial):
            failures.append("attach_button tap failed")
            return 1
        completed_steps.append("tapped_attach_button")

        _print("[1/3] Assert page_state == attach_panel")
        ok = await share._assert_page_state("attach_panel", step="attach_button", request=request)
        if not ok:
            failures.append("attach_panel state-check FAILED")
            return 1
        _print("[1/3]  -> OK (attach_panel)")

        _print("\n[2/3] Open Contact Card menu (current page or swipe to page 2)…")
        opened = await share._open_contact_card_menu(request=request)
        if not opened:
            failures.append("contact_card_menu tap failed (couldn't find Contact Card)")
            return 1
        completed_steps.append("tapped_contact_card_menu")

        # ── THE critical assertion: this is what was returning False before
        # the fix on the 2026-05-07 build (nle/cwa/Select Contact(s)). ──
        _print("[3/3] Assert page_state == contact_picker  ← REGRESSION TARGET")
        ok = await share._assert_page_state("contact_picker", step="contact_card_menu", request=request)
        # Always also do a direct, instrumented validator read so we log both signals.
        _, elements = await wecom.adb.get_ui_state(force=True)
        summary = PageStateValidator.describe(elements)
        is_picker = PageStateValidator.is_contact_picker_open(elements)
        _print(f"        validator.describe()           = {summary!r}")
        _print(f"        validator.is_contact_picker_open() = {is_picker}")

        if not ok or not is_picker:
            failures.append(
                f"contact_picker state-check FAILED  (assert={ok}, direct={is_picker}, summary={summary!r})"
            )
            return 1
        completed_steps.append("contact_picker_validated")

        _print("\nALL STEPS PASSED — fix is live on device.")
        return 0
    except Exception as exc:
        failures.append(f"unexpected exception: {exc!r}")
        logger.exception("E2E probe crashed")
        return 1
    finally:
        # Non-destructive cleanup: back out picker + attach panel.
        await _back_n(wecom, 2)
        _print("\n" + "=" * 70)
        _print(" Summary")
        _print("=" * 70)
        for s in completed_steps:
            _print(f"  ✓ {s}")
        for f in failures:
            _print(f"  ✗ {f}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
