# ruff: noqa: E402

import asyncio
import platform
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from services.conversation_storage import get_control_db_path, get_device_conversation_db_path
from services.device_manager import DeviceManager


class _QuietProcess:
    def __init__(self):
        self.returncode = None
        self.pid = 12345
        self.stdout = self._stream()
        self.stderr = self._stream()

    @staticmethod
    def _stream():
        stream = AsyncMock()
        stream.readline = AsyncMock(side_effect=[b""])
        return stream

    async def wait(self):
        await asyncio.sleep(0.05)
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


def test_storage_paths_default_to_device_isolated_root():
    manager = DeviceManager()

    output_root, images_dir, videos_dir, voices_dir = manager._resolve_storage_paths("SERIAL/01", None)

    assert output_root == Path(manager._get_device_output_root("SERIAL/01"))
    assert images_dir == output_root / "conversation_images"
    assert videos_dir == output_root / "conversation_videos"
    assert voices_dir == output_root / "conversation_voices"


def test_default_db_path_uses_device_scoped_db_when_serial_known():
    manager = DeviceManager()

    assert manager._resolve_db_path(None, "SERIAL/01") == get_device_conversation_db_path("SERIAL/01")


def test_default_db_path_falls_back_to_control_db_without_serial():
    manager = DeviceManager()

    assert manager._resolve_db_path(None) == get_control_db_path().resolve()


@pytest.mark.asyncio
async def test_shared_db_warning_mentions_peer_devices():
    manager = DeviceManager()
    logs = []

    async def callback(log):
        logs.append(log)

    shared_db = str(get_control_db_path().resolve())
    manager._db_paths["device-a"] = shared_db
    manager.register_log_callback("device-b", callback)

    await manager._warn_if_db_is_shared("device-b", Path(shared_db))

    assert logs
    assert logs[0]["level"] == "WARNING"
    assert "device-a" in logs[0]["message"]
    assert "shared SQLite DB" in logs[0]["message"]


@pytest.mark.asyncio
async def test_start_sync_passes_device_isolated_storage_args_by_default():
    manager = DeviceManager()
    process = _QuietProcess()
    captured_cmd = []

    async def spawn_capture(*args, **kwargs):
        if len(args) == 1 and isinstance(args[0], list):
            captured_cmd.extend(args[0])
        else:
            captured_cmd.extend(args)
        return process

    with ExitStack() as stack:
        if platform.system() == "Windows":
            stack.enter_context(
                patch.object(manager, "_create_subprocess_windows", AsyncMock(side_effect=spawn_capture))
            )
            job_manager = MagicMock()
            stack.enter_context(patch("services.device_manager.get_job_manager", return_value=job_manager))
        else:
            stack.enter_context(patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=spawn_capture)))

        result = await manager.start_sync("SERIAL/01")

    assert result is True

    cmd = [str(arg) for arg in captured_cmd]
    output_root = str((Path(manager._get_device_output_root("SERIAL/01"))).resolve())
    expected_images = str((Path(output_root) / "conversation_images").resolve())
    expected_videos = str((Path(output_root) / "conversation_videos").resolve())
    expected_voices = str((Path(output_root) / "conversation_voices").resolve())
    expected_db = str(get_device_conversation_db_path("SERIAL/01"))

    assert "--output-root" in cmd
    assert cmd[cmd.index("--output-root") + 1] == output_root
    assert cmd[cmd.index("--images-dir") + 1] == expected_images
    assert cmd[cmd.index("--videos-dir") + 1] == expected_videos
    assert cmd[cmd.index("--voices-dir") + 1] == expected_voices
    assert cmd[cmd.index("--db") + 1] == expected_db
