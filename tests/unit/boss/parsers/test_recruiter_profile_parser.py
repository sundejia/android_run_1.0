"""TDD tests for boss_automation/parsers/recruiter_profile_parser.py.

The primary contract fixture is
``tests/fixtures/boss/me_profile/e2e_test_has_profile.json``, captured
from a 2026-05 BOSS Zhipin 12.14x app on a vivo V2357A via
``scripts/dump_boss_ui.py``. Legacy-schema coverage is kept through
inline-built mock trees so we don't carry obsolete synthetic fixtures.
"""

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


# --- Inline legacy-schema mock builders -----------------------------
# Pre-2026-05 BOSS app versions separated name / company / position
# into three ``tv_user_*`` nodes and carried ``contentDescription`` on
# each bottom tab. Exercised inline so we don't need to ship a
# synthetic JSON fixture with stale rids.


def _legacy_logged_in_profile_tree(
    *,
    name: str = "李猎头",
    company: str = "法外狂徒科技",
    position: str = "HRBP",
) -> dict:
    return {
        "className": "android.widget.FrameLayout",
        "packageName": "com.hpbr.bosszhipin",
        "children": [
            {
                "className": "android.widget.TextView",
                "resourceId": "com.hpbr.bosszhipin:id/tv_user_name",
                "text": name,
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.hpbr.bosszhipin:id/tv_company_name",
                "text": company,
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.hpbr.bosszhipin:id/tv_user_position",
                "text": position,
            },
            {
                "className": "android.widget.TextView",
                "resourceId": "com.hpbr.bosszhipin:id/tab_mine",
                "text": "我",
                "contentDescription": "我 tab",
            },
        ],
    }


class TestDetectLoginState:
    def test_logged_in_home_is_logged_in_legacy_schema(self) -> None:
        # home/logged_in.json uses the pre-2026-05 schema with
        # content-description tabs; the parser must keep recognizing it.
        tree = _tree("home", "logged_in")
        assert detect_login_state(tree) == LoginState.LOGGED_IN

    def test_login_wall_is_logged_out(self) -> None:
        tree = _tree("home_logged_out", "login_wall")
        assert detect_login_state(tree) == LoginState.LOGGED_OUT

    def test_real_device_me_profile_may2026_is_logged_in(self) -> None:
        # Real device fixture uses plain-text ``tv_tab_*`` labels and
        # no contentDescription on tabs — exercises the May-2026 path.
        tree = _tree("me_profile", "e2e_test_has_profile")
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

    def test_single_tab_text_alone_does_not_flip_to_logged_in(self) -> None:
        # A login page that happens to render the word "我" must NOT
        # be classified as logged-in. The May-2026 text path requires
        # at least 3 distinct tab labels under ``tv_tab_*`` nodes.
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [
                {
                    "className": "android.widget.TextView",
                    "resourceId": "com.hpbr.bosszhipin:id/tv_tab_4",
                    "text": "我",
                }
            ],
        }
        assert detect_login_state(tree) == LoginState.UNKNOWN


class TestExtractRecruiterProfile:
    def test_real_device_fixture_exposes_full_profile(self) -> None:
        tree = _tree("me_profile", "e2e_test_has_profile")

        profile = extract_recruiter_profile(tree)

        assert isinstance(profile, RecruiterProfile)
        assert profile.name == "马先生"
        assert profile.company == "慧莱娱乐"
        assert profile.position == "人事主管"

    def test_legacy_schema_still_parses(self) -> None:
        tree = _legacy_logged_in_profile_tree()
        profile = extract_recruiter_profile(tree)
        assert profile is not None
        assert profile.name == "李猎头"
        assert profile.company == "法外狂徒科技"
        assert profile.position == "HRBP"

    def test_empty_profile_returns_none(self) -> None:
        tree = _tree("me_profile", "empty_profile")
        assert extract_recruiter_profile(tree) is None

    def test_logged_out_tree_returns_none(self) -> None:
        tree = _tree("home_logged_out", "login_wall")
        assert extract_recruiter_profile(tree) is None

    def test_partial_profile_with_may2026_schema(self) -> None:
        # Only the container contentDescription is set — company and
        # position remain None. Exercises the fallback path that
        # pulls ``contentDescription`` off ``ctl_f3_profile``.
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [
                {
                    "resourceId": "com.hpbr.bosszhipin:id/tv_tab_1",
                    "text": "牛人",
                },
                {
                    "resourceId": "com.hpbr.bosszhipin:id/tv_tab_2",
                    "text": "搜索",
                },
                {
                    "resourceId": "com.hpbr.bosszhipin:id/tv_tab_3",
                    "text": "消息",
                },
                {
                    "resourceId": "com.hpbr.bosszhipin:id/tv_tab_4",
                    "text": "我的",
                },
                {
                    "className": "android.widget.LinearLayout",
                    "resourceId": "com.hpbr.bosszhipin:id/ctl_f3_profile",
                    "contentDescription": "张先生",
                },
            ],
        }
        profile = extract_recruiter_profile(tree)
        assert profile is not None
        assert profile.name == "张先生"
        assert profile.company is None
        assert profile.position is None

    def test_company_and_position_split_on_middle_dot(self) -> None:
        tree = {
            "className": "android.widget.FrameLayout",
            "packageName": "com.hpbr.bosszhipin",
            "children": [
                {"resourceId": "com.hpbr.bosszhipin:id/tv_tab_1", "text": "牛人"},
                {"resourceId": "com.hpbr.bosszhipin:id/tv_tab_3", "text": "消息"},
                {"resourceId": "com.hpbr.bosszhipin:id/tv_tab_4", "text": "我的"},
                {
                    "resourceId": "com.hpbr.bosszhipin:id/ctl_f3_profile",
                    "contentDescription": "赵总",
                },
                {
                    "resourceId": "com.hpbr.bosszhipin:id/tv_company_and_position",
                    "text": "某某集团·招聘总监",
                },
            ],
        }
        profile = extract_recruiter_profile(tree)
        assert profile is not None
        assert profile.name == "赵总"
        assert profile.company == "某某集团"
        assert profile.position == "招聘总监"

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
