# Extraction Fingerprint Deduplication Bug

> **Date**: 2025-12-11
> **Status**: ✅ Fixed
> **Component**: `wecom_service.py`, `config.py`, `sync_service.py`

## Symptoms

- Message extraction missing identical messages sent at different times
- Conversations with repeated content (like "测试信息: 想的怎么样了?") only extract ~8 messages instead of ~41
- Extraction stops prematurely, hitting "reached end of conversation" too early
- Log shows `stable_threshold` triggered after just 2 passes with no new messages

Example from sdj conversation:

```
Expected messages: ~41
Extracted messages: 8

Log shows:
[INFO] Extraction pass 0 - overlap=0, added=7, total=7
[INFO] Extraction pass 1 - overlap=5, added=1, total=8
[INFO] Extraction pass 2 - overlap=6, no new messages
[INFO] Extraction complete - reached end of conversation  ← WRONG!
```

## Root Cause

Two related issues:

### Issue 1: Fingerprint Missing Timestamp

The message fingerprint used for deduplication was `(is_self, message_type, content[:100])` which **did not include the timestamp**:

```python
def get_fingerprint(msg: ConversationMessage) -> Tuple[bool, str, str]:
    content = (msg.content or "")[:100]
    return (msg.is_self, msg.message_type, content)  # NO TIMESTAMP!
```

This caused all identical messages (like "测试信息: 想的怎么样了?" sent on different days) to have the same fingerprint and be incorrectly deduplicated.

### Issue 2: Stable Threshold Too Low

The `stable_threshold=2` meant extraction stopped after just 2 consecutive scrolls with no new messages. But isolated "no new messages" scrolls can happen in the middle of long conversations (e.g., when scrolling past a long message).

### Issue 3: Max Scrolls Override

`sync_service.py` was passing `max_scrolls=self.config.scroll.max_scrolls` (20) which overrode the intended high default (500).

## Solution

### 1. Include Timestamp in Fingerprint

Changed fingerprint to include timestamp:

```python
# wecom_service.py
def get_fingerprint(msg: ConversationMessage) -> Tuple[bool, str, str, str]:
    """Include timestamp to differentiate identical messages sent at different times."""
    content = (msg.content or "")[:100]
    timestamp = msg.timestamp or ""
    return (msg.is_self, msg.message_type, timestamp, content)
```

### 2. Increase Stable Threshold

Changed `stable_threshold` from 2 to 4:

```python
# config.py
stable_threshold: int = 4  # Stop after N consecutive scrolls with no new items
```

### 3. Remove Max Scrolls Override

Removed explicit `max_scrolls` parameter from sync_service to use default 500:

```python
# sync_service.py - BEFORE
result = await self.wecom.extract_conversation_messages(
    max_scrolls=self.config.scroll.max_scrolls,  # Was 20!
    download_images=False,
)

# sync_service.py - AFTER
result = await self.wecom.extract_conversation_messages(
    download_images=False,
)  # Now uses default 500
```

## Files Changed

- `src/wecom_automation/services/wecom_service.py`
  - Changed fingerprint from `(is_self, type, content)` to `(is_self, type, timestamp, content)`
  - Updated type hints for fingerprint tuples
  - Added log message for extraction safety limit

- `src/wecom_automation/core/config.py`
  - Changed `stable_threshold` default from 2 to 4
  - Updated env default for `WECOM_STABLE_THRESHOLD`

- `src/wecom_automation/services/sync_service.py`
  - Removed `max_scrolls` parameter from `extract_conversation_messages()` call

- `tests/unit/test_config.py`
  - Updated test expectation for `stable_threshold` from 2 to 4

## Tests

```bash
# All unit tests pass
uv run pytest tests/unit/ -v  # 391 passed
```

Debug extraction verified:

```
# Before fix
Total messages extracted: 23 (many "测试信息" deduplicated)

# After fix
Total messages extracted: 41 (all messages preserved)
```

## Impact

- Conversations with repeated messages (common in customer service) now extract correctly
- Long conversations no longer stop prematurely
- Identical messages sent at different times are properly preserved
- More robust end-of-conversation detection (4 consecutive empty scrolls vs 2)
