# Sidecar Skip Button 实现方案

> **状态**: ✅ 已实现 (2026-01-05)

## 问题描述

Sidecar 界面有一个 Skip 按钮，当程序进入某个用户的聊天界面时，会提取消息并准备回复。点击 Skip 按钮应该：

1. 跳过当前用户
2. 返回用户菜单（私聊列表）
3. 继续原本的同步/followup 逻辑

## 当前实现分析

### 1. 前端实现 (SidecarView.vue)

```typescript
// Skip 按钮位置：同步进度条旁边
<button
  class="btn-secondary text-xs px-2 py-0.5"
  @click.stop="skipDeviceSync(serial)"
  title="Skip current user"
  :disabled="skipLoading[serial]"
>
  <span v-if="skipLoading[serial]">⏳</span>
  <span v-else>⏭️</span>
  Skip
</button>

// Skip 函数
async function skipDeviceSync(serial: string) {
  skipLoading[serial] = true
  const panel = ensurePanel(serial)
  panel.statusMessage = 'Skipping current user...'

  try {
    // 调用后端 API 取消队列
    const result = await api.cancelSidecarQueue(serial)

    // 清理本地状态
    panel.statusMessage = 'User skip requested'
    panel.currentQueuedMessage = null
    panel.pendingMessage = ''
    panel.queueMode = false

    // 刷新队列状态
    await fetchQueueState(serial)
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Failed to skip'
  } finally {
    skipLoading[serial] = false
  }
}
```

### 2. 后端 API (sidecar.py)

```python
@router.post("/{serial}/queue/cancel")
async def cancel_queue(serial: str):
    """Cancel all pending messages in the queue."""
    queue = _get_queue(serial)
    sync_state = _get_sync_state(serial)

    # 标记所有待处理消息为 CANCELLED
    for msg in queue:
        if msg.status in (MessageStatus.PENDING, MessageStatus.READY):
            msg.status = MessageStatus.CANCELLED

    sync_state.currentMessageId = None

    # 发送事件信号，通知等待中的进程
    event = _get_waiting_event(serial)
    event.set()

    return {"success": True, "message": "Queue cancelled"}
```

### 3. 同步流程中的 Skip 处理 (customer_syncer.py)

```python
async def _send_via_sidecar(self, message: str, context: MessageContext) -> bool:
    """通过 Sidecar 发送消息"""
    try:
        msg_id = await self._sidecar_client.add_message(...)
        await self._sidecar_client.set_message_ready(msg_id)

        # 等待消息发送决定（时长为 sidecar_timeout，默认 60 秒）
        result = await self._sidecar_client.wait_for_send(msg_id, timeout=60.0)

        reason = result.get("reason", "unknown")
        if result.get("success") or reason == "sent":
            return True
        elif reason == "cancelled":
            # 用户点击了 Skip
            raise SkipUserException("Sync skipped via sidecar")
        else:
            return False
```

```python
async def sync(self, user, options, kefu_id, device_serial):
    try:
        # ... 进入聊天、提取消息、发送回复等 ...

    except SkipUserException:
        # 捕获 Skip 请求
        self._logger.info(f"⏭️ Skipping user {user_name} by request")
        try:
            await self._exit_conversation()  # 返回用户菜单
        except Exception:
            pass
        return result  # 返回，继续处理下一个用户
```

### 4. 等待发送的轮询机制 (sidecar.py)

```python
@router.post("/{serial}/queue/wait/{message_id}")
async def wait_for_send(serial: str, message_id: str, timeout: float = 60.0):
    """等待消息发送，轮询检查状态"""
    while True:
        if elapsed >= timeout:
            return {"success": False, "reason": "timeout"}

        msg = next((m for m in queue if m.id == message_id), None)

        if msg.status == MessageStatus.CANCELLED:
            return {"success": False, "reason": "cancelled"}  # Skip 触发这个返回

        await asyncio.sleep(0.1)  # 100ms 轮询间隔
```

