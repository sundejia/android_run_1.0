"""Parse the BOSS Zhipin "我" (Me) tab to identify the logged-in recruiter.

Pure functions over a UI tree dict. No I/O, no device interaction.
Fixtures captured by ``scripts/dump_boss_ui.py`` drive the tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

# Resource IDs known to carry recruiter identity. Listed in priority
# order; the first non-empty match wins. Update only after re-dumping a
# real device fixture.
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

# Bottom-tab content descriptions that uniquely identify the
# recruiter-side main app shell.
_LOGGED_IN_TAB_HINTS: Final[frozenset[str]] = frozenset(
    {
        "首页 tab",
        "招聘 tab",
        "消息 tab",
        "我 tab",
    }
)

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


def _find_first_text_for_resource_ids(tree: dict[str, Any], resource_ids: tuple[str, ...]) -> str | None:
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


def detect_login_state(tree: dict[str, Any]) -> LoginState:
    """Classify the current BOSS Zhipin screen state.

    Returns ``LoggedIn`` if any known main-shell tab is present;
    ``LoggedOut`` if any login marker is present; ``Unknown`` otherwise.
    """
    if not isinstance(tree, dict) or not tree:
        return LoginState.UNKNOWN

    has_main_tab = False
    has_login_marker = False
    for node in _walk(tree):
        cd = _content_desc(node)
        if cd in _LOGGED_IN_TAB_HINTS:
            has_main_tab = True
        text = _text_of(node)
        if text in _LOGGED_OUT_HINTS or cd in _LOGGED_OUT_HINTS:
            has_login_marker = True

    if has_main_tab and not has_login_marker:
        return LoginState.LOGGED_IN
    if has_login_marker and not has_main_tab:
        return LoginState.LOGGED_OUT
    if has_main_tab and has_login_marker:
        # Conservative: treat ambiguous state as logged-out so we never
        # try to scrape recruiter info from a login screen.
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
        return None

    company = _find_first_text_for_resource_ids(tree, _COMPANY_IDS)
    position = _find_first_text_for_resource_ids(tree, _POSITION_IDS)

    return RecruiterProfile(name=name, company=company, position=position)
