"""
测试 Windows Job Objects 功能
"""

import asyncio
import subprocess
import time
import platform
import sys

# Add backend to path for imports
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# 只在 Windows 上运行
if platform.system() != "Windows":
    print("This test only runs on Windows")
    sys.exit(0)

from utils.windows_job import get_job_manager


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
