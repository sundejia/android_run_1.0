"""
Selector patterns for contact picker search UI elements.

Validated on WeCom Android. These patterns are designed to work across
different WeCom versions where resource IDs change with every build.
Text and contentDescription patterns are the most reliable.
"""

from __future__ import annotations

# ── Contact picker search button ────────────────────────────────
PICKER_SEARCH_TEXT_PATTERNS: tuple[str, ...] = ("搜索", "search", "Search")
PICKER_SEARCH_DESC_PATTERNS: tuple[str, ...] = ("搜索", "search", "Search")
# Substrings matched against resourceId. "ndb" is the classic picker search
# control; some builds use adjacent ids — keep append-only.
#
# 2026-05-07 (720x1612 build): contact picker top bar is laid out as
#   [Back nlc] [Title nle "Select Contact(s)"] [Search nmf] [Close nma]
# so "nmf" is the actual magnifier and "nma" is the close button. Without
# "nmf" here the keyword pass yields nothing and the position-heuristic
# fallback in find_search_button drifts to the rightmost top-right element,
# which is "nma" → tapping it dismisses the picker and the whole share
# flow silently fails. Keep "nmf" listed; if a future build moves it,
# append the new id rather than replacing the existing entries.
PICKER_SEARCH_RESOURCE_PATTERNS: tuple[str, ...] = (
    "search",
    "query",
    "find",
    "ndb",
    "ndk",
    "ndc",
    "nmf",
)
# NOTE: Do NOT include "nd7" or "nma" — both are close/back buttons.
# "nd7" = legacy close button. "nma" = 720x1612 build picker close button
# (rightmost icon; tapping it returns to chat_screen). The position-fallback
# inside find_search_button has its own _EXCLUDE_RIDS for these ids.

# ── Contact picker search input field hints ─────────────────────
PICKER_SEARCH_INPUT_CLASS_HINTS: tuple[str, ...] = ("edittext",)
PICKER_SEARCH_INPUT_TEXT_HINTS: tuple[str, ...] = ("搜索", "search")
