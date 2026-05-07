"""TDD tests for boss_automation/parsers/greet_state_detector.py."""

from __future__ import annotations

from pathlib import Path

from boss_automation.parsers.greet_state_detector import (
    GreetState,
    detect_greet_state,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / "candidate_detail" / f"{label}.json").ui_tree


def test_ready_to_greet_classified() -> None:
    assert detect_greet_state(_tree("ready_to_greet")) == GreetState.READY_TO_GREET


def test_already_greeted_classified() -> None:
    assert detect_greet_state(_tree("already_greeted")) == GreetState.ALREADY_GREETED


def test_quota_exhausted_classified() -> None:
    assert detect_greet_state(_tree("quota_exhausted")) == GreetState.QUOTA_EXHAUSTED


def test_risk_control_classified() -> None:
    assert detect_greet_state(_tree("risk_control_popup")) == GreetState.RISK_CONTROL_BLOCKED


def test_unknown_returns_unknown() -> None:
    assert detect_greet_state({}) == GreetState.UNKNOWN
    assert detect_greet_state({"className": "FrameLayout", "children": []}) == GreetState.UNKNOWN


def test_state_is_string_enum() -> None:
    assert GreetState.READY_TO_GREET == "ready_to_greet"
    assert GreetState.ALREADY_GREETED == "already_greeted"
    assert GreetState.QUOTA_EXHAUSTED == "quota_exhausted"
    assert GreetState.RISK_CONTROL_BLOCKED == "risk_control_blocked"
    assert GreetState.UNKNOWN == "unknown"


def test_priority_risk_control_beats_quota() -> None:
    # If both popups appear in the tree (very rare race), risk-control
    # MUST win because it requires the operator to halt.
    tree = {
        "className": "FrameLayout",
        "children": [
            {
                "resourceId": "com.hpbr.bosszhipin:id/risk_control_dialog",
                "children": [
                    {"resourceId": "com.hpbr.bosszhipin:id/tv_risk_dialog_title", "text": "操作过于频繁"},
                ],
            },
            {
                "resourceId": "com.hpbr.bosszhipin:id/quota_exhausted_dialog",
                "children": [
                    {"resourceId": "com.hpbr.bosszhipin:id/tv_quota_dialog_title", "text": "今日沟通次数已用完"},
                ],
            },
        ],
    }
    assert detect_greet_state(tree) == GreetState.RISK_CONTROL_BLOCKED
