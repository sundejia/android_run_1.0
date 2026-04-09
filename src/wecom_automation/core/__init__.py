"""
Core module containing fundamental components.

- config: Configuration management
- exceptions: Custom exception classes
- models: Data models
- logging: Logging setup utilities
"""

from wecom_automation.core.config import (
    DEFAULT_DB_PATH,
    PROJECT_ROOT,
    Config,
    get_default_db_path,
    get_project_root,
)
from wecom_automation.core.exceptions import (
    DeviceConnectionError,
    DeviceDisconnectedError,
    TimeoutError,
    UIElementNotFoundError,
    WeComAutomationError,
    is_device_disconnected_error,
)
from wecom_automation.core.logging import (
    add_device_sink,
    get_logger,
    init_logging,
    log_operation,
    remove_device_sink,
    setup_logger,
)
from wecom_automation.core.models import (
    AvatarInfo,
    ConversationExtractionResult,
    ConversationMessage,
    ExtractionResult,
    ImageInfo,
    MessageEntry,
    UserDetail,
)

__all__ = [
    "Config",
    "PROJECT_ROOT",
    "DEFAULT_DB_PATH",
    "get_project_root",
    "get_default_db_path",
    "WeComAutomationError",
    "DeviceConnectionError",
    "DeviceDisconnectedError",
    "UIElementNotFoundError",
    "TimeoutError",
    "is_device_disconnected_error",
    "AvatarInfo",
    "ConversationExtractionResult",
    "ConversationMessage",
    "ExtractionResult",
    "ImageInfo",
    "MessageEntry",
    "UserDetail",
    "setup_logger",
    "get_logger",
    "init_logging",
    "add_device_sink",
    "remove_device_sink",
    "log_operation",
]
