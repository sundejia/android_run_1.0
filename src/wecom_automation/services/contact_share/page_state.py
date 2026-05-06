"""
PageStateValidator — recognize the *current* WeCom screen by structural signature.

Why this exists
---------------
ContactShareService used to assume each step succeeded just because a UI
selector "matched something". With WeCom's heavily obfuscated resource IDs
plus substring matching in find_elements_by_keywords, a missed Contact-Card
tap could silently fall through and the next step (picker search, confirm
dialog) would happily match unrelated nodes still on the attach panel —
the whole share flow returned True and wrote a fake-success row to
media_action_contact_shares, permanently dedup-blocking the customer.

PageStateValidator gives the share flow a way to *verify* page transitions
between steps. Each predicate is intentionally cheap (one O(n) pass over
the flat clickable list) so it can be called between every UI action
without dominating step latency.

Signature catalog (validated on real device 2026-05-06):

  attach_panel       : resourceId contains ``ahe`` (GridView container)
  contact_picker     : resourceId contains ``nca`` (title) OR ``cth`` (list)
  confirm_send_dialog: Send button AND Cancel button both visible
                       (resource ``dak`` + ``dah`` OR Button class with
                       text "Send/Cancel/发送/取消")
  chat_screen        : an EditText input field is present AND we're NOT in
                       attach_panel / picker / confirm_dialog

The chat_screen check explicitly excludes the other three states because
the attach panel sits *on top of* the chat screen — the chat input row is
still in the UI tree even when the panel is open. Without exclusion every
state would also be "chat_screen" and the validator would be useless.
"""

from __future__ import annotations

from typing import Iterable

from wecom_automation.services.contact_share import selectors as S


def _resource_id(elem: dict) -> str:
    return (elem.get("resourceId") or "").lower()


def _text(elem: dict) -> str:
    return (elem.get("text") or "").strip()


def _class_name(elem: dict) -> str:
    return (elem.get("class") or elem.get("className") or "").lower()


def _has_resource_substring(elements: Iterable[dict], needle: str) -> bool:
    needle = needle.lower()
    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        if needle in _resource_id(elem):
            return True
    return False


def _count_resource_substring(elements: Iterable[dict], needle: str) -> int:
    needle = needle.lower()
    count = 0
    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        if needle in _resource_id(elem):
            count += 1
    return count


def _find_button_with_text(elements: Iterable[dict], texts: tuple[str, ...]) -> dict | None:
    """Find a Button-class element whose text exactly matches one of `texts`.

    Exact match is used here because the confirm dialog's Send/Cancel labels
    are short, well-known strings — substring matching would re-introduce
    the very bug this validator exists to catch (e.g. "Send to:" matching
    "Send").
    """
    wanted = {t.lower() for t in texts}
    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        if "button" not in _class_name(elem):
            continue
        if _text(elem).lower() in wanted:
            return elem
    return None


def _find_text_exact(elements: Iterable[dict], texts: tuple[str, ...]) -> dict | None:
    wanted = {t.lower() for t in texts}
    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        if _text(elem).lower() in wanted:
            return elem
    return None


def _has_edittext(elements: Iterable[dict]) -> bool:
    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        if "edittext" in _class_name(elem):
            return True
    return False


_PICKER_TITLE_TEXTS: tuple[str, ...] = (
    "Select Contact",
    "Select a Contact",
    "选择联系人",
    "选择联系人:",
    "Select",
)


_CONFIRM_SEND_TEXTS: tuple[str, ...] = ("Send", "SEND", "发送", "确定")
_CONFIRM_CANCEL_TEXTS: tuple[str, ...] = ("Cancel", "CANCEL", "取消")


