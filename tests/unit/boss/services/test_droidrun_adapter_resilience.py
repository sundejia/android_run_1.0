"""Resilience tests for ``boss_automation.services.droidrun_adapter``.

Covers the portal self-heal + uiautomator fallback machinery added in
PR1 of the 2026-05-08 E2E fix. No DroidRun or real device is touched;
everything is driven through injectable fakes so the tests are
deterministic and run in <100ms each.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from boss_automation.services.droidrun_adapter import (
    DroidRunAdapter,
    get_resilience_metrics,
    reset_resilience_metrics,
)
from boss_automation.services.uiautomator_fallback import UiAutomatorFallbackError


class FakeDriver:
    """Stand-in for ``droidrun.AdbTools`` with scripted get_state results."""

    def __init__(
        self,
        *,
        get_state_results: list[object] | None = None,
    ) -> None:
        # Entries are either (tree, elements) tuples to return, or
        # BaseException instances to raise.
        self.get_state_results: list[object] = list(get_state_results or [])
        self.get_state_calls = 0
        self.tap_by_text_calls: list[str] = []
        self.swipe_calls: list[tuple[int, int, int, int, int]] = []
        self.start_app_calls: list[str] = []

    async def start_app(self, package_name: str) -> None:
        self.start_app_calls.append(package_name)

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self.get_state_calls += 1
        if not self.get_state_results:
            raise AssertionError("FakeDriver get_state ran out of scripted results")
        item = self.get_state_results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item  # type: ignore[return-value]

    async def tap_by_text(self, text: str) -> bool:
        self.tap_by_text_calls.append(text)
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipe_calls.append((x1, y1, x2, y2, duration_ms))


class ShellRecorder:
    """Capture and canned-response the ShellRunner injection point."""

    def __init__(self, rc: int = 0) -> None:
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []
        self._rc = rc

    async def __call__(self, adb_binary: str, serial: str, args: list[str]) -> tuple[int, bytes, bytes]:
        self.calls.append((adb_binary, serial, tuple(args)))
        return self._rc, b"", b""


def make_sleep() -> tuple[Callable[[float], Awaitable[None]], list[float]]:
    delays: list[float] = []

    async def sleep(d: float) -> None:
        delays.append(d)

    return sleep, delays


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    reset_resilience_metrics()


def _sample_tree() -> dict[str, Any]:
    return {
        "resourceId": "",
        "className": "android.widget.FrameLayout",
        "packageName": "com.hpbr.bosszhipin",
        "text": "",
        "contentDescription": "",
        "children": [
            {
                "resourceId": "com.hpbr.bosszhipin:id/tv_tab_1",
                "className": "android.widget.TextView",
                "text": "牛人",
                "contentDescription": "",
                "boundsInScreen": {"left": 0, "top": 1500, "right": 180, "bottom": 1600},
                "children": [],
            },
            {
                "resourceId": "com.hpbr.bosszhipin:id/tv_tab_4",
                "className": "android.widget.TextView",
                "text": "我的",
                "contentDescription": "",
                "boundsInScreen": {"left": 540, "top": 1500, "right": 720, "bottom": 1600},
                "children": [],
            },
        ],
    }


class TestGetStateHappyPath:
    @pytest.mark.asyncio
    async def test_returns_native_tree_on_first_call(self) -> None:
        tree = _sample_tree()
        driver = FakeDriver(get_state_results=[(tree, [{"idx": 1}])])
        sleep, _ = make_sleep()
        shell = ShellRecorder()

        adapter = DroidRunAdapter(
            serial="SERIAL",
            driver=driver,
            shell_runner=shell,
            sleeper=sleep,
        )

        got_tree, got_elements = await adapter.get_state()

        assert got_tree is tree
        assert got_elements == [{"idx": 1}]
        assert driver.get_state_calls == 1
        assert shell.calls == []
        assert adapter.fallback_active is False

    @pytest.mark.asyncio
    async def test_non_portal_exception_propagates(self) -> None:
        boom = ConnectionRefusedError("adb server down")
        driver = FakeDriver(get_state_results=[boom])
        sleep, _ = make_sleep()

        adapter = DroidRunAdapter(
            serial="SERIAL",
            driver=driver,
            shell_runner=ShellRecorder(),
            sleeper=sleep,
        )

        with pytest.raises(ConnectionRefusedError):
            await adapter.get_state()
        assert adapter.fallback_active is False


class TestPortalSelfHeal:
    @pytest.mark.asyncio
    async def test_transient_portal_error_then_retry_success(self) -> None:
        tree = _sample_tree()
        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Failed to get state after 3 attempts: Portal returned error: Unknown error"),
                (tree, []),
            ]
        )
        sleep, delays = make_sleep()
        shell = ShellRecorder()

        adapter = DroidRunAdapter(
            serial="SERIAL",
            driver=driver,
            shell_runner=shell,
            sleeper=sleep,
        )

        got_tree, _ = await adapter.get_state()

        assert got_tree is tree
        assert driver.get_state_calls == 2
        # Step-1 retry only needs the 500ms sleep; force-stop path not entered.
        assert delays == [0.5]
        assert shell.calls == []
        metrics = get_resilience_metrics("SERIAL")["SERIAL"]
        assert metrics["portal_retry"] == 1
        assert metrics["portal_self_heal"] == 0
        assert metrics["uiautomator_fallback_engaged"] == 0

    @pytest.mark.asyncio
    async def test_force_stop_path_triggered_when_simple_retry_fails(self) -> None:
        tree = _sample_tree()
        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Portal returned error: Unknown error"),
                RuntimeError("Portal returned error: Unknown error"),
                (tree, []),
            ]
        )
        sleep, delays = make_sleep()
        shell = ShellRecorder()

        adapter = DroidRunAdapter(
            serial="SER2",
            driver=driver,
            shell_runner=shell,
            sleeper=sleep,
        )

        got_tree, _ = await adapter.get_state()

        assert got_tree is tree
        assert driver.get_state_calls == 3
        # 0.5s simple retry + 2s after force-stop + 3s after restart
        assert delays == [0.5, 2.0, 3.0]
        # Force-stop + start-service issued
        commands = [call[2] for call in shell.calls]
        assert ("shell", "am", "force-stop", "com.droidrun.portal") in commands
        assert any(
            args[:3] == ("shell", "am", "start-service") and "com.droidrun.portal" in args[3] for args in commands
        )

        metrics = get_resilience_metrics("SER2")["SER2"]
        assert metrics["portal_retry"] == 1
        assert metrics["portal_self_heal"] == 1


class TestUiautomatorFallback:
    @pytest.mark.asyncio
    async def test_fallback_engaged_when_self_heal_exhausted(self) -> None:
        fallback_tree = _sample_tree()
        dump_calls: list[str] = []

        async def fake_dump(serial: str) -> dict[str, Any]:
            dump_calls.append(serial)
            return fallback_tree

        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Portal returned error: Unknown error"),
                RuntimeError("Portal returned error: Unknown error"),
                RuntimeError("Portal returned error: Unknown error"),
            ]
        )
        sleep, _ = make_sleep()

        adapter = DroidRunAdapter(
            serial="SER3",
            driver=driver,
            shell_runner=ShellRecorder(),
            dump_runner=fake_dump,
            sleeper=sleep,
        )

        tree, elements = await adapter.get_state()

        assert tree is fallback_tree
        assert elements == []
        assert adapter.fallback_active is True
        assert dump_calls == ["SER3"]

        metrics = get_resilience_metrics("SER3")["SER3"]
        assert metrics["uiautomator_fallback_engaged"] == 1
        assert metrics["fallback_mode_calls"] == 1

    @pytest.mark.asyncio
    async def test_fallback_sticks_across_subsequent_calls(self) -> None:
        fallback_tree = _sample_tree()

        async def fake_dump(serial: str) -> dict[str, Any]:
            return fallback_tree

        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Portal returned error: Unknown error"),
                RuntimeError("Portal returned error: Unknown error"),
                RuntimeError("Portal returned error: Unknown error"),
            ]
        )
        sleep, _ = make_sleep()

        adapter = DroidRunAdapter(
            serial="SER4",
            driver=driver,
            shell_runner=ShellRecorder(),
            dump_runner=fake_dump,
            sleeper=sleep,
        )

        await adapter.get_state()
        assert adapter.fallback_active is True

        # Second call must not touch the driver again (no more scripted
        # results, so any native call would crash the FakeDriver).
        tree_2, _ = await adapter.get_state()
        assert tree_2 is fallback_tree

        metrics = get_resilience_metrics("SER4")["SER4"]
        assert metrics["fallback_mode_calls"] == 2

    @pytest.mark.asyncio
    async def test_dump_failure_surfaces_rather_than_silently_hiding(self) -> None:
        async def broken_dump(serial: str) -> dict[str, Any]:
            raise UiAutomatorFallbackError("device offline")

        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
            ]
        )
        sleep, _ = make_sleep()

        adapter = DroidRunAdapter(
            serial="SER5",
            driver=driver,
            shell_runner=ShellRecorder(),
            dump_runner=broken_dump,
            sleeper=sleep,
        )

        with pytest.raises(UiAutomatorFallbackError):
            await adapter.get_state()


class TestFallbackModeActions:
    @pytest.mark.asyncio
    async def test_tap_by_text_uses_adb_input_tap_when_fallback_active(self) -> None:
        fallback_tree = _sample_tree()

        async def fake_dump(serial: str) -> dict[str, Any]:
            return fallback_tree

        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
            ]
        )
        shell = ShellRecorder()
        sleep, _ = make_sleep()

        adapter = DroidRunAdapter(
            serial="SER6",
            driver=driver,
            shell_runner=shell,
            dump_runner=fake_dump,
            sleeper=sleep,
        )

        await adapter.get_state()
        assert adapter.fallback_active is True

        tapped = await adapter.tap_by_text("我的")
        assert tapped is True
        tap_commands = [c[2] for c in shell.calls if c[2][:3] == ("shell", "input", "tap")]
        assert tap_commands, "expected at least one input tap command"
        last = tap_commands[-1]
        # 我的 tab center = (540 + 720) / 2 = 630, (1500 + 1600) / 2 = 1550
        assert last == ("shell", "input", "tap", "630", "1550")

    @pytest.mark.asyncio
    async def test_tap_by_text_returns_false_when_label_absent_in_fallback(self) -> None:
        async def fake_dump(serial: str) -> dict[str, Any]:
            return _sample_tree()

        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
            ]
        )
        shell = ShellRecorder()
        sleep, _ = make_sleep()

        adapter = DroidRunAdapter(
            serial="SER7",
            driver=driver,
            shell_runner=shell,
            dump_runner=fake_dump,
            sleeper=sleep,
        )

        await adapter.get_state()
        assert adapter.fallback_active is True

        tapped = await adapter.tap_by_text("绝对不存在的按钮")
        assert tapped is False
        tap_commands = [c[2] for c in shell.calls if c[2][:3] == ("shell", "input", "tap")]
        assert tap_commands == []

    @pytest.mark.asyncio
    async def test_swipe_uses_adb_input_swipe_when_fallback_active(self) -> None:
        async def fake_dump(serial: str) -> dict[str, Any]:
            return _sample_tree()

        driver = FakeDriver(
            get_state_results=[
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
                RuntimeError("Portal returned error"),
            ]
        )
        shell = ShellRecorder()
        sleep, _ = make_sleep()

        adapter = DroidRunAdapter(
            serial="SER8",
            driver=driver,
            shell_runner=shell,
            dump_runner=fake_dump,
            sleeper=sleep,
        )

        await adapter.get_state()
        assert adapter.fallback_active is True

        await adapter.swipe(100, 200, 300, 400, duration_ms=500)

        swipe_cmds = [c[2] for c in shell.calls if c[2][:3] == ("shell", "input", "swipe")]
        assert swipe_cmds == [("shell", "input", "swipe", "100", "200", "300", "400", "500")]


class TestMetricsRegistry:
    def test_empty_metrics_for_unknown_serial_returns_zeros(self) -> None:
        got = get_resilience_metrics("NEVER_SEEN")
        assert got == {
            "NEVER_SEEN": {
                "portal_retry": 0,
                "portal_self_heal": 0,
                "uiautomator_fallback_engaged": 0,
                "fallback_mode_calls": 0,
            }
        }

    def test_reset_wipes_all_counters(self) -> None:
        driver = FakeDriver(get_state_results=[({}, [])])
        DroidRunAdapter(
            serial="TO_BE_WIPED",
            driver=driver,
            shell_runner=ShellRecorder(),
            sleeper=lambda d: _noop(d),
        )
        assert "TO_BE_WIPED" in get_resilience_metrics()
        reset_resilience_metrics()
        assert get_resilience_metrics() == {}


async def _noop(_d: float) -> None:
    return None
