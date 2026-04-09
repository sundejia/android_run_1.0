# Follow-up Message Deduplication Feature

**Implemented**: 2026-02-06

## Overview

This feature prevents sending duplicate message templates to the same customer during follow-up attempts. When enabled, the system tracks which templates have been sent to each customer and avoids re-sending them in subsequent follow-ups.

## Key Features

- **Deduplication Logic**: Tracks sent message templates per customer and filters them out in future follow-ups
- **Minimum Template Requirement**: Feature can only be enabled when there are 3+ message templates
- **Automatic Cleanup**: Clears all tracking records when message templates are modified
- **AI Compatibility**: AI-generated messages are not tracked in the deduplication system
- **Graceful Degradation**: Falls back to random selection if deduplication fails

## User Interface

### Settings Panel (Follow-up Management)

A new checkbox option "不使用重复话术补刀" (Avoid Duplicate Follow-ups) has been added below the Message Templates section.

**Behavior**:

- ✅ **Enabled** when `message_templates.length >= 3`
- ❌ **Disabled** (grayed out) when `message_templates.length < 3`
- Shows warning: "至少需要3个消息模板" (Requires at least 3 message templates)

## How It Works

### Without Deduplication (Original Behavior)

```
Templates: ["A", "B", "C", "D", "E"]
Customer receives follow-ups:
  Attempt 1: Random selection → "B"
  Attempt 2: Random selection → "B" ❌ Duplicate!
  Attempt 3: Random selection → "A"
```

### With Deduplication (New Behavior)

```
Templates: ["A", "B", "C"]
Customer receives follow-ups:
  Attempt 1: Available ["A", "B", "C"] → Selected "B" → Record {"B"}
  Attempt 2: Available ["A", "C"] (B filtered) → Selected "A" → Record {"B", "A"}
  Attempt 3: Available ["C"] (A, B filtered) → Selected "C" → Record {"B", "A", "C"}
```

### Template Modification

When message templates are modified (added, removed, or changed):

1. System calculates new template hash
2. Detects change by comparing with old hash
3. Clears **ALL** tracking records in `followup_sent_messages` table
4. Future follow-ups start fresh with new templates

## Technical Implementation

### Database Schema

**Table**: `followup_sent_messages`

```sql
CREATE TABLE followup_sent_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    message_template TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(device_serial, customer_name, message_template)
);

CREATE INDEX idx_followup_sent_messages_lookup
ON followup_sent_messages(device_serial, customer_name);
```

**Purpose**: Track which message templates have been sent to each customer

### Key Components

#### 1. FollowupSentMessagesRepository

**File**: `wecom-desktop/backend/services/followup/sent_messages_repository.py`

**Methods**:

- `get_sent_templates(device_serial, customer_name) → Set[str]` - Get sent templates for a customer
- `record_sent_message(device_serial, customer_name, message_template)` - Record a sent template
- `clear_all() → int` - Clear all tracking records (template change)

#### 2. Settings Model Updates

**Files**:

- `wecom-desktop/backend/services/settings/models.py` - Added `avoid_duplicate_messages: bool = False` field
- `wecom-desktop/backend/services/followup/settings.py`

#### 3. API Router Updates

**File**: `wecom-desktop/backend/routers/followup_manage.py`

**Changes**:

- Added `avoidDuplicateMessages: bool = False` to `FollowUpSettingsModel`
- Added `avoidDuplicateMessages` field to `get_followup_settings()` response
- Added `avoid_duplicate_messages` to `update_followup_settings()` request handler

**Purpose**: Expose the deduplication setting via REST API for frontend integration

**New Fields**:

- `avoid_duplicate_messages: bool = False` - Enable/disable deduplication
- `templates_hash: str = ""` - Hash for change detection

**New Function**:

```python
def calculate_templates_hash(templates: list[str]) -> str:
    """Calculate hash for template change detection"""
    normalized = json.dumps(sorted(templates), ensure_ascii=False)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]
```

#### 3. Message Selection Logic

**File**: `wecom-desktop/backend/services/followup/queue_manager.py`

**Modified Method**: `_generate_message()`

- Added check for `avoid_duplicate_messages` setting
- Routes to `_generate_unique_message()` when enabled

**New Method**: `_generate_unique_message()`

- Queries sent templates from repository
- Filters out already-sent templates
- Random selection from remaining
- Defensive fallback (should never be needed with 3+ templates)

#### 4. Recording Sent Messages

**File**: `wecom-desktop/backend/services/followup/queue_manager.py`

**Location**: `execute_pending_followups()` method

**Logic**:

```python
if result.status == FollowupStatus.SUCCESS:
    # ... existing code ...

    # Record sent template for deduplication
    if settings.avoid_duplicate_messages and not settings.use_ai_reply:
        sent_repo.record_sent_message(device_serial, customer_name, message)
```

#### 5. Frontend UI

**File**: `wecom-desktop/src/views/FollowUpManageView.vue`

**Changes**:

- Added `avoidDuplicateMessages: false` to settings object
- Added checkbox UI component below Message Templates list
- Checkbox disabled when `followupMessageTemplates.length < 3`
- Added warning message when disabled

## Design Constraints

### Why Minimum 3 Templates?

With `max_attempts_per_customer = 3`:

- 3 templates × 3 attempts = Perfect match
- Guarantees no duplicate messages
- No exhaustion scenario possible

### Why Clear All on Template Change?

**Settings are global** (per-backend, not per-device):

- All devices share the same templates
- When templates change, all devices should reset tracking
- Simpler than trying to track which templates were removed/modified

### Data Model Considerations

**Two Separate Tables**:

1. `followup_attempts.current_attempt` - Counts follow-up attempts (1, 2, 3...)
   - Does NOT reset on template change
   - Controls when customer reaches max_attempts

2. `followup_sent_messages` - Tracks which templates were sent
   - DOES reset on template change
   - Controls which messages are available for selection

**Example**:

```
Customer has 2 attempts sent, templates modified:
  followup_attempts.current_attempt = 2 (unchanged)
  followup_sent_messages = {} (cleared)

Attempt 3:
  → Selects from NEW templates (fresh start)
  → current_attempt becomes 3
  → Customer completes (no more follow-ups)
```

✅ **No extra follow-up opportunities** - still limited by `max_attempts`

## Usage

### Enabling the Feature

1. Open "Follow-up Management" page
2. Go to "Settings" tab
3. Scroll to "Message Templates" section
4. Add at least 3 message templates
5. Check "不使用重复话术补刀" checkbox
6. Click "Save Settings"

### Expected Behavior

- **First follow-up**: Random template from all 3+
- **Second follow-up**: Random template from remaining (excludes first)
- **Third follow-up**: Last remaining template
- **After template change**: Fresh start with new templates

## Testing

### Unit Tests

**File**: `wecom-desktop/backend/tests/test_sent_messages_repository.py`

**Test Coverage**:

- ✅ Table creation and schema validation
- ✅ Basic CRUD operations
- ✅ UNIQUE constraint enforcement
- ✅ Hash calculation correctness
- ✅ Settings field integration

### Manual Testing Checklist

- [ ] Checkbox appears below Message Templates
- [ ] Checkbox disabled with 0, 1, 2 templates
- [ ] Checkbox enabled with 3+ templates
- [ ] Enable feature and save settings
- [ ] Trigger follow-up for test customer
- [ ] Verify first message sent (check database)
- [ ] Trigger second follow-up → different message
- [ ] Trigger third follow-up → different message
- [ ] Modify templates → verify tracking cleared
- [ ] Disable feature → verify random behavior returns
- [ ] Check logs for proper debugging output

## Future Enhancements

Possible improvements for future versions:

1. **Statistics Dashboard**: Show which templates are most/least effective
2. **Per-Customer Customization**: Allow manual template exclusion
3. **Smart Ordering**: Learn from response rates to prioritize templates
4. **A/B Testing**: Compare deduplication vs random performance

## Related Files

- **Implementation**: `openspec/changes/add-followup-unique-messages/`
- **Design**: `openspec/changes/add-followup-unique-messages/design-simplified.md`
- **Tasks**: `openspec/changes/add-followup-unique-messages/tasks-simplified.md`
- **Review**: `openspec/changes/add-followup-unique-messages/DESIGN_REVIEW.md`

## Migration Notes

### Database Migration

The `followup_sent_messages` table is automatically created on first run by `FollowupSentMessagesRepository._ensure_tables()`. No manual migration needed.

### Settings Migration

Existing settings will work with default values:

- `avoid_duplicate_messages`: `false` (disabled by default)
- `templates_hash`: `""` (calculated on first save)

Users need to manually enable the feature after upgrade.

## Performance Impact

**Minimal**:

- Additional query per follow-up: `SELECT ... WHERE device_serial = ? AND customer_name = ?`
- Index on `(device_serial, customer_name)` ensures fast lookup
- Expected overhead: <10ms per follow-up

**Storage**:

- ~100 bytes per record
- 1000 customers × 3 templates = ~15 MB/year
- Negligible impact

## Troubleshooting

### Checkbox Grayed Out

**Cause**: Less than 3 message templates configured

**Solution**: Add at least 3 templates in Message Templates list

### Still Seeing Duplicates

**Possible Causes**:

1. Feature was enabled after some follow-ups were already sent
   - **Solution**: Templates are tracked from enablement onwards
2. Templates were modified recently
   - **Solution**: Tracking was cleared, fresh start
3. AI Reply mode is on
   - **Solution**: Deduplication doesn't apply to AI messages

### Hash Calculation Errors

If you see hash-related errors:

1. Check templates are valid strings
2. Verify JSON serialization works
3. Check for encoding issues

## Summary

This feature improves customer experience by ensuring they receive unique, varied follow-up messages instead of repetitive templates. It's particularly valuable when:

- Using the minimum 3 templates
- Running multiple follow-up campaigns
- Maintaining professional communication with customers

The implementation is simple, efficient, and maintains backward compatibility.