class PageStateValidator:
    """Stateless predicates for "what page are we currently on" checks.

    All methods accept the same flat element list returned by
    ``adb_service.get_ui_state(force=True)[1]``. They never raise — bad
    inputs just return False so callers can treat "unknown page" the same
    as "wrong page".
    """

    @staticmethod
    def is_attach_panel_open(elements: list[dict]) -> bool:
        """Attach panel = the +-button popup with Image / Video / Contact Card.

        Strong signal: GridView (``ahe``) container is in the tree.
        Fallback: ≥4 attach-item labels (``aha``) — covers builds where the
        GridView resourceId drifted but item IDs survived.
        """
        if not elements:
            return False
        if _has_resource_substring(elements, S.ATTACH_GRID_RESOURCE_PATTERNS[0]):
            return True
        # `aha` is the universal label resourceId for every menu item
        # (Image, Camera, Contact Card, Favorites, ...). Seeing a handful of
        # them in one snapshot is a high-confidence "attach panel" signal.
        return _count_resource_substring(elements, "aha") >= 4

    @staticmethod
    def is_contact_picker_open(elements: list[dict]) -> bool:
        """Contact picker = the "Select Contact" screen pushed by Contact Card.

        Strong signal: ``nca`` title OR ``cth`` list resourceId present.
        Fallback: title text contains "Select Contact" / "选择联系人".
        """
        if not elements:
            return False
        for needle in S.CONTACT_PICKER_TITLE_RESOURCE + S.CONTACT_PICKER_LIST_RESOURCE:
            if _has_resource_substring(elements, needle):
                return True
        return _find_text_exact(elements, _PICKER_TITLE_TEXTS) is not None

    @staticmethod
    def is_confirm_send_dialog_open(elements: list[dict]) -> bool:
        """Confirm-send dialog = the modal with "Send" + "Cancel" buttons.

        Requires BOTH a Send-style button AND a Cancel-style button to be
        visible. Either alone is too easy to false-match (a chat send
        button, a generic toolbar cancel icon, etc.).
        """
        if not elements:
            return False

        send_button = _find_button_with_text(elements, _CONFIRM_SEND_TEXTS)
        cancel_button = _find_button_with_text(elements, _CONFIRM_CANCEL_TEXTS)
        if send_button is not None and cancel_button is not None:
            return True

        # Fallback: dak/dah resource IDs (validated WeCom Android send/cancel
        # IDs) co-present. Some builds expose the buttons as ImageView, not
        # Button class, so the class-based path above misses them.
        has_send_rid = any(
            _has_resource_substring(elements, rid) for rid in S.SEND_RESOURCE_PATTERNS
        )
        has_cancel_rid = any(
            _has_resource_substring(elements, rid) for rid in S.CANCEL_RESOURCE_PATTERNS
        )
        return has_send_rid and has_cancel_rid

    @staticmethod
    def is_chat_screen(elements: list[dict]) -> bool:
        """Chat screen = the conversation view with an input EditText visible.

        Excludes the three "above" states because the chat input row is
        still in the UI tree when the attach panel pops up over it. Without
        the exclusion, attach_panel would also be "chat_screen" and the
        validator would never catch missed transitions.
        """
        if not elements:
            return False
        if not _has_edittext(elements):
            return False
        if PageStateValidator.is_attach_panel_open(elements):
            return False
        if PageStateValidator.is_contact_picker_open(elements):
            return False
        if PageStateValidator.is_confirm_send_dialog_open(elements):
            return False
        return True

    @staticmethod
    def describe(elements: list[dict]) -> str:
        """Human-readable summary of which states currently match.

        Useful for diagnostic logs when a state assertion fails — tells you
        at a glance whether you ended up on the wrong page or no recognized
        page at all.
        """
        flags = []
        if PageStateValidator.is_attach_panel_open(elements):
            flags.append("attach_panel")
        if PageStateValidator.is_contact_picker_open(elements):
            flags.append("contact_picker")
        if PageStateValidator.is_confirm_send_dialog_open(elements):
            flags.append("confirm_send_dialog")
        if PageStateValidator.is_chat_screen(elements):
            flags.append("chat_screen")
        return ",".join(flags) if flags else "unknown"
