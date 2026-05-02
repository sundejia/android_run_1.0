"""
UI element selector patterns for WeCom contact card sharing.

Validated on real device (WeCom Android, 720x1612 resolution).

Flow: chat → tap i9u (attach button) → swipe left on GridView (ahe)
      → tap "Contact Card" (aha) → select contact → tap "Send" (dak)
"""

from __future__ import annotations

# ── Attachment button in chat input area (rightmost bottom icon) ──
ATTACH_RESOURCE_PATTERNS: tuple[str, ...] = ("i9u",)
ATTACH_DESC_PATTERNS: tuple[str, ...] = ()

# ── Attachment menu GridView (for horizontal swipe) ──────────────
ATTACH_GRID_RESOURCE_PATTERNS: tuple[str, ...] = ("ahe",)

# ── "Contact Card" item in attachment menu page 2 ────────────────
CARD_TEXT_PATTERNS: tuple[str, ...] = ("Contact Card", "名片", "Personal Card")
CARD_RESOURCE_PATTERNS: tuple[str, ...] = ()
# NOTE: "aha" is the resourceId for ALL attachment item labels (Image, Camera,
# Contact Card, etc.), so it MUST NOT be included here — use text matching only.

# ── "Select Contact(s)" title in contact picker ──────────────────
CONTACT_PICKER_TITLE_RESOURCE: tuple[str, ...] = ("nca",)
CONTACT_PICKER_LIST_RESOURCE: tuple[str, ...] = ("cth",)

# ── "Send" button in the confirmation dialog ─────────────────────
SEND_TEXT_PATTERNS: tuple[str, ...] = ("Send", "SEND", "发送", "确定")
SEND_RESOURCE_PATTERNS: tuple[str, ...] = ("dak", "blz", "i_2")

# ── "Cancel" button in the confirmation dialog ───────────────────
CANCEL_TEXT_PATTERNS: tuple[str, ...] = ("Cancel", "取消")
CANCEL_RESOURCE_PATTERNS: tuple[str, ...] = ("dah",)
