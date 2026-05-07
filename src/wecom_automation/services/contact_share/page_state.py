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

Signature catalog (validated on real devices 2026-05-06 / 2026-05-07):

  attach_panel       : resourceId contains ``ahe`` (legacy) or ``aij``
                       (2026-05-06 build) — GridView container
  contact_picker     : resourceId contains ``nca`` (legacy title) /
                       ``nle`` (2026-05-07 title) OR ``cth`` (legacy list) /
                       ``cwa`` (2026-05-07 list); fallback title text
                       starts with "Select Contact" / "选择联系人"
                       (covers "Select Contact(s)" with literal parens-s)
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

from collections.abc import Iterable

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


def _find_text_prefix(elements: Iterable[dict], prefixes: tuple[str, ...]) -> dict | None:
    """Find an element whose text starts with one of ``prefixes`` (case-insensitive).

    Used for *title* recognition where the suffix drifts between WeCom
    builds (``Select Contact`` vs ``Select Contact(s)`` vs ``Select Contacts``).
    Exact-match catalogs proved fragile — every release we'd lose the
    fallback the moment WeCom appended a token. Prefix matching is still
    narrow enough to avoid false positives because the prefixes themselves
    (``Select Contact``, ``选择联系人``) only appear on the picker screen.

    Do NOT extend this helper to substring matching — substring would
    re-introduce the very class of fake-success bug the validator was
    built to catch.
    """
    normalized = tuple(p.lower() for p in prefixes)
    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        text = _text(elem).lower()
        if not text:
            continue
        if any(text.startswith(prefix) for prefix in normalized):
            return elem
    return None


def _has_edittext(elements: Iterable[dict]) -> bool:
    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        if "edittext" in _class_name(elem):
            return True
    return False


# Prefix-based title catalog — each entry is matched against the start
# of an element's text (case-insensitive). The 2026-05-07 build ships
# the title as ``Select Contact(s)`` with a literal ``(s)`` suffix; older
# builds still use the singular ``Select Contact`` / ``选择联系人``.
# Matching by prefix means we recognize both without enumerating every
# pluralization variant WeCom ships next.
#
# Do NOT add the bare token ``Select`` — too generic, would also match
# ``Select All`` and any future "Select X" toolbar action that happens
# to land in the tree.
_PICKER_TITLE_TEXT_PREFIXES: tuple[str, ...] = (
    "Select Contact",      # English: "Select Contact", "Select Contact(s)", "Select Contacts"
    "Select a Contact",    # English variant on a few older builds
    "选择联系人",            # Chinese (also matches "选择联系人:" with colon suffix)
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

        Strong signal: ANY known GridView resource id from
        ``ATTACH_GRID_RESOURCE_PATTERNS`` is in the tree
        (``ahe`` legacy / ``aij`` 2026-05-06 build / ...).

        Fallback: ≥4 attach-item label resource ids from
        ``ATTACH_ITEM_RESOURCE_PATTERNS`` — covers builds where the
        GridView resourceId drifted but item IDs survived (or vice versa).
        Captured the hard way from a real device dump: the 720x1612 build
        on 2026-05-06 uses ``aij``/``aif`` while older code only knew
        ``ahe``/``aha``, so the page check silently failed even though
        the panel was clearly open on screen.
        """
        if not elements:
            return False
        for grid_id in S.ATTACH_GRID_RESOURCE_PATTERNS:
            if _has_resource_substring(elements, grid_id):
                return True
        for item_id in S.ATTACH_ITEM_RESOURCE_PATTERNS:
            if _count_resource_substring(elements, item_id) >= 4:
                return True
        return False

    @staticmethod
    def is_contact_picker_open(elements: list[dict]) -> bool:
        """Contact picker = the "Select Contact" screen pushed by Contact Card.

        Strong signal: any title resourceId from ``CONTACT_PICKER_TITLE_RESOURCE``
        (legacy ``nca`` / 2026-05-07 ``nle`` / ...) OR any list-container
        resourceId from ``CONTACT_PICKER_LIST_RESOURCE`` (legacy ``cth`` /
        2026-05-07 ``cwa`` / ...).

        Fallback: title text starts with "Select Contact" or "选择联系人".
        Prefix matching covers ``Select Contact(s)`` (with literal
        parens-s suffix) without enumerating every WeCom plural variant.
        """
        if not elements:
            return False
        for needle in S.CONTACT_PICKER_TITLE_RESOURCE + S.CONTACT_PICKER_LIST_RESOURCE:
            if _has_resource_substring(elements, needle):
                return True
        return _find_text_prefix(elements, _PICKER_TITLE_TEXT_PREFIXES) is not None

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
