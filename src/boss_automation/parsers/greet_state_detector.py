"""Classify the BOSS Zhipin candidate-detail page state.

Returns a single ``GreetState`` value used by the executor to decide
whether to send a greeting, skip it, or halt the run entirely.

Detection priority (highest first):
1. RISK_CONTROL_BLOCKED — operator must intervene.
2. QUOTA_EXHAUSTED — daily greet quota used up.
3. ALREADY_GREETED — candidate already messaged; no-op skip.
4. READY_TO_GREET — 立即沟通 button visible and enabled.
5. UNKNOWN — anything else; the executor halts conservatively.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from enum import StrEnum
from typing import Any, Final

_RISK_DIALOG_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/risk_control_dialog",
    "com.hpbr.bosszhipin:id/tv_risk_dialog_title",
)
_RISK_TITLE_RE: Final[re.Pattern[str]] = re.compile(r"操作过于频繁|访问异常|账号异常|系统检测到风险")

_QUOTA_DIALOG_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/quota_exhausted_dialog",
    "com.hpbr.bosszhipin:id/tv_quota_dialog_title",
)
_QUOTA_TITLE_RE: Final[re.Pattern[str]] = re.compile(r"沟通次数已用完|今日额度已满|今日沟通次数已达上限")

_ALREADY_GREETED_IDS: Final[tuple[str, ...]] = (
    "com.hpbr.bosszhipin:id/btn_continue_chat",
    "com.hpbr.bosszhipin:id/tv_chat_status",
)
_ALREADY_GREETED_LABELS: Final[frozenset[str]] = frozenset({"继续沟通", "已沟通"})

_READY_BUTTON_IDS: Final[tuple[str, ...]] = ("com.hpbr.bosszhipin:id/btn_chat_now",)
_READY_BUTTON_LABELS: Final[frozenset[str]] = frozenset({"立即沟通"})


class GreetState(StrEnum):
    READY_TO_GREET = "ready_to_greet"
    ALREADY_GREETED = "already_greeted"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RISK_CONTROL_BLOCKED = "risk_control_blocked"
    UNKNOWN = "unknown"


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        yield from _walk(child)


def _has_risk_control(tree: dict[str, Any]) -> bool:
    risk_id_set = set(_RISK_DIALOG_IDS)
    for node in _walk(tree):
        if node.get("resourceId") in risk_id_set:
            text = str(node.get("text") or "")
            if _RISK_TITLE_RE.search(text) or "risk_control_dialog" in str(node.get("resourceId") or ""):
                return True
    return False


def _has_quota_exhausted(tree: dict[str, Any]) -> bool:
    quota_id_set = set(_QUOTA_DIALOG_IDS)
    for node in _walk(tree):
        if node.get("resourceId") in quota_id_set:
            text = str(node.get("text") or "")
            if _QUOTA_TITLE_RE.search(text) or "quota_exhausted_dialog" in str(node.get("resourceId") or ""):
                return True
    return False


def _has_already_greeted(tree: dict[str, Any]) -> bool:
    wanted = set(_ALREADY_GREETED_IDS)
    for node in _walk(tree):
        if node.get("resourceId") in wanted:
            text = str(node.get("text") or "").strip()
            if text in _ALREADY_GREETED_LABELS:
                return True
    return False


def _has_ready_button(tree: dict[str, Any]) -> bool:
    wanted = set(_READY_BUTTON_IDS)
    for node in _walk(tree):
        text = str(node.get("text") or "").strip()
        if node.get("resourceId") in wanted or text in _READY_BUTTON_LABELS:
            enabled = bool(node.get("enabled", True))
            if text in _READY_BUTTON_LABELS and enabled:
                return True
    return False


def detect_greet_state(tree: dict[str, Any]) -> GreetState:
    if not isinstance(tree, dict) or not tree:
        return GreetState.UNKNOWN

    if _has_risk_control(tree):
        return GreetState.RISK_CONTROL_BLOCKED
    if _has_quota_exhausted(tree):
        return GreetState.QUOTA_EXHAUSTED
    if _has_already_greeted(tree):
        return GreetState.ALREADY_GREETED
    if _has_ready_button(tree):
        return GreetState.READY_TO_GREET
    return GreetState.UNKNOWN
