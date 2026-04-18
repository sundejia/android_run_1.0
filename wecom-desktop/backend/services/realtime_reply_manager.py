"""
Realtime Reply Manager - 管理多设备的实时回复进程

效仿 DeviceManager 的设计，为每个设备启动独立的实时回复子进程。
"""

from __future__ import annotations

import asyncio
import os
import platform
import re
import subprocess
import time as _time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# 复用 DeviceManager 的工具类
if platform.system() == "Windows":
    try:
        from utils.windows_job import get_job_manager
    except ImportError:
        from backend.utils.windows_job import get_job_manager


from utils.path_utils import get_project_root

PROJECT_ROOT = get_project_root()


class RealtimeReplyStatus(str, Enum):
    """实时回复运行状态"""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class RealtimeReplyState:
    """设备的实时回复状态"""

    status: RealtimeReplyStatus = RealtimeReplyStatus.IDLE
    message: str = ""
    responses_detected: int = 0
    replies_sent: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    last_scan_at: datetime | None = None


LogCallback = Callable[[dict], Coroutine[Any, Any, None]]
StatusCallback = Callable[[dict], Coroutine[Any, Any, None]]


class RealtimeReplyManager:
    """
    管理多设备的实时回复进程

    每个设备运行在独立的子进程中，互不干扰。
    日志通过回调广播到设备对应的 WebSocket。
    """

    MAX_AUTO_RESTARTS = 10
    AUTO_RESTART_BASE_DELAY = 5.0
    AUTO_RESTART_MAX_DELAY = 300.0
    STABLE_RUN_THRESHOLD = 300.0  # seconds running before restart counter resets

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._states: dict[str, RealtimeReplyState] = {}
        self._log_callbacks: dict[str, set[LogCallback]] = {}
        self._status_callbacks: dict[str, set[StatusCallback]] = {}
        self._read_tasks: dict[str, asyncio.Task] = {}
        self._startup_params: dict[str, dict] = {}
        self._restart_counts: dict[str, int] = {}
        self._auto_restart_enabled: dict[str, bool] = {}
        self._process_start_times: dict[str, float] = {}

    # ==================== 状态查询 ====================

    def get_state(self, serial: str) -> RealtimeReplyState | None:
        """获取设备的 followup 状态"""
        return self._states.get(serial)

    def get_all_states(self) -> dict[str, RealtimeReplyState]:
        """获取所有设备的 followup 状态"""
        return self._states.copy()

    def is_running(self, serial: str) -> bool:
        """检查设备的实时回复是否在运行"""
        state = self._states.get(serial)
        if not state:
            return False
        return state.status in (RealtimeReplyStatus.RUNNING, RealtimeReplyStatus.STARTING)

    def get_active_realtime_count(self) -> int:
        """统计当前处于 running / starting 的设备数，用于并发上限校验"""
        return sum(
            1
            for state in self._states.values()
            if state.status in (RealtimeReplyStatus.RUNNING, RealtimeReplyStatus.STARTING)
        )

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

    async def start_realtime_reply(
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

        # Persist startup params for auto-restart
        self._startup_params[serial] = {
            "scan_interval": scan_interval,
            "use_ai_reply": use_ai_reply,
            "send_via_sidecar": send_via_sidecar,
        }
        self._auto_restart_enabled[serial] = True

        # 初始化状态
        self._states[serial] = RealtimeReplyState(
            status=RealtimeReplyStatus.STARTING,
            message="Starting follow-up...",
            started_at=datetime.now(),
        )
        await self._broadcast_status(serial)

        # 构建命令
        script_path = PROJECT_ROOT / "wecom-desktop" / "backend" / "scripts" / "realtime_reply_process.py"

        # Allocate unique DroidRun port for this device
        from services.device_manager import PortAllocator
        droidrun_port = PortAllocator().allocate(serial)

        cmd = [
            "uv",
            "run",
            str(script_path),
            "--serial",
            serial,
            "--scan-interval",
            str(scan_interval),
            "--tcp-port",
            str(droidrun_port),
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
            process = await self._create_subprocess(cmd, env)

            self._processes[serial] = process
            self._process_start_times[serial] = _time.monotonic()
            self._states[serial].status = RealtimeReplyStatus.RUNNING
            self._states[serial].message = "Follow-up running"
            await self._broadcast_status(serial)

            # Windows: 创建 Job Object
            if platform.system() == "Windows":
                try:
                    job_manager = get_job_manager()
                    job_manager.create_job(f"realtime_{serial}")
                    job_manager.add_process(f"realtime_{serial}", process.pid)
                except Exception as e:
                    await self._broadcast_log(serial, "WARNING", f"Failed to create job: {e}")

            # 启动输出读取
            stdout_task = asyncio.create_task(self._read_output(serial, process.stdout, is_stderr=False))
            stderr_task = asyncio.create_task(self._read_output(serial, process.stderr, is_stderr=True))

            # 启动等待完成任务
            self._read_tasks[serial] = asyncio.create_task(
                self._wait_for_completion(serial, process, stdout_task, stderr_task)
            )

            return True

        except Exception as e:
            self._states[serial].status = RealtimeReplyStatus.ERROR
            self._states[serial].message = str(e)
            self._states[serial].errors.append(str(e))
            await self._broadcast_status(serial)
            await self._broadcast_log(serial, "ERROR", f"Failed to start: {e}")
            return False

    async def stop_realtime_reply(self, serial: str) -> bool:
        """停止设备的实时回复进程"""
        self._auto_restart_enabled[serial] = False
        self._restart_counts.pop(serial, None)
        state = self._states.get(serial)

        if serial not in self._processes:
            if state and state.status in (RealtimeReplyStatus.RUNNING, RealtimeReplyStatus.STARTING):
                state.status = RealtimeReplyStatus.STOPPED
                state.message = "Follow-up stopped (process not found)"
                await self._broadcast_status(serial)
                # Clean up sidecar state even if process wasn't found
                await self._cleanup_sidecar_state(serial)
                return True
            return False

        process = self._processes[serial]

        if process.returncode is not None:
            del self._processes[serial]
            if state:
                state.status = RealtimeReplyStatus.STOPPED
                state.message = "Follow-up stopped"
                await self._broadcast_status(serial)
            # Clean up sidecar state when process already exited
            await self._cleanup_sidecar_state(serial)
            return True

        if state:
            state.status = RealtimeReplyStatus.STOPPED
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
            except TimeoutError:
                process.kill()
                await process.wait()

            if serial in self._read_tasks:
                self._read_tasks[serial].cancel()
                del self._read_tasks[serial]

            if serial in self._processes:
                del self._processes[serial]

            if state:
                state.status = RealtimeReplyStatus.STOPPED
                state.message = "Follow-up stopped"
                await self._broadcast_status(serial)

            await self._broadcast_log(serial, "INFO", "Follow-up stopped")

            # Windows: 清理 Job Object
            if platform.system() == "Windows":
                try:
                    job_manager = get_job_manager()
                    job_manager.terminate_job(f"realtime_{serial}")
                except Exception:
                    pass

            # Release DroidRun port allocation
            try:
                from services.device_manager import PortAllocator
                PortAllocator().release(serial)
            except Exception:
                pass

            # Clean up sidecar state to prevent stale skip flags on restart
            await self._cleanup_sidecar_state(serial)

            return True

        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to stop: {e}")
            # Still try to clean up sidecar state even if stop failed
            await self._cleanup_sidecar_state(serial)
            return False

    async def _cleanup_sidecar_state(self, serial: str) -> None:
        """
        Clean up sidecar state for a device.

        Called when follow-up is stopped to clear skip flags, queues, and sync state
        to prevent stale state from affecting the next follow-up session.
        """
        try:
            from routers.sidecar import clear_device_sidecar_state

            clear_device_sidecar_state(serial)
            await self._broadcast_log(serial, "INFO", "Sidecar state cleared")
        except ImportError:
            # Sidecar module not available (e.g., running standalone)
            pass
        except Exception as e:
            # Log but don't fail - cleanup is best-effort
            await self._broadcast_log(serial, "WARNING", f"Failed to clear sidecar state: {e}")

    async def pause_realtime_reply(self, serial: str) -> bool:
        """暂停设备的实时回复"""
        state = self._states.get(serial)

        if not state or state.status != RealtimeReplyStatus.RUNNING:
            return False

        if serial not in self._processes:
            return False

        process = self._processes[serial]

        if process.returncode is not None:
            return False

        try:
            if platform.system() == "Windows":
                job_manager = get_job_manager()
                success = job_manager.suspend_job(f"realtime_{serial}")
                if success:
                    state.status = RealtimeReplyStatus.PAUSED
                    state.message = "Realtime reply paused"
                    await self._broadcast_status(serial)
                    await self._broadcast_log(serial, "INFO", "Realtime reply paused")
                    return True
                return False
            else:
                import signal

                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGSTOP)
                state.status = RealtimeReplyStatus.PAUSED
                state.message = "Follow-up paused"
                await self._broadcast_status(serial)
                await self._broadcast_log(serial, "INFO", "Follow-up paused")
                return True
        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to pause: {e}")
            return False

    async def resume_realtime_reply(self, serial: str) -> bool:
        """恢复设备的实时回复"""
        state = self._states.get(serial)

        if not state or state.status != RealtimeReplyStatus.PAUSED:
            return False

        if serial not in self._processes:
            return False

        process = self._processes[serial]

        if process.returncode is not None:
            return False

        try:
            if platform.system() == "Windows":
                job_manager = get_job_manager()
                success = job_manager.resume_job(f"realtime_{serial}")
                if success:
                    state.status = RealtimeReplyStatus.RUNNING
                    state.message = "Realtime reply resumed"
                    await self._broadcast_status(serial)
                    await self._broadcast_log(serial, "INFO", "Realtime reply resumed")
                    return True
                return False
            else:
                import signal

                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGCONT)
                state.status = RealtimeReplyStatus.RUNNING
                state.message = "Follow-up resumed"
                await self._broadcast_status(serial)
                await self._broadcast_log(serial, "INFO", "Follow-up resumed")
                return True
        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to resume: {e}")
            return False

    async def request_skip(self, serial: str) -> bool:
        """
        Request follow-up process to skip current queued message.

        **统一使用 Sidecar Skip 机制**，而不是创建独立的 skip flag 文件。
        这样可以复用 sync 的 skip 实现，避免维护两套独立的 skip 系统。

        response_detector.py 中已经使用 SidecarQueueClient.is_skip_requested()
        来检测 skip 请求，它会调用 /sidecar/{serial}/skip API。

        Args:
            serial: Device serial number

        Returns:
            True if skip request was successful, False otherwise
        """
        state = self._states.get(serial)

        # Check if follow-up is running
        if not state or state.status != RealtimeReplyStatus.RUNNING:
            await self._broadcast_log(serial, "WARNING", "Cannot skip: follow-up is not running")
            return False

        try:
            # 使用 sidecar skip API（与 sync 共享同一套机制）
            # 这个 API 会设置 _skip_flags[serial] = True
            # SidecarQueueClient.is_skip_requested() 会检查这个 flag
            sidecar_skip_url = f"http://localhost:8765/sidecar/{serial}/skip"

            import httpx

            await self._broadcast_log(serial, "DEBUG", f"🔍 Requesting skip via: {sidecar_skip_url}")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(sidecar_skip_url)
                await self._broadcast_log(serial, "DEBUG", f"🔍 Skip request response status: {resp.status_code}")
                if resp.status_code == 200:
                    response_data = resp.json()
                    await self._broadcast_log(serial, "DEBUG", f"🔍 Skip request response body: {response_data}")
                    await self._broadcast_log(serial, "INFO", "Skip requested via sidecar API (unified mechanism)")
                    return True
                else:
                    response_text = resp.text
                    await self._broadcast_log(serial, "DEBUG", f"🔍 Skip request error response: {response_text}")
                    await self._broadcast_log(serial, "ERROR", f"Skip request failed: HTTP {resp.status_code}")
                    return False

        except Exception as e:
            await self._broadcast_log(serial, "ERROR", f"Failed to request skip: {e}")
            return False

    async def stop_all(self):
        """停止所有设备的 follow-up"""
        serials = list(self._processes.keys())
        for serial in serials:
            await self.stop_realtime_reply(serial)

    # ==================== 内部方法 ====================

    async def _create_subprocess(self, cmd: list[str], env: dict):
        """创建子进程（平台兼容）"""
        if platform.system() == "Windows":
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
        else:
            return await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
                env=env,
                start_new_session=True,
            )

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
                except Exception:
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
        """等待进程完成, with auto-restart on unexpected exit."""
        try:
            await asyncio.gather(stdout_task, stderr_task)
            return_code = await process.wait()

            state = self._states.get(serial)

            # Check if process ran long enough to reset restart counter
            start_ts = self._process_start_times.get(serial, 0)
            run_duration = _time.monotonic() - start_ts if start_ts else 0
            if run_duration >= self.STABLE_RUN_THRESHOLD:
                self._restart_counts[serial] = 0

            if state:
                if return_code == 0:
                    state.status = RealtimeReplyStatus.STOPPED
                    state.message = "Follow-up completed"
                    await self._broadcast_status(serial)
                elif state.status == RealtimeReplyStatus.STOPPED:
                    await self._broadcast_status(serial)
                else:
                    state.status = RealtimeReplyStatus.ERROR
                    state.message = f"Follow-up exited with code {return_code}"
                    state.errors.append(f"Exit code: {return_code}")
                    await self._broadcast_status(serial)

                    # Attempt auto-restart on abnormal exit
                    if self._auto_restart_enabled.get(serial, False):
                        asyncio.create_task(self._attempt_restart(serial))
                        return
        except asyncio.CancelledError:
            pass
        finally:
            self._processes.pop(serial, None)
            self._read_tasks.pop(serial, None)
            self._process_start_times.pop(serial, None)

    async def _attempt_restart(self, serial: str) -> None:
        """Auto-restart a crashed process with exponential backoff."""
        attempt = self._restart_counts.get(serial, 0) + 1
        self._restart_counts[serial] = attempt

        if attempt > self.MAX_AUTO_RESTARTS:
            await self._broadcast_log(
                serial, "ERROR", f"Auto-restart limit reached ({self.MAX_AUTO_RESTARTS}). Manual intervention required."
            )
            return

        delay = min(
            self.AUTO_RESTART_BASE_DELAY * (3 ** (attempt - 1)),
            self.AUTO_RESTART_MAX_DELAY,
        )
        await self._broadcast_log(
            serial,
            "WARNING",
            f"Process crashed. Auto-restart #{attempt} in {delay:.0f}s (max {self.MAX_AUTO_RESTARTS})",
        )
        await asyncio.sleep(delay)

        if not self._auto_restart_enabled.get(serial, False):
            await self._broadcast_log(serial, "INFO", "Auto-restart cancelled (stop requested)")
            return

        params = self._startup_params.get(serial, {})
        success = await self.start_realtime_reply(
            serial,
            scan_interval=params.get("scan_interval", 60),
            use_ai_reply=params.get("use_ai_reply", True),
            send_via_sidecar=params.get("send_via_sidecar", True),
        )
        if success:
            await self._broadcast_log(serial, "INFO", f"Auto-restart #{attempt} succeeded")
        else:
            await self._broadcast_log(serial, "ERROR", f"Auto-restart #{attempt} failed")


