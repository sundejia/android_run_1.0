"""Parse the BOSS Zhipin "我" (Me) tab to identify the logged-in recruiter.

Pure functions over a UI tree dict. No I/O, no device interaction.
Fixtures captured by ``scripts/dump_boss_ui.py`` drive the tests.

Schema compatibility
--------------------
Supports two BOSS Android app schemas observed in the wild:

* **Legacy (≤ 2026-03)** — separate ``tv_user_name`` / ``tv_company_name``
  / ``tv_user_position`` text nodes; bottom tabs carry
  ``contentDescription='首页 tab'`` etc.
* **May-2026 (12.14x)** — name lives only in ``ctl_f3_profile``'s
  ``contentDescription``; company and position are merged into
  ``tv_company_and_position`` joined by ``·``; bottom tabs are
  ``tv_tab_1`` through ``tv_tab_4`` with plain text labels
  ``牛人 / 搜索 / 消息 / 我的`` and no ``contentDescription``.

The parser accepts either schema. When both are present the legacy
IDs win (unlikely but harmless) so old fixtures keep the semantics
they had before the 2026-05-08 fix.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

# Legacy resource IDs (≤ 2026-03 schema). Listed in priority order;
# the first non-empty match wins.
_NAME_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/tv_user_name",
    "com.hpbr.bosszhipin:id/tv_name",
    "com.hpbr.bosszhipin:id/tv_user_nickname",
)
_COMPANY_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/tv_company_name",
    "com.hpbr.bosszhipin:id/tv_company",
)
_POSITION_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/tv_user_position",
    "com.hpbr.bosszhipin:id/tv_user_job",
    "com.hpbr.bosszhipin:id/tv_position",
)

# May-2026 schema: single node carries "<company>·<position>" text.
_COMPANY_AND_POSITION_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/tv_company_and_position",
)

# May-2026 schema: name only appears as ``contentDescription`` on the
# profile-header container. Checked last so legacy rids win when both
# forms are in the tree.
_NAME_CONTENT_DESC_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/ctl_f3_profile",
)

# Middle-dot separator used by the merged company-and-position text
# node. ``·`` (U+00B7) is the only observed variant; if BOSS ever
# switches to ``・`` or ``-`` this tuple can grow.
_COMPANY_POSITION_SEPARATORS: Final[tuple[str, ...]] = ("·",)

# Legacy bottom-tab content descriptions. Matching any one of these
# is enough to call the shell "logged in" — same behavior as before.
_LOGGED_IN_TAB_HINTS: Final[frozenset[str]] = frozenset(
    {
        "首页 tab",
        "招聘 tab",
        "消息 tab",
        "我 tab",
    }
)

# May-2026 bottom-tab text labels found on ``tv_tab_1`` .. ``tv_tab_4``.
# The real-device fixture has NO contentDescription on these, so we
# have to recognize by text. ``_LOGGED_IN_TAB_TEXT_MIN`` guards against
# a login screen that happens to display e.g. the single word "我" —
# we require at least three of these labels present simultaneously,
# which is the recruiter-side shell signature.
_LOGGED_IN_TAB_TEXTS: Final[frozenset[str]] = frozenset(
    {"牛人", "搜索", "消息", "我", "我的", "首页", "招聘", "推荐"}
)
_LOGGED_IN_TAB_TEXT_MIN: Final[int] = 3

# Text or content-description tokens that always indicate a login page.
_LOGGED_OUT_HINTS: Final[frozenset[str]] = frozenset(
    {
        "登录",
        "扫码登录",
        "Login",
        "Sign in",
    }
)


class LoginState(StrEnum):
    LOGGED_IN = "logged_in"
    LOGGED_OUT = "logged_out"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RecruiterProfile:
    name: str
    company: str | None = None
    position: str | None = None
    avatar_path: str | None = None


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Depth-first iterator over every node in a UI tree dict."""
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _text_of(node: dict[str, Any]) -> str:
    raw = node.get("text") or ""
    return str(raw).strip()


def _content_desc(node: dict[str, Any]) -> str:
    raw = node.get("contentDescription") or ""
    return str(raw).strip()


