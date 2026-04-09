# 补刀 Skip 处理重构

> 文档创建：2026-02-05
> 状态：已实现

## 背景

在补刀（FollowUp）系统的实时回复检测中，当用户点击 Sidecar 的 Skip 按钮时，需要：

1. 跳过当前用户
2. 返回用户列表（私聊列表）
3. 继续处理下一个用户

**原有实现的问题**：

- Skip 处理逻辑分散在多个位置
- 每个位置都调用 `go_back()`，可能导致重复返回
- Skip flag 清理逻辑重复
- 难以维护和调试

## 重构方案

### 核心思想

**集中式 Skip 处理**：通过异常机制（`SkipRequested`）将 Skip 请求冒泡到顶层统一处理，确保：

- Skip 只处理一次（只调用一次 `go_back()`）
- Skip flag 尽早清理
- 代码逻辑更清晰

### 实现

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

#### 1. 新增 SkipRequested 异常类

```python
class SkipRequested(Exception):
    """Raised internally to stop processing and handle skip once."""
```

**作用**：

- 作为内部异常，用于中断处理流程
- 明确标识这是 Skip 请求而非普通错误
- 便于统一捕获和处理

#### 2. 新增 \_handle_skip_once() 方法

```python
async def _handle_skip_once(self, wecom, serial: str, sidecar_client: Any | None) -> None:
    """
    Handle skip request exactly once, avoiding double go_back.

    Behavior:
    - Clear skip flag early (so subsequent loops won't re-handle it)
    - Only call go_back when we're actually in a chat screen
    """
    # Clear skip flag early to prevent duplicate handling
    if sidecar_client:
        try:
            await sidecar_client.clear_skip_flag()
            self._logger.debug(f"[{serial}] ✅ Skip flag cleared")
        except Exception as e:
            self._logger.warning(f"[{serial}] ⚠️ Failed to clear skip flag: {e}")

    # Only go back if we are in a chat screen (prevents backing out from list screens)
    try:
        screen = await wecom.get_current_screen()
    except Exception as e:
        self._logger.debug(f"[{serial}] Screen detection failed during skip handling: {e}")
        screen = None

    if screen == "chat":
        try:
            await wecom.go_back()
            await asyncio.sleep(0.5)
        except Exception as e:
            self._logger.warning(f"[{serial}] Error during go_back (skip handling): {e}")
```

**关键改进**：

1. **尽早清理 Skip flag**：防止后续循环重复处理
2. **屏幕检测**：只在聊天屏幕时才调用 `go_back()`
   - 避免在列表屏幕时误返回
   - 防止退回到主屏幕
3. **统一日志**：集中记录 Skip 处理日志

#### 3. Skip 请求点改造

**改造点 1：主循环检测 Skip**

```python
# 原代码
if skip_requested:
    self._logger.info(f"[{serial}] ⏭️ Skip requested - clearing queue and returning to chat list")
    user_queue.clear()
    try:
        await wecom.go_back()
        await asyncio.sleep(0.5)
        if client:
            try:
                await client.clear_skip_flag()
                ...
            except Exception as e:
                ...
    except Exception as e:
        ...
    break

# 新代码
if skip_requested:
    self._logger.info(f"[{serial}] ⏭️ Skip requested - clearing queue and returning to chat list")
    user_queue.clear()  # Clear remaining queue
    await self._handle_skip_once(wecom, serial, client)
    break  # Exit while loop
```

**改造点 2：用户处理异常捕获**

```python
try:
    # 处理用户...
    await self._process_unread_user_with_wait(...)

except SkipRequested:
    # Centralized skip handling (avoid double go_back)
    self._logger.info(f"[{serial}] ⏭️ Skip requested during user processing - stopping scan")
    user_queue.clear()
    await self._handle_skip_once(wecom, serial, client)
    break
except Exception as e:
    self._logger.error(f"[{serial}] Error processing {user_name}: {e}")
    ...
```

**改造点 3：AI 回复前 Skip 检测**

```python
# 原代码
if await sidecar_client.is_skip_requested():
    self._logger.info(f"[{serial}] ⏭️ Skip requested before AI reply - skipping user")
    await wecom.go_back()
    await asyncio.sleep(0.5)
    result["skipped"] = True
    return result

# 新代码
if await sidecar_client.is_skip_requested():
    self._logger.info(f"[{serial}] ⏭️ Skip requested before AI reply - skipping user")
    # Bubble up so outer loop can handle skip exactly once
    raise SkipRequested()
```

**改造点 4：等待期间 Skip 检测**

```python
# 原代码
if await sidecar_client.is_skip_requested():
    self._logger.info(f"[{serial}] ⏭️ Skip detected during wait - breaking wait loop")
    break

# 新代码
if await sidecar_client.is_skip_requested():
    self._logger.info(f"[{serial}] ⏭️ Skip detected during wait - stopping user processing")
    raise SkipRequested()
```

## 处理流程对比

### 原有流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     原有 Skip 处理流程                                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  检测 Skip 请求         │
                        └────────────┬───────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  每个 Skip 点独立处理    │
                        └────────────┬───────────┘
                                     │
            ┌────────────────────────┴────────────────────────┐
            │                         │                        │
            ▼                         ▼                        ▼
    ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
    │ Skip 点1      │      │ Skip 点2      │      │ Skip 点3      │
    │ go_back()     │      │ go_back()     │      │ go_back()     │
    │ clear flag    │      │ clear flag    │      │ clear flag    │
    └───────────────┘      └───────────────┘      └───────────────┘
            │                         │                        │
            ▼                         ▼                        ▼
        可能重复 go_back          可能重复 go_back          可能重复 go_back
