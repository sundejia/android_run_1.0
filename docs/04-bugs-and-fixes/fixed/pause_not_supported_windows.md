# Bug 分析：Pause 按钮不支持 Windows

> 时间: 2026-01-19  
> 状态: 📝 已分析（设计如此）

---

## 问题描述

点击 Pause 按钮后显示警告：

```
Pause/Resume is not supported on Windows. Use Stop instead.
```

---

## 根因分析

### 技术原因

Pause/Resume 功能依赖 **Unix 信号机制**：

| 操作   | Unix 信号 | Windows 支持 |
| ------ | --------- | ------------ |
| Pause  | `SIGSTOP` | ❌ 不支持    |
| Resume | `SIGCONT` | ❌ 不支持    |

### 代码位置

**文件**: `wecom-desktop/backend/services/device_manager.py`

```python
# 第 843-898 行: pause_sync 方法
async def pause_sync(self, serial: str) -> bool:
    ...
    # Pause is not supported on Windows
    if platform.system() == "Windows":
        await self._broadcast_log(serial, "WARNING",
            "Pause/Resume is not supported on Windows. Use Stop instead.")
        return False

    # Unix only: 使用 SIGSTOP 信号暂停进程组
    pgid = os.getpgid(process.pid)
    os.killpg(pgid, signal.SIGSTOP)  # ← 这在 Windows 上不存在
```

```python
# 第 900-955 行: resume_sync 方法
async def resume_sync(self, serial: str) -> bool:
    ...
    # Resume is not supported on Windows
    if platform.system() == "Windows":
        await self._broadcast_log(serial, "WARNING",
            "Pause/Resume is not supported on Windows.")
        return False

    # Unix only: 使用 SIGCONT 信号恢复进程组
    pgid = os.getpgid(process.pid)
    os.killpg(pgid, signal.SIGCONT)  # ← 这在 Windows 上不存在
```

---

## Windows vs Unix 信号对比

| 特性                  | Unix (Linux/macOS) | Windows     |
| --------------------- | ------------------ | ----------- |
| 进程组 (`os.getpgid`) | ✅ 支持            | ❌ 不支持   |
| `SIGSTOP` (暂停)      | ✅ 支持            | ❌ 不支持   |
| `SIGCONT` (恢复)      | ✅ 支持            | ❌ 不支持   |
| `SIGTERM` (终止)      | ✅ 支持            | ⚠️ 有限支持 |
| `SIGKILL` (强制终止)  | ✅ 支持            | ⚠️ 有限支持 |

## Windows 上实现 Pause/Resume 的技术路线

### 方案 1: Windows API - NtSuspendProcess (推荐 ⭐⭐⭐⭐)

使用 Windows 未公开的 NT API 暂停整个进程。

**优点**：

- 真正的进程级暂停
- 可以递归暂停所有子进程
- 效果与 Unix SIGSTOP 类似

**缺点**：

- 使用未公开 API，可能在未来 Windows 版本中变化
- 需要 `ctypes` 调用

**实现示例**：

```python
import ctypes
from ctypes import wintypes

ntdll = ctypes.WinDLL("ntdll")

def suspend_process(pid: int) -> bool:
    """暂停进程"""
    PROCESS_SUSPEND_RESUME = 0x0800
    kernel32 = ctypes.WinDLL("kernel32")

    handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False

    try:
        # NtSuspendProcess - 未公开 API
        result = ntdll.NtSuspendProcess(handle)
        return result == 0  # STATUS_SUCCESS
    finally:
        kernel32.CloseHandle(handle)

def resume_process(pid: int) -> bool:
    """恢复进程"""
    PROCESS_SUSPEND_RESUME = 0x0800
    kernel32 = ctypes.WinDLL("kernel32")

    handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False

    try:
        # NtResumeProcess - 未公开 API
        result = ntdll.NtResumeProcess(handle)
        return result == 0
    finally:
        kernel32.CloseHandle(handle)
```

---

### 方案 2: Windows Job Objects (推荐 ⭐⭐⭐⭐)

使用 Windows Job Objects 管理进程组，可以暂停/恢复整个进程组。

**优点**：

- 官方支持的 API
- 可以管理整个进程树
- 稳定可靠

**缺点**：

- 需要在创建进程时就关联到 Job Object
- 代码复杂度较高

**实现思路**：

```python
import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32")

# 创建 Job Object
job_handle = kernel32.CreateJobObjectW(None, None)

# 将进程添加到 Job
kernel32.AssignProcessToJobObject(job_handle, process_handle)

# 设置 Job 限制来暂停所有进程
# JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE 等限制选项
```

---

### 方案 3: 线程级暂停 (⭐⭐⭐)

遍历进程的所有线程，使用 `SuspendThread`/`ResumeThread` 暂停/恢复每个线程。

**优点**：

