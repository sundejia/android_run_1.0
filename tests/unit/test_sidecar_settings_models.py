"""Regression: SidecarSettings must accept every SIDECAR category key from the DB."""

from services.settings.models import SidecarSettings


def test_sidecar_settings_accepts_full_category_dict_from_defaults_shape():
    """Mirrors keys seeded for SIDECAR in services/settings/defaults.py."""
    data = {
        "send_via_sidecar": False,
        "countdown_seconds": 0,
        "poll_interval": 10,
        "show_logs": True,
        "max_panels": 3,
        "sidecar_timeout": 60,
        "night_mode_sidecar_timeout": 30,
        "night_mode_start_hour": 22,
        "night_mode_end_hour": 8,
    }
    s = SidecarSettings(**data)
    assert s.sidecar_timeout == 60
    assert s.night_mode_sidecar_timeout == 30
    assert s.night_mode_start_hour == 22
    assert s.night_mode_end_hour == 8
