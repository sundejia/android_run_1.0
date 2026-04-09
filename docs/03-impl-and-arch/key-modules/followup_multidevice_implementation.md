# FollowUp 多设备并行实现方案

> 文档创建于：2026-01-19  
> 版本：v1.0  
> 状态：实现文档  
> 关联：[docs/followup_system_refactor.md](./followup_system_refactor.md) - 问题 1

## 目录

1. [目标概述](#目标概述)
2. [Sync 流程参考分析](#sync-流程参考分析)
3. [FollowUp 多设备架构设计](#followup-多设备架构设计)
4. [代码实现详解](#代码实现详解)
5. [文件清单](#文件清单)
6. [测试验收](#测试验收)

---

## 目标概述

### 要解决的问题

**当前问题**：FollowUp 系统使用单进程协程模型，无法多设备并行运行。

```
当前模型：
  FastAPI 主进程
      └── BackgroundScheduler (单个 asyncio.Task)
              └── for serial in devices:
                      await scan_device(serial)  # 顺序！阻塞！
```

### 目标模型

```
目标模型：
  FastAPI 主进程
      └── FollowUpDeviceManager
              ├── Process A: followup_process.py --serial A  # 独立进程
              ├── Process B: followup_process.py --serial B  # 独立进程
              └── Process C: followup_process.py --serial C  # 独立进程
```

### 核心目标

| 目标               | 说明                                                      |
| ------------------ | --------------------------------------------------------- |
| **进程隔离**       | 每个设备运行在独立的 Python 子进程中                      |
| **互不干扰**       | 一个设备卡住不影响其他设备                                |
| **独立控制**       | 可以单独启动/停止/暂停某个设备的 FollowUp                 |
| **复用 Sync 机制** | 复用 `DeviceManager` 的进程管理、日志广播、暂停恢复等机制 |

---

## Sync 流程参考分析

### 2.1 核心组件

Sync 使用以下组件实现多设备并行：

| 组件                 | 文件                                 | 职责           |
| -------------------- | ------------------------------------ | -------------- |
| `DeviceManager`      | `backend/services/device_manager.py` | 管理多设备进程 |
| `initial_sync_v2.py` | 项目根目录                           | 单设备同步脚本 |
| `sync` router        | `backend/routers/sync.py`            | API 端点       |

### 2.2 DeviceManager 核心设计

```python
class DeviceManager:
    def __init__(self):
        # 每个设备一个子进程
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        # 每个设备一个状态
        self._sync_states: Dict[str, SyncState] = {}
        # 每个设备的日志回调
        self._log_callbacks: Dict[str, Set[LogCallback]] = {}
        # 每个设备的读取任务
        self._read_tasks: Dict[str, asyncio.Task] = {}

    async def start_sync(self, serial: str, ...):
        """启动子进程运行 initial_sync_v2.py"""
        cmd = ["uv", "run", "initial_sync_v2.py", "--serial", serial, ...]
        process = await self._create_subprocess(cmd)
        self._processes[serial] = process

        # 启动日志读取
        self._read_tasks[serial] = asyncio.create_task(
            self._read_output(serial, process)
        )

    async def _read_output(self, serial: str, process):
        """读取子进程输出，广播到对应设备的 WebSocket"""
        while True:
            line = await process.stdout.readline()
            await self._broadcast_log(serial, level, text)

    async def stop_sync(self, serial: str):
        """停止子进程"""
        process = self._processes[serial]
        # Windows: taskkill /F /T /PID
        # Unix: process.terminate()

    async def pause_sync(self, serial: str):
        """暂停子进程 (Windows: Job Object, Unix: SIGSTOP)"""

    async def resume_sync(self, serial: str):
        """恢复子进程"""
```

### 2.3 子进程脚本设计

`initial_sync_v2.py` 的关键设计：

```python
#!/usr/bin/env python3
"""单设备同步脚本，可被 DeviceManager 启动为子进程运行"""

def setup_logging(debug=False):
    """日志输出到 stdout，由父进程捕获"""
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        stream=sys.stdout,
    )

async def run(args):
    """主执行流程"""
    logger.info(f"Starting sync for {args.serial}")
    # ... 业务逻辑 ...

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    # ... 其他参数 ...
    asyncio.run(run(args))
```

### 2.4 API 路由设计

```python
# routers/sync.py
@router.post("/start")
async def start_sync(request: StartSyncRequest):
    manager = get_device_manager()
    await manager.start_sync(serial=request.serial, ...)

@router.post("/stop/{serial}")
async def stop_sync(serial: str):
    manager = get_device_manager()
    await manager.stop_sync(serial)

@router.post("/pause/{serial}")
async def pause_sync(serial: str):
    await manager.pause_sync(serial)

@router.post("/resume/{serial}")
async def resume_sync(serial: str):
    await manager.resume_sync(serial)

@router.get("/status/{serial}")
async def get_status(serial: str):
    state = manager.get_sync_state(serial)
    return {"status": state.status, ...}
```

---

## FollowUp 多设备架构设计

### 3.1 目标架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI 主进程                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                   FollowUpDeviceManager (新建)                         │  │
│  │                                                                       │  │
│  │   _processes: Dict[serial, Process]     # 每设备一个子进程            │  │
│  │   _states: Dict[serial, FollowUpState]  # 每设备一个状态              │  │
│  │   _log_callbacks: Dict[serial, Set]     # 每设备日志回调              │  │
│  │                                                                       │  │
│  │   start_followup(serial)  → 启动设备的 followup 进程                  │  │
│  │   stop_followup(serial)   → 停止设备的 followup 进程                  │  │
│  │   pause_followup(serial)  → 暂停                                      │  │
│  │   resume_followup(serial) → 恢复                                      │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                │                                            │
│        ┌───────────────────────┼───────────────────────┐                    │
│        │                       │                       │                    │
│        ▼                       ▼                       ▼                    │
│  ┌───────────────┐      ┌───────────────┐      ┌───────────────┐            │
│  │  子进程 A     │      │  子进程 B     │      │  子进程 C     │            │
│  │               │      │               │      │               │            │
│  │ followup_     │      │ followup_     │      │ followup_     │            │
│  │ process.py    │      │ process.py    │      │ process.py    │            │
│  │ --serial A    │      │ --serial B    │      │ --serial C    │            │
│  │               │      │               │      │               │            │
│  │ 1. 检测红点   │      │ 1. 检测红点   │      │ 1. 检测红点   │            │
│  │ 2. 提取消息   │      │ 2. 提取消息   │      │ 2. 提取消息   │            │
│  │ 3. 生成回复   │      │ 3. 生成回复   │      │ 3. 生成回复   │            │
│  │ 4. 发送回复   │      │ 4. 发送回复   │      │ 4. 发送回复   │            │
│  │ 5. 循环...    │      │ 5. 循环...    │      │ 5. 循环...    │            │
│  │               │      │               │      │               │            │
│  │ stdout ────────────────────┬─────────────────────────────────│           │
│  └───────────────┘      └─────│─────────┘      └───────────────┘            │
│                               │                                             │
│                               ▼                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │              日志 WebSocket 广播 (复用现有机制)                        │  │
│  │                                                                       │  │
│  │   /ws/logs/A  ← 设备 A 的 followup 日志                               │  │
│  │   /ws/logs/B  ← 设备 B 的 followup 日志                               │  │
│  │   /ws/logs/C  ← 设备 C 的 followup 日志                               │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 状态定义

```python
class FollowUpStatus(str, Enum):
    IDLE = "idle"           # 未启动
    STARTING = "starting"   # 正在启动
    RUNNING = "running"     # 运行中
    PAUSED = "paused"       # 已暂停
    STOPPED = "stopped"     # 已停止
    ERROR = "error"         # 错误

@dataclass
class FollowUpState:
    status: FollowUpStatus = FollowUpStatus.IDLE
    message: str = ""
    responses_detected: int = 0     # 检测到的回复数
    replies_sent: int = 0           # 发送的回复数
    last_scan_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
```

### 3.3 进程间通信

**日志输出**：子进程通过 stdout 输出日志，父进程读取并广播。

```
子进程 stdout 格式：
21:30:15 | INFO     | [FollowUp] Checking for unread messages...
21:30:16 | INFO     | [FollowUp] Found 2 unread user(s)
21:30:17 | INFO     | [FollowUp] Processing user: 张三
21:30:20 | INFO     | [FollowUp] Generated reply, sending...
21:30:22 | INFO     | [FollowUp] Reply sent successfully
```

**状态更新**：通过解析日志内容更新状态。

```python
async def _parse_and_update_state(self, serial: str, message: str, level: str):
    state = self._states.get(serial)

    if "Found" in message and "unread" in message:
        match = re.search(r"Found (\d+) unread", message)
        if match:
            state.responses_detected = int(match.group(1))

    if "Reply sent" in message:
        state.replies_sent += 1
        state.last_scan_at = datetime.now()
```

---

## 代码实现详解

### 4.1 FollowUpDeviceManager 完整实现

**文件**: `backend/services/followup_device_manager.py`

```python
"""
Follow-up Device Manager - 管理多设备的 followup 进程

效仿 DeviceManager 的设计，为每个设备启动独立的 followup 子进程。
"""

import asyncio
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable, Any, Coroutine

# 复用 DeviceManager 的工具类
from .device_manager import _WindowsProcessWrapper, _AsyncStreamReader

# Windows Job Objects for pause/resume
if platform.system() == "Windows":
    try:
        from utils.windows_job import get_job_manager
    except ImportError:
        from backend.utils.windows_job import get_job_manager

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
    replies_sent: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    last_scan_at: Optional[datetime] = None


LogCallback = Callable[[dict], Coroutine[Any, Any, None]]
StatusCallback = Callable[[dict], Coroutine[Any, Any, None]]


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
        self._status_callbacks: Dict[str, Set[StatusCallback]] = {}
        self._read_tasks: Dict[str, asyncio.Task] = {}

    # ==================== 状态查询 ====================

    def get_state(self, serial: str) -> Optional[FollowUpState]:
        """获取设备的 followup 状态"""
        return self._states.get(serial)

    def get_all_states(self) -> Dict[str, FollowUpState]:
        """获取所有设备的 followup 状态"""
        return self._states.copy()

    def is_running(self, serial: str) -> bool:
        """检查设备的 followup 是否在运行"""
        state = self._states.get(serial)
        if not state:
            return False
        return state.status in (FollowUpStatus.RUNNING, FollowUpStatus.STARTING)

    # ==================== 回调注册 ====================

    def register_log_callback(self, serial: str, callback: LogCallback):
        """注册日志回调"""
        if serial not in self._log_callbacks:
            self._log_callbacks[serial] = set()
        self._log_callbacks[serial].add(callback)

    def unregister_log_callback(self, serial: str, callback: LogCallback):
        """注销日志回调"""
        if serial in self._log_callbacks:
            self._log_callbacks[serial].discard(callback)

    def register_status_callback(self, serial: str, callback: StatusCallback):
        """注册状态回调"""
        if serial not in self._status_callbacks:
            self._status_callbacks[serial] = set()
        self._status_callbacks[serial].add(callback)

    # ==================== 广播 ====================

    async def _broadcast_log(self, serial: str, level: str, message: str):
        """广播日志到该设备的 WebSocket"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "source": "followup",
        }

        if serial in self._log_callbacks:
            for callback in list(self._log_callbacks[serial]):
                try:
                    await callback(log_entry)
                except Exception:
                    pass

    async def _broadcast_status(self, serial: str):
        """广播状态更新"""
        state = self._states.get(serial)
        if not state:
            return

        status_data = {
            "status": state.status.value,
            "message": state.message,
            "responses_detected": state.responses_detected,
            "replies_sent": state.replies_sent,
        }

        if serial in self._status_callbacks:
            for callback in list(self._status_callbacks[serial]):
                try:
                    await callback(status_data)
                except Exception:
                    pass

    # ==================== 核心操作 ====================

    async def start_followup(
        self,
        serial: str,
        scan_interval: int = 60,
        use_ai_reply: bool = True,
        send_via_sidecar: bool = True,
    ) -> bool:
        """
        启动设备的 follow-up 进程

        Args:
            serial: 设备序列号
            scan_interval: 扫描间隔（秒）
            use_ai_reply: 是否使用 AI 生成回复
            send_via_sidecar: 是否通过 Sidecar 发送（人工审核）

        Returns:
            是否启动成功
        """
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
        await self._broadcast_status(serial)

        # 构建命令
        script_path = PROJECT_ROOT / "followup_process.py"

        cmd = [
            "uv", "run",
            str(script_path),
            "--serial", serial,
            "--scan-interval", str(scan_interval),
        ]

        if use_ai_reply:
            cmd.append("--use-ai-reply")

        if send_via_sidecar:
            cmd.append("--send-via-sidecar")

        try:
            await self._broadcast_log(serial, "INFO", f"Starting: {' '.join(cmd)}")

            # 设置环境变量
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            # 创建子进程
            if platform.system() == "Windows":
                process = await self._create_subprocess_windows(cmd, env)
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(PROJECT_ROOT),
                    env=env,
                    start_new_session=True,
                )

            self._processes[serial] = process
            self._states[serial].status = FollowUpStatus.RUNNING
            self._states[serial].message = "Follow-up running"
            await self._broadcast_status(serial)

            # Windows: 创建 Job Object
            if platform.system() == "Windows":
                try:
                    job_manager = get_job_manager()
                    job_manager.create_job(f"followup_{serial}")
                    job_manager.add_process(f"followup_{serial}", process.pid)
                except Exception as e:
                    await self._broadcast_log(serial, "WARNING", f"Failed to create job: {e}")

            # 启动输出读取
            stdout_task = asyncio.create_task(
                self._read_output(serial, process.stdout, is_stderr=False)
            )
            stderr_task = asyncio.create_task(
                self._read_output(serial, process.stderr, is_stderr=True)
            )

            # 启动等待完成任务
            self._read_tasks[serial] = asyncio.create_task(
                self._wait_for_completion(serial, process, stdout_task, stderr_task)
            )

            return True

        except Exception as e:
            self._states[serial].status = FollowUpStatus.ERROR
            self._states[serial].message = str(e)
            self._states[serial].errors.append(str(e))
            await self._broadcast_status(serial)
            await self._broadcast_log(serial, "ERROR", f"Failed to start: {e}")
            return False

    async def stop_followup(self, serial: str) -> bool:
        """停止设备的 follow-up 进程"""
        state = self._states.get(serial)

        if serial not in self._processes:
            if state and state.status in (FollowUpStatus.RUNNING, FollowUpStatus.STARTING):
                state.status = FollowUpStatus.STOPPED
                state.message = "Follow-up stopped (process not found)"
                await self._broadcast_status(serial)
                return True
            return False

        process = self._processes[serial]

        if process.returncode is not None:
            del self._processes[serial]
            if state:
                state.status = FollowUpStatus.STOPPED
                state.message = "Follow-up stopped"
                await self._broadcast_status(serial)
            return True

        if state:
            state.status = FollowUpStatus.STOPPED
            state.message = "Stopping follow-up..."
            await self._broadcast_status(serial)

        await self._broadcast_log(serial, "WARNING", "Stopping follow-up...")

        try:
            if platform.system() == "Windows":
                try:
                    result = await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        timeout=5.0,
                    )
                    if result.returncode != 0:
                        process.terminate()
                except Exception:
                    process.terminate()
            else:
                process.terminate()

            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

            if serial in self._read_tasks:
                self._read_tasks[serial].cancel()
                del self._read_tasks[serial]

            if serial in self._processes:
                del self._processes[serial]

            if state:
                state.status = FollowUpStatus.STOPPED
                state.message = "Follow-up stopped"
                await self._broadcast_status(serial)

            await self._broadcast_log(serial, "INFO", "Follow-up stopped")

            # Windows: 清理 Job Object
            if platform.system() == "Windows":
                try:
                    job_manager = get_job_manager()
                    job_manager.terminate_job(f"followup_{serial}")
                except Exception:
                    pass

            return True

        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to stop: {e}")
            return False

    async def pause_followup(self, serial: str) -> bool:
        """暂停设备的 follow-up"""
        state = self._states.get(serial)

        if not state or state.status != FollowUpStatus.RUNNING:
            return False

        if serial not in self._processes:
            return False

        process = self._processes[serial]

        if process.returncode is not None:
            return False

        try:
            if platform.system() == "Windows":
                job_manager = get_job_manager()
                success = job_manager.suspend_job(f"followup_{serial}")
                if success:
                    state.status = FollowUpStatus.PAUSED
                    state.message = "Follow-up paused"
                    await self._broadcast_status(serial)
                    await self._broadcast_log(serial, "INFO", "Follow-up paused")
                    return True
                return False
            else:
                import signal
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGSTOP)
                state.status = FollowUpStatus.PAUSED
                state.message = "Follow-up paused"
                await self._broadcast_status(serial)
                await self._broadcast_log(serial, "INFO", "Follow-up paused")
                return True
        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to pause: {e}")
            return False

    async def resume_followup(self, serial: str) -> bool:
        """恢复设备的 follow-up"""
        state = self._states.get(serial)

        if not state or state.status != FollowUpStatus.PAUSED:
            return False

        if serial not in self._processes:
            return False

        process = self._processes[serial]

        if process.returncode is not None:
            return False

        try:
            if platform.system() == "Windows":
                job_manager = get_job_manager()
                success = job_manager.resume_job(f"followup_{serial}")
                if success:
                    state.status = FollowUpStatus.RUNNING
                    state.message = "Follow-up resumed"
                    await self._broadcast_status(serial)
                    await self._broadcast_log(serial, "INFO", "Follow-up resumed")
                    return True
                return False
            else:
                import signal
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGCONT)
                state.status = FollowUpStatus.RUNNING
                state.message = "Follow-up resumed"
                await self._broadcast_status(serial)
                await self._broadcast_log(serial, "INFO", "Follow-up resumed")
                return True
        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to resume: {e}")
            return False

    async def stop_all(self):
        """停止所有设备的 follow-up"""
        serials = list(self._processes.keys())
        for serial in serials:
            await self.stop_followup(serial)

    # ==================== 内部方法 ====================

    async def _create_subprocess_windows(self, cmd: List[str], env: dict):
        """Windows 下创建子进程"""
        cmd_str = " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd)

        def _create():
            return subprocess.Popen(
                cmd_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
                env=env,
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

        popen = await asyncio.to_thread(_create)
        return _WindowsProcessWrapper(popen)

    def _decode_output(self, data: bytes) -> str:
        """解码子进程输出"""
        if not data:
            return ""
        try:
            return data.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            if platform.system() == "Windows":
                try:
                    return data.decode("gbk").rstrip()
                except:
                    pass
            return data.decode("utf-8", errors="replace").rstrip()

    async def _read_output(self, serial: str, stream, is_stderr: bool = False):
        """读取子进程输出并广播"""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break

                text = self._decode_output(line)
                if not text:
                    continue

                # 解析日志级别
                level = "INFO"
                match = re.match(r"[\d:]+\s*\|\s*(\w+)\s*\|\s*(.+)", text)
                if match:
                    parsed_level = match.group(1).upper()
                    if parsed_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
                        level = parsed_level
                    text = match.group(2)

                # 更新状态
                await self._parse_and_update_state(serial, text, level)

                # 广播日志
                await self._broadcast_log(serial, level, text)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Output read error: {e}")

    async def _parse_and_update_state(self, serial: str, message: str, level: str):
        """解析日志更新状态"""
        state = self._states.get(serial)
        if not state:
            return

        # 更新检测数
        if "Found" in message and "unread" in message:
            match = re.search(r"Found\s+(\d+)\s+unread", message)
            if match:
                state.responses_detected += int(match.group(1))

        # 更新发送数
        if "Reply sent" in message or "sent successfully" in message:
            state.replies_sent += 1
            state.last_scan_at = datetime.now()

        # 更新状态消息
        if level == "INFO" and "unread" in message.lower():
            state.message = message

        # 记录错误
        if level == "ERROR":
            state.errors.append(message)
            if len(state.errors) > 50:
                state.errors = state.errors[-50:]

        await self._broadcast_status(serial)

    async def _wait_for_completion(self, serial: str, process, stdout_task, stderr_task):
        """等待进程完成"""
        try:
            await asyncio.gather(stdout_task, stderr_task)
            return_code = await process.wait()

            state = self._states.get(serial)
            if state:
                if return_code == 0:
                    state.status = FollowUpStatus.STOPPED
                    state.message = "Follow-up completed"
                elif state.status != FollowUpStatus.STOPPED:
                    state.status = FollowUpStatus.ERROR
                    state.message = f"Follow-up exited with code {return_code}"
                    state.errors.append(f"Exit code: {return_code}")
                await self._broadcast_status(serial)
        except asyncio.CancelledError:
            pass
        finally:
            if serial in self._processes:
                del self._processes[serial]
            if serial in self._read_tasks:
                del self._read_tasks[serial]


# ==================== 单例管理 ====================

_followup_device_manager: Optional[FollowUpDeviceManager] = None


def get_followup_device_manager() -> FollowUpDeviceManager:
    """获取或创建 FollowUpDeviceManager 单例"""
    global _followup_device_manager
    if _followup_device_manager is None:
        _followup_device_manager = FollowUpDeviceManager()
    return _followup_device_manager
```

### 4.2 followup_process.py 子进程脚本

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
from pathlib import Path
from typing import Optional

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def setup_logging(serial: str, debug: bool = False):
    """设置日志 - 输出到 stdout，由父进程捕获"""
    level = logging.DEBUG if debug else logging.INFO

    logging.basicConfig(
        level=level,
        format=f"%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    # 确保 stdout 刷新
    sys.stdout.reconfigure(line_buffering=True)

    return logging.getLogger("followup")


async def run(args):
    """主执行流程"""
    logger = setup_logging(args.serial, args.debug)

    logger.info("=" * 60)
    logger.info(f"FOLLOW-UP PROCESS STARTED FOR {args.serial}")
    logger.info("=" * 60)
    logger.info(f"Configuration:")
    logger.info(f"   - Scan Interval: {args.scan_interval}s")
    logger.info(f"   - Use AI Reply: {args.use_ai_reply}")
    logger.info(f"   - Send via Sidecar: {args.send_via_sidecar}")
    logger.info("=" * 60)

    # 导入必要模块
    try:
        from wecom_automation.core.config import get_default_db_path
        from wecom_automation.services.wecom import WeComService
        from wecom_automation.services.ai.reply_service import AIReplyService
        from wecom_automation.services.integration.sidecar import SidecarQueueClient

        # 导入 FollowUp 组件（复用现有逻辑）
        from wecom_desktop.backend.services.followup.repository import FollowUpRepository
        from wecom_desktop.backend.services.followup.settings import SettingsManager
        from wecom_desktop.backend.services.followup.response_detector import ResponseDetector
    except ImportError as e:
        # 备用导入路径
        logger.warning(f"Import warning: {e}, trying alternative paths...")
        sys.path.insert(0, str(PROJECT_ROOT / "wecom-desktop" / "backend"))

        from services.followup.repository import FollowUpRepository
        from services.followup.settings import SettingsManager
        from services.followup.response_detector import ResponseDetector

    # 初始化组件
    db_path = str(get_default_db_path())
    repository = FollowUpRepository(db_path)
    settings_manager = SettingsManager(db_path)
    detector = ResponseDetector(repository, settings_manager, logger)

    # Sidecar 客户端
    sidecar_client = None
    if args.send_via_sidecar:
        try:
            sidecar_client = SidecarQueueClient()
            logger.info("Sidecar client initialized")
        except Exception as e:
            logger.warning(f"Failed to init Sidecar client: {e}")

    # 主循环
    scan_count = 0
    while True:
        try:
            scan_count += 1
            logger.info("")
            logger.info(f"[Scan #{scan_count}] Checking for unread messages...")

            # 调用检测器
            result = await detector.detect_and_reply(
                device_serial=args.serial,
                interactive_wait_timeout=40,
            )

            # 报告结果
            responses = result.get("responses_detected", 0)
            if responses > 0:
                logger.info(f"[Scan #{scan_count}] Processed {responses} response(s)")
            else:
                logger.info(f"[Scan #{scan_count}] No unread messages")

            # 等待下一个扫描周期
            logger.info(f"Sleeping {args.scan_interval}s until next scan...")
            await asyncio.sleep(args.scan_interval)

        except asyncio.CancelledError:
            logger.info("Follow-up process cancelled")
            break
        except KeyboardInterrupt:
            logger.info("Follow-up process interrupted")
            break
        except Exception as e:
            logger.error(f"Error in follow-up loop: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.info("Waiting 30s before retry...")
            await asyncio.sleep(30)

    logger.info("Follow-up process exiting")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Follow-up process for a single device"
    )

    parser.add_argument(
        "--serial",
        required=True,
        help="Device serial number"
    )

    parser.add_argument(
        "--scan-interval",
        type=int,
        default=60,
        help="Scan interval in seconds (default: 60)"
    )

    parser.add_argument(
        "--use-ai-reply",
        action="store_true",
        help="Use AI to generate replies"
    )

    parser.add_argument(
        "--send-via-sidecar",
        action="store_true",
        help="Send via Sidecar for human review"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    return parser.parse_args()


def main():
    """入口函数"""
    args = parse_args()

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 4.3 API 路由更新

**文件**: `backend/routers/followup.py` (新增端点)

```python
# ============================================
# 新增：多设备 FollowUp API
# ============================================

from services.followup_device_manager import (
    get_followup_device_manager,
    FollowUpStatus,
)


class FollowUpDeviceOptions(BaseModel):
    """设备 FollowUp 选项"""
    scan_interval: int = 60
    use_ai_reply: bool = True
    send_via_sidecar: bool = True


@router.post("/device/{serial}/start")
async def start_device_followup(
    serial: str,
    options: FollowUpDeviceOptions = FollowUpDeviceOptions(),
):
    """启动指定设备的 follow-up 进程"""
    manager = get_followup_device_manager()

    success = await manager.start_followup(
        serial=serial,
        scan_interval=options.scan_interval,
        use_ai_reply=options.use_ai_reply,
        send_via_sidecar=options.send_via_sidecar,
    )

    return {"success": success, "serial": serial}


@router.post("/device/{serial}/stop")
async def stop_device_followup(serial: str):
    """停止指定设备的 follow-up 进程"""
    manager = get_followup_device_manager()
    success = await manager.stop_followup(serial)
    return {"success": success, "serial": serial}


@router.post("/device/{serial}/pause")
async def pause_device_followup(serial: str):
    """暂停指定设备的 follow-up"""
    manager = get_followup_device_manager()
    success = await manager.pause_followup(serial)
    return {"success": success, "serial": serial}


@router.post("/device/{serial}/resume")
async def resume_device_followup(serial: str):
    """恢复指定设备的 follow-up"""
    manager = get_followup_device_manager()
    success = await manager.resume_followup(serial)
    return {"success": success, "serial": serial}


@router.get("/device/{serial}/status")
async def get_device_followup_status(serial: str):
    """获取指定设备的 follow-up 状态"""
    manager = get_followup_device_manager()
    state = manager.get_state(serial)

    if not state:
        return {
            "serial": serial,
            "status": "idle",
            "message": "Not running",
        }

    return {
        "serial": serial,
        "status": state.status.value,
        "message": state.message,
        "responses_detected": state.responses_detected,
        "replies_sent": state.replies_sent,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "last_scan_at": state.last_scan_at.isoformat() if state.last_scan_at else None,
    }


@router.get("/devices/status")
async def get_all_device_followup_status():
    """获取所有设备的 follow-up 状态"""
    manager = get_followup_device_manager()
    states = manager.get_all_states()

    return {
        serial: {
            "status": state.status.value,
            "message": state.message,
            "responses_detected": state.responses_detected,
            "replies_sent": state.replies_sent,
        }
        for serial, state in states.items()
    }


@router.post("/devices/stop-all")
async def stop_all_device_followup():
    """停止所有设备的 follow-up"""
    manager = get_followup_device_manager()
    await manager.stop_all()
    return {"success": True, "message": "All follow-up processes stopped"}
```

---

## 文件清单

### 5.1 新建文件

| 文件                                          | 说明                       |
| --------------------------------------------- | -------------------------- |
| `backend/services/followup_device_manager.py` | FollowUp 多设备管理器      |
| `followup_process.py`                         | 单设备 followup 子进程脚本 |

### 5.2 修改文件

| 文件                          | 修改内容                               |
| ----------------------------- | -------------------------------------- |
| `backend/routers/followup.py` | 添加多设备 API 端点                    |
| `backend/main.py`             | 可选：在 lifespan 中清理 followup 进程 |

### 5.3 保留不变

| 文件                                             | 说明                   |
| ------------------------------------------------ | ---------------------- |
| `servic../03-impl-and-arch/response_detector.py` | 复用现有检测逻辑       |
| `servic../03-impl-and-arch/repository.py`        | 复用数据库操作         |
| `servic../03-impl-and-arch/settings.py`          | 复用设置管理           |
| `servic../03-impl-and-arch/scheduler.py`         | **暂时保留**，逐步废弃 |

---

## 测试验收

### 6.1 单元测试

```python
# tests/test_followup_device_manager.py

import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
class TestFollowUpDeviceManager:

    async def test_start_single_device(self):
        """测试启动单个设备"""
        from services.followup_device_manager import get_followup_device_manager
        manager = get_followup_device_manager()

        with patch.object(manager, '_create_subprocess_windows') as mock:
            mock.return_value = AsyncMock()
            success = await manager.start_followup("device_A")
            assert success
            assert manager.is_running("device_A")

    async def test_start_multiple_devices(self):
        """测试同时启动多个设备"""
        manager = get_followup_device_manager()

        await manager.start_followup("device_A")
        await manager.start_followup("device_B")
        await manager.start_followup("device_C")

        assert manager.is_running("device_A")
        assert manager.is_running("device_B")
        assert manager.is_running("device_C")

    async def test_stop_one_device(self):
        """测试停止一个设备不影响其他设备"""
        manager = get_followup_device_manager()

        await manager.start_followup("device_A")
        await manager.start_followup("device_B")

        await manager.stop_followup("device_A")

        assert not manager.is_running("device_A")
        assert manager.is_running("device_B")
```

### 6.2 集成测试

- [ ] 3 台设备同时运行 followup
- [ ] 停止其中 1 台，其他继续运行
- [ ] 暂停/恢复操作正常
- [ ] 日志正确输出到对应设备
- [ ] 进程异常退出后状态正确更新
- [ ] 重启服务后进程正确清理

### 6.3 API 测试

```bash
# 启动设备 A 的 followup
curl -X POST http://localhost:8000/a../03-impl-and-arch/device/device_A/start

# 获取状态
curl http://localhost:8000/a../03-impl-and-arch/device/device_A/status

# 暂停
curl -X POST http://localhost:8000/a../03-impl-and-arch/device/device_A/pause

# 恢复
curl -X POST http://localhost:8000/a../03-impl-and-arch/device/device_A/resume

# 停止
curl -X POST http://localhost:8000/a../03-impl-and-arch/device/device_A/stop

# 获取所有设备状态
curl http://localhost:8000/a../03-impl-and-arch/devices/status
```

---

## 实现步骤

### Step 1: 创建 FollowUpDeviceManager (2h)

1. 创建 `backend/services/followup_device_manager.py`
2. 实现状态管理、进程启动/停止
3. 实现日志读取和广播

### Step 2: 创建 followup_process.py (1h)

1. 创建项目根目录下的 `followup_process.py`
2. 复用 `ResponseDetector` 逻辑
3. 测试独立运行

### Step 3: 添加 API 端点 (1h)

1. 更新 `backend/routers/followup.py`
2. 添加多设备 API
3. 测试 API

### Step 4: 测试与调试 (2h)

1. 单元测试
2. 集成测试
3. 修复问题

**总预计工时**: 6 小时
