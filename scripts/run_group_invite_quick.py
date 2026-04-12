"""
Quick end-to-end test: pick the first visible customer and dry-run the group invite steps.

Usage:
    python scripts/run_group_invite_quick.py --serial <SERIAL>
    python scripts/run_group_invite_quick.py --all
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


async def test_device(serial: str) -> dict:
    from wecom_automation.core.config import Config, ScrollConfig
    from wecom_automation.services.wecom_service import WeComService

    print(f"\n{'=' * 60}")
    print(f"DEVICE: {serial}")
    print(f"{'=' * 60}")

    custom_scroll = dataclasses.replace(ScrollConfig(), max_scrolls=3, stable_threshold=2)
    config = Config(scroll=custom_scroll, device_serial=serial)
    wecom = WeComService(config)

    results: dict = {"serial": serial, "steps": {}, "success": False}

    # Step 0: Resolution
    print("[0] Init resolution...")
    await wecom._ensure_screen_resolution()
    w, h = wecom._screen_width, wecom._screen_height
    print(f"    {w}x{h} (sx={wecom._scale_x:.2f} sy={wecom._scale_y:.2f})")
    results["resolution"] = f"{w}x{h}"

    # Step 1: Detect screen
    screen = await wecom.get_current_screen()
    print(f"[1] Screen: {screen}")
    results["steps"]["screen"] = screen

    # Step 2: Ensure on private chats
    if screen != "private_chats":
        print("    Navigating to private chats...")
        await wecom.ensure_on_private_chats()
        screen = await wecom.get_current_screen()
        print(f"    Now: {screen}")

    # Step 3: Find first customer on screen
    print("[2] Looking for a customer in the list...")
    elements = await wecom.adb.get_clickable_elements()
    customer_name = None
    customer_element = None
    for el in elements:
        text = (el.get("text") or "").strip()
        if text.startswith("B2") and len(text) > 6:
            customer_name = text
            customer_element = el
            break

    if not customer_name:
        print("    No customer found on screen!")
        results["steps"]["find_customer"] = "NONE FOUND"
        return results

    print(f"    Found: '{customer_name}'")
    results["steps"]["find_customer"] = customer_name

    # Step 4: Click the customer
    print("[3] Clicking customer...")
    idx = customer_element.get("index")
    if idx is not None:
        await wecom.adb.tap(idx)
        await wecom.adb.wait(1.5)
        screen = await wecom.get_current_screen()
        print(f"    After click -> screen: {screen}")
        results["steps"]["click_customer"] = screen
        if screen != "chat":
            print("    WARNING: Not in chat screen!")
    else:
        print("    No index on element, trying navigate_to_chat...")
        ok = await wecom.navigate_to_chat(serial, customer_name)
        print(f"    navigate_to_chat: {ok}")
        results["steps"]["click_customer"] = "OK" if ok else "FAILED"
        if not ok:
            return results

    # Step 5: Open chat info
    print("[4] Opening chat info...")
    t0 = time.monotonic()
    opened = await wecom.open_chat_info(serial)
    print(f"    open_chat_info: {opened} ({time.monotonic() - t0:.1f}s)")
    results["steps"]["open_chat_info"] = "OK" if opened else "FAILED"
    if not opened:
        # Dump UI for debugging
        _, els = await wecom.adb.get_ui_state(force=True)
        print(f"    UI elements ({len(els)}):")
        for i, el in enumerate(els[:15]):
            txt = el.get("text", "")
            cls = (el.get("className") or "").split(".")[-1]
            ck = el.get("clickable") or el.get("isClickable")
            b = wecom._parse_element_bounds(el)
            print(f"      [{i}] {cls}: text='{txt}' click={ck} bounds={b}")
        # Go back
        await wecom.go_back()
        return results

    # Step 6: Tap add member
    print("[5] Tapping add member...")
    await asyncio.sleep(1.0)
    t0 = time.monotonic()
    added = await wecom.tap_add_member_button(serial)
    print(f"    tap_add_member: {added} ({time.monotonic() - t0:.1f}s)")
    results["steps"]["tap_add_member"] = "OK" if added else "FAILED"

    if not added:
        _, els = await wecom.adb.get_ui_state(force=True)
        print(f"    UI elements ({len(els)}):")
        for i, el in enumerate(els[:20]):
            txt = el.get("text", "")
            desc = el.get("contentDescription", "")
            cls = (el.get("className") or "").split(".")[-1]
            b = wecom._parse_element_bounds(el)
            print(f"      [{i}] {cls}: text='{txt}' desc='{desc}' bounds={b}")

    # Go back to list (don't create group)
    print("[6] Going back (dry-run, not creating group)...")
    try:
        await wecom.go_back()
        await asyncio.sleep(0.5)
        await wecom.go_back()
        await asyncio.sleep(0.5)
        await wecom.go_back()
    except Exception:
        pass

    results["success"] = results["steps"].get("tap_add_member") == "OK"
    status = "PASS" if results["success"] else "FAIL"
    print(f"\n  Result: {status}")
    return results


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", help="Device serial")
    parser.add_argument("--all", action="store_true", help="All devices")
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

    print(f"Testing {len(serials)} device(s): {serials}\n")

    all_results = []
    for serial in serials:
        r = await test_device(serial)
        all_results.append(r)

    print(f"\n\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for r in all_results:
        s = "PASS" if r["success"] else "FAIL"
        print(f"\n  {r['serial']} ({r.get('resolution', '?')}): {s}")
        for k, v in r["steps"].items():
            print(f"    {k}: {v}")

    failed = sum(1 for r in all_results if not r["success"])
    print(f"\n{len(all_results) - failed}/{len(all_results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
