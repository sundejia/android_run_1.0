# FollowUp 暂停/恢复机制修复方案

> 文档创建于：2026-01-19  
> 版本：v1.0  
> 状态：实现文档  
> 关联：[docs/followup_system_refactor.md](./followup_system_refactor.md) - 问题 2 & 问题 6

## 目录

1. [问题分析](#问题分析)
2. [修复方案概述](#修复方案概述)
3. [方案 A：在新多设备架构中解决](#方案-a在新多设备架构中解决)
4. [方案 B：临时修复现有架构](#方案-b临时修复现有架构)
5. [推荐选择](#推荐选择)
6. [代码实现](#代码实现)

---

## 问题分析

### 涉及的两个问题

| #   | 问题                           | 严重程度 | 说明                                                 |
| --- | ------------------------------ | -------- | ---------------------------------------------------- |
| 2   | **暂停/恢复操作复杂**          | 🟡 中等  | 现有的 `pause_for_sync()` 逻辑复杂，与 sync 流程耦合 |
| 6   | **Sync 结束后未恢复 FollowUp** | 🔴 严重  | Sync 启动时暂停了 FollowUp，但结束后未调用恢复       |

### 当前实现分析

#### 暂停/恢复 API

```python
# routers/followup.py

@router.post("/pause")
async def pause_for_sync():
    """Sync 启动前调用"""
    service = get_followup_service()
    result = await service.pause_for_sync()
    return result

@router.post("/resume")
async def resume_after_sync():
    """Sync 结束后调用（但现在没人调用！）"""
    service = get_followup_service()
    result = await service.resume_after_sync()
    return result
```

#### 暂停逻辑

```python
# scheduler.py

async def pause_for_sync(self) -> Dict[str, Any]:
    """暂停（用于全量同步）"""
    self._logger.info("Pausing follow-up system for full sync...")

    # 记录暂停前的状态
    self._was_running_before_pause = self._running
    self._paused_for_sync = True

    # 请求取消正在进行的扫描
    self._scanner.request_cancel()
    self._detector.request_cancel()

    # 等待扫描完成
    await asyncio.sleep(2)

    return {
        'paused': True,
        'was_running': self._was_running_before_pause,
        'message': 'Follow-up system paused for sync'
    }
```

#### 恢复逻辑

```python
# scheduler.py

async def resume_after_sync(self) -> Dict[str, Any]:
    """恢复"""
    self._logger.info("Resuming follow-up system after sync...")

    self._paused_for_sync = False
    self._scanner.reset_cancel()
    self._detector.reset_cancel()

    # 如果暂停前在运行，则重新启动
    if self._was_running_before_pause and not self._running:
        await self.start()

    return {
        'resumed': True,
        'running': self._running,
        'message': 'Follow-up system resumed'
    }
```

### 问题根源

#### 问题 2：暂停/恢复逻辑复杂

1. **全局状态管理**：`_paused_for_sync` 是全局状态，所有设备共享
2. **手动状态恢复**：需要手动记录 `_was_running_before_pause`
3. **取消机制复杂**：需要同时取消 scanner 和 detector
4. **等待逻辑硬编码**：`await asyncio.sleep(2)` 是硬编码等待

```python
# 复杂的状态管理
self._was_running_before_pause = self._running  # 记录状态
self._paused_for_sync = True                    # 设置暂停标志
self._scanner.request_cancel()                   # 取消 scanner
self._detector.request_cancel()                  # 取消 detector
await asyncio.sleep(2)                          # 硬编码等待
```

#### 问题 6：Sync 结束后未恢复

**关键问题**：Sync 流程中没有任何代码调用 `resume_after_sync()`

```python
# routers/sync.py - 启动 sync 时
@router.post("/start")
async def start_sync(request: StartSyncRequest, ...):
    manager = get_device_manager()
    await manager.start_sync(...)
    # ❌ 没有调用 pause_for_sync()，但前端可能调用

# device_manager.py - sync 进程结束时
async def _wait_for_completion(self, serial, process, ...):
    await process.wait()
    # 更新状态
    state.status = SyncStatus.COMPLETED  # 或 ERROR
    # ❌ 没有调用 resume_after_sync()
```

**调用链分析**：

```
1. 前端启动 Sync
   └── 可能调用 /a../03-impl-and-arch/pause (不确定)

2. Sync 进程运行
   └── 完全独立，不知道 FollowUp 的存在

3. Sync 进程结束
   └── DeviceManager._wait_for_completion()
       └── 更新状态为 COMPLETED/ERROR/STOPPED
       └── ❌ 没有调用 resume_after_sync()

4. FollowUp 永远处于暂停状态
   └── _paused_for_sync = True (永远)
   └── 扫描循环检测到暂停，跳过处理
```

---

## 修复方案概述

### 两个可选方案

| 方案       | 说明                 | 优点                        | 缺点               |
| ---------- | -------------------- | --------------------------- | ------------------ |
| **方案 A** | 在新多设备架构中解决 | 彻底解决，无需暂停/恢复机制 | 依赖多设备架构实现 |
| **方案 B** | 临时修复现有架构     | 快速修复，可立即部署        | 治标不治本         |

---

## 方案 A：在新多设备架构中解决

### 核心思路

在新多设备架构中，每个设备的 FollowUp 和 Sync 是完全独立的进程，**不再需要暂停/恢复机制**。

```
新架构：

Device A:
  ├── Sync 进程 (独立)
  └── FollowUp 进程 (独立)

Device B:
  ├── Sync 进程 (独立)
  └── FollowUp 进程 (独立)
```

### 为什么不需要暂停/恢复？

**当前架构需要暂停的原因**：

1. FollowUp 和 Sync 共享同一个 WeCom UI
2. FollowUp 扫描时可能干扰 Sync 的 UI 操作
3. 两者在同一个 asyncio 事件循环中运行

**新架构不需要暂停的原因**：

1. 每个设备有独立的 FollowUp 进程和 Sync 进程
2. 用户可以选择只运行其中一个
3. 如果需要同时运行，在 Sidecar 层面协调（队列机制）
4. 不再有"暂停 FollowUp 让路给 Sync"的需求

### 新架构的设备控制

```python
# 新 API 设计

# 启动设备的 FollowUp
POST /a../03-impl-and-arch/device/{serial}/start

# 停止设备的 FollowUp
POST /a../03-impl-and-arch/device/{serial}/stop

# 暂停设备的 FollowUp（进程级暂停，非业务暂停）
POST /a../03-impl-and-arch/device/{serial}/pause

# 恢复设备的 FollowUp
POST /a../03-impl-and-arch/device/{serial}/resume
```

### 用户交互流程

```
场景：用户想对设备 A 执行 Sync

旧流程:
  1. 调用 /a../03-impl-and-arch/pause (暂停全局 FollowUp)
  2. 调../03-impl-and-arch/key-modules/sync/start (启动 Sync)
  3. Sync 完成
  4. 调用 /a../03-impl-and-arch/resume (恢复全局 FollowUp) ← 经常忘记！

新流程:
  1. 调用 /a../03-impl-and-arch/device/A/stop (停止设备 A 的 FollowUp)
  2. 调../03-impl-and-arch/key-modules/sync/start (启动 Sync)
  3. Sync 完成
  4. 调用 /a../03-impl-and-arch/device/A/start (可选：重启 FollowUp)

或者更简单:
  1. 直接调../03-impl-and-arch/key-modules/sync/start (Sync 运行时 FollowUp 也可继续监听)
  2. 两者通过 Sidecar 队列协调消息发送
```

### 方案 A 的废弃计划

**需要废弃的 API**：

```python
# 旧 API (保留向后兼容，但标记废弃)
@router.post("/pause")
@deprecated("Use /a../03-impl-and-arch/device/{serial}/stop instead")
async def pause_for_sync():
    ...

@router.post("/resume")
@deprecated("Use /a../03-impl-and-arch/device/{serial}/start instead")
async def resume_after_sync():
    ...
```

---

## 方案 B：临时修复现有架构

如果暂时不实现多设备架构，可以先临时修复问题 6（Sync 结束后未恢复）。

### 修复策略

**核心改动**：在 `DeviceManager._wait_for_completion()` 中调用 `resume_after_sync()`

```python
# device_manager.py

async def _wait_for_completion(self, serial, process, stdout_task, stderr_task):
    """等待进程完成"""
    try:
        await asyncio.gather(stdout_task, stderr_task)
        return_code = await process.wait()

        # ... 更新状态 ...

    finally:
        # 清理
        if serial in self._processes:
            del self._processes[serial]

        # 🔧 新增：检查并恢复 FollowUp
        await self._try_resume_followup()

async def _try_resume_followup(self):
    """尝试恢复 FollowUp（如果所有 Sync 都结束了）"""
    # 只有当没有任何设备在 Sync 时才恢复
    if not self._processes:  # 没有正在运行的 Sync 进程
        try:
            from services.followup_service import get_followup_service
            service = get_followup_service()
            if service.is_paused_for_sync():
                await service.resume_after_sync()
                await self._broadcast_log(
                    serial, "INFO",
                    "All sync completed, FollowUp system resumed"
                )
        except Exception as e:
            await self._broadcast_log(
                serial, "WARNING",
                f"Failed to resume FollowUp: {e}"
            )
```

### 方案 B 的问题

1. **仍然是全局暂停**：一个设备 Sync，所有设备的 FollowUp 都暂停
2. **等待所有 Sync 完成**：只有所有设备 Sync 都结束才恢复
3. **竞态条件**：多个 Sync 同时结束可能导致重复恢复

### 方案 B 的改进版

```python
# 使用引用计数管理暂停状态

class FollowUpPauseManager:
    """管理 FollowUp 暂停状态"""

    def __init__(self):
        self._pause_count = 0
        self._lock = asyncio.Lock()

    async def pause_for_device(self, serial: str):
        """某个设备开始 Sync，增加暂停计数"""
        async with self._lock:
            if self._pause_count == 0:
                # 第一个 Sync，暂停 FollowUp
                service = get_followup_service()
                await service.pause_for_sync()
            self._pause_count += 1
            return self._pause_count

    async def resume_for_device(self, serial: str):
        """某个设备结束 Sync，减少暂停计数"""
        async with self._lock:
            self._pause_count = max(0, self._pause_count - 1)
            if self._pause_count == 0:
                # 所有 Sync 都结束，恢复 FollowUp
                service = get_followup_service()
                await service.resume_after_sync()
            return self._pause_count


# 使用
_pause_manager = FollowUpPauseManager()

# device_manager.py
async def start_sync(self, serial, ...):
    await _pause_manager.pause_for_device(serial)
    # ... 启动进程 ...

async def _wait_for_completion(self, serial, ...):
    try:
        # ... 等待完成 ...
    finally:
        await _pause_manager.resume_for_device(serial)
```

---

## 推荐选择

### 推荐：方案 A

**理由**：

1. **彻底解决问题**：新多设备架构从根本上消除了暂停/恢复的需求
2. **更简单的用户体验**：每个设备独立控制，无需协调
3. **Sidecar 集成**：通过队列机制协调消息发送，更加安全
4. **避免引入更多复杂性**：方案 B 的引用计数机制增加了复杂度

### 时间线

| 阶段 | 内容                         | 时间     |
| ---- | ---------------------------- | -------- |
| 短期 | 如果需要快速修复，实现方案 B | 1-2 小时 |
| 中期 | 实现多设备架构（问题 1）     | 6 小时   |
| 长期 | 废弃旧暂停/恢复 API          | 持续     |

---

## 代码实现

### 6.1 方案 A 的核心实现

**已在 `docs/followup_multidevice_implementation.md` 中详细描述**

关键点：

- `FollowUpDeviceManager` 管理每设备独立进程
- 每个设备的 `start_followup()` / `stop_followup()` 独立控制
- 无需全局暂停/恢复

### 6.2 方案 B 的快速实现

如果需要快速修复问题 6，以下是最小改动：

#### 6.2.1 修改 device_manager.py

```python
# backend/services/device_manager.py

# 在文件顶部添加导入
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from services.followup_service import FollowUpService


class DeviceManager:
    # ... 现有代码 ...

    async def _wait_for_completion(
        self,
        serial: str,
        process: asyncio.subprocess.Process,
        stdout_task: asyncio.Task,
        stderr_task: asyncio.Task,
    ):
        """Wait for subprocess to complete and update state."""
        try:
            # Wait for output readers to complete
            await asyncio.gather(stdout_task, stderr_task)

            # Wait for process to exit
            return_code = await process.wait()

            state = self._sync_states.get(serial)
            if state:
                if return_code == 0:
                    state.status = SyncStatus.COMPLETED
                    state.message = "Sync completed successfully"
                    state.progress = 100
                elif state.status != SyncStatus.STOPPED:
                    state.status = SyncStatus.ERROR
                    state.message = f"Sync failed with exit code {return_code}"

                state.completed_at = datetime.now()
                await self._broadcast_status(serial)
                await self._broadcast_log(
                    serial,
                    "INFO" if return_code == 0 else "ERROR",
                    f"Sync process exited with code {return_code}"
                )

        except asyncio.CancelledError:
            pass
        finally:
            # Cleanup
            if serial in self._processes:
                del self._processes[serial]
            if serial in self._read_tasks:
                del self._read_tasks[serial]

            # 🔧 新增：尝试恢复 FollowUp
            await self._try_resume_followup_if_needed(serial)

    async def _try_resume_followup_if_needed(self, serial: str):
        """
        如果所有 Sync 进程都结束了，恢复 FollowUp 系统
        """
        # 检查是否还有其他设备在 Sync
        if self._processes:
            # 还有其他设备在运行，不恢复
            return

        try:
            from services.followup_service import get_followup_service
            service = get_followup_service()

            # 只有当 FollowUp 处于暂停状态时才恢复
            if service.is_paused_for_sync():
                result = await service.resume_after_sync()
                await self._broadcast_log(
                    serial, "INFO",
                    f"All syncs completed, FollowUp resumed: {result.get('message', '')}"
                )
        except ImportError:
            # FollowUp 服务不可用
            pass
        except Exception as e:
            await self._broadcast_log(
                serial, "WARNING",
                f"Failed to resume FollowUp after sync: {e}"
            )
```

#### 6.2.2 修改 sync.py 路由（确保暂停）

```python
# backend/routers/sync.py

from services.device_manager import DeviceManager, SyncState, SyncStatus

# 添加导入
_followup_paused = False  # 简单标志，跟踪是否已暂停


async def _pause_followup_if_needed():
    """在 Sync 启动前暂停 FollowUp"""
    global _followup_paused
    if _followup_paused:
        return  # 已经暂停

    try:
        from services.followup_service import get_followup_service
        service = get_followup_service()

        if not service.is_paused_for_sync() and service._running:
            await service.pause_for_sync()
            _followup_paused = True
    except ImportError:
        pass
    except Exception as e:
        print(f"[sync] Failed to pause FollowUp: {e}")


@router.post("/start")
async def start_sync(request: StartSyncRequest, background_tasks: BackgroundTasks):
    """启动 Sync"""
    manager = get_device_manager()

    # 🔧 新增：Sync 启动前暂停 FollowUp
    await _pause_followup_if_needed()

    # ... 现有逻辑 ...
```

### 6.3 测试验证

#### 测试用例 1：单设备 Sync 后恢复

```bash
# 1. 启动 FollowUp
curl -X POST http://localhost:8000/a../03-impl-and-arch/scanner/start

# 2. 确认 FollowUp 在运行
curl http://localhost:8000/a../03-impl-and-arch/scan/status
# 预期: running = true

# 3. 启动 Sync
curl -X POST http://localhost:80../03-impl-and-arch/key-modules/sync/start \
  -H "Content-Type: application/json" \
  -d '{"serials": ["device_A"]}'

# 4. 等待 Sync 完成
# ...

# 5. 确认 FollowUp 自动恢复
curl http://localhost:8000/a../03-impl-and-arch/scan/status
# 预期: running = true, paused_for_sync = false
```

#### 测试用例 2：多设备 Sync 后恢复

```bash
# 1. 启动两个设备的 Sync
curl -X POST http://localhost:80../03-impl-and-arch/key-modules/sync/start \
  -H "Content-Type: application/json" \
  -d '{"serials": ["device_A", "device_B"]}'

# 2. 停止设备 A 的 Sync
curl -X POST http://localhost:80../03-impl-and-arch/key-modules/sync/stop/device_A

# 3. 确认 FollowUp 仍暂停（因为 B 还在运行）
curl http://localhost:8000/a../03-impl-and-arch/scan/status
# 预期: paused_for_sync = true

# 4. 等待设备 B 完成
# ...

# 5. 确认 FollowUp 自动恢复
curl http://localhost:8000/a../03-impl-and-arch/scan/status
# 预期: paused_for_sync = false
```

---

## 总结

### 问题 2（暂停/恢复复杂）

- **短期**：保持现状，等待多设备架构
- **长期**：在多设备架构中，每设备独立控制，无需全局暂停/恢复

### 问题 6（Sync 后未恢复）

- **快速修复**：在 `DeviceManager._wait_for_completion()` 中添加恢复逻辑
- **彻底解决**：实现多设备架构后，此问题自动消失

### 文件变更清单

| 方案   | 文件                                             | 变更                                    |
| ------ | ------------------------------------------------ | --------------------------------------- |
| 方案 B | `backend/services/device_manager.py`             | 添加 `_try_resume_followup_if_needed()` |
| 方案 B | `backend/routers/sync.py`                        | 添加 `_pause_followup_if_needed()`      |
| 方案 A | 见 `docs/followup_multidevice_implementation.md` | 全新架构                                |

### 推荐执行顺序

1. **立即**：如果问题 6 影响生产，先应用方案 B
2. **短期**：实现多设备架构（问题 1）
3. **长期**：废弃旧的暂停/恢复 API
