# Voice Message Download & Playback

**Date**: 2025-12-15  
**Status**: ✅ Complete  
**Feature Type**: Core Functionality Enhancement

## Overview

Implemented complete voice message support: inline downloading during conversation extraction, database storage, and UI playback. Voice messages sent from the agent (kefu) to streamers can now be automatically downloaded as WAV audio files and played back in both the Resources browser and Conversation detail views.

## Problem Solved

Voice messages in WeCom don't have a "Save to phone" option like videos do. The long-press menu only shows options like Speaker, Quote, Favorites, Recall, Multiple, and Delete - none of which allow downloading the audio.

## Solution

Voice messages are cached by WeCom in SILK format when played. The solution:

1. **Cache Location**: `/sdcard/Android/data/com.tencent.wework/files/voicemsg/{user_id}/` contains `.silk` files
2. **Trigger Caching**: Click on voice message to play it (caches if not already cached)
3. **Pull SILK File**: Use ADB to pull the cached SILK file from the device
4. **Convert to WAV**: Use `pilk` library to decode SILK to raw PCM, then wrap in WAV container

## Technical Details

### Voice Cache Path

```
/sdcard/Android/data/com.tencent.wework/files/voicemsg/{user_id}/*.silk
```

### SILK to WAV Conversion

- SILK is a codec developed by Skype, used by WeChat/WeCom
- Decodes to raw PCM at 24000 Hz, 16-bit, mono
- `pilk` library handles SILK decoding
- Python `wave` module creates proper WAV container

### File Size Matching

Since voice files are cached without unique identifiers, we match files by expected size:

- SILK files are approximately 1500-2500 bytes per second
- When multiple cached files exist, we select based on duration match

## Implementation

### Core Components

#### 1. Voice Download Method (`_download_voice_inline`)

Located in `src/wecom_automation/services/wecom_service.py`:

```python
async def _download_voice_inline(
    self,
    msg: ConversationMessage,
    voice_dir: Path,
    msg_index: int,
    captured_keys: Set[str],
) -> Optional[str]
```

**Process**:

1. Record existing SILK files in cache
2. Click voice message to trigger playback/caching
3. Find new or matching SILK file (by size/duration)
4. Pull SILK file from device
5. Decode SILK to PCM using pilk
6. Wrap PCM in WAV container
7. Return path to WAV file

#### 2. Model Updates

`ConversationMessage` now includes:

- `voice_local_path: Optional[str]` - Path to downloaded WAV file

`ConversationExtractionResult` now includes:

- `voices_downloaded: int` - Count of successfully downloaded voices
- `voice_count: int` - Total voice messages in conversation

### Usage

```python
result = await service.extract_conversation_messages(
    download_images=True,
    download_videos=True,
    download_voices=True,  # Enable voice download
    output_dir="./output",
)

# Voice files saved to: output/conversation_voices/voice_{index}_{timestamp}.wav
```

When sync is started through the desktop/backend multi-device flow, the default output root is now device-specific:

- `device_storage/<serial>/conversation_voices/`

If a caller explicitly passes `output_root` or `voices_dir`, that explicit path still wins.

### Test Script

Use `test_voice_download.py` to test the feature:

```bash
uv run test_voice_download.py --debug --max-scrolls 10
```

## Dependencies

- `pilk>=0.2.4` - SILK audio decoder (added to project dependencies)

## Limitations

1. **Only agent (kefu) voice messages**: Currently only downloads `is_self=True` voice messages
   - Streamer voice messages are auto-transcribed by WeCom, so audio not needed
2. **Cache-dependent**: Voice must be cached (played at least once) to be downloadable
   - Clicking triggers playback which caches the file
3. **File matching heuristics**: When multiple cached files exist, matching by duration/size is approximate

## Database Storage

Voice file paths are stored in the message's `extra_info` JSON field:

```json
{
  "voice_duration": "2\"",
  "voice_file_path": "device_storage/DEVICE_SERIAL/conversation_voices/customer_42/voice_1_20251215_202557.wav",
  "voice_file_size": 158444,
  "sequence": 0
}
```

The `update_message_extra_info()` repository method merges voice metadata into existing `extra_info` without overwriting other fields.

## Backend API Endpoints

### List Voice Messages

```
GET /resources/voice
```

Returns paginated list of voice messages with conversation context, filtering, and sorting options.

**Response includes**:

- `voice_file_exists`: Boolean indicating if audio file is available
- `voice_file_path`: Relative path to WAV file
- `voice_duration`: Duration string (e.g., "2\"")
- `voice_file_size`: File size in bytes

