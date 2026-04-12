"""
End-to-end test for group-invite workflow on real devices.

Tests each step of the group-invite flow individually:
  1. Connect to device
  2. Navigate to a customer's chat
  3. Open chat info
  4. Tap add-member
  5. Search & select a member
  6. Confirm group creation

Usage:
    python scripts/run_group_invite_e2e.py --serial <DEVICE_SERIAL> --customer <NAME> --member <NAME>

    # Dry-run: stop after add-member (no group created)
    python scripts/run_group_invite_e2e.py --serial <DEVICE_SERIAL> --customer <NAME> --dry-run

    # All connected devices:
    python scripts/run_group_invite_e2e.py --all --customer <NAME> --member <NAME>
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


async def test_device(serial: str, customer_name: str, member_name: str | None, dry_run: bool) -> dict:
    from wecom_automation.core.config import Config, ScrollConfig
    from wecom_automation.services.wecom_service import WeComService

    print(f"\n{'=' * 60}")
    print(f"TESTING DEVICE: {serial}")
    print(f"{'=' * 60}")

    custom_scroll = dataclasses.replace(ScrollConfig(), max_scrolls=5, stable_threshold=2)
    config = Config(scroll=custom_scroll, device_serial=serial)
    wecom = WeComService(config)

    results = {
        "serial": serial,
        "steps": {},
        "success": False,
    }

    # Step 0: Connect & detect screen resolution
    print("\n[Step 0] Initializing device connection & resolution...")
    try:
        await wecom._ensure_screen_resolution()
        w = wecom._screen_width
        h = wecom._screen_height
        print(f"  Screen: {w}x{h} (scale_x={wecom._scale_x:.2f}, scale_y={wecom._scale_y:.2f})")
        results["resolution"] = f"{w}x{h}"
        results["steps"]["init"] = "OK"
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["init"] = f"FAILED: {e}"
        return results

    # Step 1: Detect current screen
    print("\n[Step 1] Detecting current screen...")
    try:
        screen = await wecom.get_current_screen()
        print(f"  Current screen: {screen}")
        results["steps"]["detect_screen"] = screen
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["detect_screen"] = f"FAILED: {e}"
        return results

    # Step 2: Navigate to private chats list
    print("\n[Step 2] Ensuring on private chats list...")
    try:
        on_list = await wecom.ensure_on_private_chats()
        print(f"  On private chats: {on_list}")
        results["steps"]["ensure_private_chats"] = "OK" if on_list else "FAILED"
        if not on_list:
            print("  WARNING: Could not confirm private chats screen, continuing anyway...")
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["ensure_private_chats"] = f"FAILED: {e}"

    # Step 3: Navigate to customer chat
    print(f"\n[Step 3] Navigating to customer: '{customer_name}'...")
    try:
        t0 = time.monotonic()
        found = await wecom.navigate_to_chat(serial, customer_name)
        elapsed = time.monotonic() - t0
        print(f"  Navigate result: {found} ({elapsed:.1f}s)")
        results["steps"]["navigate_to_chat"] = "OK" if found else "FAILED"
        if not found:
            print(f"  FAILED: Customer '{customer_name}' not found in chat list")
            return results
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["navigate_to_chat"] = f"FAILED: {e}"
        return results

    # Step 4: Verify we're on a chat screen
    print("\n[Step 4] Verifying chat screen...")
    try:
        await asyncio.sleep(1.0)
        screen = await wecom.get_current_screen()
        print(f"  Current screen after navigation: {screen}")
        results["steps"]["verify_chat"] = screen
        if screen != "chat":
            print(f"  WARNING: Expected 'chat' but got '{screen}'")
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["verify_chat"] = f"FAILED: {e}"

    # Step 5: Open chat info
    print("\n[Step 5] Opening chat info...")
    try:
        t0 = time.monotonic()
        opened = await wecom.open_chat_info(serial)
        elapsed = time.monotonic() - t0
        print(f"  Open chat info: {opened} ({elapsed:.1f}s)")
        results["steps"]["open_chat_info"] = "OK" if opened else "FAILED"
        if not opened:
            print("  FAILED: Could not find or tap chat info button")
            return results
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["open_chat_info"] = f"FAILED: {e}"
        return results

    # Step 6: Tap add-member button
    print("\n[Step 6] Tapping add-member button...")
    try:
        await asyncio.sleep(1.0)
        t0 = time.monotonic()
        added = await wecom.tap_add_member_button(serial)
        elapsed = time.monotonic() - t0
        print(f"  Tap add-member: {added} ({elapsed:.1f}s)")
        results["steps"]["tap_add_member"] = "OK" if added else "FAILED"
        if not added:
            print("  FAILED: Could not find add-member button")
            # Dump UI tree for debugging
            _, elements = await wecom.adb.get_ui_state(force=True)
            print(f"  UI elements ({len(elements)} total):")
            for i, el in enumerate(elements[:15]):
                txt = el.get("text", "")
                desc = el.get("contentDescription", "")
                cls = (el.get("className") or "").split(".")[-1]
                rid = (el.get("resourceId") or "").split("/")[-1]
                print(f"    [{i}] {cls}: text='{txt}', desc='{desc}', rid='{rid}'")
            return results
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["tap_add_member"] = f"FAILED: {e}"
        return results

    if dry_run:
        print("\n[DRY RUN] Stopping here (steps 1-6 passed). Going back...")
        # Go back twice (from add-member -> chat info -> chat)
        try:
            await wecom.go_back()
            await asyncio.sleep(0.5)
            await wecom.go_back()
        except Exception:
            pass
        results["steps"]["dry_run"] = "STOPPED"
        results["success"] = True
        return results

    if not member_name:
        print("\n  No member name specified. Stopping here.")
        results["steps"]["search_member"] = "SKIPPED (no --member)"
        return results

    # Step 7: Search and select member
    print(f"\n[Step 7] Searching for member: '{member_name}'...")
    try:
        await asyncio.sleep(1.0)
        t0 = time.monotonic()
        selected = await wecom.search_and_select_member(serial, member_name)
        elapsed = time.monotonic() - t0
        print(f"  Search & select member: {selected} ({elapsed:.1f}s)")
        results["steps"]["search_member"] = "OK" if selected else "FAILED"
        if not selected:
            print(f"  FAILED: Member '{member_name}' not found")
            return results
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["search_member"] = f"FAILED: {e}"
        return results

    # Step 8: Confirm group creation
    print("\n[Step 8] Confirming group creation...")
    try:
        await asyncio.sleep(0.5)
        t0 = time.monotonic()
        confirmed = await wecom.confirm_group_creation(serial, post_confirm_wait_seconds=2.0)
        elapsed = time.monotonic() - t0
        print(f"  Confirm group: {confirmed} ({elapsed:.1f}s)")
        results["steps"]["confirm_group"] = "OK" if confirmed else "FAILED"
        if not confirmed:
            print("  FAILED: Could not confirm group creation")
            return results
    except Exception as e:
        print(f"  FAILED: {e}")
        results["steps"]["confirm_group"] = f"FAILED: {e}"
        return results

    results["success"] = True
    print(f"\n{'=' * 60}")
    print(f"ALL STEPS PASSED for {serial}")
    print(f"{'=' * 60}")
    return results


async def main():
    parser = argparse.ArgumentParser(description="E2E group invite test on real devices")
    parser.add_argument("--serial", help="Device serial (or use --all)")
    parser.add_argument("--all", action="store_true", help="Test all connected devices")
    parser.add_argument("--customer", required=True, help="Customer name to open chat with")
    parser.add_argument("--member", help="Member name to add to group (skip if not given)")
    parser.add_argument("--dry-run", action="store_true", help="Stop after add-member (don't actually create group)")
    args = parser.parse_args()

    if args.all:
        from wecom_automation.services.device_service import DeviceDiscoveryService

        discovery = DeviceDiscoveryService()
        devices = await discovery.list_devices(include_properties=False)
        serials = [d.serial for d in devices if d.is_online]
        if not serials:
            print("ERROR: No online devices found")
            sys.exit(1)
        print(f"Found {len(serials)} device(s): {serials}")
    elif args.serial:
        serials = [args.serial]
    else:
        print("ERROR: Specify --serial or --all")
        sys.exit(1)

    all_results = []
    for serial in serials:
        result = await test_device(serial, args.customer, args.member, args.dry_run)
        all_results.append(result)

    print(f"\n\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for r in all_results:
        status = "PASS" if r["success"] else "FAIL"
        print(f"\n  Device {r['serial']}: {status}")
        print(f"  Resolution: {r.get('resolution', 'unknown')}")
        for step_name, step_result in r["steps"].items():
            marker = "OK" if step_result == "OK" or step_result == "chat" else "!!"
            print(f"    [{marker}] {step_name}: {step_result}")

    failed = [r for r in all_results if not r["success"]]
    if failed:
        print(f"\n{len(failed)} device(s) FAILED")
        sys.exit(1)
    else:
        print(f"\nAll {len(all_results)} device(s) PASSED")


if __name__ == "__main__":
    asyncio.run(main())
