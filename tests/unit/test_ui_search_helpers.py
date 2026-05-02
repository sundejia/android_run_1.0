"""
Tests for ui_search.ui_helpers — pure functions for UI element analysis.

Covers bounds parsing, keyword finding, layout sorting, search input/button
finding, and result candidate matching.
"""

from __future__ import annotations

from wecom_automation.services.ui_search.ui_helpers import (
    find_elements_by_keywords,
    find_result_candidates,
    find_search_button,
    find_search_input,
    layout_sort_key,
    parse_element_bounds,
    pick_bottom_right_element,
    pick_first_by_layout,
    pick_top_right_element,
)

# ── parse_element_bounds ────────────────────────────────────────


class TestParseElementBounds:
    def test_parses_string_bounds(self):
        elem = {"bounds": "[36,200][540,280]"}
        assert parse_element_bounds(elem) == (36, 200, 540, 280)

    def test_parses_negative_numbers(self):
        elem = {"bounds": "[-10,0][100,50]"}
        assert parse_element_bounds(elem) == (-10, 0, 100, 50)

    def test_parses_dict_bounds(self):
        elem = {"bounds": {"left": 10, "top": 20, "right": 300, "bottom": 400}}
        assert parse_element_bounds(elem) == (10, 20, 300, 400)

    def test_parses_boundsInScreen_key(self):
        elem = {"boundsInScreen": {"left": 0, "top": 0, "right": 1080, "bottom": 2340}}
        assert parse_element_bounds(elem) == (0, 0, 1080, 2340)

    def test_parses_bounds_in_screen_key(self):
        elem = {"bounds_in_screen": {"left": 1, "top": 2, "right": 3, "bottom": 4}}
        assert parse_element_bounds(elem) == (1, 2, 3, 4)

    def test_returns_none_for_none(self):
        assert parse_element_bounds(None) is None

    def test_returns_none_for_missing_bounds(self):
        assert parse_element_bounds({}) is None

    def test_returns_none_for_short_string(self):
        assert parse_element_bounds({"bounds": "[10,20]"}) is None

    def test_prefers_bounds_over_boundsInScreen(self):
        elem = {"bounds": "[1,2][3,4]", "boundsInScreen": {"left": 99, "top": 99, "right": 99, "bottom": 99}}
        assert parse_element_bounds(elem) == (1, 2, 3, 4)


# ── find_elements_by_keywords ───────────────────────────────────


class TestFindElementsByKeywords:
    def test_matches_text_pattern(self):
        elements = [
            {"text": "Contact Card"},
            {"text": "Something else"},
        ]
        result = find_elements_by_keywords(elements, text_patterns=("Contact",))
        assert len(result) == 1
        assert result[0]["text"] == "Contact Card"

    def test_matches_desc_pattern(self):
        elements = [{"contentDescription": "Search contacts"}]
        result = find_elements_by_keywords(elements, desc_patterns=("search",))
        assert len(result) == 1

    def test_matches_resource_pattern(self):
        elements = [{"resourceId": "com.tencent.wework:id/search_bar"}]
        result = find_elements_by_keywords(elements, resource_patterns=("search",))
        assert len(result) == 1

    def test_returns_empty_for_no_match(self):
        elements = [{"text": "Hello", "contentDescription": "World", "resourceId": "abc"}]
        result = find_elements_by_keywords(elements, text_patterns=("xyz",))
        assert result == []

    def test_case_insensitive_matching(self):
        elements = [{"text": "SEARCH"}]
        result = find_elements_by_keywords(elements, text_patterns=("search",))
        assert len(result) == 1

    def test_is_flat_list_walks_children(self):
        tree = [
            {
                "text": "Parent",
                "children": [
                    {"text": "Search Target"},
                ],
            }
        ]
        result = find_elements_by_keywords(tree, text_patterns=("Search Target",), is_flat_list=False)
        assert len(result) == 1  # only child matches

    def test_skips_non_dict_elements(self):
        elements = [{"text": "Valid"}, "not a dict", 42]
        result = find_elements_by_keywords(elements, text_patterns=("Valid",))
        assert len(result) == 1


# ── layout_sort_key ─────────────────────────────────────────────