### Get Voice by Message ID

```
GET /resources/voice/by-message/{message_id}
```

Returns voice metadata for a specific message, used by conversation detail view.

**Response**:

```json
{
  "db_path": "...",
  "message_id": 1,
  "voice": {
    "message_id": 1,
    "file_exists": true,
    "file_path": "device_storage/DEVICE_SERIAL/conversation_voices/customer_42/voice_1_20251215_202557.wav",
    "duration": "2\"",
    "file_size": 158444
  }
}
```

### Serve Voice File

```
GET /resources/voice/{message_id}/file
```

Serves the actual WAV audio file for playback. Returns `audio/wav` content type.

### Delete Voice Message

```
DELETE /resources/voice/{message_id}
```

Deletes voice message record from database (cascades to related records).

## Frontend UI Playback

### Resources View (`/resources?tab=voice`)

**Table View**:

- Voice icon with play button overlay on hover
- Click to play inline audio player modal
- Shows duration and transcription

**Gallery View**:

- Voice cards with play button
- Duration and streamer info
- Click to open audio player modal

### Conversation Detail View (`/conversations/{id}`)

**Voice Message Display**:

- Inline play button with waveform visualization
- Play/Stop toggle (red when playing)
- Duration display with "Playing..." indicator
- Animated waveform bars during playback
- Keyboard support (Escape to stop)

**Features**:

- Auto-fetches voice info for all voice messages on load
- Caches voice info to avoid repeated API calls
- Shows loading state while fetching
- Displays "No audio file" when file doesn't exist

## API Client Methods

Located in `wecom-desktop/src/services/api.ts`:

```typescript
// Get voice info by message ID
async getVoiceByMessageId(messageId: number): Promise<VoiceByMessageResponse>

// Get voice file URL for playback
getVoiceFileUrl(messageId: number): string
```

## Content Security Policy

Audio playback requires CSP to allow media from localhost. The CSP in `index.html` includes:

```
media-src 'self' http://localhost:* blob:
```

This allows audio files served from the backend API.

## Output Format

- **Format**: WAV (RIFF)
- **Sample Rate**: 24000 Hz
- **Bit Depth**: 16-bit
- **Channels**: Mono
- **Filename**: `voice_{msg_index}_{timestamp}.wav`
- **Storage**: `{output_dir}/conversation_voices/`

## Known Issues & Fixes

### Issue: Voice file paths not saved to database

**Status**: ✅ Fixed  
**Solution**: Added `update_message_extra_info()` method to `ConversationRepository` to merge voice metadata into message `extra_info` field.

### Issue: "No audio file" shown even when files exist

**Status**: ✅ Fixed  
**Solution**: Updated database records with correct `voice_file_path` values. Future syncs will automatically save paths via `_save_message_voice()` method.

### Issue: Backend API missing `json` import

**Status**: ✅ Fixed  
**Solution**: Added `import json` to `resources.py` to fix 500 errors when parsing `extra_info`.

### Issue: Voice transcription timeout

**Status**: ✅ Fixed (2025-12-16)  
**Solution**: Fixed wrong API response path (`resp.text` → `result.text`) and replaced blocking `time.sleep()` with async `asyncio.sleep()`. See [Voice Transcription Timeout Bug](../04-bugs-and-fixes/fixed/2025/12-16-voice-transcription-timeout.md).

## Voice Transcription

Voice messages can be transcribed to text using the Volcengine ASR (Automatic Speech Recognition) API.

### Configuration

Configure Volcengine ASR in Settings → 🎤 Volcengine ASR Settings:

- **Enabled**: Toggle transcription feature on/off
- **API Key**: Your Volcengine ASR API key (UUID format)
- **Resource ID**: `volc.seedasr.auc` (default)
- **Test Button**: Verify API connection before use

### Transcription Flow

1. Click ✍️ button in voice message actions column
2. Backend reads WAV file and encodes to base64
3. Submits to Volcengine ASR submit endpoint
4. Polls query endpoint until transcription complete
5. Updates message `content` field with transcribed text
6. UI refreshes to show transcription

### API Endpoints

```
POST /resources/voice/{message_id}/transcribe
```

Transcribes a voice message using Volcengine ASR.

### Related Documentation

- [Volcengine ASR Test Button](2025-12-16-volcengine-asr-test-button.md) - Test API connection
- [Voice Transcription Timeout Bug](../04-bugs-and-fixes/fixed/2025/12-16-voice-transcription-timeout.md) - Bug fix details
