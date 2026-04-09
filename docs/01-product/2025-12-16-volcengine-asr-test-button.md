# Volcengine ASR Test Button

> **Date**: 2025-12-16
> **Status**: ✅ Complete
> **Related**: Voice Transcription Feature, Settings Page

## Summary

Added a "Test Connection" button to the Volcengine ASR settings section that allows users to verify their API credentials are working before using the transcription feature.

## Problem

Users had no way to verify if their Volcengine ASR API configuration was correct without attempting to transcribe an actual voice message. This led to confusion when transcription failed due to invalid credentials.

## Solution

### Backend Changes (`routers/settings.py`)

Added a new endpoint `POS../03-impl-and-arch/key-modules/volcengine-asr/test` that:

1. Reads the configured Volcengine ASR settings (API key, resource ID)
2. Submits a test audio (uses Volcengine's sample audio URL) to the ASR API
3. Polls the query endpoint for transcription results
4. Returns the test result with latency info and a sample transcription

```python
class VolcengineAsrTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: Optional[int] = None
    transcription: Optional[str] = None

@router.post../03-impl-and-arch/key-modules/volcengine-asr/test", response_model=VolcengineAsrTestResponse)
async def test_volcengine_asr():
    # Tests connection using sample audio URL from Volcengine docs
    # Returns success/failure with transcription result
```

### Frontend Changes (`SettingsView.vue`)

Added test functionality:

- `testVolcengineConnection()` - Makes the test request to the backend
- `volcengineTestLoading` - Shows loading state (⏳) while testing
- `volcengineTestResult` - Displays success/failure message with transcription snippet

```vue
<!-- Test Connection -->
<div class="flex items-center justify-between bg-wecom-surface/50 rounded-lg px-4 py-3">
  <div class="flex items-center gap-2 flex-1">
    <span class="text-sm text-wecom-text">Test ASR Connection</span>
    <span v-if="volcengineTestResult"
          :class="volcengineTestResult.success ? 'text-green-400' : 'text-red-400'">
      {{ volcengineTestResult.message }}
    </span>
  </div>
  <button class="btn-secondary text-sm" @click="testVolcengineConnection">
    <span v-if="volcengineTestLoading" class="animate-spin">⏳</span>
    <span v-else>🔌</span>
    Test
  </button>
</div>
```

## Test Audio

The test uses a public sample audio URL from [Volcengine's ASR documentation](https://www.volcengine.com/docs/6561/1354868):

- URL: `https://lf3-static.bytednsdoc.com/obj/eden-cn/lm_hz_ihsph/ljhwZthlaukjlkulzlp/console/bigtts/zh_female_cancan_mars_bigtts.mp3`
- A short Chinese audio clip that the API transcribes to verify connectivity

## UI Behavior

| State   | Display                                                     |
| ------- | ----------------------------------------------------------- |
| Idle    | Button shows `🔌 Test`                                      |
| Loading | Button shows `⏳ Test` (disabled)                           |
| Success | Green message: `Connected! (Xms) - "transcription text..."` |
| Failure | Red message: Error description                              |

## Files Modified

- `wecom-desktop/backend/routers/settings.py` - Added test endpoint
- `wecom-desktop/src/views/SettingsView.vue` - Added test button UI

## Testing

1. Navigate to Settings page
2. Scroll to "🎤 Volcengine ASR Settings" section
3. Click "🔌 Test" button
4. Verify connection result appears next to button
