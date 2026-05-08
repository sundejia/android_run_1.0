"""High-level orchestration for the BOSS Zhipin Android app.

Provides three public operations used during M1 bootstrap:
- ``launch()``: open the BOSS app on the bound device.
- ``is_logged_in()`` / ``detect_login_state()``: classify the current UI.
- ``get_recruiter_profile()``: navigate to the "我" tab if needed and
  return the recruiter identity.

The service depends on an ``AdbPort`` Protocol, never on DroidRun
directly. Production callers wire in a thin adapter around the legacy
``wecom_automation.services.adb_service.ADBService``; unit tests pass a
fake.
"""

from __future__ import annotations

from typing import Final

from boss_automation.parsers.recruiter_profile_parser import (
    LoginState,
    RecruiterProfile,
    detect_login_state,
    extract_recruiter_profile,
)
from boss_automation.services.adb_port import AdbPort

DEFAULT_PACKAGE_NAME: Final[str] = "com.hpbr.bosszhipin"
# Tab-label candidates tried in order when we need to force-navigate to
# the "我" tab. BOSS 12.14x renamed the tab text to "我的"; earlier
# builds used a bare "我". Trying both keeps M1/M3/M5 working across
# app versions.
ME_TAB_TEXT_CANDIDATES: Final[tuple[str, ...]] = ("我的", "我")


class BossAppError(Exception):
    """Base class for service-level errors."""


class LoginRequiredError(BossAppError):
    """The recruiter is not logged in on the device.

    Callers must surface this to the operator, who logs in by hand
    (scan code or phone number). The framework never automates login.
    """


class BossAppService:
    """Bootstrap-stage service for the BOSS Zhipin app on one device."""

    def __init__(
        self,
        adb: AdbPort,
        *,
        package_name: str = DEFAULT_PACKAGE_NAME,
    ) -> None:
        self._adb = adb
        self._package_name = package_name

    async def launch(self) -> None:
        await self._adb.start_app(self._package_name)

    async def detect_login_state(self) -> LoginState:
        tree, _ = await self._adb.get_state()
        return detect_login_state(tree)

    async def is_logged_in(self) -> bool:
        return await self.detect_login_state() == LoginState.LOGGED_IN

    async def get_recruiter_profile(self) -> RecruiterProfile | None:
        """Return the logged-in recruiter, navigating to the "我" tab if needed.

        Raises ``LoginRequiredError`` if the device is on a login screen.
        Returns ``None`` if the "我" tab is reachable but the profile
        fields are empty (recruiter just signed up, no company filled
        in, etc.).
        """
        tree, _ = await self._adb.get_state()
        state = detect_login_state(tree)
        if state == LoginState.LOGGED_OUT:
            raise LoginRequiredError("BOSS Zhipin is on the login screen; recruiter must sign in by hand")

        profile = extract_recruiter_profile(tree)
        if profile is not None:
            return profile

        # Not on the "我" tab yet, or the tree did not include the
        # profile section. Try each known tab-label variant; if any
        # tap lands us on the right screen, re-read the UI.
        for candidate in ME_TAB_TEXT_CANDIDATES:
            tapped = await self._adb.tap_by_text(candidate)
            if tapped:
                break
        else:
            return None

        tree2, _ = await self._adb.get_state()
        return extract_recruiter_profile(tree2)
