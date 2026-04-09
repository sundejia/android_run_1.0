# 补刀错误处理增强

> 文档创建：2026-02-05
> 状态：已实现

## 概述

在完成补刀系统的主要功能重构后，继续进行了错误处理的增强改进，使系统更加健壮和易于调试。

---

## 改进内容

### 1. SkipRequested 异常传播优化

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

**问题**：

- `SkipRequested` 异常在某些情况下可能被意外捕获
- 异常传播链不清晰，可能导致 Skip 行为不一致

**解决方案**：

- 在关键的 Skip 检测点添加显式的 `except SkipRequested: raise` 块
- 确保 `SkipRequested` 异常正确传播到顶层处理函数

**代码变更**：

```python
# Skip 检测点 1：AI 回复前
try:
    if await sidecar_client.is_skip_requested():
        self._logger.info(f"[{serial}] ⏭️ Skip requested before AI reply - skipping user")
        # Bubble up so outer loop can handle skip exactly once
        raise SkipRequested()
except SkipRequested:
    # Re-raise SkipRequested to propagate it properly
    raise
except Exception as e:
    self._logger.warning(f"[{serial}] Error checking skip before AI: {type(e).__name__}: {e}")

# Skip 检测点 2：等待期间
try:
    if await sidecar_client.is_skip_requested():
        self._logger.info(f"[{serial}] ⏭️ Skip detected during wait - stopping user processing")
        raise SkipRequested()
except SkipRequested:
    # Re-raise SkipRequested to propagate it properly
    raise
except Exception as e:
    self._logger.warning(f"[{serial}] Error checking skip during wait: {type(e).__name__}: {e}")
```

**优势**：

- 明确的异常传播路径
- 防止 `SkipRequested` 被通用异常处理器捕获
- 保持 Skip 行为的一致性

---

### 2. 错误日志增强

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

**改进**：

- 在错误日志中添加异常类型名称 `{type(e).__name__}`
- 保留完整的异常信息 `{e}`
- 添加注释说明错误的上下文和处理方式

**变更示例**：

```python
# 原日志
self._logger.error(f"[{serial}] ❌ Error checking skip flag: {e}")

# 新日志
self._logger.error(f"[{serial}] ❌ Error checking skip flag: {type(e).__name__}: {e}")
```

**影响位置**：

1. 主循环 Skip 检测
2. 进入聊天前 Skip 检测
3. AI 回复前 Skip 检测
4. 等待期间 Skip 检测

**优势**：

- 更详细的错误信息，便于调试
- 快速识别异常类型
- 保留完整错误上下文

---

### 3. Sidecar 会话错误处理

**文件**: `src/wecom_automation/services/integration/sidecar.py`

**问题**：

- 当 Sidecar 会话未初始化或关闭时，会抛出 `RuntimeError`
- 未处理的异常导致 Skip 检测失败
- 影响系统稳定性

**解决方案**：

- 捕获 `RuntimeError` 并记录警告
- 返回 `False` 表示没有 Skip 请求
- 在队列状态检查中也添加相同的处理

**代码变更**：

```python
async def is_skip_requested(self) -> bool:
    """Check if user has requested to skip current operation."""
    try:
        # API 调用
        response = await self._client.get(
            f"{self._base_url}/skip_flag",
            timeout=2.0
        )
        ...
    except TimeoutError:
        self._logger.warning("⚠️ Skip flag API check timed out after 2s")
    except RuntimeError as e:
        # Session not initialized or closed - log warning and return False
        self._logger.warning(f"⚠️ Skip flag check failed (session error): {e}")
        return False
    except Exception as e:
        self._logger.warning(f"⚠️ Skip flag check failed, falling back to queue: {e}")

    # Fallback: check if any message is cancelled
    try:
        state = await self.get_queue_state()
        queue = state.get("queue", [])

        for msg in queue:
            if msg.get("status") == "cancelled":
                self._logger.debug("✅ Skip detected via cancelled queue message")
                return True
    except RuntimeError as e:
        # Session not initialized or closed - log warning and return False
        self._logger.warning(f"⚠️ Queue state check failed (session error): {e}")
        return False
    except Exception as e:
        self._logger.warning(f"⚠️ Queue state check failed: {e}")

    self._logger.debug("🔍 No skip request detected")
    return False
```

**优势**：

- 优雅处理会话未初始化的情况
- 防止未处理异常导致程序崩溃
- 保留功能降级机制（检查队列状态）
- 详细的日志记录便于问题排查

---

## 技术细节

### 异常传播链

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Skip 请求检测流程                                 │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │  检测 Skip 请求         │
                        └────────────┬───────────┘
                                     │
                        ┌────────────┴────────────┐
                        │ is_skip_requested()    │
                        └────────────┬─────────────┘
                                     │
                        ┌────────────┴────────────┐
                        │ 抛出异常?               │
                        ▼                         │
                  ┌─────────────────┐               │
                  │ SkipRequested   │               │
                  └─────────────────┘               │
                        │                         │
                        ▼                         │
        ┌───────────────────────────────────────┐  │
        │ except SkipRequested: raise          │  │
        │ 确保异常正确传播                      │  │
        └───────────────────────────────────────┘  │
                        │                         │
                        ▼                         │
                  ┌─────────────────┐               │
                  │ 异常冒泡到顶层    │◄─────────────┘
                  │ _handle_skip_once│
                  └─────────────────┘
                        │
                        ▼
              ┌───────────────────┐
              │ 统一处理 Skip      │
              │ go_back()         │
              │ clear flag        │
              └───────────────────┘
```

### 错误处理层级

```
Level 1: SkipRequested 异常
  ↓ 明确传播
Level 2: RuntimeError (会话错误)
  ↓ 返回 False，降级处理
Level 3: 其他 Exception
  ↓ 记录警告，继续执行
```

---

## 日志示例

### 场景 1：正常 Skip 请求

```
[AN2FVB1706003302] 🔍 Skip check result: skip_requested=True
[AN2FVB1706003302] ⏭️ Skip requested before AI reply - skipping user
[AN2FVB1706003302] ⏭️ Skip requested during user processing - stopping scan
[AN2FVB1706003302] ✅ Skip flag cleared
[AN2FVB1706003302] 检测到当前屏幕: chat
[AN2FVB1706003302] 执行返回操作
```

### 场景 2：会话未初始化错误

```
[AN2FVB1706003302] ⚠️ Skip flag check failed (session error): No session found
[AN2FVB1706003302] ⚠️ Queue state check failed (session error): No session found
[AN2FVB1706003302] 🔍 No skip request detected
```

### 场景 3：详细错误信息

```
[AN2FVB1706003302] ❌ Error checking skip flag: ConnectionError: Connection refused
```

**优势**：立即识别错误类型为 `ConnectionError`，而不是只有错误消息

---

## 相关文档

- [Skip 处理重构](./2026-02-05-followup-skip-handling-refactor.md)
- [补刀系统流程分析](../03-impl-and-arch/followup-flow-analysis.md)
- [Sidecar 集成](../03-impl-and-arch/instant-response-sidecar-upgrade.md)

---

## 版本历史

- **2026-02-05**: 初始版本，记录 SkipRequested 异常传播优化和错误日志增强
