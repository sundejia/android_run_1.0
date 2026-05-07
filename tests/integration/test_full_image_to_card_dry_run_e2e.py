"""
End-to-end DRY-RUN test for the full image → pre-share-message → contact card pipeline.

What this verifies (without sending a single real message):

  1. AutoContactShareAction.should_execute() returns True for a customer-image
     MediaEvent + the configured media auto-action settings.
  2. render_media_template() correctly renders the pre-share message text
     against the event's placeholder context ({customer_name}, {kefu_name},
     {device_serial}). The message is printed but NOT sent.
  3. On a real device, the contact-share UI flow walks through:
        chat -> tap attach -> swipe to find Contact Card -> tap Contact Card
        -> contact picker -> SearchContactFinder("刘晓璐") -> select contact
     using the same step functions that ContactShareService relies on.
  4. After contact selection, the device must reach the "Confirm Send" dialog
     (validated via PageStateValidator.is_confirm_send_dialog_open). We do NOT
     tap Send. Instead the dialog is dismissed by tapping Cancel (with Back
     fallback) so no message ever leaves the device.

Prerequisites:
  - Device connected via ADB (auto-detected if --serial omitted)
  - DroidRun app running on device with overlay port open
  - WeCom open on the private chats list OR already inside a customer chat
  - Reuses the step helpers in test_contact_search_e2e.py

Usage:
    .venv/bin/python tests/integration/test_full_image_to_card_dry_run_e2e.py
    .venv/bin/python tests/integration/test_full_image_to_card_dry_run_e2e.py \
        --serial 10AE9P1DTT002LE --port 8080 --contact 刘晓璐
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse the well-tested step helpers from the contact-search E2E test. Importing
# this module also calls init_logging() once at module level — that is fine.
import test_contact_search_e2e as cs  # noqa: E402

from wecom_automation.core.config import Config  # noqa: E402
from wecom_automation.core.logging import get_logger  # noqa: E402
from wecom_automation.services.contact_share.page_state import PageStateValidator  # noqa: E402
from wecom_automation.services.contact_share.selectors import (  # noqa: E402
    CANCEL_RESOURCE_PATTERNS,
    CANCEL_TEXT_PATTERNS,
)
from wecom_automation.services.media_actions.actions.auto_contact_share import (  # noqa: E402
    AutoContactShareAction,
)
from wecom_automation.services.media_actions.interfaces import MediaEvent  # noqa: E402
from wecom_automation.services.media_actions.template_resolver import (  # noqa: E402
    render_media_template,
)
from wecom_automation.services.wecom_service import WeComService  # noqa: E402

logger = get_logger("test.full_image_to_card_dry_run")


# ── Configuration for the simulated event + settings ──────────────


def _build_dry_run_settings(contact_name: str) -> dict:
    """Settings that would normally come from the control DB.

    Mirrors DEFAULT_MEDIA_AUTO_ACTION_SETTINGS but force-enables the bits we
    care about and configures a deterministic pre-share message template.
    """
    return {
        "enabled": True,
        "auto_contact_share": {
            "enabled": True,
            "contact_name": contact_name,
            "skip_if_already_shared": False,
            "send_message_before_share": True,
            "pre_share_message_text": (
                "宝宝您好 {customer_name}~ 收到您发的图片，"
                "已为您发送 {kefu_name} 的同事名片，请查收 "
                "(device={device_serial})"
            ),
            "kefu_overrides": {},
        },
        "auto_group_invite": {"enabled": False},
        "auto_blacklist": {"enabled": False},
    }


def _build_simulated_event(serial: str, customer_name: str) -> MediaEvent:
    return MediaEvent(
        event_type="customer_media_detected",
        message_type="image",
        customer_id=999_999,
        customer_name=customer_name,
        channel="@WeChat",
        device_serial=serial,
        kefu_name="测试客服",
        message_id=None,
        timestamp=datetime.now(),
    )


# ── Step 0 / 0.5: trigger gating + template rendering ──────────────


async def _step_validate_action_should_run(
    action: AutoContactShareAction, event: MediaEvent, settings: dict
) -> tuple[bool, str]:
    ok = await action.should_execute(event, settings)
    if not ok:
        return False, "AutoContactShareAction.should_execute() returned False"
    return True, "AutoContactShareAction.should_execute() == True (would fire)"


def _step_render_pre_share_message(event: MediaEvent, settings: dict) -> tuple[bool, str]:
    cs_cfg = settings.get("auto_contact_share", {})
    if not cs_cfg.get("send_message_before_share"):
        return False, "send_message_before_share is False — skipped"
    template = cs_cfg.get("pre_share_message_text") or ""
    if not template:
        return False, "pre_share_message_text is empty"
    rendered = render_media_template(template, event, preserve_on_error=True)
    if "{" in rendered:
        return False, f"Template still has unresolved placeholders: {rendered!r}"
    print(f"  >> 预设话术 (DRY-RUN, NOT sent): {rendered}")
    return True, f"Rendered ({len(rendered)} chars): {rendered[:80]!r}"


# ── Step 7': verify confirm-send dialog reached ────────────────────


async def _step_assert_confirm_send_dialog(wecom: WeComService) -> tuple[bool, str]:
    for attempt in range(5):
        try:
            _ui_tree, elements = await wecom.adb.get_ui_state(force=True)
        except Exception as exc:
            logger.warning(f"get_ui_state failed (attempt {attempt + 1}): {exc}")
            await asyncio.sleep(0.6)
            continue

        if PageStateValidator.is_confirm_send_dialog_open(elements):
            describe = PageStateValidator.describe(elements)
            return True, f"Confirm-send dialog detected (states: {describe})"
        if attempt < 4:
            await asyncio.sleep(0.6)
    describe = PageStateValidator.describe(elements) if elements else "unknown"
    return False, f"Confirm-send dialog NOT detected after 5 polls (states: {describe})"


# ── Step 8: dry-run cancellation ───────────────────────────────────


async def _step_cancel_send(wecom: WeComService) -> tuple[bool, str]:
    """Tap Cancel on the confirm-send dialog so nothing is sent.

    Strategy:
      1. Try resource-based Cancel button (CANCEL_RESOURCE_PATTERNS).
      2. Try exact text Cancel (CANCEL_TEXT_PATTERNS).
      3. Fall back to repeated `go_back()` until the dialog dismisses.
    """
    from wecom_automation.services.ui_search.ui_helpers import find_elements_by_keywords

    try:
        _ui_tree, elements = await wecom.adb.get_ui_state(force=True)
    except Exception as exc:
        return False, f"get_ui_state failed: {exc}"

    matches = find_elements_by_keywords(elements, resource_patterns=CANCEL_RESOURCE_PATTERNS)
    if not matches:
        matches = find_elements_by_keywords(elements, text_patterns=CANCEL_TEXT_PATTERNS)
    if matches:
        idx = matches[0].get("index")
        if idx is not None:
            try:
                await wecom.adb.tap(int(idx))
                await asyncio.sleep(1.2)
                return True, f"Tapped Cancel (index={idx}, text='{matches[0].get('text', '')}')"
            except Exception as exc:
                logger.warning(f"Tap Cancel failed: {exc}")

    for attempt in range(3):
        try:
            await wecom.go_back()
            await asyncio.sleep(0.6)
        except Exception as exc:
            logger.warning(f"go_back attempt {attempt + 1} failed: {exc}")
        try:
            _ui_tree, elements = await wecom.adb.get_ui_state(force=True)
            if not PageStateValidator.is_confirm_send_dialog_open(elements):
                return True, f"Dialog dismissed via go_back (attempts={attempt + 1})"
        except Exception:
            pass
    return False, "Could not dismiss confirm-send dialog via Cancel or back"


async def _step_verify_no_send_happened(wecom: WeComService) -> tuple[bool, str]:
    try:
        _ui_tree, elements = await wecom.adb.get_ui_state(force=True)
    except Exception as exc:
        return False, f"get_ui_state failed: {exc}"
    if PageStateValidator.is_confirm_send_dialog_open(elements):
        return False, "Confirm-send dialog STILL open after cancel — manual recovery needed"
    screen = await wecom.get_current_screen()
    return True, f"Final screen: {screen}; no send dialog visible"


# ── Pipeline ───────────────────────────────────────────────────────


async def run_pipeline(serial: str, contact_name: str, port: int) -> list[cs.StepResult]:
    steps: list[cs.StepResult] = []
    config = Config(device_serial=serial, use_tcp=False, droidrun_port=port)
    wecom = WeComService(config)

    settings = _build_dry_run_settings(contact_name)
    event = _build_simulated_event(serial, contact_name)

    print("\n" + "=" * 60)
    print("  Step 0: 触发判定 + 话术渲染（不连真机）")
    print("=" * 60)

    from wecom_automation.services.contact_share.service import ContactShareService

    cs_service = ContactShareService(wecom)
    action = AutoContactShareAction(cs_service, restore_navigation_after_execute=False)

    step = await cs.run_step(
        "AutoContactShareAction.should_execute",
        _step_validate_action_should_run(action, event, settings),
    )
    steps.append(step)
    cs._print_step(step)
    if not step.passed:
        return steps

    start = time.perf_counter()
    template_ok, template_msg = _step_render_pre_share_message(event, settings)
    elapsed = (time.perf_counter() - start) * 1000
    step = cs.StepResult(
        name="render_media_template (pre-share message)",
        passed=template_ok,
        duration_ms=elapsed,
        message=template_msg,
    )
    steps.append(step)
    cs._print_step(step)
    if not step.passed:
        return steps

    print("\n" + "=" * 60)
    print("  真机阶段：附件 → 名片 → 搜索（dry-run，不点 Send）")
    print("=" * 60)

    print("\n[Step 1] DroidRun Portal 连接...")
    step = await cs.run_step("DroidRun Portal 连接", cs._test_portal(wecom))
    steps.append(step)
    cs._print_step(step)
    if not step.passed:
        return steps

    print("\n[Step 1.5] 关闭权限对话框（如有）...")
    await cs._dismiss_permission_dialogs(wecom)

    print("\n[Step 1.6] 确保在聊天界面...")
    screen = await wecom.get_current_screen()
    print(f"  当前屏幕: {screen}")
    if screen != "chat":
        if not await wecom.ensure_on_private_chats():
            print("  无法导航到私聊列表，尝试启动企业微信...")
            await wecom.launch_wecom(wait_for_ready=True)
            await asyncio.sleep(2.0)
            await wecom.ensure_on_private_chats()

        _ui_tree, elements = await wecom.adb.get_ui_state(force=True)
        skip_prefixes = (
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
            if not text or any(first_line.startswith(p) for p in skip_prefixes):
                continue
            if not ("hrr" in rid or "hzj" in rid):
                continue
            idx = elem.get("index")
            if idx is None:
                continue
            print(f"  尝试进入聊天: {first_line[:40]}")
            await wecom.adb.tap(int(idx))
            await asyncio.sleep(2.0)
            break

    screen = await wecom.get_current_screen()
    print(f"  最终屏幕: {screen}")
    if screen != "chat":
        steps.append(
            cs.StepResult(
                name="进入聊天界面",
                passed=False,
                message=f"Expected screen=chat, got {screen}",
            )
        )
        cs._print_step(steps[-1])
        return steps

    print("\n[Step 2] 点附件按钮...")
    step = await cs.run_step("点击附件按钮", cs._test_tap_attach(wecom))
    steps.append(step)
    cs._print_step(step)
    if not step.passed:
        return steps
    await asyncio.sleep(1.5)

    print("\n[Step 3] 打开名片菜单...")
    step = await cs.run_step("打开名片菜单", cs._test_open_contact_card(wecom))
    steps.append(step)
    cs._print_step(step)
    if not step.passed:
        await cs._safe_go_back(wecom)
        return steps
    await asyncio.sleep(1.5)

    print("\n[Step 4] 探测联系人选择器 UI...")
    step = await cs.run_step("探测选择器 UI", cs._test_probe_picker_ui(wecom))
    steps.append(step)
    cs._print_step(step)

    print(f"\n[Step 5] 搜索联系人: {contact_name} ...")
    step = await cs.run_step(
        f"搜索联系人 ({contact_name})", cs._test_search_contact(wecom, contact_name)
    )
    steps.append(step)
    cs._print_step(step)
    if not step.passed:
        await cs._safe_go_back(wecom)
        await cs._safe_go_back(wecom)
        return steps
    await asyncio.sleep(1.0)

    print("\n[Step 6] 验证确认发送对话框已出现（DRY-RUN，不点 Send）...")
    step = await cs.run_step("确认发送对话框 present", _step_assert_confirm_send_dialog(wecom))
    steps.append(step)
    cs._print_step(step)

    print("\n[Step 7] 取消发送（DRY-RUN）...")
    step = await cs.run_step("取消发送 (Cancel/Back)", _step_cancel_send(wecom))
    steps.append(step)
    cs._print_step(step)

    print("\n[Step 8] 验证无消息发出 + 状态已恢复...")
    step = await cs.run_step("验证状态恢复", _step_verify_no_send_happened(wecom))
    steps.append(step)
    cs._print_step(step)

    return steps


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="完整 dry-run E2E：图片→话术→搜索发名片（不真发任何消息）"
    )
    parser.add_argument("--serial", default="10AE9P1DTT002LE", help="设备序列号")
    parser.add_argument("--port", type=int, default=8080, help="DroidRun 端口")
    parser.add_argument("--contact", default="刘晓璐", help="要搜索的联系人名字")
    args = parser.parse_args()

    print("=" * 60)
    print("  完整 DRY-RUN 端到端测试")
    print(f"  设备: {args.serial}")
    print(f"  搜索联系人: {args.contact}")
    print(f"  DroidRun 端口: {args.port}")
    print("  注意：本测试不会真实发送任何消息（话术 + 名片均为 dry-run）")
    print("=" * 60)

    steps = await run_pipeline(args.serial, args.contact, args.port)

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

    expected_min_steps = 10
    if total < expected_min_steps:
        print(f"\n  [ABORT] 仅完成 {total}/{expected_min_steps} 步，链路未跑完，视为失败。")
        return 1
    return 0 if all(s.passed for s in steps) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
