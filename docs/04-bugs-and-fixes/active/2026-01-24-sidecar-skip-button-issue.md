# Sidecar Skip 按钮问题分析

**日期**: 2026-01-24
**相关文件**:

- `wecom-desktop/src/views/SidecarView.vue`
- `wecom-desktop/backend/routers/sidecar.py`
- `wecom-desktop/backend/routers/followup.py`
- `wecom-desktop/backend/services/followup_device_manager.py`
- `src/wecom_automation/services/integration/sidecar.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

---

## 问题描述

**用户报告**: followup 的 sidecar 界面中，skip 按钮无法使用。

**预期行为**: 点击 skip 按钮后，应该跳过当前正在处理的用户，返回到聊天列表，继续处理下一个用户。

**实际行为**: 点击 skip 按钮后，没有反应或无法正确跳过。

---

## 架构分析

### Skip 流程的双路径设计

SidecarView.vue 中的 `skipDeviceSync` 函数（第 1095-1161 行）根据当前进程类型选择不同的 skip 路径：

```
┌─────────────────────────────────────────────────────────────┐
│                    skipDeviceSync(serial)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 检查控制类型     │
                    │ getProgressControlType(serial)
                    └─────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │ controlType ==  │             │ controlType ==  │
    │   'followup'    │             │    'sync'       │
    └─────────────────┘             └─────────────────┘
              │                               │
              ▼                               ▼
  ┌─────────────────────┐         ┌─────────────────────┐
  │ POST /a../03-impl-and-arch/ │         │ POS../03-impl-and-arch/{serial}/skip
  │ device/{serial}/skip│         │   (api.requestSkip)  │
  └─────────────────────┘         └─────────────────────┘
              │                               │
              ▼                               ▼
  ┌─────────────────────┐         ┌─────────────────────┐
  │ 创建 skip flag 文件 │         │ 设置 _skip_flags[serial] = True
  │ followup_skip_{serial}      │ 清空队列消息
  │ 在 temp 目录        │         │ 设置 waiting event
  └─────────────────────┘         └─────────────────────┘
```

---

## 问题分析

### 1. Followup Skip 流程

**API 端点**: `POST /a../03-impl-and-arch/device/{serial}/skip`

**实现位置**: `wecom-desktop/backend/services/followup_device_manager.py:408-448`

```python
async def request_skip(self, serial: str) -> bool:
    """创建 skip flag 文件"""
    flag_filename = f"{FOLLOWUP_SKIP_FLAG_PREFIX}{serial}"
    flag_path = Path(tempfile.gettempdir()) / flag_filename

    # 写入时间戳
    timestamp = datetime.now().isoformat()
    flag_path.write_text(timestamp, encoding="utf-8")

    return True
```

**问题 1: 子进程如何检测 skip flag？**

Followup 子进程需要检查 `followup_skip_{serial}` 文件是否存在。让我查找相关代码...

### 2. Sync Skip 流程

**API 端点**: `POS../03-impl-and-arch/{serial}/skip`

**实现位置**: `wecom-desktop/backend/routers/sidecar.py:1074-1094`

```python
@router.post("/{serial}/skip")
async def request_skip(serial: str):
    """设置 skip flag 并清空队列"""
    _set_skip_flag(serial, True)

    # 取消队列中的消息
    queue = _get_queue(serial)
    for msg in queue:
        if msg.status in (MessageStatus.PENDING, MessageStatus.READY):
            msg.status = MessageStatus.CANCELLED

    # 通知等待的进程
    event = _get_waiting_event(serial)
    event.set()

    return {"success": True, "message": "Skip requested", "skip_flag": True}
```

**检测机制**: `SidecarQueueClient.is_skip_requested()`

**实现位置**: `src/wecom_automation/services/integration/sidecar.py:196-223`

```python
async def is_skip_requested(self) -> bool:
    """检查是否请求跳过"""
    # 1. 检查专用的 skip flag API
    try:
        url = f"{self.backend_ur../03-impl-and-arch/{self.serial}/skip"
        async with self.session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("skip_requested", False):
                    return True
    except Exception as e:
        pass

    # 2. Fallback: 检查是否有取消的消息
    state = await self.get_queue_state()
    queue = state.get("queue", [])

    for msg in queue:
        if msg.get("status") == "cancelled":
            return True

    return False
```

**使用位置**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py:341`

```python
while user_queue and not self._cancel_requested:
    # 检查 skip flag
    if client and await client.is_skip_requested():
        self._logger.info(f"[{serial}] ⏭️ Skip requested - clearing queue and returning to chat list")
        user_queue.clear()  # 清空队列
        await wecom.go_back()
        await asyncio.sleep(0.5)
        break  # 退出 while 循环
```

---

## 根本原因分析

### 问题 1: Followup Skip Flag 文件检测缺失

**现象**: Followup 流程创建了 skip flag 文件，但子进程没有检查这个文件。

