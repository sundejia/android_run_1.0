# Windows Pause/Resume 实现计划

## 使用 Windows Job Objects 方案

> 创建时间: 2026-01-19  
> 状态: 📋 计划中

---

## 概述

使用 Windows Job Objects API 实现进程暂停/恢复功能。Job Objects 是 Windows 官方支持的进程组管理机制，可以对一组相关进程进行统一控制。

---

## 技术原理

### Job Objects 简介

Windows Job Objects 允许：

1. 将多个进程（包括子进程）关联到一个 Job 对象
2. 对 Job 中的所有进程应用统一的限制和控制
3. 监控 Job 中所有进程的状态

### 关键 API

| API                                    | 功能                      |
| -------------------------------------- | ------------------------- |
| `CreateJobObjectW`                     | 创建 Job 对象             |
| `AssignProcessToJobObject`             | 将进程添加到 Job          |
| `SetInformationJobObject`              | 设置 Job 属性（如限制）   |
| `NtSuspendProcess` / `NtResumeProcess` | 暂停/恢复进程（配合使用） |

---

## 实现架构

```
┌─────────────────────────────────────────────────────────┐
│                    DeviceManager                         │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐    │
│  │              WindowsJobManager                   │    │
│  │  ┌─────────────────────────────────────────┐    │    │
│  │  │  Job Object (per device serial)          │    │    │
│  │  │  ├── Main Python Process (sync script)  │    │    │
│  │  │  ├── Child Process 1 (adb)              │    │    │
│  │  │  └── Child Process N                     │    │    │
│  │  └─────────────────────────────────────────┘    │    │
│  │                                                  │    │
│  │  Methods:                                        │    │
│  │  - create_job(serial) -> job_handle             │    │
│  │  - add_process(job_handle, process)             │    │
│  │  - suspend_job(serial)                          │    │
│  │  - resume_job(serial)                           │    │
│  │  - terminate_job(serial)                        │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## 详细实现步骤

### 第一阶段：创建 WindowsJobManager 类

#### 文件位置

`wecom-desktop/backend/utils/windows_job.py`

#### 代码结构

```python
"""
Windows Job Objects 管理器

用于在 Windows 上实现进程的暂停/恢复功能。
"""

import ctypes
from ctypes import wintypes
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Windows API 常量
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_SUSPEND_RESUME = 0x0800

# 加载 Windows DLL
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)


