# Bug 分析：Skip后无法点击下一个用户

> 时间: 2026-01-19  
> 状态: ✅ 已修复

---

## 问题描述

在发送消息阶段点击 Skip 跳过当前用户后，程序无法点击下一个用户，显示 "Skip requested via sidecar" 错误。

---

## 日志分析

```
12:41:42  Skip flag cleared after skip           # 1y- 用户跳过后清除标志
12:41:47  Starting: click_user_in_list [user=W.] # 开始处理下一个用户
12:41:47  Skip requested - interrupting operation # 又检测到 skip！
12:41:47  Failed: click_user_in_list [error=Skip requested via sidecar]
```

---

## 根因分析

### is_skip_requested() 的双重检查

`SidecarQueueClient.is_skip_requested()` 方法有两种检查方式：

1. **主检查**：调用../03-impl-and-arch/{serial}/skip` API 检查 skip 标志
2. **回退检查**：检查队列中是否有 `cancelled` 状态的消息

```python
async def is_skip_requested(self) -> bool:
    # First check the dedicated skip flag API
    try:
        url = f"{self.backend_ur../03-impl-and-arch/{self.serial}/skip"
        async with self.session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("skip_requested", False):
                    return True
    except Exception:
        pass

    # Fallback: check if any message is cancelled  ← 问题在这里！
    state = await self.get_queue_state()
    queue = state.get("queue", [])

    for msg in queue:
        if msg.get("status") == "cancelled":
            return True  # 只要有 cancelled 消息就返回 True

    return False
```

### 问题流程

```
1. 用户点击 Skip
2. request_skip API:
   - 设置 skip_flag = True
   - 将队列消息状态设为 CANCELLED
3. SkipUserException 被抛出，跳过当前用户
4. clear_skip_flag API:
   - 设置 skip_flag = False
   - 队列中的 CANCELLED 消息仍然存在！ ← 问题根源
5. 开始处理下一个用户
6. is_skip_requested() 检查：
   - skip_flag = False ✓
   - 队列中有 CANCELLED 消息 → 返回 True！ ← 误检测
7. 抛出 SkipUserException，跳过下一个用户
```

---

## 解决方案

### 方案 A: 清除 skip 标志时同时清除队列（推荐）

修改 `clear_skip` API 同时清除队列中的 cancelled 消息：

```python
@router.delete("/{serial}/skip")
async def clear_skip(serial: str):
    """Clear the skip flag for a device."""
    _set_skip_flag(serial, False)

    # Also clear cancelled messages from queue to prevent false positive
    queue = _get_queue(serial)
    # Remove cancelled messages or reset queue
    _queues[serial] = [m for m in queue if m.status != MessageStatus.CANCELLED]

    return {"success": True, "message": "Skip flag cleared", "skip_flag": False}
```

### 方案 B: 修改回退检查逻辑

移除 `is_skip_requested()` 中的回退检查，只依赖 skip 标志 API。

---

## 修复文件清单

1. `wecom-desktop/backend/routers/sidecar.py`
   - 修改 `clear_skip` 函数，清除队列中的 cancelled 消息