**原因**: `response_detector.py:341` 只检查了 `SidecarQueueClient.is_skip_requested()`，而这个方法只查询../03-impl-and-arch/{serial}/skip` API（sync 的 skip flag），**没有检查 followup 专用的 skip flag 文件**。

**证据**:

- Followup skip flag 文件: `followup_skip_{serial}` 在 `tempfile.gettempdir()`
- Sidecar skip flag API: `GE../03-impl-and-arch/{serial}/skip` 返回内存中的 `_skip_flags[serial]`

**这两个是完全独立的机制！**

### 问题 2: 前端 Skip 按钮逻辑混淆

**代码位置**: `wecom-desktop/src/views/SidecarView.vue:1095-1161`

```javascript
async function skipDeviceSync(serial: string) {
  // 检查是 followup 还是 sync
  const controlType = getProgressControlType(serial)

  if (controlType === 'followup') {
    // 调用 followup skip API
    const response = await fetch(`http://localhost:8765/a../03-impl-and-arch/device/${serial}/skip`, {
      method: 'POST',
    })
    // ...
  } else {
    // 调用 sync skip API
    const result = await api.requestSkip(serial)
    // ...
  }
}
```

**问题**: 这个逻辑看起来没问题，但实际上：

1. Followup skip API 创建了 flag 文件，但 `response_detector.py` 不检查这个文件
2. Sync skip API 设置了内存 flag，但 followup 子进程不使用 SidecarQueueClient

### 问题 3: Followup 和 Sync 使用不同的 Skip 机制

| 特性           | Sync Skip                                | Followup Skip                             |
| -------------- | ---------------------------------------- | ----------------------------------------- |
| **存储位置**   | 内存 `_skip_flags[serial]`               | 文件系统 `followup_skip_{serial}`         |
| **API 端点**   | ../03-impl-and-arch/{serial}/skip`       | ../03-impl-and-arch/device/{serial}/skip` |
| **检测方式**   | `SidecarQueueClient.is_skip_requested()` | **未知（未实现）**                        |
| **实现位置**   | `sidecar.py`                             | `followup_device_manager.py`              |
| **子进程检测** | ✅ 已实现                                | ❌ **未实现**                             |

---

## 解决方案

### 方案 A: 统一使用 Sidecar Skip 机制（推荐）

**优点**: 复用已有的 sync skip 机制，代码统一

**实现**:

1. 在 `response_detector.py` 中已经使用 `SidecarQueueClient.is_skip_requested()`
2. Followup skip API 也调用../03-impl-and-arch/{serial}/skip` 而不是创建自己的 flag 文件

**修改位置**:

```python
# wecom-desktop/backend/services/followup_device_manager.py
async def request_skip(self, serial: str) -> bool:
    """不再创建独立的 skip flag 文件，而是调用 sidecar skip API"""
    import httpx

    sidecar_skip_url = f"http://localhost:87../03-impl-and-arch/{serial}/skip"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(sidecar_skip_url)
            if resp.status_code == 200:
                await self._broadcast_log(serial, "INFO", "Skip requested via sidecar API")
                return True
            else:
                await self._broadcast_log(serial, "ERROR", f"Skip request failed: {resp.status_code}")
                return False
    except Exception as e:
        await self._broadcast_log(serial, "ERROR", f"Skip request error: {e}")
        return False
```

### 方案 B: 在 Followup 子进程中检查 Skip Flag 文件

**优点**: 保留独立机制

**实现**:
在 `response_detector.py` 中添加 skip flag 文件检查：

```python
async def _check_followup_skip_flag(self, serial: str) -> bool:
    """检查 followup skip flag 文件是否存在"""
    import tempfile
    from pathlib import Path

    flag_filename = f"followup_skip_{serial}"
    flag_path = Path(tempfile.gettempdir()) / flag_filename

    if flag_path.exists():
        # 清除 flag 文件
        flag_path.unlink()
        return True

    return False

# 在 while 循环中使用
while user_queue and not self._cancel_requested:
    # 检查 followup skip flag 文件
    if await self._check_followup_skip_flag(serial):
        self._logger.info(f"[{serial}] ⏭️ Skip requested (via flag file)")
        user_queue.clear()
        await wecom.go_back()
        await asyncio.sleep(0.5)
        break

    # 检查 sidecar skip flag（用于 sidecar 队列消息）
    if client and await client.is_skip_requested():
        # ... 现有逻辑
```

### 方案 C: Sidecar Skip 同时设置 Followup Skip Flag

**优点**: 向后兼容，两个机制都支持

**实现**:

```python
# sidecar.py
@router.post("/{serial}/skip")
async def request_skip(serial: str):
    """设置 skip flag 并清空队列"""
    # 现有逻辑
    _set_skip_flag(serial, True)
    # ... 队列清理 ...

    # 新增：同时创建 followup skip flag 文件
    import tempfile
    from pathlib import Path
    from datetime import datetime

    flag_filename = f"followup_skip_{serial}"
    flag_path = Path(tempfile.gettempdir()) / flag_filename
    flag_path.write_text(datetime.now().isoformat(), encoding="utf-8")

    return {"success": True, "message": "Skip requested"}
```

---

## 推荐方案

**推荐方案 A**：统一使用 Sidecar Skip 机制

**理由**:

1. ✅ 代码更简洁，避免重复机制
2. ✅ `response_detector.py` 已经在使用 `SidecarQueueClient.is_skip_requested()`
3. ✅ 不需要维护两套 skip 系统
4. ✅ 前端 `skipDeviceSync` 函数不需要修改

**实施步骤**:

1. 修改 `followup_device_manager.py:request_skip()` 调用 sidecar API
2. 测试 followup skip 功能
3. 移除不再使用的 followup skip flag 文件相关代码

---

## 相关文档

- `docs/sidecar-skip-button-implementation.md` - Skip 按钮原始实现文档
- `do../04-bugs-and-fixes/active/skip_blocks_next_user.md` - Skip 相关的其他问题

---

## 状态

- [x] 分析 sync skip 机制
- [x] 分析 followup skip 机制
- [x] 识别根本原因：两套独立的 skip 机制
- [x] 提出三种解决方案
- [ ] 实施推荐方案
- [ ] 测试验证
