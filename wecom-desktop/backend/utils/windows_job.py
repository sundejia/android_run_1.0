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
