"""Regression tests for the relaxed user-list matcher used by ``click_user_in_list``.

Background: the old matcher required exact case-insensitive equality between
the target name and the cell text. WeCom list rows commonly truncate long
display names (`B2605080143-(保底正…`) or render parens in full-width form
(`B2605080143-（保底正常）`), so exact `==` failed and the click hit the
"User not found after 5 scrolls" branch — feeding back into the click-cooldown
loop that broke 2026-05-09.

See docs/04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def service():
    """Stand-up a bare WeComService just for the matcher tests."""
    from wecom_automation.core.config import Config
    from wecom_automation.services.wecom_service import WeComService

    svc = object.__new__(WeComService)
    svc.config = Config()
    svc.logger = MagicMock()
    svc.adb = MagicMock()
    svc.ui_parser = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# _normalize_user_text
# ---------------------------------------------------------------------------


class TestNormalizeUserText:
    def test_strips_outer_whitespace_and_lowercases(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._normalize_user_text("  Hello WORLD  ") == "hello world"

    def test_drops_trailing_unicode_ellipsis(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._normalize_user_text("B2605080143-(保底正…") == "b2605080143-(保底正"

    def test_drops_trailing_three_dot_ellipsis(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._normalize_user_text("B2605080143-(保底正...") == "b2605080143-(保底正"

    def test_folds_full_width_parens(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._normalize_user_text(
            "B2605080143-（保底正常）"
        ) == "b2605080143-(保底正常)"

    def test_folds_full_width_brackets(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._normalize_user_text(
            "B2604130225-［重复(保底正常)］"
        ) == "b2604130225-[重复(保底正常)]"

    def test_empty_or_none_is_empty(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._normalize_user_text("") == ""
        assert WeComService._normalize_user_text(None) == ""


# ---------------------------------------------------------------------------
# _user_text_match_tier
# ---------------------------------------------------------------------------


class TestUserTextMatchTier:
    def test_exact_case_insensitive_match_is_tier_1(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._user_text_match_tier("Hello", "hello") == 1

    def test_normalized_paren_match_is_tier_2(self):
        from wecom_automation.services.wecom_service import WeComService

        # Full-width parens on the rendered side; half-width on the target side.
        tier = WeComService._user_text_match_tier(
            "B2605080143-(保底正常)", "B2605080143-（保底正常）"
        )
        assert tier == 2

    def test_truncated_prefix_is_tier_3_for_long_name(self):
        from wecom_automation.services.wecom_service import WeComService

        tier = WeComService._user_text_match_tier(
            "B2605080143-(保底正常)", "B2605080143-(保底正…"
        )
        assert tier == 3

    def test_truncated_prefix_rejected_for_short_name(self):
        """`你好` is only 2 chars — must NOT accept a truncated 'X…' as a match."""
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._user_text_match_tier("你好", "你…") == 0
        assert WeComService._user_text_match_tier("你好", "你好的天气真不错…") == 0

    def test_non_truncated_prefix_is_rejected(self):
        """Without an ellipsis marker we MUST require exact (or normalized) match
        — otherwise any preview that starts with the target name would match."""
        from wecom_automation.services.wecom_service import WeComService

        # No ellipsis on the rendered text -> must not match.
        assert (
            WeComService._user_text_match_tier(
                "B2605080143-(保底正常)", "B2605080143-(保底正"
            )
            == 0
        )

    def test_substring_inside_other_text_does_not_match(self):
        """Sanity: the rendered text being a substring of the target is fine
        only when truncated; a completely unrelated longer string must not
        match by accident."""
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._user_text_match_tier("Hello World", "Hello") == 0

    def test_empty_inputs_do_not_match(self):
        from wecom_automation.services.wecom_service import WeComService

        assert WeComService._user_text_match_tier("", "x") == 0
        assert WeComService._user_text_match_tier("x", "") == 0


# ---------------------------------------------------------------------------
# _find_user_element — end-to-end scenarios
# ---------------------------------------------------------------------------


def _make_row(text: str, *, clickable: bool = True, index: int = 0, children=None) -> dict:
    return {
        "text": text,
        "clickable": clickable,
        "index": index,
        "children": children or [],
    }


class TestFindUserElement:
    def test_exact_match_preferred_over_prefix(self, service):
        elements = [
            _make_row("B2605080143-(保底正…", clickable=True, index=11),
            _make_row("B2605080143-(保底正常)", clickable=True, index=22),
        ]

        result = service._find_user_element(
            elements, "B2605080143-(保底正常)", channel=None, is_flat_list=True
        )

        assert result is not None
        # The full (tier 1) row should be picked, not the truncated (tier 3) one.
        assert result["index"] == 22

    def test_full_width_paren_row_matches(self, service):
        elements = [
            _make_row("B2605080143-（保底正常）", clickable=True, index=7),
        ]
        result = service._find_user_element(
            elements, "B2605080143-(保底正常)", channel=None, is_flat_list=True
        )
        assert result is not None
        assert result["index"] == 7

    def test_truncated_row_matches_for_long_name(self, service):
        elements = [
            _make_row("B2605080143-(保底正…", clickable=True, index=4),
        ]
        result = service._find_user_element(
            elements, "B2605080143-(保底正常)", channel=None, is_flat_list=True
        )
        assert result is not None
        assert result["index"] == 4

    def test_truncated_row_does_not_falsely_match_short_name(self, service):
        """Default-display-name `你好` must NOT match a chat preview that
        starts with `你好…` — that was the 2026-05-10 failure mode."""
        elements = [
            _make_row("你好的天气真不错…", clickable=True, index=99),
        ]
        result = service._find_user_element(
            elements, "你好", channel=None, is_flat_list=True
        )
        assert result is None

    def test_recursive_match_returns_clickable_ancestor(self, service):
        """When the matching text is on a non-clickable child, the clickable
        row ancestor must be returned so ``tap(index)`` lands on the row."""
        row = _make_row(
            "",
            clickable=True,
            index=42,
            children=[_make_row("B2605080143-(保底正常)", clickable=False, index=43)],
        )
        result = service._find_user_element([row], "B2605080143-(保底正常)", channel=None)
        assert result is not None
        assert result["index"] == 42  # the clickable row, not its inner text node

    def test_bracketed_duplicate_suffix_matches(self, service):
        elements = [
            _make_row("B2604130225-［重复(保底正常)］", clickable=True, index=15),
        ]
        result = service._find_user_element(
            elements, "B2604130225-[重复(保底正常)]", channel=None, is_flat_list=True
        )
        assert result is not None
        assert result["index"] == 15

    def test_no_match_returns_none(self, service):
        elements = [
            _make_row("不相关的客户A", clickable=True, index=1),
            _make_row("不相关的客户B", clickable=True, index=2),
        ]
        assert (
            service._find_user_element(
                elements, "B2605080143-(保底正常)", channel=None, is_flat_list=True
            )
            is None
        )


# ---------------------------------------------------------------------------
# click_user_in_list — max-scrolls floor
# ---------------------------------------------------------------------------


def test_click_user_min_scrolls_floor_constant():
    """Production env occasionally ships WECOM_MAX_SCROLLS=5; the click loop
    must floor at the safer ``_CLICK_USER_MIN_SCROLLS`` value."""
    from wecom_automation.services.wecom_service import WeComService

    assert WeComService._CLICK_USER_MIN_SCROLLS >= 10
