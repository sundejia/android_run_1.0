"""Unit tests for BossNavigator — BOSS tab-aware navigation."""

from __future__ import annotations

from typing import Any

import pytest

from boss_automation.services.boss_navigator import (
    TAB_CANDIDATES,
    TAB_MESSAGES,
    BossNavigator,
)


class FakeAdbPort:
    """Minimal fake implementing the AdbPort protocol."""

    def __init__(self) -> None:
        self.tap_by_text_calls: list[str] = []
        self.tap_by_text_results: list[bool] = []
        self.press_back_count = 0
        self.get_state_calls = 0
        self._tap_index = 0

    async def start_app(self, package_name: str) -> None:
        pass

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self.get_state_calls += 1
        return {}, []

    async def tap_by_text(self, text: str) -> bool:
        self.tap_by_text_calls.append(text)
        if self._tap_index < len(self.tap_by_text_results):
            result = self.tap_by_text_results[self._tap_index]
        else:
            result = False
        self._tap_index += 1
        return result

    async def tap(self, x: int, y: int) -> bool:
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        pass

    async def type_text(self, text: str) -> bool:
        return True

    async def press_back(self) -> None:
        self.press_back_count += 1


@pytest.fixture
def fake_adb() -> FakeAdbPort:
    return FakeAdbPort()


class TestNavigateToTab:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self, fake_adb: FakeAdbPort) -> None:
        fake_adb.tap_by_text_results = [True]
        nav = BossNavigator(fake_adb, sleep=0)
        result = await nav.navigate_to_tab(TAB_MESSAGES)
        assert result is True
        assert fake_adb.tap_by_text_calls == [TAB_MESSAGES]
        assert fake_adb.press_back_count == 0

    @pytest.mark.asyncio
    async def test_retries_after_back(self, fake_adb: FakeAdbPort) -> None:
        fake_adb.tap_by_text_results = [False, True]
        nav = BossNavigator(fake_adb, sleep=0)
        result = await nav.navigate_to_tab(TAB_CANDIDATES)
        assert result is True
        assert fake_adb.tap_by_text_calls == [TAB_CANDIDATES, TAB_CANDIDATES]
        assert fake_adb.press_back_count == 1

    @pytest.mark.asyncio
    async def test_fails_after_max_retries(self, fake_adb: FakeAdbPort) -> None:
        fake_adb.tap_by_text_results = [False, False]
        nav = BossNavigator(fake_adb, sleep=0)
        result = await nav.navigate_to_tab(TAB_MESSAGES)
        assert result is False
        assert fake_adb.press_back_count == 2


class TestEnsureOnPages:
    @pytest.mark.asyncio
    async def test_ensure_on_messages(self, fake_adb: FakeAdbPort) -> None:
        fake_adb.tap_by_text_results = [True]
        nav = BossNavigator(fake_adb, sleep=0)
        assert await nav.ensure_on_messages() is True
        assert fake_adb.tap_by_text_calls == [TAB_MESSAGES]

    @pytest.mark.asyncio
    async def test_ensure_on_candidates(self, fake_adb: FakeAdbPort) -> None:
        fake_adb.tap_by_text_results = [True]
        nav = BossNavigator(fake_adb, sleep=0)
        assert await nav.ensure_on_candidates() is True
        assert fake_adb.tap_by_text_calls == [TAB_CANDIDATES]


class TestPressBack:
    @pytest.mark.asyncio
    async def test_delegates_to_adb(self, fake_adb: FakeAdbPort) -> None:
        nav = BossNavigator(fake_adb, sleep=0)
        await nav.press_back()
        assert fake_adb.press_back_count == 1


class TestNavigateToMeTab:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_candidate(self, fake_adb: FakeAdbPort) -> None:
        fake_adb.tap_by_text_results = [True]
        nav = BossNavigator(fake_adb, sleep=0)
        result = await nav.navigate_to_me_tab()
        assert result is True
        assert fake_adb.tap_by_text_calls == ["我的"]

    @pytest.mark.asyncio
    async def test_falls_back_to_short_label(self, fake_adb: FakeAdbPort) -> None:
        # "我的" fails both retries, then "我" succeeds.
        fake_adb.tap_by_text_results = [False, False, True]
        nav = BossNavigator(fake_adb, sleep=0)
        result = await nav.navigate_to_me_tab()
        assert result is True
        assert fake_adb.tap_by_text_calls == ["我的", "我的", "我"]
