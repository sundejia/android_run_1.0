# MessageTracker Logging Enhancement

> Date: 2026-02-03
> Status: ✅ Complete

## Summary

Enhanced the `MessageTracker` class in `response_detector.py` with comprehensive logging capabilities to improve debugging and observability of message detection and deduplication logic.

## Changes Made

### 1. Device-Specific Logging

**Before**: `MessageTracker` had no device context in logs
**After**: Added `serial` parameter to identify device in log messages

```python
# Before
def __init__(self, max_history: int = 500):
    ...

# After
def __init__(self, max_history: int = 500, serial: str = ""):
    self.serial = serial  # Device serial for logging
    self._logger = logging.getLogger("followup.message_tracker")
```

### 2. Separate Log File

Created dedicated log file for MessageTracker to isolate message detection logs from general followup logs.

**Log File**: `lo../03-impl-and-arch/message_tracker.log`

**Configuration**:

- Time-based rotation: Daily (midnight)
- Encoding: UTF-8
- Format: `YYYY-MM-DD HH:MM:SS | LEVEL | Message`
- No backup retention (0 days)

### 3. Comprehensive Message Detection Logging

Added detailed logging at each step of `find_new_customer_messages()`:

#### A. Initial State Logging

```
========== 消息检测开始 ==========
当前提取到 N 条消息:
  [0] [KEFU] text: 你好，请问有什么可以帮...
  [1] [CUST] text: 我想咨询一下产品价格...
  ...
已缓存消息数: M, 已处理签名数: K
```

#### B. Anchor Detection

```
锚点位置: 5 (内容: 好的，谢谢)
```

#### C. Message Processing

```
[6] 新消息缓存 is_self=False: 这个产品怎么样...
[6] ✅ 新客户消息: 这个产品怎么样
```

#### D. Skipped Messages

```
被跳过的消息 (3 条):
  [3] 好的 - 原因: 简单签名已存在且不在末尾 (cached_is_self=True, current_is_self=True)
  [4] 收到 - 原因: 完整签名已存在 (cached_is_self=False)
```

#### E. is_self Inconsistency Detection

```
WARNING: [8] is_self 不一致! cached=True, current=False, 使用缓存值. 内容: 再见
```

#### F. Final Results

```
========== 检测结果 ==========
新客户消息: 2 条
  [NEW-0] 这个产品怎么样
  [NEW-1] 有优惠吗
========== 消息检测结束 ==========
```

### 4. Cache Management Logging

Added logging for cache operations:

```python
# New cache entries
self._logger.info(f"{prefix} record_current_state: {len(messages)} msgs, "
                  f"新缓存 {new_cached_count} 条, 总缓存 {len(self.is_self_cache)} 条")

# Cache cleanup
self._logger.info(f"{prefix} 清理历史记录，保留 {len(self.processed_signatures)} 条签名")
```

## Log File Structure

```
lo../03-impl-and-arch/
├── followup.log              # Main followup service logs
└── message_tracker.log       # MessageTracker detection logs (NEW)
```

## Log Message Format

Each log entry includes:

1. **Timestamp**: `YYYY-MM-DD HH:MM:SS`
2. **Device Prefix**: `[DEVICE123]` or `[Tracker]` if no serial
3. **Level**: `INFO`, `WARNING`, `DEBUG`
4. **Message Content**: Contextual information

### Example Output

```
2026-02-03 14:30:15 | INFO     | [DEVICE123] ========== 消息检测开始 ==========
2026-02-03 14:30:15 | INFO     | [DEVICE123] 当前提取到 5 条消息:
2026-02-03 14:30:15 | INFO     | [DEVICE123]   [0] [KEFU] text: 你好...
2026-02-03 14:30:15 | INFO     | [DEVICE123]   [1] [CUST] text: 我想咨询...
2026-02-03 14:30:15 | INFO     | [DEVICE123] 已缓存消息数: 10, 已处理签名数: 8
2026-02-03 14:30:15 | INFO     | [DEVICE123] 锚点位置: 3 (内容: 好的)
2026-02-03 14:30:15 | INFO     | [DEVICE123]   [4] 新消息缓存 is_self=False: 请问有优惠吗
2026-02-03 14:30:15 | INFO     | [DEVICE123]   [4] ✅ 新客户消息: 请问有优惠吗
2026-02-03 14:30:15 | INFO     | [DEVICE123] ========== 检测结果 ==========
2026-02-03 14:30:15 | INFO     | [DEVICE123] 新客户消息: 1 条
2026-02-03 14:30:15 | INFO     | [DEVICE123] ========== 消息检测结束 ==========
```

