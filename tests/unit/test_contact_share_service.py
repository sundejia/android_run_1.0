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


class TestContactShareAttachButtonSelector:
    """Regression tests for the attach-button selector drift fix.

    The original selector hardcoded ``i9u`` and silently failed on devices
    where WeCom's resource ID had drifted to ``id8`` or another mangled name.
    These tests pin the new behavior:
      1. ``id8`` works without the position fallback.
      2. When NO known resource ID matches, the position heuristic picks the
         rightmost clickable in the bottom band of the screen.
      3. The Send button is excluded from the position fallback.
    """

    @pytest.mark.asyncio
    async def test_attach_button_matches_id8_resource(self, service, mock_wecom):
        """id8 (1080x2340 build) should match without falling back to position heuristic."""
        elements = [
            {
                "index": 12,
                "resourceId": "com.tencent.wework:id/id8",
                "bounds": "[660,1700][720,1760]",
                "clickable": True,
            },
        ]
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, elements))
        mock_wecom.adb.tap = AsyncMock()

        result = await service._tap_attach_button()

        assert result is True
        mock_wecom.adb.tap.assert_awaited_once_with(12)

    @pytest.mark.asyncio
    async def test_attach_button_falls_back_to_position_when_resource_unknown(self, service, mock_wecom):
        """When neither i9u nor id8 is present, the rightmost bottom clickable wins."""
        elements = [
            # Random unrelated middle-of-screen element
            {
                "index": 5,
                "resourceId": "com.tencent.wework:id/abc",
                "bounds": "[10,800][200,860]",
                "clickable": True,
            },
            # Bottom-left input field — must be skipped (EditText)
            {
                "index": 6,
                "className": "android.widget.EditText",
                "resourceId": "com.tencent.wework:id/idj",
                "bounds": "[10,1700][600,1760]",
                "clickable": True,
            },
            # Voice/keyboard toggle on left
            {
                "index": 7,
                "resourceId": "com.tencent.wework:id/xyz",
                "bounds": "[0,1700][60,1760]",
                "clickable": True,
            },
            # Attach button (rightmost) — should be picked by position heuristic
            {
                "index": 8,
                "resourceId": "com.tencent.wework:id/zzz_renamed",
                "bounds": "[660,1700][720,1760]",
                "clickable": True,
            },
        ]
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, elements))
        mock_wecom.adb.tap = AsyncMock()

        result = await service._tap_attach_button()

        assert result is True
        mock_wecom.adb.tap.assert_awaited_once_with(8)

    @pytest.mark.asyncio
    async def test_attach_button_position_fallback_skips_send_button(self, service, mock_wecom):
        """Send button at the bottom-right MUST NOT be selected as the attach button."""
        elements = [
            # Send button on the far right — must be excluded
            {
                "index": 20,
                "resourceId": "com.tencent.wework:id/dak",
                "text": "Send",
                "bounds": "[640,1700][720,1760]",
                "clickable": True,
            },
            # Real attach button to the left of Send
            {
                "index": 21,
                "resourceId": "com.tencent.wework:id/something_new",
                "bounds": "[560,1700][620,1760]",
                "clickable": True,
            },
        ]
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, elements))
        mock_wecom.adb.tap = AsyncMock()

        result = await service._tap_attach_button()

        assert result is True
        mock_wecom.adb.tap.assert_awaited_once_with(21)

    @pytest.mark.asyncio
    async def test_attach_button_returns_false_when_no_candidates(self, service, mock_wecom):
        """When the bottom band has no clickable icons, return False (not raise)."""
        elements = [
            {
                "index": 1,
                "resourceId": "header",
                "bounds": "[0,0][720,100]",
                "clickable": True,
            },
        ]
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, elements))
        mock_wecom.adb.tap = AsyncMock()

        result = await service._tap_attach_button()

        assert result is False
        mock_wecom.adb.tap.assert_not_awaited()
