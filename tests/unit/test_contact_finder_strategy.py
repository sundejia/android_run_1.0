"""
TDD tests for ContactFinderStrategy — ScrollContactFinder and SearchContactFinder.

Tests cover:
- ScrollContactFinder: prefix match, no match, retries
- SearchContactFinder: full search flow, fallback strategies, failure cases
- Strategy injection into ContactShareService
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from wecom_automation.services.ui_search.strategy import (
    CompositeContactFinder,
    ContactFinderStrategy,
    ScrollContactFinder,
    SearchContactFinder,
)

# ── Helpers ─────────────────────────────────────────────────────


def _elem(text="", index=None, bounds=None, **extra):
    """Build a minimal UI element dict."""
    e = {}
    if text:
        e["text"] = text
    if index is not None:
        e["index"] = index
    if bounds:
        e["bounds"] = bounds
    e.update(extra)
    return e


def _adb_mock(get_ui_state_side_effect=None):
    """Create a mock ADBService with common async methods."""
    adb = AsyncMock()
    adb.tap = AsyncMock(return_value="ok")
    adb.tap_coordinates = AsyncMock(return_value="ok")
    adb.clear_text_field = AsyncMock()
    adb.input_text = AsyncMock()
    adb.wait = AsyncMock()
    if get_ui_state_side_effect is not None:
        adb.get_ui_state = get_ui_state_side_effect
    else:
        adb.get_ui_state = AsyncMock(return_value=(None, []))
    return adb


# ── ScrollContactFinder ─────────────────────────────────────────


class TestScrollContactFinderFindsContact:
    @pytest.mark.asyncio
    async def test_finds_contact_by_prefix_match(self):
        adb = _adb_mock(
            get_ui_state_side_effect=AsyncMock(
                return_value=(
                    None,
                    [
                        _elem(text="张三-经理", index=5, bounds="[100,200][500,260]"),
                    ],
                )
            )
        )
        finder = ScrollContactFinder()
        result = await finder.find_and_select("张三", adb)
        assert result is True
        adb.tap.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    async def test_finds_exact_match(self):
        adb = _adb_mock(
            get_ui_state_side_effect=AsyncMock(
                return_value=(
                    None,
                    [
                        _elem(text="李四", index=10, bounds="[100,200][500,260]"),
                    ],
                )
            )
        )
        finder = ScrollContactFinder()
        result = await finder.find_and_select("李四", adb)
        assert result is True
        adb.tap.assert_awaited_once_with(10)

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        adb = _adb_mock(
            get_ui_state_side_effect=AsyncMock(
                return_value=(
                    None,
                    [
                        _elem(text="李四", index=5, bounds="[100,200][500,260]"),
                    ],
                )
            )
        )
        finder = ScrollContactFinder(max_retries=2)
        result = await finder.find_and_select("张三", adb)
        assert result is False

    @pytest.mark.asyncio
    async def test_retries_on_empty_elements(self):
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            return (None, [])

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = ScrollContactFinder(max_retries=3)
        result = await finder.find_and_select("张三", adb)
        assert result is False
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_get_ui_state_exception(self):
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("UI timeout")

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = ScrollContactFinder(max_retries=2)
        result = await finder.find_and_select("张三", adb)
        assert result is False
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_skips_elements_without_index(self):
        adb = _adb_mock(
            get_ui_state_side_effect=AsyncMock(
                return_value=(
                    None,
                    [
                        _elem(text="张三", bounds="[100,200][500,260]"),
                    ],
                )
            )
        )
        finder = ScrollContactFinder()
        result = await finder.find_and_select("张三", adb)
        assert result is False  # No index to tap


# ── SearchContactFinder ─────────────────────────────────────────


class TestSearchContactFinderFullFlow:
    @pytest.mark.asyncio
    async def test_finds_contact_via_search_button(self):
        """Full flow: search button → input field → type → match result → tap."""
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: find search button
                return (
                    None,
                    [
                        _elem(text="搜索", index=10, bounds="[900,50][1000,120]", clickable=True),
                    ],
                )
            elif call_count == 2:
                # After tapping search: find input field
                return (
                    None,
                    [
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )
            else:
                # After typing: find matching result (x1=200 >= 1080*0.14=151)
                return (
                    None,
                    [
                        _elem(text="张三", index=20, bounds="[200,200][800,260]"),
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder()
        result = await finder.find_and_select("张三", adb)
        assert result is True
        adb.clear_text_field.assert_awaited_once()
        adb.input_text.assert_awaited_once_with("张三")

    @pytest.mark.asyncio
    async def test_finds_contact_when_input_already_visible(self):
        """Search input is already on screen, skip search button."""
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    None,
                    [
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )
            else:
                return (
                    None,
                    [
                        _elem(text="李四", index=20, bounds="[200,200][800,260]"),
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder()
        result = await finder.find_and_select("李四", adb)
        assert result is True

    @pytest.mark.asyncio
    async def test_uses_position_fallback_when_no_keywords_match(self):
        """Falls back to top-right position heuristic for search button."""
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    None,
                    [
                        _elem(
                            className="android.widget.ImageView",
                            clickable=True,
                            index=10,
                            bounds="[900,30][1000,100]",
                        ),
                    ],
                )
            elif call_count == 2:
                return (
                    None,
                    [
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )
            else:
                return (
                    None,
                    [
                        _elem(text="王五", index=20, bounds="[200,200][800,260]"),
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder()
        result = await finder.find_and_select("王五", adb)
        assert result is True

    @pytest.mark.asyncio
    async def test_matches_by_substring_bidirectional(self):
        """Result text contains target name as substring."""
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    None,
                    [
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )
            else:
                return (
                    None,
                    [
                        _elem(text="赵六-部门主管", index=20, bounds="[200,200][800,260]"),
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder()
        result = await finder.find_and_select("赵六", adb)
        assert result is True


class TestSearchContactFinderFailure:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_search_button_or_input(self):
        adb = _adb_mock(get_ui_state_side_effect=AsyncMock(return_value=(None, [])))
        finder = SearchContactFinder()
        result = await finder.find_and_select("张三", adb)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_matching_results(self):
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    None,
                    [
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )
            else:
                return (
                    None,
                    [
                        _elem(text="李四", index=20, bounds="[200,200][800,260]"),
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder(max_retries=2)
        result = await finder.find_and_select("张三", adb)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_search_button_tap_fails(self):
        """Search button found but tapping doesn't open input field."""
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    None,
                    [
                        _elem(text="搜索", index=10, bounds="[900,50][1000,120]"),
                    ],
                )
            else:
                # After tapping search, still no input field
                return (None, [])

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder()
        result = await finder.find_and_select("张三", adb)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_get_ui_state_exception(self):
        async def mock_get_ui_state(force=False):
            raise RuntimeError("ADB disconnected")

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder()
        result = await finder.find_and_select("张三", adb)
        assert result is False


