"""
End-to-end test for the full auto group invite workflow.

Runs the complete group creation flow on connected devices:
  open chat -> chat info -> tap add-member -> search member -> select -> confirm group

Usage:
    uv run tests/integration/test_group_invite_e2e.py --member 孙德家
    uv run tests/integration/test_group_invite_e2e.py --member 孙德家 --serial 10AEB80XHX006D4
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Ensure src is on the path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wecom_automation.core.config import Config
from wecom_automation.core.logging import get_logger, init_logging
from wecom_automation.services.wecom_service import WeComService

init_logging(hostname="test", level="INFO", console=True)
logger = get_logger("test.group_invite")

ADB_PATH = str(PROJECT_ROOT / "wecom-desktop" / "adb" / "adb.exe")


@dataclass
class StepResult:
    name: str
    passed: bool
    duration_ms: float = 0.0
    message: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class DeviceTestReport:
    serial: str
    model: str = ""
    steps: list[StepResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.steps) and not self.skipped

    def summary(self) -> str:
        lines = [f"\n{'='*60}", f"设备: {self.serial} ({self.model})", f"{'='*60}"]
        if self.skipped:
            lines.append(f"  [SKIP] {self.skip_reason}")
            return "\n".join(lines)

        for i, step in enumerate(self.steps, 1):
            status = "PASS" if step.passed else "FAIL"
            lines.append(f"  Step {i}: [{status}] {step.name} ({step.duration_ms:.0f}ms)")
            if step.message:
                lines.append(f"          {step.message}")

        total = len(self.steps)
        passed = sum(1 for s in self.steps if s.passed)
        lines.append(f"\n  结果: {passed}/{total} 步骤通过")
        return "\n".join(lines)


def discover_devices() -> list[dict]:
    """Use ADB to discover connected devices."""
    result = subprocess.run(
        [ADB_PATH, "devices", "-l"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    devices = []
    for line in result.stdout.strip().splitlines():
        if line.startswith("List of") or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serial = parts[0]
            model = ""
            for token in parts[2:]:
                if token.startswith("model:"):
                    model = token.split(":", 1)[1]
            devices.append({"serial": serial, "model": model})
    return devices


async def run_step(name: str, coro) -> StepResult:
    """Run a test step and capture result."""
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


async def test_device(serial: str, model: str, droidrun_port: int, member_name: str) -> DeviceTestReport:
    """Run the complete group invite workflow on a single device."""
    report = DeviceTestReport(serial=serial, model=model)
    print(f"\n{'='*60}")
    print(f"开始测试设备: {serial} ({model}), DroidRun port: {droidrun_port}")
    print(f"拉群成员: {member_name}")
    print(f"{'='*60}")

    config = Config(
        device_serial=serial,
        use_tcp=False,
        droidrun_port=droidrun_port,
    )
    wecom = WeComService(config)

    # Step 1: DroidRun Portal connection
    print("\n[Step 1] 测试 DroidRun Portal 连接...")
    step1 = await run_step("DroidRun Portal 连接", _test_portal_connection(wecom))
    report.steps.append(step1)
    print(f"  -> {'PASS' if step1.passed else 'FAIL'}: {step1.message} ({step1.duration_ms:.0f}ms)")
    if not step1.passed:
        print("  !! Portal 连接失败，后续步骤将跳过")
        return report

    # Step 2: Launch / verify WeCom is running
    print("\n[Step 2] 确认企业微信已打开...")
    step2 = await run_step("企业微信启动", _test_wecom_launch(wecom))
    report.steps.append(step2)
    print(f"  -> {'PASS' if step2.passed else 'FAIL'}: {step2.message} ({step2.duration_ms:.0f}ms)")
    if not step2.passed:
        return report

    # Step 3: Navigate to private chats
    print("\n[Step 3] 导航到私聊列表...")
    step3 = await run_step("导航到私聊", _test_navigate_private_chats(wecom))
    report.steps.append(step3)
    print(f"  -> {'PASS' if step3.passed else 'FAIL'}: {step3.message} ({step3.duration_ms:.0f}ms)")
    if not step3.passed:
        return report

    # Step 4: Extract customer list
    print("\n[Step 4] 获取客户列表...")
    step4_result = await _test_extract_customers(wecom)
    customers = step4_result.get("customers", [])
    step4 = StepResult(
        name="提取客户列表",
        passed=step4_result["passed"],
        duration_ms=step4_result["duration_ms"],
        message=step4_result["message"],
        details={"customers": customers},
    )
    report.steps.append(step4)
    print(f"  -> {'PASS' if step4.passed else 'FAIL'}: {step4.message} ({step4.duration_ms:.0f}ms)")
    if customers:
        print(f"  发现客户: {', '.join(customers[:5])}" + ("..." if len(customers) > 5 else ""))
    if not step4.passed or not customers:
        return report

    # Step 5: Open first customer's chat
    test_customer = customers[0]
    print(f"\n[Step 5] 打开客户聊天: {test_customer}")
    step5 = await run_step(f"打开客户聊天 ({test_customer})", _test_navigate_to_chat(wecom, serial, test_customer))
    report.steps.append(step5)
    print(f"  -> {'PASS' if step5.passed else 'FAIL'}: {step5.message} ({step5.duration_ms:.0f}ms)")
    if not step5.passed:
        return report

    # Step 6: Open chat info
    print("\n[Step 6] 打开聊天详情...")
    step6 = await run_step("打开聊天详情", _test_open_chat_info(wecom, serial))
    report.steps.append(step6)
    print(f"  -> {'PASS' if step6.passed else 'FAIL'}: {step6.message} ({step6.duration_ms:.0f}ms)")
    if not step6.passed:
        await _safe_go_back(wecom)
        return report

    # Step 7: Click add-member button
    print("\n[Step 7] 点击添加成员按钮...")
    step7 = await run_step("点击添加成员按钮", _test_tap_add_member(wecom, serial))
    report.steps.append(step7)
    print(f"  -> {'PASS' if step7.passed else 'FAIL'}: {step7.message} ({step7.duration_ms:.0f}ms)")
    if not step7.passed:
        await _safe_go_back(wecom)
        return report

    # Step 8: Search and select member
    print(f"\n[Step 8] 搜索并选择成员: {member_name}")
    step8 = await run_step(f"搜索并选择成员 ({member_name})", _test_search_and_select_member(wecom, serial, member_name))
    report.steps.append(step8)
    print(f"  -> {'PASS' if step8.passed else 'FAIL'}: {step8.message} ({step8.duration_ms:.0f}ms)")
    if not step8.passed:
        await _safe_go_back(wecom)
        return report

    # Step 9: Confirm group creation
    print("\n[Step 9] 确认建群...")
    step9 = await run_step("确认建群", _test_confirm_group_creation(wecom, serial))
    report.steps.append(step9)
    print(f"  -> {'PASS' if step9.passed else 'FAIL'}: {step9.message} ({step9.duration_ms:.0f}ms)")

    # Step 10: Go back to clean state
    print("\n[Step 10] 返回清理状态...")
    step10 = await run_step("返回到私聊列表", _test_go_back_to_list(wecom))
    report.steps.append(step10)
    print(f"  -> {'PASS' if step10.passed else 'FAIL'}: {step10.message} ({step10.duration_ms:.0f}ms)")

    return report


async def _test_portal_connection(wecom: WeComService) -> tuple[bool, str]:
    """Test that DroidRun portal is reachable."""
    try:
        ui_tree, elements = await wecom.adb.get_ui_state(force=True)
        if ui_tree is not None:
            return True, f"Portal 连接成功，获取到 {len(elements)} 个可点击元素"
        return False, "Portal 返回空 UI 树"
    except Exception as exc:
        return False, f"Portal 连接失败: {exc}"


async def _test_wecom_launch(wecom: WeComService) -> tuple[bool, str]:
    """Test that WeCom can be launched."""
    try:
        await wecom.launch_wecom(wait_for_ready=True)
        screen = await wecom.get_current_screen()
        return True, f"企业微信已启动，当前屏幕: {screen}"
    except Exception as exc:
        return False, f"启动失败: {exc}"


async def _test_navigate_private_chats(wecom: WeComService) -> tuple[bool, str]:
    """Test navigating to private chats list."""
    try:
        result = await wecom.switch_to_private_chats()
        if result:
            return True, "成功切换到私聊列表"
        return False, "无法切换到私聊列表"
    except Exception as exc:
        return False, f"导航失败: {exc}"


async def _test_extract_customers(wecom: WeComService) -> dict:
    """Extract first-screen visible customers (no scrolling needed for test)."""
    start = time.perf_counter()
    try:
        ui_tree = await wecom.adb.get_ui_tree()
        users = wecom.ui_parser.extract_users_from_tree(ui_tree)
        elapsed = (time.perf_counter() - start) * 1000
        if users:
            names = [u.name for u in users if u.name]
            return {
                "passed": bool(names),
                "duration_ms": elapsed,
                "message": f"提取到 {len(names)} 个客户（首屏）",
                "customers": names,
            }
        return {
            "passed": False,
            "duration_ms": elapsed,
            "message": "未找到任何客户",
            "customers": [],
        }
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            "passed": False,
            "duration_ms": elapsed,
            "message": f"提取失败: {exc}",
            "customers": [],
        }


async def _test_navigate_to_chat(wecom: WeComService, serial: str, customer_name: str) -> tuple[bool, str]:
    """Test navigating to a customer's chat."""
    try:
        ok = await wecom.navigate_to_chat(serial, customer_name)
        if ok:
            screen = await wecom.get_current_screen()
            return True, f"成功打开 {customer_name} 的聊天 (screen={screen})"
        return False, f"无法打开 {customer_name} 的聊天"
    except Exception as exc:
        return False, f"导航失败: {exc}"


