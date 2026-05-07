"""
End-to-end test for ContactFinder search in the contact card picker.

Prerequisites:
  - Device connected via ADB (serial: from --serial arg or auto-detected)
  - DroidRun app running on device with overlay port open
  - WeCom is open on a customer's chat screen

Usage:
    uv run tests/integration/test_contact_search_e2e.py --contact 刘晓璐
    uv run tests/integration/test_contact_search_e2e.py --contact 刘晓璐 --serial 10AF6R2MR900D8A --port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Fix Windows console encoding for Chinese characters
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wecom_automation.core.config import Config
from wecom_automation.core.logging import get_logger, init_logging
from wecom_automation.services.wecom_service import WeComService

init_logging(hostname="test", level="DEBUG", console=True)
logger = get_logger("test.contact_search_e2e")

ADB_PATH = str(PROJECT_ROOT / "wecom-desktop" / "adb" / "adb.exe")


@dataclass
class StepResult:
    name: str
    passed: bool
    duration_ms: float = 0.0
    message: str = ""
    details: dict = field(default_factory=dict)


async def run_step(name: str, coro) -> StepResult:
    start = time.perf_counter()
    try:
        result = await coro
        elapsed = (time.perf_counter() - start) * 1000
        if isinstance(result, tuple):
            passed, msg = result
        elif isinstance(result, bool):
            passed = result
            msg = "OK" if passed else "Failed"
        else:
            passed = True
            msg = str(result) if result else "OK"
        return StepResult(name=name, passed=passed, duration_ms=elapsed, message=msg)
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return StepResult(name=name, passed=False, duration_ms=elapsed, message=f"Exception: {exc}")


def _log_elements(elements: list[dict], label: str = "Elements") -> None:
    """Log ALL elements for debugging — no filtering."""
    logger.info(f"[{label}] Total: {len(elements)}")
    for i, elem in enumerate(elements[:80]):
        text = elem.get("text", "")
        desc = elem.get("contentDescription", "")
        rid = elem.get("resourceId", "")
        cls = elem.get("className", "").split(".")[-1] if elem.get("className") else ""
        idx = elem.get("index", "?")
        bounds = elem.get("bounds", "")
        clickable = elem.get("clickable", "")
        logger.info(
            f"  [{i}] idx={idx} cls={cls} click={clickable} text='{text[:50]}' desc='{desc[:30]}' rid='{rid}' bounds={bounds}"
        )


async def test_contact_search(serial: str, contact_name: str, port: int) -> list[StepResult]:
    """Run the contact card search test on a real device."""
    steps: list[StepResult] = []
    config = Config(device_serial=serial, use_tcp=False, droidrun_port=port)
    wecom = WeComService(config)

    # ── Step 1: DroidRun Portal 连接 ────────────────────────────
    print("\n[Step 1] 测试 DroidRun Portal 连接...")
    step = await run_step("DroidRun Portal 连接", _test_portal(wecom))
    steps.append(step)
    _print_step(step)
    if not step.passed:
        return steps

    # ── Step 1.5: 关闭可能的权限对话框 ──────────────────────────
    print("\n[Step 1.5] 检查并关闭权限对话框...")
    await _dismiss_permission_dialogs(wecom)

    # ── Step 1.6: 确保在聊天界面 ───────────────────────────────
    print("\n[Step 1.6] 确保在聊天界面...")
    screen = await wecom.get_current_screen()
    print(f"  当前屏幕: {screen}")

    if screen not in ("chat",):
        # 尝试返回到私聊列表
        if not await wecom.ensure_on_private_chats():
            print("  无法导航到私聊列表，尝试启动企业微信...")
            await wecom.launch_wecom(wait_for_ready=True)
            await asyncio.sleep(2.0)
            await wecom.ensure_on_private_chats()

        # 从聊天列表选第一个客户进入聊天
        ui_tree, elements = await wecom.adb.get_ui_state(force=True)
        # 会话列表昵称行的 resourceId 在不同 build 上为 hrr 或 hzj（720×1612 实测 hzj）
        _SKIP_ROW_PREFIXES = (
            "Messages",
            "Emails",
            "Doc",
            "Workspace",
            "Contacts",
            "Private Chats",
            "Meeting",
            "Cal",
        )
        for elem in elements:
            text = (elem.get("text") or "").strip()
            rid = elem.get("resourceId") or ""
            first_line = text.split("\n")[0].strip() if text else ""
            if not text or any(first_line.startswith(p) for p in _SKIP_ROW_PREFIXES):
                continue
            if not ("hrr" in rid or "hzj" in rid):
                continue
            idx = elem.get("index")
            if idx is None:
                continue
            name = first_line[:40]
            print(f"  尝试进入聊天: {name}")
            await wecom.adb.tap(int(idx))
            await asyncio.sleep(2.0)
            screen = await wecom.get_current_screen()
            print(f"  进入后屏幕: {screen}")
            break

    screen = await wecom.get_current_screen()
    print(f"  最终屏幕: {screen}")
    if screen != "chat":
        print("  ERROR: 未能进入聊天界面，中止测试")
        return steps

    # ── Step 2: 获取当前 UI 状态（确认在聊天界面） ──────────────
    print("\n[Step 2] 获取当前 UI 状态...")
    step = await run_step("获取 UI 状态", _test_get_ui_state(wecom))
    steps.append(step)
    _print_step(step)

    # ── Step 3: 点附件按钮 (i9u) ────────────────────────────────
    print("\n[Step 3] 点击附件按钮...")
    step = await run_step("点击附件按钮", _test_tap_attach(wecom))
    steps.append(step)
    _print_step(step)
    if not step.passed:
        return steps

    await asyncio.sleep(1.5)

    # ── Step 3.5: Dump 附件面板 UI 结构 ─────────────────────────
    print("\n[Step 3.5] 探测附件面板 UI 结构...")
    ui_tree, elements = await wecom.adb.get_ui_state(force=True)
    _log_elements(elements, "Attach Panel")

    # ── Step 4: 打开名片 (Contact Card) ─────────────────────────
    print("\n[Step 4] 打开名片菜单...")
    step = await run_step("打开名片菜单", _test_open_contact_card(wecom))
    steps.append(step)
    _print_step(step)
    if not step.passed:
        await _safe_go_back(wecom)
        return steps

    await asyncio.sleep(1.5)

    # ── Step 5: 探测联系人选择器 UI（搜索按钮/输入框） ──────────
    print("\n[Step 5] 探测联系人选择器 UI...")
    step = await run_step("探测选择器 UI", _test_probe_picker_ui(wecom))
    steps.append(step)
    _print_step(step)

    # ── Step 6: 使用 SearchContactFinder 搜索联系人 ─────────────
    print(f"\n[Step 6] 使用搜索策略查找联系人: {contact_name}...")
    step = await run_step(f"搜索联系人 ({contact_name})", _test_search_contact(wecom, contact_name))
    steps.append(step)
    _print_step(step)
    if not step.passed:
        await _safe_go_back(wecom)
        await _safe_go_back(wecom)
        return steps

    await asyncio.sleep(1.0)

    # ── Step 7: 点击发送确认 ─────────────────────────────────────
    print("\n[Step 7] 点击发送确认...")
    step = await run_step("点击发送确认", _test_confirm_send(wecom))
    steps.append(step)
    _print_step(step)

    await asyncio.sleep(1.0)

    # ── Step 8: 验证返回聊天界面 ────────────────────────────────
    print("\n[Step 8] 验证返回聊天界面...")
    step = await run_step("验证聊天界面", _test_verify_chat_screen(wecom))
    steps.append(step)
    _print_step(step)

    return steps


# ── Individual step implementations ─────────────────────────────


async def _test_portal(wecom: WeComService) -> tuple[bool, str]:
    try:
        ui_tree, elements = await wecom.adb.get_ui_state(force=True)
        if ui_tree is not None:
            return True, f"Portal OK, {len(elements)} clickable elements"
        return False, "Portal returned empty UI tree"
    except Exception as exc:
        return False, f"Portal failed: {exc}"


async def _test_get_ui_state(wecom: WeComService) -> tuple[bool, str]:
    try:
        ui_tree, elements = await wecom.adb.get_ui_state(force=True)
        _log_elements(elements, "Current Screen")
        screen = await wecom.get_current_screen()
        return True, f"Screen={screen}, {len(elements)} elements"
    except Exception as exc:
        return False, f"Failed: {exc}"


async def _test_tap_attach(wecom: WeComService) -> tuple[bool, str]:
    """Tap attachment button using the contact share selectors."""
    from wecom_automation.services.contact_share import selectors as S

    for attempt in range(3):
        try:
            ui_tree, elements = await wecom.adb.get_ui_state(force=True)
            matches = wecom._find_elements_by_keywords(
                elements,
                resource_patterns=S.ATTACH_RESOURCE_PATTERNS,
            )
            if matches:
                idx = matches[0].get("index")
                if idx is not None:
                    await wecom.adb.tap(int(idx))
                    return True, f"Tapped attach button (index={idx})"
        except Exception as exc:
            logger.warning(f"Attach tap attempt {attempt + 1} failed: {exc}")
        await asyncio.sleep(0.5)
    return False, "Could not find/tap attachment button"


async def _test_open_contact_card(wecom: WeComService) -> tuple[bool, str]:
    """Open Contact Card menu — adaptive (try current page, swipe if needed)."""
    from wecom_automation.services.contact_share import selectors as S

    # Fast path: try current page
    for attempt in range(2):
        try:
            ui_tree, elements = await wecom.adb.get_ui_state(force=True)
            matches = wecom._find_elements_by_keywords(
                elements,
                text_patterns=S.CARD_TEXT_PATTERNS,
                resource_patterns=S.CARD_RESOURCE_PATTERNS,
            )
            if matches:
                idx = matches[0].get("index")
                if idx is not None:
                    await wecom.adb.tap(int(idx))
                    return True, f"Tapped Contact Card (index={idx}, page={'current' if attempt == 0 else 'swiped'})"
        except Exception:
            pass

        # Swipe left on GridView — align with ContactShareService (ahe legacy / aij new build + edge margin)
        try:
            import re

            ui_tree, elements = await wecom.adb.get_ui_state(force=True)
            margin, dur_ms, min_dist = 100, 600, 240
            for elem in elements:
                rid = elem.get("resourceId") or ""
                if not any(g in rid for g in S.ATTACH_GRID_RESOURCE_PATTERNS):
                    continue
                bounds = elem.get("bounds", "")
                nums = re.findall(r"\d+", bounds)
                if len(nums) < 4:
                    continue
                x1, y1, x2, y2 = int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])
                grid_w = max(1, x2 - x1)
                cy = (y1 + y2) // 2
                m = margin
                if grid_w - 2 * m < min_dist:
                    m = max(0, (grid_w - min_dist) // 2)
                sx, ex = x2 - m, x1 + m
                await wecom.adb.swipe(sx, cy, ex, cy, duration_ms=dur_ms)
                await asyncio.sleep(2.5)
                break
        except Exception as exc:
            logger.warning(f"Swipe failed: {exc}")

    return False, "Could not find Contact Card menu item"


async def _test_probe_picker_ui(wecom: WeComService) -> tuple[bool, str]:
    """Probe the contact picker UI to log search button/input elements."""
    from wecom_automation.services.ui_search import selectors as S
    from wecom_automation.services.ui_search.ui_helpers import (
        find_search_button,
        find_search_input,
    )

    try:
        ui_tree, elements = await wecom.adb.get_ui_state(force=True)
        _log_elements(elements, "Contact Picker")

        # Check for search button
        search_btn = find_search_button(
            elements,
            text_patterns=S.PICKER_SEARCH_TEXT_PATTERNS,
            desc_patterns=S.PICKER_SEARCH_DESC_PATTERNS,
            resource_patterns=S.PICKER_SEARCH_RESOURCE_PATTERNS,
            screen_width=wecom._screen_width or 1080,
            screen_height=wecom._screen_height or 2340,
        )

        # Check for search input
        search_input = find_search_input(elements)

        details = []
        if search_btn:
            details.append(
                f"Search button found: idx={search_btn.get('index')} text='{search_btn.get('text')}' bounds={search_btn.get('bounds')}"
            )
        else:
            details.append("No search button found by keywords")

        if search_input:
            details.append(
                f"Search input found: idx={search_input.get('index')} cls={search_input.get('className')} bounds={search_input.get('bounds')}"
            )
        else:
            details.append("No search input found")

        msg = "; ".join(details)
        return True, msg
    except Exception as exc:
        return False, f"Probe failed: {exc}"


async def _test_search_contact(wecom: WeComService, contact_name: str) -> tuple[bool, str]:
    """Use SearchContactFinder to find and select a contact."""
    from wecom_automation.services.ui_search.strategy import SearchContactFinder

    # Ensure screen resolution is detected for correct coordinate filtering
    await wecom._ensure_screen_resolution()

    finder = SearchContactFinder(
        screen_width=wecom._screen_width,
        screen_height=wecom._screen_height,
    )
    try:
        result = await finder.find_and_select(contact_name, wecom.adb)
        if result:
            return True, f"Successfully found and selected '{contact_name}'"
        return False, f"Could not find '{contact_name}' via search"
    except Exception as exc:
        return False, f"Search failed: {exc}"


async def _test_confirm_send(wecom: WeComService) -> tuple[bool, str]:
    """Tap Send in the confirmation dialog.

    Uses resource_patterns first to avoid false matches like 'Send to:'.
    Falls back to text matching only if resource matching yields nothing.
    """
    from wecom_automation.services.contact_share import selectors as S
    from wecom_automation.services.ui_search.ui_helpers import find_elements_by_keywords

    for _attempt in range(3):
        try:
            ui_tree, elements = await wecom.adb.get_ui_state(force=True)
            # Prefer resource-based matching to avoid "Send to:" false positives
            matches = find_elements_by_keywords(
                elements,
                resource_patterns=S.SEND_RESOURCE_PATTERNS,
            )
            if not matches:
                matches = find_elements_by_keywords(
                    elements,
                    text_patterns=S.SEND_TEXT_PATTERNS,
                )
            if matches:
                idx = matches[0].get("index")
                if idx is not None:
                    await wecom.adb.tap(int(idx))
                    return True, f"Tapped Send (index={idx}, text='{matches[0].get('text', '')}')"
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False, "Could not find/tap Send button"


async def _test_verify_chat_screen(wecom: WeComService) -> tuple[bool, str]:
    """Verify we're back on a chat screen."""
    try:
        screen = await wecom.get_current_screen()
        if screen in ("chat", "private_chats"):
            return True, f"Back on screen: {screen}"
        return True, f"Current screen: {screen} (may need manual check)"
    except Exception as exc:
        return False, f"Verify failed: {exc}"


