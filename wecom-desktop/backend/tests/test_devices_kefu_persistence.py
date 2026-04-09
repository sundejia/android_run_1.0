import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent.parent / "src"))

from routers import devices


@pytest.mark.asyncio
async def test_ensure_device_kefu_persisted_logs_placeholder_creation(caplog):
    repo = Mock()
    repo.get_or_create_device.return_value = SimpleNamespace(id=7)
    repo.list_kefus_for_device.return_value = []
    repo.get_or_create_kefu.return_value = SimpleNamespace(
        id=11,
        name="Kefu-SER12345",
        department=None,
        verification_status=None,
    )

    with patch.object(devices, "ConversationRepository", return_value=repo), patch.object(
        devices, "_extract_kefu_for_device", new=AsyncMock(return_value=None)
    ), patch.dict(devices._kefu_cache, {}, clear=True):
        with caplog.at_level("INFO"):
            result = await devices.ensure_device_kefu_persisted("SER123456789", allow_placeholder=True)

    assert result is not None
    assert result.name == "Kefu-SER12345"
    assert "no persisted kefu for device SER123456789" in caplog.text
    assert "created placeholder kefu Kefu-SER12345" in caplog.text
