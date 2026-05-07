"""End-to-end recruiter bootstrap test (requires a real device).

Marked as integration so it is excluded from CI. Run locally with:

    BOSS_DEVICE_SERIAL=<serial> pytest -m integration \
        tests/integration/test_recruiter_bootstrap_e2e.py -v

Skipped automatically when DroidRun or BOSS_DEVICE_SERIAL is not
available so the file can live in the test tree without breaking
the unit-test gate.
"""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path

import pytest

from boss_automation.database.recruiter_repository import RecruiterRepository
from boss_automation.parsers.recruiter_profile_parser import RecruiterProfile
from boss_automation.services.boss_app_service import BossAppService

pytestmark = pytest.mark.integration

DEVICE_SERIAL = os.environ.get("BOSS_DEVICE_SERIAL")

skip_reason: str | None = None
if not DEVICE_SERIAL:
    skip_reason = "BOSS_DEVICE_SERIAL not set"
elif find_spec("droidrun") is None:
    skip_reason = "droidrun is not installed"

pytestmark = [pytest.mark.integration, pytest.mark.skipif(bool(skip_reason), reason=str(skip_reason))]


@pytest.mark.asyncio
async def test_bootstrap_reads_recruiter_from_real_device(tmp_path: Path) -> None:
    """Launch BOSS, detect login, read profile, persist it.

    The on-device recruiter must already be signed in. The test does
    NOT automate login; if not signed in, ``LoginRequiredError`` is
    raised and the test fails so the operator knows to sign in.
    """
    from droidrun import AdbTools  # type: ignore[import-not-found]

    class _Adapter:
        def __init__(self, adb: AdbTools) -> None:
            self._adb = adb

        async def start_app(self, package_name: str) -> None:
            await self._adb.start_app(package_name)

        async def get_state(self):
            return await self._adb.get_state()

        async def tap_by_text(self, text: str) -> bool:
            try:
                await self._adb.tap_by_text(text)
                return True
            except Exception:
                return False

    adb = AdbTools(serial=DEVICE_SERIAL)
    service = BossAppService(adb=_Adapter(adb))
    await service.launch()
    profile = await service.get_recruiter_profile()
    assert profile is not None, "BOSS app reported logged in but no profile was extracted"
    assert isinstance(profile, RecruiterProfile)

    repo = RecruiterRepository(str(tmp_path / "boss_e2e.db"))
    repo.upsert(DEVICE_SERIAL, profile)
    record = repo.get_by_serial(DEVICE_SERIAL)
    assert record is not None
    assert record.name == profile.name