## 当前流程图

```
用户点击 Skip
    │
    ▼
前端: api.cancelSidecarQueue(serial)
    │
    ▼
后端: cancel_queue()
    ├── 标记所有消息为 CANCELLED
    └── 设置 waiting_event
    │
    ▼
wait_for_send 检测到 CANCELLED
    │
    ▼
返回 {"reason": "cancelled"}
    │
    ▼
CustomerSyncer._send_via_sidecar()
    │
    ▼
抛出 SkipUserException
    │
    ▼
CustomerSyncer.sync() 捕获异常
    │
    ▼
调用 _exit_conversation() 返回
    │
    ▼
SyncOrchestrator 继续处理下一个用户
```

## 已知问题

### Bug 1: Skip 按钮仅在消息等待阶段有效

**问题**: Skip 按钮依赖于 `wait_for_send` 轮询机制。如果程序正在执行其他操作（如提取消息、滚动页面等），Skip 不会立即生效。

**原因**: `is_skip_requested()` 检查仅在特定时机被调用。

### Bug 2: Followup 流程未处理 Skip

**问题**: 当前 Skip 实现主要在 `CustomerSyncer` 中，但 Followup 流程（`ResponseDetector`, `FollowUpScanner`）可能没有相同的 Skip 处理。

### Bug 3: 前端状态可能不同步

**问题**: Skip 完成后，前端可能没有正确更新显示状态。

## 修复方案

### 方案 1: 增强 Cancel Checker 覆盖范围

在所有长时间操作中定期检查 Skip 状态：

```python
# customer_syncer.py
async def _extract_messages(self):
    """提取消息（支持 Skip 中断）"""
    messages = []

    for _ in range(max_scrolls):
        # 每次滚动前检查 Skip
        if self._sidecar_client:
            if await self._sidecar_client.is_skip_requested():
                raise SkipUserException("Skip requested during extraction")

        # ... 提取消息逻辑 ...
```

### 方案 2: 新增专用 Skip API

创建一个专门的 Skip API，不依赖队列取消：

```python
# 后端
_skip_flags: Dict[str, bool] = {}

@router.post("/{serial}/skip-current-user")
async def skip_current_user(serial: str):
    """请求跳过当前用户"""
    _skip_flags[serial] = True

    # 同时取消队列
    await cancel_queue(serial)

    return {"success": True, "message": "Skip requested"}

@router.get("/{serial}/skip-flag")
async def get_skip_flag(serial: str):
    """检查是否有 Skip 请求"""
    return {"skip_requested": _skip_flags.get(serial, False)}

@router.post("/{serial}/clear-skip-flag")
async def clear_skip_flag(serial: str):
    """清除 Skip 标志"""
    _skip_flags[serial] = False
    return {"success": True}
```

```python
# SidecarQueueClient 新增方法
async def request_skip(self) -> bool:
    """请求跳过当前用户"""
    url = f"{self.backend_ur../03-impl-and-arch/{self.serial}/skip-current-user"
    async with self.session.post(url) as resp:
        return resp.status == 200

async def is_skip_requested(self) -> bool:
    """检查是否有跳过请求"""
    url = f"{self.backend_ur../03-impl-and-arch/{self.serial}/skip-flag"
    async with self.session.get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get("skip_requested", False)
    return False

async def clear_skip_flag(self) -> bool:
    """清除跳过标志"""
    url = f"{self.backend_ur../03-impl-and-arch/{self.serial}/clear-skip-flag"
    async with self.session.post(url) as resp:
        return resp.status == 200
```

### 方案 3: 统一 Skip 处理中间件

在 WeComService 层添加 Skip 检查装饰器：

