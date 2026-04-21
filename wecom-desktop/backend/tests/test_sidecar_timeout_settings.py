"""Regression tests for ``ResponseDetector._get_sidecar_timeout``.

These tests lock in two pieces of behaviour:

1. The configured ``sidecar_timeout`` / ``night_mode_sidecar_timeout`` /
   ``night_mode_start_hour`` / ``night_mode_end_hour`` values are actually
   honoured. Historically this code accidentally called a non-existent
   ``SettingsService.get_all_settings_flat()`` method which raised
   ``AttributeError``; the broad ``except Exception`` swallowed it and the
   method silently returned the hard-coded defaults forever.
2. Programming errors (typo'd attribute, future API breakage) now log at
   WARNING instead of being silently absorbed, while expected runtime
   errors (bad cast, settings module missing) only emit a DEBUG line.

Usage:
    pytest wecom-desktop/backend/tests/test_sidecar_timeout_settings.py -v
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from utils.path_utils import get_project_root  # noqa: E402

project_root = get_project_root()
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from services.followup.response_detector import ResponseDetector  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_detector() -> tuple[ResponseDetector, MagicMock]:
    """Build a ResponseDetector with mocked deps and a MagicMock logger.

    ``_get_sidecar_timeout`` does not touch the repository or settings_manager,
    so passing MagicMocks is safe and keeps the test free of any DB / loguru
    setup. The returned logger mock is the one ``self._logger`` resolves to.
    """
    logger = MagicMock(name="logger")
    detector = ResponseDetector(
        repository=MagicMock(name="repository"),
        settings_manager=MagicMock(name="settings_manager"),
        logger=logger,
    )
    return detector, logger


class _FakeService:
    """Minimal stand-in for SettingsService that returns a fixed flat dict."""

    def __init__(self, flat: dict):
        self._flat = flat

    def get_flat_settings(self) -> dict:
        return self._flat


class _TypoService:
    """SettingsService stub WITHOUT the canonical method.

    Reproduces the historical regression: a caller that asks for the wrong
    attribute name should now surface as a WARNING, not be silently
    absorbed.
    """

    def get_all_settings_flat(self):  # pragma: no cover - intentionally wrong
        return {}


def _patch_now(hour: int):
    """Patch ``datetime`` inside response_detector so ``datetime.now().hour``
    returns the requested hour. Other ``datetime`` behaviour is untouched.
    """
    fake_now = datetime(2026, 4, 21, hour, 0, 0)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401, ARG003
            return fake_now

    return patch("services.followup.response_detector.datetime", _Frozen)


# ---------------------------------------------------------------------------
# Tests: configured values are honoured
# ---------------------------------------------------------------------------


def test_get_sidecar_timeout_uses_configured_day_value():
    """At noon the configured day timeout (not 60) must be returned."""
    detector, logger = _make_detector()
    fake = _FakeService(
        {
            "sidecar_timeout": 75,
            "night_mode_sidecar_timeout": 25,
            "night_mode_start_hour": 22,
            "night_mode_end_hour": 8,
        }
    )

    with patch("services.settings.get_settings_service", return_value=fake), _patch_now(
        12
    ):
        assert detector._get_sidecar_timeout() == 75.0
    logger.warning.assert_not_called()


def test_get_sidecar_timeout_uses_configured_night_value_late_evening():
    """At 23:00 the configured night timeout (not 30) must be returned."""
    detector, logger = _make_detector()
    fake = _FakeService(
        {
            "sidecar_timeout": 75,
            "night_mode_sidecar_timeout": 25,
            "night_mode_start_hour": 22,
            "night_mode_end_hour": 8,
        }
    )

    with patch("services.settings.get_settings_service", return_value=fake), _patch_now(
        23
    ):
        assert detector._get_sidecar_timeout() == 25.0
    logger.warning.assert_not_called()


def test_get_sidecar_timeout_night_window_crosses_midnight_pre_dawn():
    """At 05:00 the night window (22 -> 8 wrap) must still apply."""
    detector, _logger = _make_detector()
    fake = _FakeService(
        {
            "sidecar_timeout": 75,
            "night_mode_sidecar_timeout": 25,
            "night_mode_start_hour": 22,
            "night_mode_end_hour": 8,
        }
    )

    with patch("services.settings.get_settings_service", return_value=fake), _patch_now(
        5
    ):
        assert detector._get_sidecar_timeout() == 25.0


def test_get_sidecar_timeout_non_wrapping_window():
    """When start <= end the non-wrap branch is used (sanity check)."""
    detector, _logger = _make_detector()
    fake = _FakeService(
        {
            "sidecar_timeout": 75,
            "night_mode_sidecar_timeout": 25,
            "night_mode_start_hour": 1,
            "night_mode_end_hour": 5,
        }
    )

    with patch("services.settings.get_settings_service", return_value=fake):
        with _patch_now(3):
            assert detector._get_sidecar_timeout() == 25.0
        with _patch_now(7):
            assert detector._get_sidecar_timeout() == 75.0


# ---------------------------------------------------------------------------
# Tests: failure surfaces (this is the regression that motivated the fix)
# ---------------------------------------------------------------------------


def test_typo_on_settings_service_logs_warning_and_returns_default():
    """Programming-error (AttributeError) path must log WARNING, not silence.

    This is the exact shape of the bug we just fixed: an ``AttributeError``
    on the SettingsService used to be swallowed by ``except Exception`` and
    the method would return the hard-coded default (60.0) forever, with no
    visible signal.
    """
    detector, logger = _make_detector()

    with patch(
        "services.settings.get_settings_service", return_value=_TypoService()
    ), _patch_now(12):
        result = detector._get_sidecar_timeout()

    assert result == 60.0
    assert logger.warning.called, "AttributeError should surface as WARNING"
    formatted = logger.warning.call_args.args[0] % logger.warning.call_args.args[1:]
    assert "AttributeError" in formatted


def test_bad_value_logs_debug_not_warning():
    """ValueError (bad cast) is an expected runtime failure -> DEBUG only."""
    detector, logger = _make_detector()
    fake = _FakeService({"sidecar_timeout": "not-a-number"})

    with patch("services.settings.get_settings_service", return_value=fake), _patch_now(
        12
    ):
        result = detector._get_sidecar_timeout()

    assert result == 60.0
    assert logger.debug.called, "Expected DEBUG log for ValueError fallback"
    logger.warning.assert_not_called()


def test_settings_module_missing_logs_debug_not_warning():
    """ImportError (settings module unavailable) -> DEBUG only."""
    detector, logger = _make_detector()

    fake_settings_pkg = MagicMock()
    fake_settings_pkg.get_settings_service.side_effect = ImportError(
        "services.settings not importable in this subprocess"
    )

    with patch.dict(sys.modules, {"services.settings": fake_settings_pkg}), _patch_now(
        12
    ):
        result = detector._get_sidecar_timeout()

    assert result == 60.0
    assert logger.debug.called
    logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# Sanity: the canonical method name still exists on SettingsService
# ---------------------------------------------------------------------------


def test_settings_service_exposes_get_flat_settings():
    """If this fails, ``_get_sidecar_timeout`` will fall back to defaults."""
    from services.settings.service import SettingsService

    assert callable(getattr(SettingsService, "get_flat_settings", None)), (
        "SettingsService.get_flat_settings is the canonical method used by "
        "_get_sidecar_timeout and PeriodicAIHealthChecker startup."
    )
    assert getattr(SettingsService, "get_all_settings_flat", None) is None, (
        "Found legacy/typo'd method 'get_all_settings_flat' on SettingsService. "
        "Either rename it or update callers; both call sites historically "
        "called this non-existent method and silently used defaults."
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