class WindowsJobManager:
    """
    Windows Job Objects 管理器

    管理每个设备的 Job Object，支持暂停/恢复整个进程树。
    """

    def __init__(self):
        self._jobs: Dict[str, int] = {}  # serial -> job_handle
        self._processes: Dict[str, int] = {}  # serial -> main_process_handle
        self._suspended: Dict[str, bool] = {}  # serial -> is_suspended
        self._logger = logger

    def create_job(self, serial: str) -> Optional[int]:
        """
        创建 Job Object

        Args:
            serial: 设备序列号

        Returns:
            Job handle，失败返回 None
        """
        # 创建 Job Object
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            self._logger.error(f"Failed to create job object: {ctypes.get_last_error()}")
            return None

        self._jobs[serial] = job_handle
        self._suspended[serial] = False
        self._logger.info(f"Created job object for {serial}: handle={job_handle}")

        return job_handle

    def add_process(self, serial: str, pid: int) -> bool:
        """
        将进程添加到 Job Object

        Args:
            serial: 设备序列号
            pid: 进程 ID

        Returns:
            是否成功
        """
        if serial not in self._jobs:
            self._logger.error(f"No job object for {serial}")
            return False

        job_handle = self._jobs[serial]

        # 打开进程句柄
        process_handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not process_handle:
            self._logger.error(f"Failed to open process {pid}: {ctypes.get_last_error()}")
            return False

        # 将进程添加到 Job
        success = kernel32.AssignProcessToJobObject(job_handle, process_handle)
        if not success:
            self._logger.error(f"Failed to assign process to job: {ctypes.get_last_error()}")
            kernel32.CloseHandle(process_handle)
            return False

        self._processes[serial] = process_handle
        self._logger.info(f"Added process {pid} to job for {serial}")

        return True

    def suspend_job(self, serial: str) -> bool:
        """
        暂停 Job 中的所有进程

        由于 Job Objects 本身不支持暂停，我们需要遍历 Job 中的所有进程
        并使用 NtSuspendProcess 暂停每个进程。

        Args:
            serial: 设备序列号

        Returns:
            是否成功
        """
        if serial not in self._jobs:
            self._logger.error(f"No job object for {serial}")
            return False

        if self._suspended.get(serial):
            self._logger.warning(f"Job for {serial} already suspended")
            return True

        # 获取 Job 中的所有进程并暂停
        try:
            pids = self._get_job_processes(serial)
            for pid in pids:
                self._suspend_process(pid)

            self._suspended[serial] = True
            self._logger.info(f"Suspended {len(pids)} processes for {serial}")
            return True

        except Exception as e:
            self._logger.error(f"Failed to suspend job: {e}")
            return False

    def resume_job(self, serial: str) -> bool:
        """
        恢复 Job 中的所有进程

        Args:
            serial: 设备序列号

        Returns:
            是否成功
        """
        if serial not in self._jobs:
            self._logger.error(f"No job object for {serial}")
            return False

        if not self._suspended.get(serial):
            self._logger.warning(f"Job for {serial} not suspended")
            return True

        try:
            pids = self._get_job_processes(serial)
            for pid in pids:
                self._resume_process(pid)

            self._suspended[serial] = False
            self._logger.info(f"Resumed {len(pids)} processes for {serial}")
            return True

        except Exception as e:
            self._logger.error(f"Failed to resume job: {e}")
            return False

    def terminate_job(self, serial: str) -> bool:
        """
        终止 Job 中的所有进程并清理资源

        Args:
            serial: 设备序列号

        Returns:
            是否成功
        """
        if serial not in self._jobs:
            return True

        try:
            job_handle = self._jobs[serial]

            # 终止 Job 中的所有进程
            kernel32.TerminateJobObject(job_handle, 1)

            # 关闭句柄
            kernel32.CloseHandle(job_handle)

            if serial in self._processes:
                kernel32.CloseHandle(self._processes[serial])
                del self._processes[serial]

            del self._jobs[serial]
            if serial in self._suspended:
                del self._suspended[serial]

            self._logger.info(f"Terminated and cleaned up job for {serial}")
            return True

        except Exception as e:
            self._logger.error(f"Failed to terminate job: {e}")
            return False

    def is_suspended(self, serial: str) -> bool:
        """检查 Job 是否被暂停"""
        return self._suspended.get(serial, False)

    def _get_job_processes(self, serial: str) -> list:
        """
        获取 Job 中的所有进程 ID

        使用 QueryInformationJobObject 获取进程列表
        """
        import psutil

        # 简化实现：使用 psutil 获取主进程的所有子进程
        if serial in self._processes:
            try:
                # 获取主进程 PID
                main_pid = None
                process_handle = self._processes[serial]
                main_pid = kernel32.GetProcessId(process_handle)

                if main_pid:
                    proc = psutil.Process(main_pid)
                    pids = [main_pid]
                    for child in proc.children(recursive=True):
                        pids.append(child.pid)
                    return pids
            except Exception:
                pass

        return []

    def _suspend_process(self, pid: int) -> bool:
        """使用 NtSuspendProcess 暂停单个进程"""
        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False

        try:
            result = ntdll.NtSuspendProcess(handle)
            return result == 0
        finally:
            kernel32.CloseHandle(handle)

    def _resume_process(self, pid: int) -> bool:
        """使用 NtResumeProcess 恢复单个进程"""
        handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False

        try:
            result = ntdll.NtResumeProcess(handle)
            return result == 0
        finally:
            kernel32.CloseHandle(handle)


# 全局单例
_job_manager: Optional[WindowsJobManager] = None

def get_job_manager() -> WindowsJobManager:
    """获取全局 Job Manager 单例"""
    global _job_manager
    if _job_manager is None:
        _job_manager = WindowsJobManager()
    return _job_manager
```

---

### 第二阶段：修改 DeviceManager

#### 修改文件

`wecom-desktop/backend/services/device_manager.py`

#### 修改内容

##### 1. 导入 WindowsJobManager

```python
# 在文件顶部添加
import platform

if platform.system() == "Windows":
    from backend.utils.windows_job import get_job_manager
```

##### 2. 修改 start_sync 方法

```python
async def start_sync(self, serial: str, ...) -> bool:
    # ... 现有代码 ...

    # 在创建进程后添加
    if platform.system() == "Windows":
        job_manager = get_job_manager()
        job_manager.create_job(serial)
        job_manager.add_process(serial, process.pid)

    # ... 继续现有代码 ...
```

##### 3. 修改 pause_sync 方法

```python
async def pause_sync(self, serial: str) -> bool:
    """暂停同步操作"""
    state = self._sync_states.get(serial)

    if not state:
        await self._broadcast_log(serial, "WARNING", "Cannot pause: no sync state found")
        return False

    if state.status != SyncStatus.RUNNING:
        await self._broadcast_log(serial, "WARNING", f"Cannot pause: sync is {state.status.value}")
        return False

    # Windows: 使用 Job Objects
    if platform.system() == "Windows":
        job_manager = get_job_manager()
        success = job_manager.suspend_job(serial)

        if success:
            state.status = SyncStatus.PAUSED
            state.message = "Sync paused"
            await self._broadcast_status(serial)
            await self._broadcast_log(serial, "INFO", "⏸️ Sync paused")
            return True
        else:
            await self._broadcast_log(serial, "ERROR", "Failed to pause sync")
            return False

    # Unix: 使用 SIGSTOP (现有代码)
    else:
        # ... 现有 Unix 实现 ...
