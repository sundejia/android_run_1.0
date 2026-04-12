"""
GroupChatService - WeCom UI automation for creating group chats.

Provides an abstraction layer over the ADB-based WeComService for
group chat creation. Designed to be mockable for testing and
swappable for different WeCom versions.
"""

from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager

from wecom_automation.database.schema import get_db_path
from wecom_automation.services.group_invite.models import (
    DuplicateNamePolicy,
    GroupInviteRequest,
)
from wecom_automation.services.group_invite.service import GroupInviteWorkflowService

logger = logging.getLogger(__name__)

MEDIA_ACTION_GROUPS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS media_action_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_serial TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        group_name TEXT NOT NULL,
        group_members TEXT,
        status TEXT DEFAULT 'created',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

MEDIA_ACTION_GROUPS_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_media_action_groups_lookup
    ON media_action_groups (device_serial, customer_name, group_name)
"""


def ensure_media_action_groups_table(db_path: str | None = None) -> str:
    """Ensure the media_action_groups tracking table exists."""
    resolved_db_path = str(get_db_path(db_path))
    conn = sqlite3.connect(resolved_db_path)
    try:
        conn.execute(MEDIA_ACTION_GROUPS_TABLE_SQL)
        conn.execute(MEDIA_ACTION_GROUPS_INDEX_SQL)
        conn.commit()
    finally:
        conn.close()
    return resolved_db_path


class IGroupChatService(ABC):
    """Interface for group chat operations."""

    @abstractmethod
    async def create_group_chat(
        self,
        device_serial: str,
        customer_name: str,
        group_members: list[str],
        group_name: str,
        *,
        send_test_message: bool = True,
        test_message_text: str = "测试",
        duplicate_name_policy: str = DuplicateNamePolicy.FIRST.value,
        post_confirm_wait_seconds: float = 1.0,
    ) -> bool:
        """
        Create a group chat including the customer and specified members.

        Args:
            device_serial: Target device serial number.
            customer_name: The customer to include in the group.
            group_members: Additional members to invite.
            group_name: Display name for the group chat.

        Returns:
            True if group was created successfully.
        """
        ...

    @abstractmethod
    async def restore_navigation(self) -> bool:
        """Navigate back from a group chat to the private chats list.

        Should be called after group creation completes to restore the UI
        to the expected state for subsequent operations.

        Returns:
            True if successfully returned to the private chats list.
        """
        ...

    @abstractmethod
    async def group_exists(
        self,
        device_serial: str,
        customer_name: str,
        group_name: str,
    ) -> bool:
        """
        Check if a group with the given name already exists for this customer.

        Args:
            device_serial: Target device serial number.
            customer_name: The customer name.
            group_name: Expected group name.

        Returns:
            True if the group already exists.
        """
        ...


class GroupChatService(IGroupChatService):
    """
    Concrete implementation using WeComService for ADB-based UI automation.

    Group creation flow:
    1. Navigate to the customer's chat
    2. Tap the "+" button to open the member-add dialog
    3. Search and select each configured member
    4. Confirm group creation
    5. Optionally rename the group

    This class also maintains a local record of created groups in the
    database for idempotency checks.
    """

    def __init__(
        self,
        wecom_service=None,
        db_path: str | None = None,
        workflow_service: GroupInviteWorkflowService | None = None,
    ) -> None:
        self._wecom_service = wecom_service
        self._db_path = db_path
        self._workflow_service = workflow_service or (
            GroupInviteWorkflowService(wecom_service) if wecom_service is not None else None
        )
        self._ensure_table()

    @contextmanager
    def _connection(self):
        if not self._db_path:
            self._db_path = str(get_db_path())
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        """Create the group_chats tracking table if it doesn't exist."""
        try:
            self._db_path = ensure_media_action_groups_table(self._db_path)
        except Exception as exc:
            logger.warning("Failed to ensure media_action_groups table: %s", exc)

    async def create_group_chat(
        self,
        device_serial: str,
        customer_name: str,
        group_members: list[str],
        group_name: str,
        *,
        send_test_message: bool = True,
        test_message_text: str = "测试",
        duplicate_name_policy: str = DuplicateNamePolicy.FIRST.value,
        post_confirm_wait_seconds: float = 1.0,
    ) -> bool:
        """
        Create a group chat via WeCom UI automation.

        The actual ADB automation steps are delegated to WeComService.
        This method handles the orchestration and record-keeping.
        """
        logger.info(
            "Creating group chat: device=%s, customer=%s, members=%s, name=%s",
            device_serial,
            customer_name,
            group_members,
            group_name,
        )

        try:
            if self._wecom_service is not None:
                success = await self._perform_ui_group_creation(
                    device_serial,
                    customer_name,
                    group_members,
                    group_name,
                    send_test_message=send_test_message,
                    test_message_text=test_message_text,
                    duplicate_name_policy=duplicate_name_policy,
                    post_confirm_wait_seconds=post_confirm_wait_seconds,
                )
            else:
                logger.warning("No WeComService available; recording group creation intent only")
                success = True

            if success:
                self._record_group(device_serial, customer_name, group_name, group_members)

            return success

        except Exception as exc:
            logger.error("Group chat creation failed: %s", exc)
            return False

    async def _perform_ui_group_creation(
        self,
        device_serial: str,
        customer_name: str,
        group_members: list[str],
        group_name: str,
        *,
        send_test_message: bool = True,
        test_message_text: str = "测试",
        duplicate_name_policy: str = DuplicateNamePolicy.FIRST.value,
        post_confirm_wait_seconds: float = 1.0,
    ) -> bool:
        """
        Execute the ADB UI automation steps for group creation.

        This is the integration point with WeComService. The actual
        implementation depends on the WeCom UI version and layout.
        """
        try:
            if self._workflow_service is None:
                logger.warning("No group invite workflow available")
                return False

            try:
                duplicate_policy = DuplicateNamePolicy(duplicate_name_policy)
            except ValueError:
                logger.warning(
                    "Unsupported duplicate_name_policy '%s', falling back to '%s'",
                    duplicate_name_policy,
                    DuplicateNamePolicy.FIRST.value,
                )
                duplicate_policy = DuplicateNamePolicy.FIRST

            request = GroupInviteRequest(
                device_serial=device_serial,
                customer_name=customer_name,
                members=group_members,
                group_name=group_name,
                duplicate_name_policy=duplicate_policy,
                post_confirm_wait_seconds=post_confirm_wait_seconds,
                send_test_message=send_test_message,
                test_message_text=test_message_text,
            )
            result = await self._workflow_service.create_group_chat(request)
            if not result.success:
                logger.error("UI automation for group creation failed: %s", result.error_message)
                return False

            for warning in result.warnings:
                logger.warning("Group invite workflow warning: %s", warning)

            logger.info("Group chat created successfully via UI automation")
            return True

        except Exception as exc:
            logger.error("UI automation for group creation failed: %s", exc)
            return False

    def _record_group(
        self,
        device_serial: str,
        customer_name: str,
        group_name: str,
        group_members: list[str],
    ) -> None:
        """Record the created group in the database for tracking."""
        import json

        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO media_action_groups
                        (device_serial, customer_name, group_name, group_members)
                    VALUES (?, ?, ?, ?)
                    """,
                    (device_serial, customer_name, group_name, json.dumps(group_members, ensure_ascii=False)),
                )
        except Exception as exc:
            logger.warning("Failed to record group creation: %s", exc)

    async def restore_navigation(self) -> bool:
        """Navigate from the newly created group chat back to private chats list."""
        if self._wecom_service is None:
            logger.debug("No WeComService available; cannot restore navigation")
            return False
        try:
            return await self._wecom_service.ensure_on_private_chats()
        except Exception as exc:
            logger.warning("Failed to restore navigation to private chats: %s", exc)
            return False

    async def group_exists(
        self,
        device_serial: str,
        customer_name: str,
        group_name: str,
    ) -> bool:
        """Check if we've already created a group for this customer."""
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT 1 FROM media_action_groups
                    WHERE device_serial = ?
                      AND customer_name = ?
                      AND group_name = ?
                      AND status = 'created'
                    LIMIT 1
                    """,
                    (device_serial, customer_name, group_name),
                )
                return cursor.fetchone() is not None
        except Exception as exc:
            logger.warning("Failed to check group existence: %s", exc)
            return False