```python
# wecom_service.py
class WeComService:
    def __init__(self):
        self._skip_checker = None

    def set_skip_checker(self, checker: Callable[[], Awaitable[bool]]):
        """设置 Skip 检查器"""
        self._skip_checker = checker

    async def _check_skip(self):
        """检查是否需要跳过"""
        if self._skip_checker and await self._skip_checker():
            raise SkipUserException("Skip requested")

    async def click_user(self, name: str, channel: Optional[str] = None) -> bool:
        await self._check_skip()
        # ... 原有逻辑 ...

    async def scroll_up(self) -> bool:
        await self._check_skip()
        # ... 原有逻辑 ...
```

### 方案 4: 前端增加 Skip 状态反馈

```typescript
// SidecarView.vue
async function skipDeviceSync(serial: string) {
  skipLoading[serial] = true
  const panel = ensurePanel(serial)
  panel.statusMessage = 'Skipping current user...'

  try {
    // 调用新的 skip API
    await api.skipCurrentUser(serial)

    panel.statusMessage = '⏭️ Skip requested - returning to chat list...'

    // 等待同步状态更新
    let attempts = 0
    while (attempts < 30) {
      // 最多等待 3 秒
      await new Promise((r) => setTimeout(r, 100))
      await fetchState(serial, false)

      // 检查是否已返回到聊天列表
      if (!panel.state?.conversation?.contact_name) {
        panel.statusMessage = '✅ User skipped successfully'
        break
      }
      attempts++
    }

    // 清理状态
    panel.currentQueuedMessage = null
    panel.pendingMessage = ''
    panel.queueMode = false

    await fetchQueueState(serial)
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : 'Failed to skip'
  } finally {
    skipLoading[serial] = false
  }
}
```

## 推荐实现顺序

1. **阶段 1**: 实现方案 2（专用 Skip API）- 提供可靠的跳过信号
2. **阶段 2**: 实现方案 1（增强 Cancel Checker）- 在所有长操作中检查
3. **阶段 3**: 实现方案 4（前端状态反馈）- 改善用户体验
4. **阶段 4**: 实现方案 3（统一中间件）- 代码重构优化

## 测试要点

1. 在消息等待阶段点击 Skip - 应立即返回
2. 在消息提取阶段点击 Skip - 应在当前滚动完成后返回
3. 在头像处理阶段点击 Skip - 应正确中断并返回
4. Skip 后下一个用户应正常处理
5. Skip 后前端状态应正确清理
6. 连续多次 Skip 应正常工作

## 相关文件

- `wecom-desktop/src/views/SidecarView.vue` - 前端 Skip 按钮
- `wecom-desktop/backend/routers/sidecar.py` - 后端队列 API
- `src/wecom_automation/services/sync/customer_syncer.py` - 同步器 Skip 处理
- `src/wecom_automation/services/integration/sidecar.py` - Sidecar 客户端
- `src/wecom_automation/core/exceptions.py` - SkipUserException 定义

---

## ✅ 实现完成记录

### 实现的方案

结合了 **方案 2 (专用 Skip API)** 和 **方案 3 (统一 Skip 处理中间件)** 的核心思想：

### 1. 后端 - 专用 Skip API (`wecom-desktop/backend/routers/sidecar.py`)

新增了独立的 skip flag 机制：

```python
# 全局 skip 标志存储
_skip_flags: Dict[str, bool] = {}

# 新增 API 端点
POST ../03-impl-and-arch/{serial}/skip    # 请求跳过当前用户
GET  ../03-impl-and-arch/{serial}/skip    # 获取跳过状态
DELET../03-impl-and-arch/{serial}/skip    # 清除跳过标志
```

特点：

- 独立于队列取消机制
- 同时设置 skip flag 和取消队列消息
- 通过 event 信号通知等待中的进程

### 2. SidecarQueueClient (`src/wecom_automation/services/integration/sidecar.py`)

新增方法：

- `is_skip_requested()` - 检查跳过状态（优先使用 skip flag API）
- `request_skip()` - 请求跳过
- `clear_skip_flag()` - 清除跳过标志

