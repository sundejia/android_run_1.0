# AI 回复后无法 Skip 问题分析

**日期**: 2025-01-31  
**模块**: `response_detector.py`, `sidecar.py`, `SidecarView.vue`  
**问题描述**: AI 生成回复后，点击 Skip 按钮无效，无法跳过当前用户。  
**状态**: ✅ 已修复 (2025-01-31)

## 修复摘要

- **修改文件**: `wecom-desktop/backend/routers/sidecar.py`
- **修改内容**: 在 `wait_for_send` 的轮询循环中，每次迭代先检查 `_get_skip_flag(serial)`；若为 True，则将对应消息标记为 CANCELLED 并返回 `{"success": False, "reason": "cancelled"}`。
- **效果**: 用户在 AI 回复后、消息发送前点击 Skip，后端在 100ms 内检测到 skip flag 并中断等待，Follow-up/Sync 进程收到取消信号后跳过当前用户。

## 问题现象

1. Follow-up 或 Sync 检测到客户消息
2. AI 生成回复后，消息显示在 Sidecar 输入框中
3. 10秒倒计时开始
4. 用户点击 Skip 按钮
5. **Skip 无效**，消息仍然被发送或持续等待

## 核心流程分析

### 消息发送流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    response_detector.py                              │
├─────────────────────────────────────────────────────────────────────┤
│  1. _process_unread_user_with_wait()                                │
│     ├── 检查 skip (line 585) ✅                                     │
│     ├── 进入聊天                                                    │
│     ├── 提取消息                                                    │
│     ├── 检查 skip (line 690) ✅                                     │
│     ├── 生成 AI 回复                                                │
│     └── _send_reply_wrapper() ← 关键！                              │
│                                                                     │
│  2. _send_reply_wrapper()                                           │
│     ├── sidecar_client.add_message()     → 添加到队列               │
│     ├── sidecar_client.set_message_ready() → 启动倒计时             │
│     └── sidecar_client.wait_for_send()   → 阻塞等待 ⚠️             │
│                                          (最长 300 秒)              │
│                                                                     │
│  3. _interactive_wait_loop()                                        │
│     └── 检查 skip (line 852) ✅                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    sidecar.py (后端路由)                            │
├─────────────────────────────────────────────────────────────────────┤
│  wait_for_send() - line 1203                                        │
│  ├── 每 100ms 轮询消息状态                                          │
│  ├── ✅ 检查 skip flag → 标记取消并返回 cancelled                   │
│  ├── 检查: SENT → 返回成功                                          │
│  ├── 检查: FAILED → 返回失败                                        │
│  └── 检查: CANCELLED → 返回取消                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Skip 检查点分布（修复后）

| 位置           | 文件                         | 行号          | 是否覆盖      |
| -------------- | ---------------------------- | ------------- | ------------- |
| 循环开始处     | response_detector.py         | 343-348       | ✅            |
| 进入聊天前     | response_detector.py         | 585           | ✅            |
| 点击用户前     | response_detector.py         | 594           | ✅ (清除)     |
| AI 回复前      | response_detector.py         | 690           | ✅            |
| **等待发送中** | **sidecar.py wait_for_send** | **1226-1235** | **✅ 已修复** |
| 交互等待循环   | response_detector.py         | 852           | ✅            |

## 问题根因（已修复）

### 1. `wait_for_send` 不检查 Skip Flag (主要问题) — 已修复

**修复前**: `wait_for_send` 只轮询消息状态，不检查 skip flag。  
**修复后**: 在 `wecom-desktop/backend/routers/sidecar.py` 的 `wait_for_send` 中，每轮询先检查 `_get_skip_flag(serial)`；若为 True，则将对应消息标记为 CANCELLED 并立即返回 `{"success": False, "reason": "cancelled"}`。

### 2. Skip 请求与 wait_for_send 的交互问题

```
用户点击 Skip
    │
    ▼
POS../03-impl-and-arch/{serial}/skip
    ├── _skip_flags[serial] = True
    ├── 取消队列中 PENDING/READY 的消息 → status = CANCELLED
    └── 触发 waiting_event

但是：
    - wait_for_send 检查的是 message.status
    - 如果消息已经是 READY 状态，取消逻辑可能不会立即生效
    - wait_for_send 不直接检查 _skip_flags
```

### 3. 前端 Skip 按钮显示条件

```vue
<!-- SidecarView.vue line 1975 -->
<div v-if="shouldShowProgressControls(serial)" ...>
  <!-- Skip 按钮只在这里显示 -->
</div>
```

```javascript
// line 1095-1107
function shouldShowProgressControls(serial: string) {
  const syncStatus = getSyncProgress(serial)
  const syncRunning = syncStatus && ['running', 'starting', 'paused'].includes(syncStatus.status)
  const followUpRunning = isFollowUpRunning(serial)
  return syncRunning || followUpRunning  // 只有 sync/followup 运行时显示
}
```

**问题**: 如果 sync/followup 状态检测不准确，Skip 按钮可能不显示或显示时机不对。

## 未覆盖的 Skip 场景

### 场景 1: wait_for_send 阻塞期间 — ✅ 已修复

- **时机**: AI 回复生成后，消息进入队列等待发送
- **原表现**: 300秒等待期间 Skip 无效
- **修复**: `wait_for_send` 每轮询检查 skip flag，检测到即取消并返回