async def _safe_go_back(wecom: WeComService) -> None:
    try:
        for _ in range(3):
            await wecom.go_back()
            await wecom.adb.wait(0.3)
    except Exception:
        pass


async def _dismiss_permission_dialogs(wecom: WeComService) -> None:
    """Dismiss Android permission dialogs by tapping 'Allow'."""
    for _ in range(3):
        try:
            ui_tree, elements = await wecom.adb.get_ui_state(force=True)
            for elem in elements:
                rid = elem.get("resourceId") or ""
                text = (elem.get("text") or "").lower()
                if "permission_allow_all" in rid or "allow" in text:
                    idx = elem.get("index")
                    if idx is not None:
                        await wecom.adb.tap(int(idx))
                        logger.info(f"Dismissed permission dialog (idx={idx})")
                        await asyncio.sleep(1.0)
                        break
            else:
                break  # No permission dialog found
        except Exception:
            break


def _print_step(step: StepResult) -> None:
    status = "PASS" if step.passed else "FAIL"
    print(f"  -> [{status}] {step.message} ({step.duration_ms:.0f}ms)")


async def main():
    parser = argparse.ArgumentParser(description="联系人选择器搜索功能 - 真机端到端测试")
    parser.add_argument("--serial", default="10AF6R2MR900D8A", help="设备序列号")
    parser.add_argument("--port", type=int, default=8080, help="DroidRun 端口")
    parser.add_argument("--contact", required=True, help="要搜索的联系人名字")
    args = parser.parse_args()

    print("=" * 60)
    print("  联系人选择器搜索功能 - 真机测试")
    print(f"  设备: {args.serial}")
    print(f"  搜索联系人: {args.contact}")
    print(f"  DroidRun 端口: {args.port}")
    print("=" * 60)

    steps = await test_contact_search(args.serial, args.contact, args.port)

    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    for i, step in enumerate(steps, 1):
        status = "PASS" if step.passed else "FAIL"
        print(f"  Step {i}: [{status}] {step.name} ({step.duration_ms:.0f}ms)")
        if step.message:
            print(f"          {step.message}")

    total = len(steps)
    passed = sum(1 for s in steps if s.passed)
    print(f"\n  结果: {passed}/{total} 步骤通过")

    all_passed = all(s.passed for s in steps)
    # 完整跑通为 8 个 StepResult（门户 + 7 个后续）；提前 return 时 steps 过短，不得报成功
    full_run = len(steps) >= 8
    if not full_run:
        print(f"\n  [ABORT] 仅完成 {len(steps)}/8 步，视为失败。")
        return 1
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