### 3. WeComService (`src/wecom_automation/services/wecom_service.py`)

在所有长时间操作中添加 `_check_cancelled()` 调用：

- `extract_private_chat_users()` - 每次滚动前检查
- `_capture_avatars()` - 每次循环前检查
- `extract_conversation_messages()` - Phase 1 滚动和 Phase 2 提取都检查
- `_download_video_from_wecom()` - 视频下载等待时检查
- `download_images_from_conversation()` - 图片下载循环检查
- `download_images_via_fullscreen()` - 图片下载循环检查
- `wait_for_new_messages()` - 每次轮询前检查
- `click_user_in_list()` - 每次滚动前检查

### 4. CustomerSyncer (`src/wecom_automation/services/sync/customer_syncer.py`)

在关键循环中直接检查 skip 状态：

- `_interactive_reply_loop()` - 每轮交互开始时检查
- `_wait_for_new_customer_messages()` - 每次轮询前检查

在捕获 `SkipUserException` 后自动清除 skip flag：

```python
except SkipUserException:
    # ... 退出对话 ...
    # 清除 skip flag，准备处理下一个用户
    if self._sidecar_client:
        await self._sidecar_client.clear_skip_flag()
```

### 5. 前端 (`wecom-desktop/src/views/SidecarView.vue`)

更新 `skipDeviceSync()` 函数使用新 API：

- 调用 `api.requestSkip(serial)`
- 清除本地状态
- 刷新状态显示

新增 API 方法 (`wecom-desktop/src/services/api.ts`):

- `requestSkip(serial)`
- `getSkipStatus(serial)`
- `clearSkipFlag(serial)`

### 新的 Skip 流程图

```
用户点击 Skip 按钮
    │
    ▼
前端: api.requestSkip(serial)
    │
    ▼
后端: request_skip()
    ├── 设置 _skip_flags[serial] = True
    ├── 标记所有队列消息为 CANCELLED
    └── 设置 waiting_event
    │
    ▼
同步进程检测到 skip (多个检查点):
    ├── wait_for_send 返回 cancelled
    ├── WeComService._check_cancelled() 在操作间隙检测
    └── SidecarQueueClient.is_skip_requested() 直接检查
    │
    ▼
抛出 SkipUserException
    │
    ▼
CustomerSyncer.sync() 捕获异常
    │
    ▼
退出对话 + 清除 skip flag
    │
    ▼
继续处理下一个用户
```

### 优势

1. **可靠性**: 独立的 skip flag 不依赖队列状态
2. **响应性**: 在多个检查点检测 skip 请求
3. **清洁性**: 处理完成后自动清除 flag
4. **兼容性**: 同时支持新旧检测方式

### Skip 检查点完整列表

| 文件                 | 方法                                  | 检查点                     |
| -------------------- | ------------------------------------- | -------------------------- |
| `wecom_service.py`   | `extract_private_chat_users()`        | 每次滚动前                 |
| `wecom_service.py`   | `_capture_avatars()`                  | 每次循环                   |
| `wecom_service.py`   | `extract_conversation_messages()`     | Phase 1 滚动, Phase 2 提取 |
| `wecom_service.py`   | `_download_video_from_wecom()`        | 视频等待轮询               |
| `wecom_service.py`   | `download_images_from_conversation()` | 图片下载循环               |
| `wecom_service.py`   | `download_images_via_fullscreen()`    | 图片下载循环               |
| `wecom_service.py`   | `wait_for_new_messages()`             | 每次轮询前                 |
| `wecom_service.py`   | `click_user_in_list()`                | 每次滚动前                 |
| `customer_syncer.py` | `_interactive_reply_loop()`           | 每轮交互开始               |
| `customer_syncer.py` | `_wait_for_new_customer_messages()`   | 每次轮询前                 |
| `customer_syncer.py` | `_send_via_sidecar()`                 | 等待发送响应时             |