- 使用公开的 Windows API
- 可以精确控制

**缺点**：

- 需要遍历所有线程
- 可能错过动态创建的线程
- 需要递归处理子进程

**实现示例**：

```python
import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32")

def suspend_process_threads(pid: int) -> bool:
    """暂停进程的所有线程"""
    import psutil

    try:
        proc = psutil.Process(pid)

        # 暂停所有线程
        for thread in proc.threads():
            thread_handle = kernel32.OpenThread(0x0002, False, thread.id)  # THREAD_SUSPEND_RESUME
            if thread_handle:
                kernel32.SuspendThread(thread_handle)
                kernel32.CloseHandle(thread_handle)

        # 递归处理子进程
        for child in proc.children(recursive=True):
            suspend_process_threads(child.pid)

        return True
    except Exception:
        return False

def resume_process_threads(pid: int) -> bool:
    """恢复进程的所有线程"""
    import psutil

    try:
        proc = psutil.Process(pid)

        for thread in proc.threads():
            thread_handle = kernel32.OpenThread(0x0002, False, thread.id)
            if thread_handle:
                kernel32.ResumeThread(thread_handle)
                kernel32.CloseHandle(thread_handle)

        for child in proc.children(recursive=True):
            resume_process_threads(child.pid)

        return True
    except Exception:
        return False
```

---

### 方案 4: 应用层协作暂停 (⭐⭐⭐⭐⭐ 最简单)

不依赖操作系统信号，而是在应用层实现暂停逻辑。

**优点**：

- 跨平台兼容
- 不需要特殊权限
- 实现简单

**缺点**：

- 需要修改同步脚本
- 只能在特定检查点暂停

**实现方案**：

1. **使用文件标志**：

```python
# device_manager.py
async def pause_sync(self, serial: str) -> bool:
    # 创建暂停标志文件
    pause_file = Path(f".pause_{serial}")
    pause_file.touch()
    return True

async def resume_sync(self, serial: str) -> bool:
    # 删除暂停标志文件
    pause_file = Path(f".pause_{serial}")
    pause_file.unlink(missing_ok=True)
    return True
```

2. **在同步脚本中检查**：

```python
# orchestrator.py / customer_syncer.py
async def _check_pause(self):
    """检查是否需要暂停"""
    pause_file = Path(f".pause_{self._device_serial}")
    while pause_file.exists():
        self._logger.info("⏸️ Sync paused, waiting for resume...")
        await asyncio.sleep(1.0)
```

3. **在关键位置调用**：

```python
# 在每个用户同步前检查
for customer in customers:
    await self._check_pause()  # 检查暂停
    await self._sync_customer(customer)
```

---

### 方案 5: 使用 pywin32 (⭐⭐⭐)

使用 `pywin32` 包提供的 Windows API 封装。

**优点**：

- 更 Pythonic 的 API
- 官方 Windows API 封装

**缺点**：

- 需要额外安装 `pywin32` 包
- 仍然使用底层 Windows API

```python
import win32api
import win32process
import win32con

def suspend_process(pid):
    handle = win32api.OpenProcess(win32con.PROCESS_SUSPEND_RESUME, False, pid)
    # 使用 NtSuspendProcess 通过 ctypes
    ...
```

---

## 技术路线对比

| 方案                     | 复杂度 | 可靠性 | 跨平台 | 推荐度     |
| ------------------------ | ------ | ------ | ------ | ---------- |
| 方案 1: NtSuspendProcess | 中     | 高     | ❌     | ⭐⭐⭐⭐   |
| 方案 2: Job Objects      | 高     | 高     | ❌     | ⭐⭐⭐⭐   |
| 方案 3: 线程级暂停       | 高     | 中     | ❌     | ⭐⭐⭐     |
| 方案 4: 应用层协作       | 低     | 高     | ✅     | ⭐⭐⭐⭐⭐ |
| 方案 5: pywin32          | 中     | 高     | ❌     | ⭐⭐⭐     |

---

## 推荐方案

### 首选：方案 4 - 应用层协作暂停

**理由**：

1. 实现最简单，不需要底层 Windows API
2. 跨平台兼容（Unix 也可以使用）
3. 不需要特殊权限
4. 可控性强，只在安全的检查点暂停

### 次选：方案 1 - NtSuspendProcess

**理由**：

1. 真正的进程级暂停，与 Unix SIGSTOP 效果最接近
2. 代码量较少
3. 虽然是未公开 API，但已被广泛使用多年

---

## 实施建议

如果要实现此功能，建议分步骤：

1. **第一步**：先实现方案 4（应用层协作），验证功能可行
2. **第二步**：可选添加方案 1 作为更彻底的备选方案
3. **第三步**：在前端 UI 上隐藏/显示 Pause 按钮的逻辑可以保留，因为即使实现了应用层暂停，也不是真正的"立即暂停"