```

##### 4. 修改 resume_sync 方法

```python
async def resume_sync(self, serial: str) -> bool:
    """恢复同步操作"""
    state = self._sync_states.get(serial)

    if not state:
        await self._broadcast_log(serial, "WARNING", "Cannot resume: no sync state found")
        return False

    if state.status != SyncStatus.PAUSED:
        await self._broadcast_log(serial, "WARNING", f"Cannot resume: sync is {state.status.value}")
        return False

    # Windows: 使用 Job Objects
    if platform.system() == "Windows":
        job_manager = get_job_manager()
        success = job_manager.resume_job(serial)

        if success:
            state.status = SyncStatus.RUNNING
            state.message = "Sync resumed"
            await self._broadcast_status(serial)
            await self._broadcast_log(serial, "INFO", "▶️ Sync resumed")
            return True
        else:
            await self._broadcast_log(serial, "ERROR", "Failed to resume sync")
            return False

    # Unix: 使用 SIGCONT (现有代码)
    else:
        # ... 现有 Unix 实现 ...
```

##### 5. 修改 stop_sync 方法

```python
async def stop_sync(self, serial: str) -> bool:
    # ... 现有代码 ...

    # 在清理部分添加
    if platform.system() == "Windows":
        job_manager = get_job_manager()
        job_manager.terminate_job(serial)

    # ... 继续现有代码 ...
```

---

### 第三阶段：创建测试脚本

#### 文件位置

`tests/test_windows_job.py`

```python
"""测试 Windows Job Objects 功能"""

import asyncio
import subprocess
import time
import platform
import sys

# 只在 Windows 上运行
if platform.system() != "Windows":
    print("This test only runs on Windows")
    sys.exit(0)

from backend.utils.windows_job import get_job_manager


async def test_pause_resume():
    """测试暂停/恢复功能"""
    manager = get_job_manager()
    serial = "test_device"

    # 1. 创建一个测试进程（例如 ping）
    print("Starting test process...")
    process = subprocess.Popen(
        ["ping", "-t", "localhost"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    # 2. 创建 Job 并添加进程
    print(f"Creating job for serial: {serial}")
    manager.create_job(serial)
    manager.add_process(serial, process.pid)

    # 3. 运行 3 秒
    print("Process running for 3 seconds...")
    time.sleep(3)

    # 4. 暂停
    print("Pausing process...")
    success = manager.suspend_job(serial)
    print(f"Pause result: {success}")
    print(f"Is suspended: {manager.is_suspended(serial)}")

    # 5. 暂停 3 秒
    print("Paused for 3 seconds...")
    time.sleep(3)

    # 6. 恢复
    print("Resuming process...")
    success = manager.resume_job(serial)
    print(f"Resume result: {success}")
    print(f"Is suspended: {manager.is_suspended(serial)}")

    # 7. 运行 2 秒
    print("Process running for 2 more seconds...")
    time.sleep(2)

    # 8. 终止
    print("Terminating...")
    manager.terminate_job(serial)

    print("Test completed!")


if __name__ == "__main__":
    asyncio.run(test_pause_resume())
```

---

## 任务清单

### 阶段 1: 基础实现 (预计 2 小时)

- [ ] 创建 `wecom-desktop/backend/utils/windows_job.py`
- [ ] 实现 `WindowsJobManager` 类
- [ ] 实现 `create_job` 方法
- [ ] 实现 `add_process` 方法
- [ ] 实现 `suspend_job` 方法
- [ ] 实现 `resume_job` 方法
- [ ] 实现 `terminate_job` 方法

### 阶段 2: 集成到 DeviceManager (预计 1 小时)

- [ ] 在 `start_sync` 中创建 Job 并添加进程
- [ ] 修改 `pause_sync` 使用 `WindowsJobManager`
- [ ] 修改 `resume_sync` 使用 `WindowsJobManager`
- [ ] 修改 `stop_sync` 清理 Job 资源
- [ ] 删除/修改 Windows 不支持的警告

### 阶段 3: 测试 (预计 1 小时)

- [ ] 创建测试脚本
- [ ] 测试基本暂停/恢复功能
- [ ] 测试子进程处理
- [ ] 测试异常情况（进程已退出等）
- [ ] 集成测试（完整同步流程）

### 阶段 4: 优化和文档 (预计 0.5 小时)

- [ ] 添加错误处理和日志
- [ ] 更新文档
- [ ] 代码审查

---

## 风险和注意事项

### 风险

1. **子进程关联**：需要确保所有子进程都被添加到 Job Object
2. **权限问题**：某些操作可能需要管理员权限
3. **NtSuspendProcess 兼容性**：这是未公开 API，未来 Windows 版本可能变化

### 缓解措施

1. 使用 `CREATE_NEW_PROCESS_GROUP` 创建进程，便于管理
2. 添加权限检查和友好错误提示
3. 添加 fallback 机制（如线程级暂停）

---

## 预计工时

| 阶段             | 预计时间     |
| ---------------- | ------------ |
| 阶段 1: 基础实现 | 2 小时       |
| 阶段 2: 集成     | 1 小时       |
| 阶段 3: 测试     | 1 小时       |
| 阶段 4: 优化     | 0.5 小时     |
| **总计**         | **4.5 小时** |

---

## 下一步

1. 确认计划无误后开始实施
2. 先实现并测试 `WindowsJobManager`
3. 再集成到 `DeviceManager`
4. 完成端到端测试
