# Follow-up System 重构升级文档

> 文档创建于：2026-01-19  
> 版本：v1.0  
> 状态：设计文档

## 目录

1. [背景与问题分析](#背景与问题分析)
2. [重构目标](#重构目标)
3. [当前架构分析](#当前架构分析)
4. [新架构设计](#新架构设计)
5. [详细改动方案](#详细改动方案)
6. [Sidecar 集成方案](#sidecar-集成方案)
7. [迁移步骤](#迁移步骤)
8. [代码实现指南](#代码实现指南)
9. [测试计划](#测试计划)
10. [后续优化](#后续优化)

---

## 背景与问题分析

### 当前状态

Follow-up System 最初设计包含两个功能：

- **补刀功能 (Phase 2)**：向未回复的客户发送跟进消息
- **自动回复功能 (Phase 1)**：检测到客户消息后自动生成回复

**当前使用情况**：

- ✅ **自动回复功能**：主要使用中，是核心需求
- ⚠️ **补刀功能**：暂时不使用，存在问题需要后续修复

### 现有问题

| #   | 问题                           | 严重程度 | 说明                                                 |
| --- | ------------------------------ | -------- | ---------------------------------------------------- |
| 1   | **无法多设备并行运行**         | 🔴 严重  | 当前是单进程模型，多设备会相互干扰                   |
| 2   | **暂停/恢复操作复杂**          | 🟡 中等  | 现有的 `pause_for_sync()` 逻辑复杂，与 sync 流程耦合 |
| 3   | **日志混乱**                   | 🟡 中等  | 所有设备的日志混在一起，难以追踪单个设备             |
| 4   | **无人工监督**                 | 🔴 严重  | 自动回复直接发送，没有人工审核环节                   |
| 5   | **架构与 Sync 不一致**         | 🟡 中等  | Sync 使用子进程模型，Followup 使用协程模型           |
| 6   | **Sync 结束后未恢复 FollowUp** | 🔴 严重  | Sync 启动时暂停了 FollowUp，但结束后未调用恢复       |

### 问题深度分析

#### 问题 1：多设备并行问题

**当前实现**：

```python
# scheduler.py - 在扫描循环中顺序处理所有设备
for serial in device_serials:
    result = await self._scanner.scan_device_for_candidates(
        device_serial=serial,
        candidates=ready_candidates
    )
```

**问题**：

- 所有设备共享同一个 `BackgroundScheduler` 实例
- 设备间顺序处理，无法并行
- 如果一个设备卡住，所有设备都会阻塞
- 无法单独控制某个设备的扫描

#### 问题 2：日志问题

**当前实现**：

```python
# service.py
logger = logging.getLogger("followup_service")

# 所有设备共用一个 logger 和一个 WebSocket 端点
# /a../03-impl-and-arch/ws/logs
```

**问题**：

- 日志来自 `followup_service` 而非 `设备-serial`
- 无法在 Sidecar 面板中看到对应设备的 followup 日志
- 日志显示在单独的 FollowUp 页面，而非设备的日志流

#### 问题 3：无人工监督

**当前实现**：

```python
# response_detector.py
async def _generate_reply(self, user_name, messages, serial):
    reply = await self._get_ai_reply(...)

    # 直接发送！没有人工确认环节
    await wecom.input.type_text(reply)
    await wecom.input.send_text_message()
```

**问题**：

- AI 生成的回复直接发送给客户
- 没有经过 Sidecar 队列审核
- 可能发送不恰当的内容

#### 问题 6：Sync 结束后未恢复 FollowUp

**当前实现**：

```python
# Sync 启动时：前端可能调用 /a../03-impl-and-arch/pause
# 但 Sync 进程结束后（无论成功还是失败）都没有调用 /a../03-impl-and-arch/resume

# routers/sync.py - 完全没有调用 followup 相关的暂停/恢复
@router.post("/start")
async def start_sync(request: StartSyncRequest, ...):
    # ... 启动 sync 进程
    # ❌ 没有调用 followup.pause_for_sync()

# DeviceManager._wait_for_completion() - 进程结束时
async def _wait_for_completion(self, serial, process, ...):
    await process.wait()
    # ❌ 没有调用 followup.resume_after_sync()
```

**问题**：

- Sync 启动时暂停了 FollowUp 系统（通过 `_paused_for_sync = True`）
- Sync 进程结束后（完成/失败/停止），没有任何代码调用 `resume_after_sync()`
- FollowUp 系统永远处于暂停状态，直到手动调用恢复 API 或重启服务
- 这导致自动回复功能在 Sync 后完全失效

**影响范围**：

- 所有设备共享同一个 FollowUp 系统状态
- 任何一个设备启动 Sync 都会暂停整个 FollowUp
- 必须手动调用 `/a../03-impl-and-arch/resume` 才能恢复

**解决思路（在新架构中）**：

- 新架构使用 per-device 的 followup 进程
- Sync 和 FollowUp 完全独立，不再相互干扰
- 无需暂停/恢复机制，因为不会共享 UI 控制

---

## 重构目标

### 核心目标

| #   | 目标             | 优先级 | 说明                           |
| --- | ---------------- | ------ | ------------------------------ |
| 1   | **多设备并行**   | P0     | 每个设备一个独立进程，互不干扰 |
| 2   | **接入 Sidecar** | P0     | 所有回复必须经过人工审核       |
| 3   | **统一日志**     | P1     | 日志输出到对应设备的日志流     |
| 4   | **复用现有控制** | P1     | 复用 Sync 的暂停/恢复/停止机制 |

### 非目标（本次不处理）

- 修复补刀功能的具体问题
- 优化 AI 回复质量
- 添加更多的自动化策略

---

## 当前架构分析

### 组件结构

```
servic../03-impl-and-arch/
├── __init__.py           # 模块入口
├── models.py             # 数据模型
├── settings.py           # 设置管理
├── repository.py         # 数据库操作
├── scanner.py            # 补刀扫描器 (Phase 2)
├── response_detector.py  # 响应检测器 (Phase 1)
├── scheduler.py          # 后台调度器
└── service.py            # 主服务入口
```

### 当前运行模型

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI 主进程                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  FollowUpService (单例)                  │    │
│  │                                                         │    │
│  │  ┌─────────────────┐  ┌─────────────────────────────┐   │    │
│  │  │ BackgroundScheduler │  │  Settings/Repository     │   │    │
│  │  │ (单个 asyncio.Task) │  │                           │   │    │
│  │  └────────┬────────┘  └────────────────────────────┘   │    │
│  │           │                                             │    │
│  │           ▼                                             │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │              _scan_loop()                        │    │    │
│  │  │    for serial in device_serials:                 │    │    │
│  │  │        await scan_device(serial)  # 顺序处理!    │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  │                                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌──────────────────────────┐  ┌──────────────────────────┐    │
│  │      Device A            │  │      Device B            │    │
│  │   (等待 A 完成后处理)     │  │   (等待 A 完成后处理)     │    │
│  └──────────────────────────┘  └──────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**问题点**：

- ❌ 单个 `asyncio.Task` 顺序处理所有设备
- ❌ 所有设备共享状态，无法单独控制
- ❌ 日志混在一起

### Sync 的运行模型（参考）

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI 主进程                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  DeviceManager (单例)                    │    │
│  │                                                         │    │
│  │  _processes: Dict[serial, Process]  ← 每个设备独立进程   │    │
│  │  _sync_states: Dict[serial, SyncState]                  │    │
│  │  _log_callbacks: Dict[serial, Set[Callback]]            │    │
│  │                                                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│                          │                                      │
│      ┌───────────────────┼───────────────────┐                 │
│      │                   │                   │                 │
│      ▼                   ▼                   ▼                 │
│   ┌──────────┐       ┌──────────┐       ┌──────────┐           │
│   │ Process A │       │ Process B │       │ Process C │           │
│   │           │       │           │       │           │           │
│   │ sync_v2.py│       │ sync_v2.py│       │ sync_v2.py│           │
│   │ --serial A│       │ --serial B│       │ --serial C│           │
│   └──────────┘       └──────────┘       └──────────┘           │
│       ↑                   ↑                   ↑                 │
│       └───────────────────┴───────────────────┘                 │
│                    独立进程，互不干扰                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**优点**：

- ✅ 每个设备独立子进程
- ✅ 可以单独启动/停止/暂停
- ✅ 日志按设备隔离
- ✅ 一个设备崩溃不影响其他设备

---

## 新架构设计

### 目标架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          FastAPI 主进程                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              FollowUpDeviceManager (新建-效仿 DeviceManager) │    │
│  │                                                             │    │
│  │  _processes: Dict[serial, Process]                          │    │
│  │  _states: Dict[serial, FollowUpState]                       │    │
│  │  _log_callbacks: Dict[serial, Set[Callback]]                │    │
│  │                                                             │    │
│  │  start_followup(serial) → 启动该设备的 followup 进程         │    │
│  │  stop_followup(serial)  → 停止该设备的 followup 进程         │    │
│  │  pause_followup(serial) → 暂停                              │    │
│  │  resume_followup(serial)→ 恢复                              │    │
│  │                                                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                      │
│         ┌────────────────────┼────────────────────┐                 │
│         │                    │                    │                 │
│         ▼                    ▼                    ▼                 │
│   ┌────────────┐       ┌────────────┐       ┌────────────┐          │
│   │ Process A  │       │ Process B  │       │ Process C  │          │
│   │            │       │            │       │            │          │
│   │followup.py │       │followup.py │       │followup.py │          │
│   │--serial A  │       │--serial B  │       │--serial C  │          │
│   │            │       │            │       │            │          │
│   │ 检测回复   │       │ 检测回复   │       │ 检测回复   │          │
│   │     ↓      │       │     ↓      │       │     ↓      │          │
│   │ 生成 AI 回复│      │ 生成 AI 回复│      │ 生成 AI 回复│          │
│   │     ↓      │       │     ↓      │       │     ↓      │          │
│   │ 推送到 Sidecar│    │ 推送到 Sidecar│    │ 推送到 Sidecar│        │
│   │ (等待人工确认)│    │ (等待人工确认)│    │ (等待人工确认)│        │
│   └────────────┘       └────────────┘       └────────────┘          │
│         │                    │                    │                 │
│         └────────────────────┼────────────────────┘                 │
│                              ▼                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │                      Sidecar Queue                           │   │
│   │                                                             │   │
│   │   Device A Queue: [ msg1 (pending) ]                        │   │
│   │   Device B Queue: [ msg2 (ready) ]                          │   │
│   │   Device C Queue: []                                        │   │
│   │                                                             │   │
│   │   操作员在 Sidecar 面板审核并发送                            │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 核心变更点

| 组件                    | 变更          | 说明                                 |
| ----------------------- | ------------- | ------------------------------------ |
| `BackgroundScheduler`   | **废弃/重构** | 不再使用单进程调度模型               |
| `FollowUpDeviceManager` | **新建**      | 效仿 `DeviceManager`，管理多设备进程 |
| `followup_process.py`   | **新建**      | 单设备 followup 脚本（可独立运行）   |
| `response_detector.py`  | **修改**      | 输出到设备日志，通过 Sidecar 发送    |
| 日志系统                | **修改**      | 使用设备对应的 WebSocket 广播        |

---

## 详细改动方案

### 5.1 新建 FollowUpDeviceManager

**文件**: `backend/services/followup_device_manager.py`

```python
"""
Follow-up Device Manager - 管理多设备的 followup 进程

效仿 DeviceManager 的设计，为每个设备启动独立的 followup 子进程。
"""

import asyncio
import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable, Any, Coroutine

# 复用 DeviceManager 的工具类
from .device_manager import _WindowsProcessWrapper, _AsyncStreamReader

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


class FollowUpStatus(str, Enum):
    """Follow-up 运行状态"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class FollowUpState:
    """设备的 follow-up 状态"""
    status: FollowUpStatus = FollowUpStatus.IDLE
    message: str = ""
    responses_detected: int = 0
    replies_queued: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    last_scan_at: Optional[datetime] = None


LogCallback = Callable[[dict], Coroutine[Any, Any, None]]


class FollowUpDeviceManager:
    """
    管理多设备的 follow-up 进程

    每个设备运行在独立的子进程中，互不干扰。
    日志通过回调广播到设备对应的 WebSocket。
    """

    def __init__(self):
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._states: Dict[str, FollowUpState] = {}
        self._log_callbacks: Dict[str, Set[LogCallback]] = {}
        self._read_tasks: Dict[str, asyncio.Task] = {}

    def get_state(self, serial: str) -> Optional[FollowUpState]:
        return self._states.get(serial)

    def get_all_states(self) -> Dict[str, FollowUpState]:
        return self._states.copy()

    def register_log_callback(self, serial: str, callback: LogCallback):
        if serial not in self._log_callbacks:
            self._log_callbacks[serial] = set()
        self._log_callbacks[serial].add(callback)

    async def _broadcast_log(self, serial: str, level: str, message: str):
        """广播日志到该设备的 WebSocket"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": f"[FollowUp] {message}",  # 添加前缀便于识别
            "source": "followup",
        }

        if serial in self._log_callbacks:
            for callback in list(self._log_callbacks[serial]):
                try:
                    await callback(log_entry)
                except Exception:
                    pass

    async def start_followup(
        self,
        serial: str,
        scan_interval: int = 60,
        use_ai_reply: bool = True,
        send_via_sidecar: bool = True,  # 强制通过 Sidecar
    ) -> bool:
        """启动设备的 follow-up 进程"""

        # 检查是否已在运行
        if serial in self._processes:
            process = self._processes[serial]
            if process.returncode is None:
                await self._broadcast_log(serial, "WARNING", "Follow-up already running")
                return False

        # 初始化状态
        self._states[serial] = FollowUpState(
            status=FollowUpStatus.STARTING,
            message="Starting follow-up...",
            started_at=datetime.now(),
        )

        # 构建命令
        script_path = PROJECT_ROOT / "followup_process.py"  # 新脚本

        cmd = [
            "uv", "run",
            str(script_path),
            "--serial", serial,
            "--scan-interval", str(scan_interval),
        ]

        if use_ai_reply:
            cmd.append("--use-ai-reply")

        if send_via_sidecar:
            cmd.append("--send-via-sidecar")  # 强制！

        try:
            await self._broadcast_log(serial, "INFO", f"Starting: {' '.join(cmd)}")

            # 创建子进程（复用 DeviceManager 的方法）
            process = await self._create_subprocess(cmd)

            self._processes[serial] = process
            self._states[serial].status = FollowUpStatus.RUNNING
            self._states[serial].message = "Follow-up running"

            # 启动输出读取
            self._read_tasks[serial] = asyncio.create_task(
                self._read_output(serial, process)
            )

            return True

        except Exception as e:
            self._states[serial].status = FollowUpStatus.ERROR
            self._states[serial].message = str(e)
            await self._broadcast_log(serial, "ERROR", f"Failed to start: {e}")
            return False

    async def stop_followup(self, serial: str) -> bool:
        """停止设备的 follow-up 进程"""
        # ... 复用 DeviceManager.stop_sync() 的逻辑 ...
        pass

    async def pause_followup(self, serial: str) -> bool:
        """暂停设备的 follow-up"""
        # ... 复用 DeviceManager.pause_sync() 的逻辑 ...
        pass

    async def resume_followup(self, serial: str) -> bool:
        """恢复设备的 follow-up"""
        # ... 复用 DeviceManager.resume_sync() 的逻辑 ...
        pass
```

### 5.2 新建 followup_process.py 脚本

**文件**: `followup_process.py` (项目根目录)

```python
#!/usr/bin/env python3
"""
Follow-up Process - 单设备 follow-up 独立脚本

为单个设备运行 follow-up 检测和回复生成。
可被 FollowUpDeviceManager 启动为子进程运行。

Usage:
    python followup_process.py --serial DEVICE_SERIAL [options]
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime

# ... imports ...


def setup_logging(serial: str):
    """设置日志 - 输出到 stdout，由父进程捕获"""
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s | %(levelname)-8s | [{serial}] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger("followup")


async def main(args):
    logger = setup_logging(args.serial)

    logger.info("=" * 60)
    logger.info(f"FOLLOW-UP PROCESS STARTED FOR {args.serial}")
    logger.info("=" * 60)

    # 初始化组件
    # ...

    while True:
        try:
            # 1. 检测未读消息
            logger.info("Checking for unread messages...")
            unread = await detector.scan_for_unread(args.serial)

            if unread:
                logger.info(f"Found {len(unread)} unread conversation(s)")

                for conv in unread:
                    # 2. 生成 AI 回复
                    logger.info(f"Generating reply for {conv.customer_name}...")
                    reply = await ai_service.generate_reply(conv)

                    if args.send_via_sidecar:
                        # 3. 推送到 Sidecar 队列（核心变更！）
                        logger.info(f"Queueing reply to Sidecar for review...")
                        await sidecar_client.queue_message(
                            serial=args.serial,
                            customer_name=conv.customer_name,
                            message=reply,
                            source="followup",
                        )
                        logger.info(f"Reply queued, waiting for operator approval")
                    else:
                        # 直接发送（不推荐，仅用于测试）
                        logger.warning("Direct send mode - no human review!")
                        await send_message(reply)

            # 等待下一个扫描周期
            logger.info(f"Sleeping {args.scan_interval}s until next scan...")
            await asyncio.sleep(args.scan_interval)

        except asyncio.CancelledError:
            logger.info("Follow-up process cancelled")
            break
        except Exception as e:
            logger.error(f"Error in follow-up loop: {e}")
            await asyncio.sleep(30)  # 错误后等待重试


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--scan-interval", type=int, default=60)
    parser.add_argument("--use-ai-reply", action="store_true")
    parser.add_argument("--send-via-sidecar", action="store_true")

    args = parser.parse_args()

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
```

### 5.3 日志输出到设备日志流

**变更**：followup 进程的日志通过 stdout 输出，由 `FollowUpDeviceManager` 捕获并广播到对应设备的 WebSocket。

```python
# FollowUpDeviceManager._read_output()
async def _read_output(self, serial: str, process):
    """读取子进程输出，广播到设备日志"""
    while True:
        line = await process.stdout.readline()
        if not line:
            break

        text = line.decode("utf-8").strip()
        level = self._parse_log_level(text)

        # 广播到该设备的 WebSocket（复用现有机制）
        await self._broadcast_log(serial, level, text)
```

**结果**：

- 日志显示在 Sidecar 面板的日志区域
- 而非单独的 FollowUp 页面
- 每个设备的日志独立

---

## Sidecar 集成方案

### 核心变更：所有回复必须经过 Sidecar 审核

```python
# 当前实现（直接发送）
async def _generate_reply(self, ...):
    reply = await ai_service.get_reply(...)
    await wecom.input.type_text(reply)      # 直接输入
    await wecom.input.send_text_message()   # 直接发送
```

```python
# 新实现（推送到 Sidecar）
async def _generate_reply(self, ...):
    reply = await ai_service.get_reply(...)

    # 推送到 Sidecar 队列，等待操作员确认
    await sidecar_client.queue_message(
        serial=self.serial,
        customer_name=user_name,
        channel=channel,
        message=reply,
        source="followup",  # 标记来源
        is_ai_generated=True,
    )

    # 日志记录
    logger.info(f"[Sidecar] Reply queued for {user_name}, awaiting approval")

    # 不再直接发送！
```

### Sidecar 队列消息格式

```python
@dataclass
class QueuedMessage:
    id: str
    serial: str
    customer_name: str
    channel: Optional[str]
    message: str
    status: Literal["pending", "ready", "sent", "rejected"]
    source: Literal["sync", "followup", "manual"]  # 新增 followup
    is_ai_generated: bool
    created_at: datetime
```

### 前端 Sidecar 面板变更

| 变更             | 说明                              |
| ---------------- | --------------------------------- |
| **消息来源标记** | 显示消息是来自 sync 还是 followup |
| **AI 标记**      | 显示是否为 AI 生成的回复          |
| **自动刷新**     | 检测到新队列消息时刷新            |

---

## 迁移步骤

### Phase 1: 创建新组件 (Day 1)

- [ ] 创建 `FollowUpDeviceManager` 类
- [ ] 创建 `followup_process.py` 脚本
- [ ] 复用 `DeviceManager` 的进程管理代码

### Phase 2: 迁移 ResponseDetector (Day 2)

- [ ] 修改 `response_detector.py` 支持独立运行
- [ ] 修改日志输出到 stdout（而非自定义 WebSocket）
- [ ] 修改发送逻辑：推送到 Sidecar 而非直接发送

### Phase 3: 添加 API 端点 (Day 2)

- [ ] `POST /a../03-impl-and-arch/start/{serial}` - 启动设备 followup
- [ ] `POST /a../03-impl-and-arch/stop/{serial}` - 停止设备 followup
- [ ] `POST /a../03-impl-and-arch/pause/{serial}` - 暂停
- [ ] `POST /a../03-impl-and-arch/resume/{serial}` - 恢复
- [ ] `GET /a../03-impl-and-arch/status/{serial}` - 获取状态
- [ ] `GET /a../03-impl-and-arch/status` - 获取所有设备状态

### Phase 4: 前端集成 (Day 3)

- [ ] 在 Sidecar 面板添加 Follow-up 启动/停止按钮
- [ ] 在设备列表显示 Follow-up 状态
- [ ] 队列消息显示来源标记

### Phase 5: 测试与清理 (Day 4)

- [ ] 多设备并行测试
- [ ] Sidecar 队列测试
- [ ] 废弃旧的 `BackgroundScheduler` 代码
- [ ] 更新文档

---

## 代码实现指南

### 8.1 关键文件变更清单

| 文件                                                     | 操作          | 说明                 |
| -------------------------------------------------------- | ------------- | -------------------- |
| `backend/services/followup_device_manager.py`            | **新建**      | 多设备进程管理       |
| `followup_process.py`                                    | **新建**      | 单设备 followup 脚本 |
| `backend/routers/followup.py`                            | **修改**      | 添加新 API           |
| `backend/servic../03-impl-and-arch/response_detector.py` | **修改**      | 接入 Sidecar         |
| `backend/servic../03-impl-and-arch/scheduler.py`         | **废弃/保留** | 标记为废弃，保留兼容 |
| `backend/servic../03-impl-and-arch/queue.py`             | **修改**      | 支持 followup 来源   |
| `src/views/SidecarView.vue`                              | **修改**      | 添加 followup 控制   |

### 8.2 API 接口设计

```python
# backend/routers/followup.py

@router.post("/device/{serial}/start")
async def start_device_followup(
    serial: str,
    options: FollowUpOptions = FollowUpOptions(),
) -> dict:
    """启动指定设备的 follow-up"""
    manager = get_followup_device_manager()
    success = await manager.start_followup(
        serial=serial,
        scan_interval=options.scan_interval,
        use_ai_reply=options.use_ai_reply,
        send_via_sidecar=True,  # 强制
    )
    return {"success": success, "serial": serial}


@router.post("/device/{serial}/stop")
async def stop_device_followup(serial: str) -> dict:
    """停止指定设备的 follow-up"""
    manager = get_followup_device_manager()
    success = await manager.stop_followup(serial)
    return {"success": success, "serial": serial}


@router.get("/device/{serial}/status")
async def get_device_followup_status(serial: str) -> dict:
    """获取指定设备的 follow-up 状态"""
    manager = get_followup_device_manager()
    state = manager.get_state(serial)
    return {
        "serial": serial,
        "status": state.status.value if state else "idle",
        "message": state.message if state else "",
    }


@router.get("/devices/status")
async def get_all_followup_status() -> dict:
    """获取所有设备的 follow-up 状态"""
    manager = get_followup_device_manager()
    states = manager.get_all_states()
    return {
        serial: {
            "status": state.status.value,
            "message": state.message,
        }
        for serial, state in states.items()
    }
```

---

## 测试计划

### 9.1 单元测试

```python
# tests/test_followup_device_manager.py

class TestFollowUpDeviceManager:
    async def test_start_single_device(self):
        """测试启动单个设备的 followup"""
        pass

    async def test_start_multiple_devices(self):
        """测试同时启动多个设备"""
        pass

    async def test_stop_one_device_while_others_run(self):
        """测试停止一个设备不影响其他设备"""
        pass

    async def test_logs_go_to_correct_device(self):
        """测试日志输出到正确的设备"""
        pass
```

### 9.2 集成测试

- [ ] 3 台设备同时运行 followup
- [ ] 停止其中 1 台，其他继续
- [ ] 暂停/恢复操作
- [ ] 日志显示在正确的 Sidecar 面板
- [ ] AI 回复正确推送到 Sidecar 队列
- [ ] 操作员审核后消息正确发送

---

## 后续优化

### 10.1 补刀功能修复 (后续版本)

- 补刀逻辑重新设计
- 与自动回复功能解耦
- 独立的补刀策略配置

### 10.2 性能优化

- 进程池复用
- 减少进程创建开销
- 批量处理未读消息

### 10.3 监控与告警

- 添加 followup 运行状态监控
- 异常情况告警
- 操作日志记录

---

## 附录：文件对照表

| 当前文件                                         | 新文件/变更                           | 说明                       |
| ------------------------------------------------ | ------------------------------------- | -------------------------- |
| `servic../03-impl-and-arch/scheduler.py`         | 废弃                                  | 单进程调度器不再使用       |
| `servic../03-impl-and-arch/service.py`           | 保留+修改                             | 移除调度相关，保留工具方法 |
| `servic../03-impl-and-arch/response_detector.py` | 修改                                  | 接入 Sidecar               |
| `servic../03-impl-and-arch/scanner.py`           | 保留                                  | 补刀功能，暂不改动         |
| -                                                | `services/followup_device_manager.py` | 新建：多设备管理           |
| -                                                | `followup_process.py`                 | 新建：独立运行脚本         |
| `routers/followup.py`                            | 修改                                  | 添加新 API                 |
