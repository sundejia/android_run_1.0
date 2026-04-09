# AI Reply Recording Bug

> **Date**: 2025-12-10
> **Status**: ✅ Fixed
> **Component**: `sync_service.py`, `initial_sync.py`, `wecom_service.py`

## Symptoms

- Database records show mock "测试信息" messages instead of actual AI-generated replies
- AI server generates and sends correct replies to customers
- Sidecar UI shows the correct AI reply being sent
- But database stores the original mock message template

Example:

```
Actual sent:     "宝子~[表情] 上次的消息是不是被淹没啦？TT老师又来戳戳你啦！[可爱]..."
Recorded in DB:  "测试信息: 想的怎么样了?"
```

## Root Cause

The issue was in the message flow architecture:

1. `sync_service.py` creates a mock message: `test_message = "测试信息: 想的怎么样了?"`
2. Calls `send_message(test_message)` which is monkey-patched to `sidecar_send_message`
3. `sidecar_send_message` gets AI reply and sends `final_message` (AI reply)
4. **BUG**: `send_message` returns `bool` (success only), not the actual message sent
5. `sync_service.py` stores `test_message` (the original mock), not `final_message` (AI reply)

```python
# The problematic flow
success = await self.wecom.send_message(test_message)  # Returns bool
if success:
    test_record = MessageRecord(content=test_message)  # Stores MOCK, not AI reply!
```

## Solution

Changed `send_message` return type from `bool` to `Tuple[bool, str]`:

- First element: success status
- Second element: actual message that was sent

### Changes Made

#### 1. `wecom_service.py` - Base method

```python
async def send_message(self, text: str) -> Tuple[bool, str]:
    """Returns (success, actual_message_sent)."""
    # ... implementation ...
    return True, text  # Normal mode returns input text
```

#### 2. `initial_sync.py` - Sidecar mode

```python
async def sidecar_send_message(message: str) -> Tuple[bool, str]:
    final_message = message
    if ai_service:
        ai_reply = await ai_service.get_ai_reply(message, serial)
        if ai_reply:
            final_message = ai_reply
    # ... send to sidecar ...
    return True, final_message  # Returns AI reply!
```

#### 3. `sync_service.py` - Database storage

```python
success, actual_message = await self.wecom.send_message(test_message)
if success:
    test_record = MessageRecord(content=actual_message)  # Now stores AI reply!
```

#### 4. `backend/routers/sidecar.py` - Backend handler

```python
async def send_message(self, text: str) -> bool:
    success, _ = await self.service.send_message(text)  # Unpack tuple
    return success
```

## Files Changed

- `src/wecom_automation/services/wecom_service.py`
  - Changed `send_message()` return type to `Tuple[bool, str]`

- `initial_sync.py`
  - Updated `sidecar_send_message()` to return `Tuple[bool, str]`

- `src/wecom_automation/services/sync_service.py`
  - Updated `_send_test_message_and_wait()` to use returned actual message
  - Updated `_wait_and_process_responses()` to use returned actual message

- `wecom-desktop/backend/routers/sidecar.py`
  - Updated `SidecarSession.send_message()` to unpack tuple

- `wecom-desktop/backend/tests/test_sidecar_priority.py`
  - Updated `FakeWeComService.send_message()` to return tuple

## Tests

```bash
# All unit tests pass
uv run pytest tests/unit/ -v  # 364 passed

# Backend tests pass
cd wecom-desktop/backend && python -m pytest tests/ -v  # 23 passed
```

## Impact

- When AI reply is enabled (`--use-ai-reply`), database now correctly stores the AI-generated message
- Sidecar conversation history will show accurate sent messages
- Analytics and reporting will reflect actual content sent to customers