## Key Features

### 1. is_self Inconsistency Detection

The system now detects when a message's `is_self` value differs between cache and current extraction:

```python
if cached_is_self != current_is_self:
    self._logger.warning(
        f"{prefix}   [{i}] is_self 不一致! cached={cached_is_self}, current={current_is_self}, "
        f"使用缓存值. 内容: {content}"
    )
```

This helps identify:

- Message parsing issues
- Race conditions in message extraction
- UI state inconsistencies

### 2. Skip Reason Tracking

Every skipped message now includes a clear reason:

- **简单签名已存在且不在末尾**: Duplicate content not in tail region
- **完整签名已存在**: Exact signature match found
- **末尾区域新消息**: Same content in tail (within 2 messages of end)

### 3. Device Context

All logs include device serial number prefix, enabling:

- Multi-device debugging
- Per-device log analysis
- Device-specific issue identification

## Benefits

### For Debugging

1. **Full Visibility**: See every message processed and why
2. **Trace Decisions**: Understand why messages were detected or skipped
3. **Identify Issues**: is_self inconsistencies are explicitly logged
4. **Performance Analysis**: Track cache size and cleanup operations

### For Development

1. **Easier Testing**: Verify message detection logic works correctly
2. **Regression Prevention**: Compare logs across versions
3. **Issue Isolation**: Separate MessageTracker logs from general followup logs

### For Operations

1. **Troubleshooting**: Quick access to detailed message detection flow
2. **Audit Trail**: Complete history of message detection decisions
3. **Multi-Device**: Clear separation of logs per device

## Usage

### Viewing Logs

```bash
# View MessageTracker logs
tail -f lo../03-impl-and-arch/message_tracker.log

# View specific device
grep "[DEVICE123]" lo../03-impl-and-arch/message_tracker.log

# View inconsistencies
grep "is_self 不一致" lo../03-impl-and-arch/message_tracker.log

# View new customer messages
grep "✅ 新客户消息" lo../03-impl-and-arch/message_tracker.log
```

### Log Levels

| Level   | Usage                                        |
| ------- | -------------------------------------------- |
| INFO    | Normal operations, message detection results |
| WARNING | is_self inconsistencies                      |
| DEBUG   | Detailed state (cache size, etc.)            |

## Integration with Existing Logging

The MessageTracker logging integrates with the existing followup logging system:

1. **Same Directory**: Logs stored in `lo../03-impl-and-arch/`
2. **Consistent Format**: Similar timestamp and level format
3. **Unified Rotation**: Both use daily rotation
4. **WebSocket Streaming**: Available via `/ws/logs/{serial}` endpoint

## Related Documentation

- [FollowUp Logging Enhancement](./followup-logging-enhancement.md) - Main followup logging
- [FollowUp System Logic](./followup-system-logic.md) - System architecture
- [Message Deduplication](../04-bugs-and-fixes/fixed/2025/01-07-message-deduplication-bug.md) - Deduplication logic

## Files Modified

| File                                                                   | Changes                                      | Lines |
| ---------------------------------------------------------------------- | -------------------------------------------- | ----- |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | Added serial param, logger, detailed logging | ~150  |

**Total**: ~150 lines added/modified

## Testing Checklist

- [x] Code syntax validated
- [x] Log file created successfully
- [x] Device serial appears in logs
- [x] Message detection logs are complete
- [x] is_self inconsistencies are detected
- [ ] Test with real device
- [ ] Verify log rotation works
- [ ] Test with multiple devices

## Future Enhancements

1. **Structured Logging**: JSON format for log aggregation
2. **Metrics Export**: Prometheus metrics for message detection
3. **Log Analysis**: Automated analysis of patterns
4. **Dashboard Integration**: Real-time visualization of detection stats