class TestLayoutSortKey:
    def test_sorts_by_y_then_x(self):
        top_left = {"bounds": "[0,100][100,200]"}
        top_right = {"bounds": "[500,100][600,200]"}
        bottom_left = {"bounds": "[0,300][100,400]"}
        sorted_elems = sorted([bottom_left, top_right, top_left], key=layout_sort_key)
        assert sorted_elems == [top_left, top_right, bottom_left]

    def test_returns_large_values_for_missing_bounds(self):
        assert layout_sort_key({}) == (10**9, 10**9)

    def test_returns_large_values_for_none(self):
        assert layout_sort_key(None) == (10**9, 10**9)


# ── pick_top_right_element ──────────────────────────────────────


class TestPickTopRightElement:
    def test_picks_rightmost_highest(self):
        elements = [
            {"bounds": "[0,0][100,100]"},
            {"bounds": "[900,50][1000,150]"},
            {"bounds": "[500,0][600,100]"},
        ]
        result = pick_top_right_element(elements)
        assert result["bounds"] == "[900,50][1000,150]"

    def test_returns_none_for_empty(self):
        assert pick_top_right_element([]) is None

    def test_single_element(self):
        elements = [{"bounds": "[10,20][30,40]"}]
        assert pick_top_right_element(elements)["bounds"] == "[10,20][30,40]"


# ── pick_bottom_right_element ───────────────────────────────────


class TestPickBottomRightElement:
    def test_picks_lowest_rightmost(self):
        elements = [
            {"bounds": "[0,0][100,100]"},
            {"bounds": "[900,2000][1000,2100]"},
        ]
        result = pick_bottom_right_element(elements)
        assert result["bounds"] == "[900,2000][1000,2100]"

    def test_returns_none_for_empty(self):
        assert pick_bottom_right_element([]) is None


# ── pick_first_by_layout ────────────────────────────────────────


class TestPickFirstByLayout:
    def test_picks_topmost_leftmost(self):
        elements = [
            {"bounds": "[500,200][600,300]"},
            {"bounds": "[100,50][200,150]"},
        ]
        result = pick_first_by_layout(elements)
        assert result["bounds"] == "[100,50][200,150]"

    def test_returns_none_for_empty(self):
        assert pick_first_by_layout([]) is None


# ── find_search_input ───────────────────────────────────────────


class TestFindSearchInput:
    def test_finds_edittext(self):
        elements = [{"className": "android.widget.EditText", "bounds": "[50,60][700,110]"}]
        result = find_search_input(elements)
        assert result is not None

    def test_finds_by_search_text(self):
        elements = [{"text": "Search contacts", "bounds": "[50,60][700,110]"}]
        result = find_search_input(elements)
        assert result is not None

    def test_finds_by_search_resource_id(self):
        elements = [{"resourceId": "com.tencent.wework:id/search_input", "bounds": "[50,60][700,110]"}]
        result = find_search_input(elements)
        assert result is not None

    def test_finds_by_search_content_desc(self):
        elements = [{"contentDescription": "Search field", "bounds": "[50,60][700,110]"}]
        result = find_search_input(elements)
        assert result is not None

    def test_returns_none_when_no_input(self):
        elements = [{"text": "Hello", "className": "android.widget.TextView"}]
        assert find_search_input(elements) is None

    def test_picks_topmost_when_multiple(self):
        elements = [
            {"className": "android.widget.EditText", "bounds": "[50,500][700,550]"},
            {"className": "android.widget.EditText", "bounds": "[50,100][700,150]"},
        ]
        result = find_search_input(elements)
        assert result["bounds"] == "[50,100][700,150]"


# ── find_result_candidates ──────────────────────────────────────