```

**问题**：

- 每个 Skip 点都调用 `go_back()`
- 可能在列表屏幕时误返回
- Skip flag 清理逻辑重复

### 重构后流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     重构后 Skip 处理流程                                │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  检测 Skip 请求         │
                        └────────────┬───────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  抛出 SkipRequested    │
                        │  异常                 │
                        └────────────┬───────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  异常冒泡到顶层         │
                        └────────────┬───────────┘
                                     │
                                     ▼
            ┌────────────────────────────────────────────────┐
            │  顶层统一捕获: _handle_skip_once()           │
            └────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                   ▼
        ┌───────────────────────┐     ┌───────────────────────┐
        │  1. 清理 Skip flag    │     │  2. 检测屏幕状态      │
        │  (尽早清理)           │     │  (只在 chat 时返回)  │
        └───────────────────────┘     └───────────────────────┘
                    │                                   │
                    └────────────────┬────────────────┘
                                     ▼
                        ┌────────────────────────┐
                        │  3. 调用 go_back()     │
                        │  (仅一次)             │
                        └────────────┬───────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  4. 返回用户列表        │
                        └────────────────────────┘
```

**优势**：

- Skip 只处理一次（单一 `go_back()` 调用）
- Skip flag 尽早清理（防止重复处理）
- 屏幕检测避免误返回
- 代码更简洁清晰

## 关键改进

### 1. 避免重复 go_back

**原问题**：

- Skip 处理逻辑分散在 4+ 个位置
- 每个位置都调用 `go_back()`
- 可能导致连续返回到主屏幕

**解决方案**：

- 使用异常机制将 Skip 冒泡到顶层
- 顶层统一调用 `_handle_skip_once()`
- 确保只调用一次 `go_back()`

### 2. 尽早清理 Skip flag

**原问题**：

- Skip flag 在多个位置检查和清理
- 可能出现清理时机不当

**解决方案**：

- 在 `_handle_skip_once()` 开始时就清理 flag
- 后续循环不会重复处理

### 3. 屏幕状态检测

**原问题**：

- 无条件调用 `go_back()`
- 可能在列表屏幕时误返回

**解决方案**：

- 使用 `get_current_screen()` 检测当前屏幕
- 只在 `screen == "chat"` 时才调用 `go_back()`
- 防止退回到主屏幕

### 4. 统一日志记录

**改进**：

- 所有 Skip 处理都记录到 `_handle_skip_once()`
- 日志格式统一，便于调试
- 清晰标识 Skip 处理的各个步骤

## 日志示例

### 场景 1：主循环检测到 Skip

```
[AN2FVB1706003302] ⏭️ Skip requested - clearing queue and returning to chat list
[AN2FVB1706003302] ✅ Skip flag cleared
[AN2FVB1706003302] 检测到当前屏幕: chat
[AN2FVB1706003302] 执行返回操作
```

### 场景 2：用户处理期间 Skip

```
[AN2FVB1706003302] 📝 Processing: 张三
[AN2FVB1706003302] 提取到 2 条消息
[AN2FVB1706003302] ⏭️ Skip requested before AI reply - skipping user
[AN2FVB1706003302] ⏭️ Skip requested during user processing - stopping scan
[AN2FVB1706003302] ✅ Skip flag cleared
[AN2FVB1706003302] 检测到当前屏幕: chat
[AN2FVB1706003302] 执行返回操作
```

### 场景 3：等待期间 Skip

```
[AN2FVB1706003302] 等待用户操作 (5s)...
[AN2FVB1706003302] ⏭️ Skip detected during wait - stopping user processing
[AN2FVB1706003302] ⏭️ Skip requested during user processing - stopping scan
[AN2FVB1706003302] ✅ Skip flag cleared
[AN2FVB1706003302] 检测到当前屏幕: chat
[AN2FVB1706003302] 执行返回操作
```

### 场景 4：非聊天屏幕 Skip

```
[AN2FVB1706003302] ⏭️ Skip requested - clearing queue and returning to chat list
[AN2FVB1706003302] ✅ Skip flag cleared
[AN2FVB1706003302] 检测到当前屏幕: messages
[AN2FVB1706003302] ⚠️ 当前不在聊天屏幕，跳过返回操作
```

## 代码质量改进

### 1. 减少代码重复

**原代码**：Skip 处理逻辑在 4+ 个位置重复
**新代码**：集中在 `_handle_skip_once()` 方法

### 2. 提高可维护性

**优势**：

- Skip 处理逻辑集中，易于修改
- 日志统一，便于调试
- 异常机制清晰表达意图

### 3. 增强健壮性

**改进**：

- 屏幕检测避免误返回
- Skip flag 尽早清理
- 异常捕获更全面

## 相关文件

| 文件                                                                   | 描述           |
| ---------------------------------------------------------------------- | -------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 补刀响应检测器 |

## 参考文档

- [Sidecar Skip Button 实现](../03-impl-and-arch/sidecar-skip-button-implementation.md)
- [补刀系统逻辑文档](../03-impl-and-arch/followup-system-logic.md)
- [实时回复 Sidecar 升级](../03-impl-and-arch/instant-response-sidecar-upgrade.md)