### 场景 2: 直接发送模式

```python
# _send_reply_wrapper line 1782-1807
# 直接发送（无人工审核）- 使用 Sidecar 的 send API
try:
    url = f"http://localhost:87../03-impl-and-arch/{serial}/send"
    # 直接发送，没有 skip 检查点
```

- **时机**: 无 sidecar_client 时直接发送
- **表现**: 消息直接发送，无法中断
- **原因**: 直接发送不经过队列，没有 skip 机制

### 场景 3: 消息已发送后

- **时机**: 10秒倒计时结束，消息已发送
- **表现**: Skip 无效（消息已发）
- **原因**: 这是预期行为，但用户可能误解

### 场景 4: 网络延迟

- **时机**: Skip API 调用延迟
- **表现**: Skip 似乎无效，实际是延迟
- **原因**: 网络或后端响应慢

### 场景 5: Skip Flag 残留

- **时机**: 上次 skip 后 flag 没清除
- **表现**: 下一个用户被意外跳过
- **原因**: `clear_skip_flag` 调用失败或遗漏

## 修复建议

### 方案 1: 在 wait_for_send 中检查 Skip Flag (推荐) ✅ 已应用

```python
# sidecar.py - 已修改
@router.post("/{serial}/queue/wait/{message_id}")
async def wait_for_send(serial: str, message_id: str, timeout: float = 300.0):
    logger = logging.getLogger(__name__)
    while True:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return {"success": False, "reason": "timeout"}

        # ✅ 新增: 检查 skip flag - 允许用户在等待期间取消
        if _get_skip_flag(serial):
            logger.info(f"⏭️ Skip flag detected during wait_for_send for {serial}")
            # 标记消息为取消
            queue = _get_queue(serial)
            msg = next((m for m in queue if m.id == message_id), None)
            if msg and msg.status not in (MessageStatus.SENT, MessageStatus.FAILED):
                msg.status = MessageStatus.CANCELLED
            return {"success": False, "reason": "cancelled"}

        # 现有状态检查...
```

### 方案 2: 使用 Event 中断等待

```python
# 在 request_skip 中触发 event
@router.post("/{serial}/skip")
async def request_skip(serial: str):
    _set_skip_flag(serial, True)

    # 触发等待中断
    event = _get_waiting_event(serial)
    event.set()  # 这已经存在，但 wait_for_send 不使用它

    return {"success": True}

# 修改 wait_for_send 使用 event
async def wait_for_send(serial: str, message_id: str, timeout: float = 300.0):
    event = _get_waiting_event(serial)

    while True:
        # 使用 event 等待而不是 sleep
        try:
            await asyncio.wait_for(event.wait(), timeout=poll_interval)
            # Event 被触发，检查是否是 skip
            if _get_skip_flag(serial):
                return {"success": False, "reason": "cancelled"}
        except asyncio.TimeoutError:
            pass  # 正常超时，继续轮询

        # 检查消息状态...
```

### 方案 3: 前端实时 Skip 状态同步

```javascript
// SidecarView.vue - 在倒计时期间持续检查 skip 状态
async function monitorSkipDuringCountdown(serial) {
  while (sidecars[serial]?.countdown !== null) {
    const status = await api.getSkipStatus(serial)
    if (status.skip_requested) {
      // Skip 已被其他地方请求，立即停止倒计时
      clearCountdown(serial)
      panel.statusMessage = 'Skip requested'
      break
    }
    await new Promise((r) => setTimeout(r, 500))
  }
}
```

## 测试验证步骤

1. **验证 Skip Flag 设置**

   ```bash
   # 设置 skip flag
   curl -X POST http://localhost:87../03-impl-and-arch/{serial}/skip

   # 检查 skip flag
   curl http://localhost:87../03-impl-and-arch/{serial}/skip
   # 应返回: {"skip_requested": true}
   ```

2. **验证 wait_for_send 行为**
   - 添加消息到队列
   - 在倒计时期间调用 skip API
   - 观察 wait_for_send 是否返回

3. **验证前端按钮状态**
   - 检查 `shouldShowProgressControls` 返回值
   - 检查 followup/sync 状态是否正确

## 相关代码位置

| 功能                   | 文件                 | 行号      |
| ---------------------- | -------------------- | --------- |
| Skip 按钮 UI           | SidecarView.vue      | 2039-2048 |
| skipDeviceSync 函数    | SidecarView.vue      | 1150-1215 |
| Skip API 路由          | sidecar.py           | 1131-1159 |
| wait_for_send          | sidecar.py           | 1203-1246 |
| is_skip_requested      | sidecar.py (client)  | 191-229   |
| \_send_reply_wrapper   | response_detector.py | 1716-1807 |
| Skip 检查点 (主循环)   | response_detector.py | 333-363   |
| Skip 检查点 (AI前)     | response_detector.py | 688-697   |
| Skip 检查点 (等待循环) | response_detector.py | 848-856   |

## 影响范围

- Follow-up 模式: 高度影响
- Sync 模式: 高度影响
- 直接发送模式: 完全无法 skip

## 优先级

**高** - 影响用户体验和操作效率，用户无法在关键时刻中断不想发送的消息。
