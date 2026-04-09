# UI Parser Unread Badge Bug

> **Date**: 2025-12-10
> **Status**: ✅ Fixed
> **Component**: `src/wecom_automation/services/ui_parser.py`

## Symptoms

- Customer names in database showing as numbers like "1", "4", "2" instead of actual names
- Actual customer names appearing in `last_message_preview` field instead of `name` field
- Filter headers like "Internal chats" and "External chats" being saved as customer records
- Latest messages appearing not stored (actually stored under wrong customer records)

Example corrupted data:

```
id | name | last_message_preview
1  | 1    | zxy              <- "zxy" should be the name
2  | 4    | wgz(302)         <- "wgz(302)" should be the name
11 | Internal chats | ...   <- should not be a customer
```

## Root Cause

The issue was in `_extract_user_from_row()` in `ui_parser.py`. The third-pass heuristic for name assignment was picking up:

1. **Unread count badges** (like "1", "4", "2") as the first text node in UI rows
2. **Filter headers** (like "Internal chats", "External chats") as customer names

The heuristic logic was:

```python
if not name and remaining_texts:
    name = remaining_texts[0]  # This picked up unread badge numbers!
```

Since unread badges appear as text nodes and don't match timestamp or channel patterns, they were being assigned as customer names.

## Failed Approaches

N/A - Issue was diagnosed correctly on first analysis.

## Solution

Added two new detection methods and updated the name assignment logic:

### 1. `looks_like_unread_badge()` method

```python
def looks_like_unread_badge(self, value: str) -> bool:
    """Detects unread count badges like '1', '99+', 'new'."""
    if value.isdigit() and len(value) <= 3:  # 1-999
        return True
    if re.match(r'^\d+\+$', value):  # "99+"
        return True
    if value.lower() in ('new', '新', '新消息'):
        return True
    return False
```

### 2. `looks_like_filter_header()` method

```python
def looks_like_filter_header(self, value: str) -> bool:
    """Detects filter headers like 'Internal chats', '私聊'."""
    filter_headers = (
        "internal chats", "external chats",
        "内部聊天", "外部聊天", "私聊", "群聊", "单聊",
    )
    # Case-insensitive matching
```

### 3. Updated name assignment logic

```python
if not name and remaining_texts:
    for text in remaining_texts:
        if (not self.looks_like_unread_badge(text) and
            not self.looks_like_timestamp(text) and
            not self.looks_like_channel(text) and
            not self.looks_like_filter_header(text)):
            name = text
            break
```

## Files Changed

- `src/wecom_automation/services/ui_parser.py`
  - Added `looks_like_unread_badge()` method
  - Added `looks_like_filter_header()` method
  - Updated `_extract_user_from_row()` third-pass heuristic
  - Updated filter check at end to include filter headers

- `tests/unit/test_ui_parser.py`
  - Added `TestUIParserUnreadBadgeDetection` class (24 test cases)
  - Added `TestUIParserFilterHeaderDetection` class (18 test cases)

## Tests

```bash
# Run specific new tests
uv run pytest tests/unit/test_ui_parser.py -v -k "unread or filter_header"

# All UI parser tests (120 total, all passing)
uv run pytest tests/unit/test_ui_parser*.py -v
```

## Recovery for Affected Databases

Existing corrupted databases need manual cleanup:

```bash
# Option 1: Delete corrupted customers and re-sync
sqlite3 wecom_conversations.db "DELETE FROM customers WHERE name GLOB '[0-9]*' OR name IN ('Internal chats', 'External chats')"

# Option 2: Start fresh
rm wecom_conversations.db
# Then run initial_sync.py again
```

## Related Issues

- This bug was NOT caused by database schema changes (commit 45aea8d)
- All worktrees were at the same git commit with the same schema