class TestFindResultCandidates:
    def test_matches_by_exact_name(self):
        elements = [{"text": "张三", "bounds": "[200,200][800,260]"}]
        result = find_result_candidates(elements, "张三", screen_width=1080)
        assert len(result) == 1

    def test_matches_by_substring_bidirectional(self):
        # target is substring of element text
        elements = [{"text": "张三-经理", "bounds": "[200,200][800,260]"}]
        result = find_result_candidates(elements, "张三", screen_width=1080)
        assert len(result) == 1

        # element text is substring of target
        elements2 = [{"text": "张", "bounds": "[200,200][800,260]"}]
        result2 = find_result_candidates(elements2, "张三", screen_width=1080)
        assert len(result2) == 1

    def test_no_match(self):
        elements = [{"text": "李四", "bounds": "[200,200][800,260]"}]
        result = find_result_candidates(elements, "张三", screen_width=1080)
        assert result == []

    def test_filters_by_anchor_position(self):
        anchor = {"bounds": "[0,100][1080,150]"}
        # Element above anchor should be filtered out (y1=50 < anchor bottom=150)
        elements = [{"text": "张三", "bounds": "[200,50][800,80]"}]
        result = find_result_candidates(elements, "张三", anchor=anchor, screen_width=1080)
        assert result == []

    def test_filters_by_left_margin(self):
        elements = [{"text": "张三", "bounds": "[50,200][100,260]"}]  # x1=50 < 1080*0.14=151
        result = find_result_candidates(elements, "张三", screen_width=1080)
        assert result == []

    def test_sorted_by_layout(self):
        elements = [
            {"text": "张三", "bounds": "[200,400][800,460]"},
            {"text": "张三2", "bounds": "[200,200][800,260]"},
        ]
        result = find_result_candidates(elements, "张三", screen_width=1080)
        assert result[0]["bounds"] == "[200,200][800,260]"
        assert result[1]["bounds"] == "[200,400][800,460]"

    def test_excludes_edittext_elements(self):
        """EditText (search input) should not appear as a result candidate."""
        elements = [
            {"text": "张三", "className": "android.widget.EditText", "bounds": "[200,200][800,260]"},
            {"text": "张三-经理", "className": "android.widget.TextView", "bounds": "[200,300][800,360]"},
        ]
        result = find_result_candidates(elements, "张三", screen_width=1080)
        assert len(result) == 1
        assert result[0]["text"] == "张三-经理"


# ── find_search_button ──────────────────────────────────────────


class TestFindSearchButton:
    def test_finds_by_text_pattern(self):
        elements = [
            {"text": "搜索", "bounds": "[900,50][1000,120]", "clickable": True},
        ]
        result = find_search_button(
            elements,
            text_patterns=("搜索",),
            screen_width=1080,
            screen_height=2340,
        )
        assert result is not None

    def test_position_fallback_top_right(self):
        # No keyword match, but clickable image in top-right
        elements = [
            {
                "className": "android.widget.ImageView",
                "clickable": True,
                "bounds": "[900,30][1000,100]",
            },
        ]
        result = find_search_button(
            elements,
            text_patterns=("不存在",),
            screen_width=1080,
            screen_height=2340,
        )
        assert result is not None

    def test_returns_none_when_nothing_found(self):
        elements = [{"text": "Hello", "className": "android.widget.LinearLayout", "bounds": "[0,0][100,100]"}]
        result = find_search_button(
            elements,
            text_patterns=("搜索",),
            screen_width=1080,
            screen_height=2340,
        )
        assert result is None

    def test_excludes_nd7_close_button(self):
        """nd7 (close/back button) must never be selected as the search button."""
        elements = [
            {
                "text": "",
                "resourceId": "com.tencent.wework:id/nd7",
                "className": "android.widget.TextView",
                "bounds": "[624,56][720,152]",
            },
        ]
        result = find_search_button(
            elements,
            resource_patterns=("nd7",),
            screen_width=1080,
            screen_height=2340,
        )
        assert result is None

    def test_prefers_ndb_over_nd7_in_position_fallback(self):
        """Position heuristic should pick ndb but not nd7."""
        elements = [
            {
                "text": "",
                "resourceId": "com.tencent.wework:id/ndb",
                "className": "android.widget.TextView",
                "bounds": "[528,56][624,152]",
            },
            {
                "text": "",
                "resourceId": "com.tencent.wework:id/nd7",
                "className": "android.widget.TextView",
                "bounds": "[624,56][720,152]",
            },
        ]
        result = find_search_button(
            elements,
            text_patterns=("不存在",),
            screen_width=720,
            screen_height=1612,
        )
        assert result is not None
        assert "ndb" in result.get("resourceId", "")
