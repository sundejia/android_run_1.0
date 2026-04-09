import shutil
import uuid
from pathlib import Path
from unittest.mock import patch

from wecom_automation.services.message.handlers.image import ImageMessageHandler


class _DummyRepository:
    pass


def test_image_message_handler_accepts_wait_for_review():
    images_dir = Path("tests_tmp") / f"image_handler_{uuid.uuid4().hex}"
    images_dir.mkdir(parents=True, exist_ok=True)
    try:
        with patch("wecom_automation.services.message.handlers.base.TimestampParser"):
            handler = ImageMessageHandler(
                repository=_DummyRepository(),
                wecom_service=object(),
                images_dir=images_dir,
                wait_for_review=True,
            )

        assert handler is not None
        assert handler._wait_for_review is True
    finally:
        shutil.rmtree(images_dir, ignore_errors=True)
