"""
UI element selector patterns for WeCom contact card sharing.

Validated on real device (WeCom Android, 720x1612 resolution among others).

Flow: chat → tap attach button (see ``ATTACH_RESOURCE_PATTERNS``) → swipe left
      on GridView (see ``ATTACH_GRID_RESOURCE_PATTERNS``: legacy ``ahe`` or
      newer ``aij``) → tap Contact Card by **exact text** (``CARD_TEXT_PATTERNS``;
      **not** by shared label rid ``aha``/``aif``) → select contact → tap Send.

Resource IDs for the attach button and attach-panel widgets drift between WeCom
builds, so patterns are **append-only** lists and we fall back to position when
no attach pattern matches. Removing an old token breaks older fleet devices.
"""

from __future__ import annotations

# ── Attachment button in chat input area (rightmost bottom icon) ──
# Multiple patterns to support different WeCom versions:
#   * "i9u": validated on WeCom Android 720x1612 (older builds)
#   * "id8": validated on WeCom Android 1080x2340 (newer builds, image_sender)
#   * "igu": validated on WeCom Android 720x1612, 2026-05-06 build
#           (observed via position fallback when i9u/id8 missed)
# IMPORTANT: keep this list append-only — devices in the fleet may be on
# different WeCom versions, removing an old ID will silently break older builds.
# DO NOT add too-short prefixes like "i_a" — find_elements_by_keywords does
# substring matching on resourceId, so a 2-char token will explode false matches.
ATTACH_RESOURCE_PATTERNS: tuple[str, ...] = ("i9u", "id8", "igu")
ATTACH_DESC_PATTERNS: tuple[str, ...] = ("更多功能", "more functions", "more")

# ── Attachment menu GridView (for horizontal swipe) ──────────────
# Multiple patterns to support different WeCom builds:
#   * "ahe": legacy (validated 1080x2340 + older 720 builds)
#   * "aij": validated WeCom Android 720x1612, 2026-05-06 build
#           (captured from contact_share_dump on the live device)
# Append-only so older fleet devices keep working.
ATTACH_GRID_RESOURCE_PATTERNS: tuple[str, ...] = ("ahe", "aij")

# ── Attachment menu item LABELS (the visible text node in each cell) ──
# All attach-panel item cells share one resourceId for their label TextView.
# Like the GridView, this drifts between builds:
#   * "aha": legacy
#   * "aif": validated WeCom Android 720x1612, 2026-05-06 build
# This is used for *page-state recognition only* (count ≥ N tells you the
# attach panel really opened). Do NOT add it to CARD_RESOURCE_PATTERNS —
# every item shares this id, so substring matching it would tap the wrong
# cell. Selecting Contact Card must still go through CARD_TEXT_PATTERNS.
ATTACH_ITEM_RESOURCE_PATTERNS: tuple[str, ...] = ("aha", "aif")

# ── "Contact Card" item in attachment menu page 2 ────────────────
CARD_TEXT_PATTERNS: tuple[str, ...] = ("Contact Card", "名片", "Personal Card")
CARD_RESOURCE_PATTERNS: tuple[str, ...] = ()
# NOTE: see ATTACH_ITEM_RESOURCE_PATTERNS comment above — the per-item
# resourceId is shared across every cell, so it MUST NOT be included here.
# Use exact text matching only for the menu item itself.

# ── "Select Contact(s)" title in contact picker ──────────────────
# Multiple patterns to support different WeCom builds — append-only just
# like ATTACH_RESOURCE_PATTERNS so older fleet devices keep working.
#   * "nca": legacy WeCom Android picker title resourceId.
#   * "nle": validated WeCom Android 720x1612, 2026-05-07 build (captured
#           from logs/contact_share_dump_20260507_134355_*_contact_card_menu.json
#           where Contact Card was correctly tapped but the page-state
#           envelope still rejected the picker because the title rid had
#           drifted from "nca" to "nle").
CONTACT_PICKER_TITLE_RESOURCE: tuple[str, ...] = ("nca", "nle")
# List container that holds the contact rows.
#   * "cth": legacy.
#   * "cwa": validated 2026-05-07 build alongside "nle".
CONTACT_PICKER_LIST_RESOURCE: tuple[str, ...] = ("cth", "cwa")

# ── "Send" button in the confirmation dialog ─────────────────────
SEND_TEXT_PATTERNS: tuple[str, ...] = ("Send", "SEND", "发送", "确定")
# Substrings matched against resourceId for the confirm-dialog Send button.
# Append-only — new builds rename, old ones keep working.
#
# 2026-05-07 (720x1612 build): the confirm dialog is rendered as plain
# TextView (NOT Button / NOT ImageView) with rid=de5 for Send and rid=de2
# for Cancel. Without "de5" here, ContactShareService._confirm_send falls
# back to text-substring matching ("Send"), which previously matched the
# picker's "Send to:" label and dialog detection silently failed.
SEND_RESOURCE_PATTERNS: tuple[str, ...] = ("dak", "blz", "i_2", "de5")

# ── "Cancel" button in the confirmation dialog ───────────────────
CANCEL_TEXT_PATTERNS: tuple[str, ...] = ("Cancel", "取消")
# Substrings matched against resourceId for the confirm-dialog Cancel button.
# 2026-05-07 build: TextView with rid=de2 (paired with rid=de5 for Send).
CANCEL_RESOURCE_PATTERNS: tuple[str, ...] = ("dah", "de2")
