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
PICKER_SEARCH_RESOURCE_PATTERNS: tuple[str, ...] = ("search", "query", "find", "ndb", "ndk", "ndc")
# NOTE: Do NOT include "nd7" — that is the close/back button (rightmost).

# ── Contact picker search input field hints ─────────────────────
PICKER_SEARCH_INPUT_CLASS_HINTS: tuple[str, ...] = ("edittext",)
PICKER_SEARCH_INPUT_TEXT_HINTS: tuple[str, ...] = ("搜索", "search")
