"""TDD tests for boss_automation/services/boss_app_service.py.

Uses an in-memory fake AdbPort so we never touch DroidRun or a real
device. The service must be able to:

- Launch the BOSS app via the ADB port.
- Detect login state from the current UI tree.
- Navigate to the "我" tab when needed.
- Return a typed RecruiterProfile or raise LoginRequiredError.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from boss_automation.parsers.recruiter_profile_parser import (
    LoginState,
    RecruiterProfile,
)
from boss_automation.services.boss_app_service import (
    BossAppService,
    LoginRequiredError,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _load_tree(page: str, label: str) -> dict[str, Any]:
    return load_fixture(FIXTURE_ROOT / page / f"{label}.json").ui_tree


class FakeAdbPort:
    """In-memory ``AdbPort`` for unit tests.

    Configure with a sequence of UI trees the service will receive on
    successive ``get_state()`` calls. Records every call for inspection.
    """

    def __init__(self, trees: Sequence[dict[str, Any]]) -> None:
        self._trees = list(trees)
        self._idx = 0
        self.start_app_calls: list[str] = []
        self.tap_text_calls: list[str] = []

    async def start_app(self, package_name: str) -> None:
        self.start_app_calls.append(package_name)

    async def get_state(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._idx >= len(self._trees):
            tree = self._trees[-1] if self._trees else {}
        else:
            tree = self._trees[self._idx]
            self._idx += 1
        return tree, []

    async def tap_by_text(self, text: str) -> bool:
        self.tap_text_calls.append(text)
        return True

    async def tap(self, x: int, y: int) -> bool:
        return True

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        pass

    async def type_text(self, text: str) -> bool:
        return True

    async def press_back(self) -> None:
        pass


class TestLaunch:
    @pytest.mark.asyncio
    async def test_launch_calls_start_app_with_known_package(self) -> None:
        adb = FakeAdbPort(trees=[_load_tree("home", "logged_in")])
        service = BossAppService(adb=adb)

        await service.launch()

        assert adb.start_app_calls == ["com.hpbr.bosszhipin"]


class TestIsLoggedIn:
    @pytest.mark.asyncio
    async def test_returns_true_for_logged_in_home(self) -> None:
        adb = FakeAdbPort(trees=[_load_tree("home", "logged_in")])
        service = BossAppService(adb=adb)
        assert await service.is_logged_in() is True

    @pytest.mark.asyncio
    async def test_returns_false_for_login_wall(self) -> None:
        adb = FakeAdbPort(trees=[_load_tree("home_logged_out", "login_wall")])
        service = BossAppService(adb=adb)
        assert await service.is_logged_in() is False

    @pytest.mark.asyncio
    async def test_unknown_state_is_not_considered_logged_in(self) -> None:
        adb = FakeAdbPort(trees=[{}])
        service = BossAppService(adb=adb)
        assert await service.is_logged_in() is False


class TestGetRecruiterProfile:
    @pytest.mark.asyncio
    async def test_returns_profile_when_already_on_me_tab(self) -> None:
        adb = FakeAdbPort(trees=[_load_tree("me_profile", "e2e_test_has_profile")])
        service = BossAppService(adb=adb)

        profile = await service.get_recruiter_profile()

        assert isinstance(profile, RecruiterProfile)
        assert profile.name == "马先生"
        assert profile.company == "慧莱娱乐"
        # Already on the right tab so no navigation tap should have happened.
        assert adb.tap_text_calls == []

    @pytest.mark.asyncio
    async def test_navigates_to_me_tab_when_currently_on_home(self) -> None:
        adb = FakeAdbPort(
            trees=[
                _load_tree("home", "logged_in"),
                _load_tree("me_profile", "e2e_test_has_profile"),
            ]
        )
        service = BossAppService(adb=adb)

        profile = await service.get_recruiter_profile()

        assert profile is not None
        assert profile.name == "马先生"
        # Accept either legacy "我" or May-2026 "我的" as the tap label
        # that navigates to the Me tab.
        assert any(label in adb.tap_text_calls for label in ("我的", "我"))

    @pytest.mark.asyncio
    async def test_raises_login_required_when_logged_out(self) -> None:
        adb = FakeAdbPort(trees=[_load_tree("home_logged_out", "login_wall")])
        service = BossAppService(adb=adb)

        with pytest.raises(LoginRequiredError):
            await service.get_recruiter_profile()

    @pytest.mark.asyncio
    async def test_returns_none_when_profile_is_empty_after_navigation(
        self,
    ) -> None:
        adb = FakeAdbPort(
            trees=[
                _load_tree("home", "logged_in"),
                _load_tree("me_profile", "empty_profile"),
            ]
        )
        service = BossAppService(adb=adb)

        profile = await service.get_recruiter_profile()
        assert profile is None


class TestDetectLoginStateExposed:
    @pytest.mark.asyncio
    async def test_returns_enum_value(self) -> None:
        adb = FakeAdbPort(trees=[_load_tree("home", "logged_in")])
        service = BossAppService(adb=adb)
        state = await service.detect_login_state()
        assert state == LoginState.LOGGED_IN
