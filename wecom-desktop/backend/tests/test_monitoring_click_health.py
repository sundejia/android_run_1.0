"""Contract test for the ``/api/monitoring/click-health*`` endpoints.

These endpoints expose the per-device dayblock / cooldown surface so the
2026-05-09 click-loop outage is visible in near-real-time rather than only
via post-mortem log forensics. See
``docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md``
and ``docs/03-impl-and-arch/key-modules/click-health-monitoring.md``.

What we lock in here:
- both routes exist and return JSON (200)
- per-device filtering works
- ``dayblock_keys`` / ``active_cooldowns`` are decoded from JSON columns into
  native lists for the frontend (no double-encoding gotchas)
- ``device_serial`` is the dict key on the ``/latest`` route
- inserts via ``record_click_health`` round-trip end-to-end
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))


@pytest.fixture()
def temp_monitoring_db(tmp_path, monkeypatch):
    """Point ``heartbeat_service`` at a tmp SQLite file for this test."""
    from services import heartbeat_service

    db_dir = tmp_path
    db_dir.mkdir(exist_ok=True)
    fake_db = db_dir / "monitoring.db"

    monkeypatch.setattr(heartbeat_service, "_get_monitoring_db_path", lambda: fake_db)
    heartbeat_service.ensure_tables()
    return fake_db


def _build_test_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import monitoring as monitoring_router

    app = FastAPI()
    app.include_router(monitoring_router.router, prefix="/api/monitoring")
    return TestClient(app)


def test_click_health_endpoints_return_empty_when_no_samples(temp_monitoring_db):
    client = _build_test_client()

    r1 = client.get("/api/monitoring/click-health")
    assert r1.status_code == 200
    assert r1.json() == []

    r2 = client.get("/api/monitoring/click-health/latest")
    assert r2.status_code == 200
    assert r2.json() == {}


def test_record_click_health_round_trip_decodes_json_columns(temp_monitoring_db):
    from services.heartbeat_service import record_click_health

    record_click_health(
        device_serial="DEVICE_A",
        scan_number=42,
        dayblock_day="2026-05-12",
        dayblock_size=2,
        dayblock_keys=["DEVICE_A:卡死客户1", "DEVICE_A:卡死客户2"],
        active_cooldown_count=1,
        active_cooldowns=[{"key": "DEVICE_A:cooldown_x", "fail_count": 3, "retry_in_seconds": 250}],
        unique_customers_clicked=7,
        priority_queue_repeats=12,
    )

    client = _build_test_client()
    r = client.get("/api/monitoring/click-health", params={"device_serial": "DEVICE_A"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    sample = rows[0]

    assert sample["device_serial"] == "DEVICE_A"
    assert sample["scan_number"] == 42
    assert sample["dayblock_day"] == "2026-05-12"
    assert sample["dayblock_size"] == 2
    # The JSON columns must be returned decoded — not raw strings — so the
    # frontend can use them directly.
    assert sample["dayblock_keys"] == ["DEVICE_A:卡死客户1", "DEVICE_A:卡死客户2"]
    assert sample["active_cooldowns"][0]["key"] == "DEVICE_A:cooldown_x"
    assert sample["active_cooldowns"][0]["fail_count"] == 3
    assert sample["unique_customers_clicked"] == 7
    assert sample["priority_queue_repeats"] == 12


def test_latest_click_health_picks_most_recent_per_device(temp_monitoring_db):
    from services.heartbeat_service import record_click_health

    # Two samples on DEVICE_A, one on DEVICE_B.
    record_click_health(
        device_serial="DEVICE_A",
        scan_number=1,
        dayblock_day="2026-05-12",
        dayblock_size=0,
        dayblock_keys=[],
        active_cooldown_count=0,
        active_cooldowns=[],
    )
    record_click_health(
        device_serial="DEVICE_A",
        scan_number=2,
        dayblock_day="2026-05-12",
        dayblock_size=1,
        dayblock_keys=["DEVICE_A:second_sample_winner"],
        active_cooldown_count=0,
        active_cooldowns=[],
    )
    record_click_health(
        device_serial="DEVICE_B",
        scan_number=99,
        dayblock_day="2026-05-12",
        dayblock_size=3,
        dayblock_keys=["DEVICE_B:a", "DEVICE_B:b", "DEVICE_B:c"],
        active_cooldown_count=0,
        active_cooldowns=[],
    )

    client = _build_test_client()
    r = client.get("/api/monitoring/click-health/latest")
    assert r.status_code == 200
    body = r.json()

    assert set(body.keys()) == {"DEVICE_A", "DEVICE_B"}
    # DEVICE_A should resolve to scan #2, NOT scan #1.
    assert body["DEVICE_A"]["scan_number"] == 2
    assert body["DEVICE_A"]["dayblock_keys"] == ["DEVICE_A:second_sample_winner"]
    assert body["DEVICE_B"]["dayblock_size"] == 3
    assert body["DEVICE_B"]["dayblock_keys"] == ["DEVICE_B:a", "DEVICE_B:b", "DEVICE_B:c"]


def test_click_health_limit_parameter_caps_response(temp_monitoring_db):
    from services.heartbeat_service import record_click_health

    for i in range(5):
        record_click_health(
            device_serial="DEVICE_X",
            scan_number=i,
            dayblock_day="2026-05-12",
            dayblock_size=0,
            dayblock_keys=[],
            active_cooldown_count=0,
            active_cooldowns=[],
        )

    client = _build_test_client()
    r = client.get("/api/monitoring/click-health", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_click_health_filter_isolates_one_device(temp_monitoring_db):
    from services.heartbeat_service import record_click_health

    for serial in ("DEVICE_KEEP", "DEVICE_FILTER_OUT"):
        record_click_health(
            device_serial=serial,
            scan_number=1,
            dayblock_day="2026-05-12",
            dayblock_size=0,
            dayblock_keys=[],
            active_cooldown_count=0,
            active_cooldowns=[],
        )

    client = _build_test_client()
    r = client.get("/api/monitoring/click-health", params={"device_serial": "DEVICE_KEEP"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["device_serial"] == "DEVICE_KEEP"