async def _test_open_chat_info(wecom: WeComService, serial: str) -> tuple[bool, str]:
    """Test opening the chat info screen."""
    try:
        ok = await wecom.open_chat_info(serial)
        if ok:
            return True, "成功打开聊天详情"
        return False, "找不到聊天详情按钮"
    except Exception as exc:
        return False, f"打开详情失败: {exc}"


async def _test_tap_add_member(wecom: WeComService, serial: str) -> tuple[bool, str]:
    """Tap the add-member button on the chat info screen."""
    try:
        ok = await wecom.tap_add_member_button(serial)
        if ok:
            return True, "成功点击添加成员按钮"
        return False, "未找到或无法点击添加成员按钮"
    except Exception as exc:
        return False, f"点击失败: {exc}"


async def _test_search_and_select_member(wecom: WeComService, serial: str, member_name: str) -> tuple[bool, str]:
    """Search for a member by name and select them."""
    try:
        ok = await wecom.search_and_select_member(serial, member_name)
        if ok:
            return True, f"成功搜索并选择成员: {member_name}"
        return False, f"未找到或无法选择成员: {member_name}"
    except Exception as exc:
        return False, f"搜索选择失败: {exc}"


async def _test_confirm_group_creation(wecom: WeComService, serial: str) -> tuple[bool, str]:
    """Confirm group creation."""
    try:
        ok = await wecom.confirm_group_creation(serial, post_confirm_wait_seconds=2.0)
        if ok:
            screen = await wecom.get_current_screen()
            return True, f"建群成功，当前屏幕: {screen}"
        return False, "确认建群失败（未找到确认按钮或未进入群聊）"
    except Exception as exc:
        return False, f"确认建群失败: {exc}"


