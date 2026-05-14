# Fix: UnreadUserExtractor Name/Preview Swap Bug

> **Date**: 2026-05-14
> **Status**: Implemented

## Problem

`UnreadUserExtractor._extract_entry_from_row()` assigned the `name` field by matching text nodes' `resourceId` against `NAME_RESOURCE_ID_HINTS` ("title", "name", etc.) in the first pass — without verifying the text actually looks like a customer name. When a message preview text node's resourceId happened to contain one of these hints, the preview text (e.g., "我想做哔哩哔哩") became `name`, and the real customer identifier (e.g., "1766909895-[重复(保底正常)]") fell into `message_preview`.

### Production Impact

From device `9586492623004ZE` logs (2026-05-13):

| Extracted Name (WRONG) | Preview (contains real name) | Entered Click Queue? |
|------------------------|------------------------------|---------------------|
| `我想做哔哩哔哩` | `1766909895-[重复(保底正常)]` | Yes — entered processing |
| `有过几次` | `bili_82076709740-1787652898(重复[保底正常])` | Yes — clicked (10 scroll timeout + accidental match at index 32) |
| `之前直播过语音厅` | *(various)* | Yes — entered processing |
| `房间号在哪看` | `None` | No (Priority: False) |
| `好的` / `可以` | `None` | No (Priority: False) |

`click_user_in_list("有过几次")` wasted 41 seconds searching 10 scrolls, then on retry found the text at index 32 in another conversation's UI and clicked it — entering the **wrong chat**.

### Why the Safety Filter Didn't Catch It

`_is_low_confidence_priority_user()` in `response_detector.py` had this bypass:

```python
if preview not in (None, "", "None"):
    return False  # not suspicious if preview exists
```

After a name/preview swap, `preview` contains the real customer name (non-None), so the filter was bypassed entirely.

## Resolution: 3-Layer Defense

### Layer 1: resourceId-Level Prevention (Extraction)

**Files**: `src/wecom_automation/services/user/unread_detector.py`, `src/wecom_automation/services/sync_service.py`

1. Added `PREVIEW_RESOURCE_ID_HINTS` constant with WeCom-specific preview resourceIds (`mid2txt`, `idk`, `icx`, `ig6`, `igj`) plus generic hints (`content`, `summary`, `snippet`, etc.). Source: `UIParserConfig.snippet_resource_id_hints` in `core/config.py`.

2. Added `mid1txt` to `NAME_RESOURCE_ID_HINTS` (WeCom's conversation list name field).

3. Modified first pass: when a node matches **both** name and preview hints, the preview hint wins. This prevents a preview text node from being assigned as `name` even if its resourceId contains a name hint substring.

### Layer 2: Post-Extraction Swap Detection (Extraction)

**Files**: same two files

Added three new class methods to both `UnreadUserExtractor` copies:

- `_is_strong_customer_id()`: Detects unambiguous system-generated customer identifiers (B-prefix, bili-prefix, numeric IDs, alphanumeric-ID-with-brackets patterns). These can never be message text.
- `_looks_like_customer_name()`: Broader check including short Chinese names, emoji names.
- `_check_and_fix_name_preview_swap()`: Called before `return` in `_extract_entry_from_row()`. Uses two-tier logic:
  1. If preview is a strong customer ID and name is not → swap (catches B-prefix, bili-prefix, numeric IDs)
  2. If preview looks like a customer name and name does not → swap (catches generic cases)

### Layer 3: Enhanced Safety Filter (Queue Entry)

**File**: `wecom-desktop/backend/services/followup/response_detector.py`

- Modified `_is_low_confidence_priority_user()` to detect swaps even when `preview` is non-None
- Added `_preview_looks_more_like_name()`: cross-field check that flags entries where preview contains B-prefix or numeric-ID patterns but name does not

## Files Changed

| File | Change |
|------|--------|
| `src/wecom_automation/services/user/unread_detector.py` | `PREVIEW_RESOURCE_ID_HINTS`, `mid1txt` in `NAME_RESOURCE_ID_HINTS`, preview-priority first pass, `_is_strong_customer_id()`, `_looks_like_customer_name()`, `_check_and_fix_name_preview_swap()`, swap check before return |
| `src/wecom_automation/services/sync_service.py` | Identical changes (parity) |
| `wecom-desktop/backend/services/followup/response_detector.py` | `_preview_looks_more_like_name()`, enhanced `_is_low_confidence_priority_user()` with cross-field swap detection |
| `tests/unit/test_unread_user_extractor_row_parsing.py` | 5 new test cases covering swap reproduction, preview hint priority, no false swaps |

## Tests

5 new regression tests parameterized across both `UnreadUserExtractor` copies (10 test runs total):

1. `test_swap_corrected_when_preview_node_has_name_resourceId` — production bug reproduction (titleTv on preview node)
2. `test_swap_corrected_with_bili_prefix_real_name_in_preview` — bili-prefix ID in preview field
3. `test_preview_hint_takes_priority_over_name_hint` — mid1Txt vs mid2Txt disambiguation
4. `test_no_false_swap_on_correct_data` — existing correct extraction unchanged
5. `test_no_swap_when_both_look_ambiguous` — neither looks like a strong ID → no swap

All 889 unit tests pass with zero regressions.

## Related Docs

- [Row Parsing Regression Tests Background](./2026-05-10-click-loop-row-parser.md) — original click loop bug that prompted row parsing tests
- [New Friend False Positive Click Loop (2026-05-12)](../04-bugs-and-fixes/resolved/2026-05-12-new-friend-false-positive-click-loop.md) — related filter bypass pattern