class TestSearchContactFinderCustomPatterns:
    @pytest.mark.asyncio
    async def test_uses_custom_search_patterns(self):
        """Custom patterns override defaults."""
        call_count = 0

        async def mock_get_ui_state(force=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (
                    None,
                    [
                        _elem(text="CustomSearch", index=10, bounds="[900,50][1000,120]"),
                    ],
                )
            elif call_count == 2:
                return (
                    None,
                    [
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )
            else:
                return (
                    None,
                    [
                        _elem(text="张三", index=20, bounds="[200,200][800,260]"),
                        _elem(className="android.widget.EditText", index=15, bounds="[50,60][700,110]"),
                    ],
                )

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder(
            search_text_patterns=("CustomSearch",),
            search_desc_patterns=(),
            search_resource_patterns=(),
        )
        result = await finder.find_and_select("张三", adb)
        assert result is True


class TestContactFinderStrategyIsABC:
    def test_cannot_instantiate_base_class(self):
        with pytest.raises(TypeError):
            ContactFinderStrategy()

    def test_scroll_is_subclass(self):
        assert issubclass(ScrollContactFinder, ContactFinderStrategy)

    def test_search_is_subclass(self):
        assert issubclass(SearchContactFinder, ContactFinderStrategy)


class TestCompositeContactFinder:
    """CompositeContactFinder must short-circuit on the first hit and try
    every strategy on misses without leaking exceptions.
    """

    @pytest.mark.asyncio
    async def test_returns_true_on_first_hit_and_skips_later_strategies(self):
        first = AsyncMock(spec=ContactFinderStrategy)
        first.find_and_select = AsyncMock(return_value=True)
        second = AsyncMock(spec=ContactFinderStrategy)
        second.find_and_select = AsyncMock(return_value=False)
        composite = CompositeContactFinder([first, second])

        adb = _adb_mock()
        ok = await composite.find_and_select("张三", adb)

        assert ok is True
        first.find_and_select.assert_awaited_once_with("张三", adb)
        second.find_and_select.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_through_to_scroll_when_search_misses(self):
        first = AsyncMock(spec=ContactFinderStrategy)
        first.find_and_select = AsyncMock(return_value=False)
        second = AsyncMock(spec=ContactFinderStrategy)
        second.find_and_select = AsyncMock(return_value=True)
        composite = CompositeContactFinder([first, second])

        adb = _adb_mock()
        ok = await composite.find_and_select("孙德家", adb)

        assert ok is True
        first.find_and_select.assert_awaited_once_with("孙德家", adb)
        second.find_and_select.assert_awaited_once_with("孙德家", adb)

    @pytest.mark.asyncio
    async def test_continues_after_strategy_raises(self):
        boom = AsyncMock(spec=ContactFinderStrategy)
        boom.find_and_select = AsyncMock(side_effect=RuntimeError("ADB down"))
        good = AsyncMock(spec=ContactFinderStrategy)
        good.find_and_select = AsyncMock(return_value=True)
        composite = CompositeContactFinder([boom, good])

        adb = _adb_mock()
        ok = await composite.find_and_select("孙德家", adb)

        assert ok is True
        good.find_and_select.assert_awaited_once_with("孙德家", adb)

    def test_rejects_empty_finder_list(self):
        with pytest.raises(ValueError):
            CompositeContactFinder([])


class TestSearchContactFinderScreenWidthAutoDetect:
    """Reproduces the 720px-device incident: the hard-coded 1080 default
    pushed `min_x = 1080 * 0.14 = 151` which over-filtered candidate rows
    on a 720-wide screen, dropping otherwise-valid matches.
    """

    @pytest.mark.asyncio
    async def test_finds_match_on_720_wide_device_when_x_below_1080_min_margin(self):
        """A row with x1=110 should be matched on a 720px device.
        On the old hard-coded 1080 default, min_x=151 would discard it.
        """
        call_count = 0

        async def mock_get_ui_state(force=False):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            # Every batch advertises a 720x1612 screen via root bounds
            screen_anchor = _elem(index=0, bounds="[0,0][720,1612]")
            if call_count == 1:
                return (
                    None,
                    [
                        screen_anchor,
                        _elem(
                            className="android.widget.EditText",
                            index=15,
                            bounds="[40,60][680,110]",
                        ),
                    ],
                )
            return (
                None,
                [
                    screen_anchor,
                    # x1=110 — would be filtered out by min_x=151 (1080 default)
                    # but should pass at min_x = 720 * 0.14 ≈ 100.
                    _elem(text="苏南老师", index=20, bounds="[110,200][620,260]"),
                    _elem(
                        className="android.widget.EditText",
                        index=15,
                        bounds="[40,60][680,110]",
                    ),
                ],
            )

        adb = _adb_mock(get_ui_state_side_effect=mock_get_ui_state)
        finder = SearchContactFinder()  # default 1080 — should self-correct
        ok = await finder.find_and_select("苏南老师", adb)

        assert ok is True
        adb.tap.assert_any_await(20)
