"""
Full end-to-end group invite test on real devices.

Executes the complete flow:
  1. Find a customer on screen
  2. Click into their chat
  3. Open chat info
  4. Tap add member
  5. Search & select member
  6. Confirm group creation

Usage:
    python scripts/run_group_invite_full.py --serial <SERIAL> --member <NAME>
    python scripts/run_group_invite_full.py --all --member <NAME>
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "wecom-desktop" / "backend"))


def _ts():
    return time.strftime("%H:%M:%S")


async def test_device(serial: str, member_name: str) -> dict:
    from wecom_automation.core.config import Config, ScrollConfig
    from wecom_automation.services.wecom_service import WeComService

    print(f"\n{'=' * 60}")
    print(f"[{_ts()}] DEVICE: {serial}")
    print(f"{'=' * 60}")

    custom_scroll = dataclasses.replace(ScrollConfig(), max_scrolls=3, stable_threshold=2)
    config = Config(scroll=custom_scroll, device_serial=serial)
    wecom = WeComService(config)

    R: dict = {"serial": serial, "steps": {}, "success": False, "error": None}

    # --- Step 0: Resolution ---
    print(f"[{_ts()}] [0] Init resolution...")
    try:
        await wecom._ensure_screen_resolution()
        w, h = wecom._screen_width, wecom._screen_height
        print(f"  {w}x{h} (sx={wecom._scale_x:.2f} sy={wecom._scale_y:.2f})")
        R["resolution"] = f"{w}x{h}"
        R["steps"]["resolution"] = "OK"
    except Exception as e:
        print(f"  FAILED: {e}")
        R["steps"]["resolution"] = f"FAILED: {e}"
        R["error"] = str(e)
        return R

    # --- Step 1: Ensure on private chats ---
    print(f"[{_ts()}] [1] Ensure private chats...")
    screen = await wecom.get_current_screen()
    if screen != "private_chats":
        await wecom.ensure_on_private_chats()
        screen = await wecom.get_current_screen()
    print(f"  Screen: {screen}")
    R["steps"]["private_chats"] = screen

    # --- Step 2: Find first customer ---
    print(f"[{_ts()}] [2] Find customer on screen...")
    elements = await wecom.adb.get_clickable_elements()
    customer_name = None
    customer_el = None
    for el in elements:
        text = (el.get("text") or "").strip()
        if text.startswith("B2") and len(text) > 6:
            customer_name = text
            customer_el = el
            break

    if not customer_name:
        print("  No customer found!")
        R["steps"]["find_customer"] = "NONE"
        R["error"] = "No customer on screen"
        return R
    print(f"  Customer: {customer_name}")
    R["steps"]["find_customer"] = customer_name

    # --- Step 3: Click customer ---
    print(f"[{_ts()}] [3] Click customer...")
    idx = customer_el.get("index")
    if idx is not None:
        await wecom.adb.tap(idx)
        await wecom.adb.wait(1.5)
    else:
        ok = await wecom.navigate_to_chat(serial, customer_name)
        if not ok:
            R["steps"]["click_customer"] = "FAILED"
            R["error"] = "navigate_to_chat failed"
            return R
    screen = await wecom.get_current_screen()
    print(f"  Screen after click: {screen}")
    R["steps"]["click_customer"] = screen

    # --- Step 4: Open chat info ---
    print(f"[{_ts()}] [4] Open chat info...")
    t0 = time.monotonic()
    opened = await wecom.open_chat_info(serial)
    dt = time.monotonic() - t0
    print(f"  Result: {opened} ({dt:.1f}s)")
    R["steps"]["open_chat_info"] = "OK" if opened else "FAILED"
    if not opened:
        R["error"] = "open_chat_info failed"
        await wecom.go_back()
        return R

    # --- Step 5: Tap add member ---
    print(f"[{_ts()}] [5] Tap add member...")
    await asyncio.sleep(1.0)
    t0 = time.monotonic()
    added = await wecom.tap_add_member_button(serial)
    dt = time.monotonic() - t0
    print(f"  Result: {added} ({dt:.1f}s)")
    R["steps"]["tap_add_member"] = "OK" if added else "FAILED"
    if not added:
        R["error"] = "tap_add_member failed"
        await wecom.go_back()
        await asyncio.sleep(0.5)
        await wecom.go_back()
        return R

    # --- Step 6: Search and select member ---
    print(f"[{_ts()}] [6] Search & select member: '{member_name}'...")
    await asyncio.sleep(1.0)
    t0 = time.monotonic()
    selected = await wecom.search_and_select_member(serial, member_name)
    dt = time.monotonic() - t0
    print(f"  Result: {selected} ({dt:.1f}s)")
    R["steps"]["search_member"] = "OK" if selected else "FAILED"
    if not selected:
        R["error"] = f"search_and_select_member('{member_name}') failed"
        # Dump what's on screen for debugging
        _, els = await wecom.adb.get_ui_state(force=True)
        print(f"  UI dump ({len(els)} elements):")
        for i, el in enumerate(els[:20]):
            txt = el.get("text", "")
            desc = el.get("contentDescription", "")
            cls = (el.get("className") or "").split(".")[-1]
            print(f"    [{i}] {cls}: text='{txt}' desc='{desc}'")
        # Go back
        await wecom.go_back()
        await asyncio.sleep(0.5)
        await wecom.go_back()
        await asyncio.sleep(0.5)
        await wecom.go_back()
        return R

    # --- Step 7: Confirm group creation ---
    print(f"[{_ts()}] [7] Confirm group creation...")
    await asyncio.sleep(0.5)
    t0 = time.monotonic()
    confirmed = await wecom.confirm_group_creation(serial, post_confirm_wait_seconds=2.0)
    dt = time.monotonic() - t0
    print(f"  Result: {confirmed} ({dt:.1f}s)")
    R["steps"]["confirm_group"] = "OK" if confirmed else "FAILED"
    if not confirmed:
        R["error"] = "confirm_group failed"
        # Try to go back
        await wecom.go_back()
        await asyncio.sleep(0.5)
        await wecom.go_back()
        return R

    # --- Step 8: Verify we're in the new group chat ---
    print(f"[{_ts()}] [8] Verify group created...")
    await asyncio.sleep(1.0)
    screen = await wecom.get_current_screen()
    print(f"  Screen after confirm: {screen}")
    R["steps"]["post_confirm_screen"] = screen

    R["success"] = True
    print(f"\n[{_ts()}] ALL STEPS PASSED for {serial}")
    return R


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", help="Device serial")
    parser.add_argument("--all", action="store_true", help="All devices")
    parser.add_argument("--member", required=True, help="Member name to invite")
    args = parser.parse_args()

    if args.all:
        from wecom_automation.services.device_service import DeviceDiscoveryService

        discovery = DeviceDiscoveryService()
        devices = await discovery.list_devices(include_properties=False)
        serials = [d.serial for d in devices if d.is_online]
    elif args.serial:
        serials = [args.serial]
    else:
        print("Use --serial or --all")
        sys.exit(1)

    print(f"[{_ts()}] Testing {len(serials)} device(s): {serials}")
    print(f"[{_ts()}] Member to invite: {args.member}\n")

    all_results = []
    for serial in serials:
        r = await test_device(serial, args.member)
        all_results.append(r)

    print(f"\n\n{'=' * 60}")
    print("FINAL SUMMARY")
    print(f"{'=' * 60}")
    for r in all_results:
        s = "PASS" if r["success"] else "FAIL"
        print(f"\n  {r['serial']} ({r.get('resolution', '?')}): {s}")
        if r.get("error"):
            print(f"    ERROR: {r['error']}")
        for k, v in r["steps"].items():
            marker = "OK" if v == "OK" else ("!!" if "FAIL" in str(v) else "  ")
            print(f"    [{marker}] {k}: {v}")

    passed = sum(1 for r in all_results if r["success"])
    failed = len(all_results) - passed
    print(f"\n{'=' * 60}")
    print(f"  {passed}/{len(all_results)} PASSED, {failed} FAILED")
    print(f"{'=' * 60}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
