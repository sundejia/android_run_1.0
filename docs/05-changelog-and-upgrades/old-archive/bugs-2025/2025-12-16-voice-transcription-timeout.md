# Voice Transcription Timeout Bug

> **Date**: 2025-12-16
> **Status**: ✅ Fixed
> **Severity**: High
> **Component**: Backend - Voice Transcription API

## Symptoms

- Voice transcription for 2-3 second audio files would timeout after 60 seconds
- Error message: "Transcription timed out. Please try again."
- The Volcengine ASR "Test" button worked fine (using URL-based audio)
- Direct API testing with the same audio files worked perfectly

## Root Cause

Two bugs in `routers/resources.py`:

### Bug 1: Wrong Response Path

The code was checking the wrong path in the Volcengine API response:

```python
# WRONG: API returns result.text, not resp.text
resp = query_result.get("resp", {})
if resp.get("text"):
    transcription = resp["text"]
```

The actual Volcengine API response structure:

```json
{
  "audio_info": { "duration": 3299 },
  "result": {
    "text": "能听到我的消息吗？你好。"
  }
}
```

### Bug 2: Blocking Sleep in Async Function

The code used `time.sleep()` which blocks the entire async event loop:

```python
# WRONG: Blocks the async event loop
for attempt in range(max_attempts):
    time.sleep(poll_interval)  # <-- Blocking call!
    query_response = await client.post(...)
```

## Fix Applied

### Fix 1: Correct Response Path

```python
# CORRECT: Check result.text
result = query_result.get("result", {})
if result.get("text"):
    transcription = result["text"]
```

### Fix 2: Async Sleep

```python
import asyncio

# CORRECT: Non-blocking async sleep
for attempt in range(max_attempts):
    await asyncio.sleep(poll_interval)  # <-- Non-blocking
    query_response = await client.post(...)
```

### Fix 3: Updated Error Code Handling

Updated to match Volcengine API documentation:

- Code `20000000`: Success
- Code `20000001`: Still processing
- Code `20000002`: Task in queue

```python
# Check for error codes
code = query_result.get("code")
if code and code not in [0, 20000000, 20000001, 20000002]:
    raise HTTPException(
        status_code=500,
        detail=f"ASR API query error: {query_result.get('message', 'Unknown error')} (code: {code})",
    )
```

## Verification

Direct API test with actual voice file:

```python
# Test result - works immediately on first poll!
Audio size: 158444 bytes
Request ID: 494471a2-def5-4864-83e7-7935a9520886

--- Submitting ---
Status: 200
Response: {}

--- Polling ---
Attempt 1: {"audio_info": {"duration": 3299}, "result": {"text": "能听到我的消息吗？你好。"}}

✅ SUCCESS: 能听到我的消息吗？你好。
```

## Files Modified

- `wecom-desktop/backend/routers/resources.py`
  - Added `import asyncio`
  - Changed `resp = query_result.get("resp", {})` to `result = query_result.get("result", {})`
  - Changed `time.sleep(poll_interval)` to `await asyncio.sleep(poll_interval)`
  - Updated error code handling for Volcengine API codes

## Testing Steps

1. Navigate to Resources → Voice tab
2. Click ✍️ (transcribe) button on any voice message
3. Wait ~2-5 seconds for transcription to complete
4. Verify transcribed text appears in the Content column

## Tested Results

| Voice   | Duration | Transcription              |
| ------- | -------- | -------------------------- |
| Voice 1 | 2 sec    | 能听到我的消息吗？你好。   |
| Voice 2 | 3 sec    | 你好啊，能收到我的消息吗？ |

## Lessons Learned

1. Always verify API response structure against documentation
2. Never use `time.sleep()` in async functions - use `await asyncio.sleep()`
3. When a test passes but production fails, check for differences in implementation (URL vs base64 audio)