def _find_first_text_for_resource_ids(
    tree: dict[str, Any], resource_ids: tuple[str, ...]
) -> str | None:
    """Return the first non-empty stripped text of any node with one of
    the given resource ids.
    """
    wanted = set(resource_ids)
    for node in _walk(tree):
        rid = node.get("resourceId")
        if rid in wanted:
            text = _text_of(node)
            if text:
                return text
    return None


def _find_first_content_desc_for_resource_ids(
    tree: dict[str, Any], resource_ids: tuple[str, ...]
) -> str | None:
    """May-2026 fallback: some identity fields now live only in
    ``contentDescription`` on container nodes."""
    wanted = set(resource_ids)
    for node in _walk(tree):
        rid = node.get("resourceId")
        if rid in wanted:
            cd = _content_desc(node)
            if cd:
                return cd
    return None


def _split_company_and_position(
    text: str,
) -> tuple[str | None, str | None]:
    """Split a merged ``"<company>·<position>"`` node on any known
    separator. Returns ``(company, position)``; either side may be
    ``None`` if the input lacks a separator or a side is empty."""
    for sep in _COMPANY_POSITION_SEPARATORS:
        if sep in text:
            left, right = text.split(sep, 1)
            left = left.strip() or None
            right = right.strip() or None
            return left, right
    # No recognized separator: treat the whole string as the company
    # (it's almost always the company field when present).
    stripped = text.strip()
    return (stripped or None, None)


def detect_login_state(tree: dict[str, Any]) -> LoginState:
    """Classify the current BOSS Zhipin screen state.

    Returns ``LOGGED_IN`` when either the legacy tab-content-description
    markers or the May-2026 tab-text signature is present; ``LOGGED_OUT``
    when a login marker is visible; ``UNKNOWN`` otherwise. Ambiguous
    trees (both signals) collapse to ``LOGGED_OUT`` as a safety
    default — we never want to scrape recruiter info off a login page.
    """
    if not isinstance(tree, dict) or not tree:
        return LoginState.UNKNOWN

    has_legacy_tab = False
    tv_tab_text_matches = 0
    has_login_marker = False
    for node in _walk(tree):
        cd = _content_desc(node)
        if cd in _LOGGED_IN_TAB_HINTS:
            has_legacy_tab = True
        text = _text_of(node)
        rid = node.get("resourceId") or ""
        if (
            rid.startswith("com.hpbr.bosszhipin:id/tv_tab_")
            and text in _LOGGED_IN_TAB_TEXTS
        ):
            tv_tab_text_matches += 1
        if text in _LOGGED_OUT_HINTS or cd in _LOGGED_OUT_HINTS:
            has_login_marker = True

    has_main_tab = has_legacy_tab or tv_tab_text_matches >= _LOGGED_IN_TAB_TEXT_MIN

    if has_main_tab and not has_login_marker:
        return LoginState.LOGGED_IN
    if has_login_marker and not has_main_tab:
        return LoginState.LOGGED_OUT
    if has_main_tab and has_login_marker:
        return LoginState.LOGGED_OUT
    return LoginState.UNKNOWN


def extract_recruiter_profile(tree: dict[str, Any]) -> RecruiterProfile | None:
    """Return the recruiter profile from a "我" tab tree, or ``None``.

    Returns ``None`` when:
    - The tree is empty or not a dict.
    - The tree is a known logged-out screen.
    - The name field is missing or whitespace-only.
    """
    if not isinstance(tree, dict) or not tree:
        return None
    if detect_login_state(tree) == LoginState.LOGGED_OUT:
        return None

    name = _find_first_text_for_resource_ids(tree, _NAME_IDS)
    if not name:
        name = _find_first_content_desc_for_resource_ids(tree, _NAME_CONTENT_DESC_IDS)
    if not name:
        return None

    company = _find_first_text_for_resource_ids(tree, _COMPANY_IDS)
    position = _find_first_text_for_resource_ids(tree, _POSITION_IDS)

    if company is None or position is None:
        merged = _find_first_text_for_resource_ids(tree, _COMPANY_AND_POSITION_IDS)
        if merged:
            merged_company, merged_position = _split_company_and_position(merged)
            if company is None:
                company = merged_company
            if position is None:
                position = merged_position

    return RecruiterProfile(name=name, company=company, position=position)