# ==================== 单例管理 ====================

_realtime_reply_manager: RealtimeReplyManager | None = None


def get_realtime_reply_manager() -> RealtimeReplyManager:
    """获取或创建 RealtimeReplyManager 单例"""
    global _realtime_reply_manager
    if _realtime_reply_manager is None:
        _realtime_reply_manager = RealtimeReplyManager()
    return _realtime_reply_manager


# Windows 进程包装器（从 DeviceManager 复用）
if platform.system() == "Windows":

    class _WindowsProcessWrapper:
        """Wrapper to make subprocess.Popen compatible with asyncio.subprocess.Process interface."""

        def __init__(self, popen: subprocess.Popen):
            self._popen = popen
            self.stdout = _AsyncStreamReader(popen.stdout)
            self.stderr = _AsyncStreamReader(popen.stderr)
            self.pid = popen.pid

        @property
        def returncode(self):
            return self._popen.returncode

        async def wait(self):
            """Wait for process to complete."""
            return await asyncio.to_thread(self._popen.wait)

        def terminate(self):
            """Terminate the process."""
            self._popen.terminate()

        def kill(self):
            """Kill the process."""
            self._popen.kill()

    class _AsyncStreamReader:
        """Wrapper to make synchronous stream readable in async context."""

        def __init__(self, stream):
            self._stream = stream

        async def readline(self) -> bytes:
            """Read a line from the stream."""
            if self._stream is None:
                return b""
            return await asyncio.to_thread(self._stream.readline)
