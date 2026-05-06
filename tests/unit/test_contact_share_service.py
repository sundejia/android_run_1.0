"""
Tests for ContactShareService pre-share message behavior.

Covers:
- _perform_ui_share sends message when request has send_message_before_share=True
- _perform_ui_share skips message when send_message_before_share=False
- _perform_ui_share continues card sharing even if message sending fails
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wecom_automation.services.contact_share.models import ContactShareRequest
from wecom_automation.services.contact_share.service import ContactShareService


@pytest.fixture
def mock_wecom():
    """Create a mock WeComService with all methods used by ContactShareService."""
    wecom = AsyncMock()
    wecom.navigate_to_chat = AsyncMock(return_value=True)
    wecom.get_current_screen = AsyncMock(return_value="private_chats")
    wecom.send_message = AsyncMock(return_value=(True, None))
    wecom.ensure_on_private_chats = AsyncMock(return_value=True)

    adb = AsyncMock()
    adb.get_ui_state = AsyncMock(return_value=(None, []))
    adb.tap = AsyncMock()
    adb.swipe = AsyncMock()
    wecom.adb = adb

    return wecom


@pytest.fixture
def service(mock_wecom):
    """Create a ContactShareService with mocked dependencies."""
    with patch(
        "wecom_automation.services.contact_share.service.ensure_contact_shares_table",
        return_value=":memory:",
    ):
        svc = ContactShareService(wecom_service=mock_wecom, db_path=":memory:")
    return svc


class TestContactShareServicePreShareMessage:
    """Tests for pre-share message sending in _perform_ui_share."""

    @pytest.mark.asyncio
    async def test_perform_ui_share_sends_message_when_configured(self, service, mock_wecom):
        """When request has send_message_before_share=True and text, send_message should be called."""
        # Make all UI steps succeed
        mock_wecom.navigate_to_chat = AsyncMock(return_value=True)
        mock_wecom.send_message = AsyncMock(return_value=(True, None))

        # Mock _tap_attach_button and subsequent steps to succeed
        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=True), \
             patch.object(service, "_confirm_send", return_value=True):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="主管王",
                send_message_before_share=True,
                pre_share_message_text="你好张三，推荐主管给你",
            )

            result = await service._perform_ui_share(request)

        assert result is True
        mock_wecom.send_message.assert_awaited_once_with("你好张三，推荐主管给你")

    @pytest.mark.asyncio
    async def test_perform_ui_share_uses_current_chat_without_re_navigation(self, service, mock_wecom):
        """When already in the customer chat, sharing should not leave and re-enter the list."""
        mock_wecom.get_current_screen = AsyncMock(return_value="chat")
        mock_wecom.navigate_to_chat = AsyncMock(return_value=True)

        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=True), \
             patch.object(service, "_confirm_send", return_value=True):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="主管王",
                send_message_before_share=False,
                pre_share_message_text="",
                assume_current_chat=True,
            )

            result = await service._perform_ui_share(request)

        assert result is True
        mock_wecom.navigate_to_chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_perform_ui_share_skips_message_when_not_configured(self, service, mock_wecom):
        """When request has send_message_before_share=False, send_message should NOT be called."""
        mock_wecom.navigate_to_chat = AsyncMock(return_value=True)

        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=True), \
             patch.object(service, "_confirm_send", return_value=True):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="主管王",
                send_message_before_share=False,
                pre_share_message_text="",
            )

            result = await service._perform_ui_share(request)

        assert result is True
        mock_wecom.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_perform_ui_share_continues_on_message_failure(self, service, mock_wecom):
        """When send_message fails, card sharing should still proceed."""
        mock_wecom.navigate_to_chat = AsyncMock(return_value=True)
        mock_wecom.send_message = AsyncMock(return_value=(False, "Send failed"))

        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=True), \
             patch.object(service, "_confirm_send", return_value=True):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="主管王",
                send_message_before_share=True,
                pre_share_message_text="你好",
            )

            result = await service._perform_ui_share(request)

        assert result is True
        mock_wecom.send_message.assert_awaited_once_with("你好")

    @pytest.mark.asyncio
    async def test_perform_ui_share_continues_on_message_exception(self, service, mock_wecom):
        """When send_message raises an exception, card sharing should still proceed."""
        mock_wecom.navigate_to_chat = AsyncMock(return_value=True)
        mock_wecom.send_message = AsyncMock(side_effect=RuntimeError("ADB timeout"))

        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=True), \
             patch.object(service, "_confirm_send", return_value=True):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="主管王",
                send_message_before_share=True,
                pre_share_message_text="你好",
            )

            result = await service._perform_ui_share(request)

        assert result is True
