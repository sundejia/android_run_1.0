"""TDD tests for boss_automation/parsers/recruiter_profile_parser.py."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from boss_automation.parsers.recruiter_profile_parser import (
    LoginState,
    RecruiterProfile,
    detect_login_state,
    extract_recruiter_profile,
)
from tests._fixtures.loader import load_fixture

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "boss"


def _tree(page: str, label: str) -> dict:
    return load_fixture(FIXTURE_ROOT / page / f"{label}.json").ui_tree


class TestDetectLoginState:
    def test_logged_in_home_is_logged_in(self) -> None:
        tree = _tree("home", "logged_in")
        assert detect_login_state(tree) == LoginState.LOGGED_IN

    def test_login_wall_is_logged_out(self) -> None:
        tree = _tree("home_logged_out", "login_wall")
        assert detect_login_state(tree) == LoginState.LOGGED_OUT

    def test_me_profile_with_data_is_logged_in(self) -> None:
        tree = _tree("me_profile", "has_profile")
        assert detect_login_state(tree) == LoginState.LOGGED_IN

    def test_empty_dict_is_unknown(self) -> None:
        assert detect_login_state({}) == LoginState.UNKNOWN

    def test_arbitrary_node_without_signals_is_unknown(self) -> None:
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [{"className": "android.view.View", "text": "Loading..."}],
        }
        assert detect_login_state(tree) == LoginState.UNKNOWN

    def test_login_text_anywhere_in_tree_marks_logged_out(self) -> None:
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [
                {
                    "className": "android.widget.TextView",
                    "text": "Login",
                }
            ],
        }
        assert detect_login_state(tree) == LoginState.LOGGED_OUT


class TestExtractRecruiterProfile:
    def test_full_profile_extracted(self) -> None:
        tree = _tree("me_profile", "has_profile")

        profile = extract_recruiter_profile(tree)

        assert isinstance(profile, RecruiterProfile)
        assert profile.name == "王经理"
        assert profile.company == "ACME 互联网科技有限公司"
        assert profile.position == "HRBP"

    def test_empty_profile_returns_none(self) -> None:
        tree = _tree("me_profile", "empty_profile")
        assert extract_recruiter_profile(tree) is None

    def test_logged_out_tree_returns_none(self) -> None:
        tree = _tree("home_logged_out", "login_wall")
        assert extract_recruiter_profile(tree) is None

    def test_partial_profile_keeps_known_fields(self) -> None:
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [
                {
                    "className": "android.widget.TextView",
                    "resourceId": "com.hpbr.bosszhipin:id/tv_user_name",
                    "text": "李猎头",
                }
            ],
        }
        profile = extract_recruiter_profile(tree)
        assert profile is not None
        assert profile.name == "李猎头"
        assert profile.company is None
        assert profile.position is None

    def test_whitespace_only_name_treated_as_missing(self) -> None:
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [
                {
                    "className": "android.widget.TextView",
                    "resourceId": "com.hpbr.bosszhipin:id/tv_user_name",
                    "text": "   ",
                }
            ],
        }
        assert extract_recruiter_profile(tree) is None


class TestRecruiterProfileDataclass:
    def test_is_frozen(self) -> None:
        profile = RecruiterProfile(name="X")
        with pytest.raises((AttributeError, TypeError, FrozenInstanceError)):
            profile.name = "Y"  # type: ignore[misc]

    def test_default_optional_fields_are_none(self) -> None:
        profile = RecruiterProfile(name="X")
        assert profile.company is None
        assert profile.position is None
        assert profile.avatar_path is None