async def _test_go_back_to_list(wecom: WeComService) -> tuple[bool, str]:
    """Go back to the private chats list."""
    try:
        for _ in range(3):
            await wecom.go_back()
            await wecom.adb.wait(0.5)
            screen = await wecom.get_current_screen()
            if screen == "private_chats":
                return True, "已返回私聊列表"
        return True, "已执行返回操作"
    except Exception as exc:
        return False, f"返回失败: {exc}"


async def _safe_go_back(wecom: WeComService) -> None:
    """Best-effort go back."""
    try:
        for _ in range(3):
            await wecom.go_back()
            await wecom.adb.wait(0.3)
    except Exception:
        pass


async def main():
    parser = argparse.ArgumentParser(description="自动拉群功能 - 完整端到端测试")
    parser.add_argument("--serial", help="只测试指定设备")
    parser.add_argument("--member", required=True, help="要拉入群的成员名字（企业微信通讯录中的名字）")
    args = parser.parse_args()

    print("=" * 60)
    print("  自动拉群功能 - 完整端到端测试")
    print(f"  拉群成员: {args.member}")
    print("=" * 60)

    # Discover devices
    print("\n正在发现设备...")
    devices = discover_devices()
    if not devices:
        print("错误: 没有发现已连接的设备")
        sys.exit(1)

    print(f"发现 {len(devices)} 台设备:")
    for d in devices:
        print(f"  - {d['serial']} ({d['model']})")

    if args.serial:
        devices = [d for d in devices if d["serial"] == args.serial]
        if not devices:
            print(f"错误: 未找到指定设备 {args.serial}")
            sys.exit(1)

    # Run tests on each device sequentially (to avoid port conflicts)
    reports: list[DeviceTestReport] = []
    base_port = 8080
    for i, device in enumerate(devices):
        port = base_port + (i * 10)
        report = await test_device(device["serial"], device["model"], port, args.member)
        reports.append(report)

    # Print final summary
    print("\n" + "=" * 60)
    print("  测试汇总")
    print("=" * 60)
    for report in reports:
        print(report.summary())

    # Overall result
    all_passed = all(r.passed for r in reports)
    print(f"\n{'='*60}")
    if all_passed:
        print("  总结: 所有设备测试通过! 完整拉群流程执行成功。")
    else:
        failed_devices = [r.serial for r in reports if not r.passed]
        print(f"  总结: 以下设备存在问题: {', '.join(failed_devices)}")
    print(f"{'='*60}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
