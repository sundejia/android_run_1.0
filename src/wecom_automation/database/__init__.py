"""
Database module for WeCom Automation.

This module provides SQLite-based persistence for:
- Device information
- Kefu (customer service representative) profiles
- Customer contacts
- Conversation messages (text, voice, image, etc.)
"""

from wecom_automation.database.models import (
    CustomerRecord,
    DeviceRecord,
    ImageRecord,
    KefuRecord,
    MessageRecord,
    MessageType,
    VideoRecord,
    VoiceRecord,
)
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.database.schema import (
    DATABASE_VERSION,
    get_connection,
    init_database,
)

__all__ = [
    # Schema
    "init_database",
    "get_connection",
    "DATABASE_VERSION",
    # Models
    "DeviceRecord",
    "KefuRecord",
    "CustomerRecord",
    "MessageRecord",
    "ImageRecord",
    "VideoRecord",
    "VoiceRecord",
    "MessageType",
    # Repository
    "ConversationRepository",
]
