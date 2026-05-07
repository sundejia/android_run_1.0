"""
Tests for ContactShareService pre-share message behavior.

Covers:
- _perform_ui_share sends message when request has send_message_before_share=True
- _perform_ui_share skips message when send_message_before_share=False
- _perform_ui_share continues card sharing even if message sending fails
- Page-state assertion (introduced after 2026-05-06 22:58 fake-success):
  every UI step is verified by re-reading the screen, mismatches dump the
  UI tree, abort the flow, and never write to the dedup table.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wecom_automation.services.contact_share.models import ContactShareRequest
from wecom_automation.services.contact_share.service import ContactShareService


def _state_ok():
    """Default _assert_page_state stub: every page transition succeeds.

    Most tests don't care about state validation — they want to exercise
    the surrounding flow under "happy path" conditions. Tests that *do*
    care simply override this stub via patch.object inside the test body.
    """
    return AsyncMock(return_value=True)


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
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_assert_page_state", _state_ok()):

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
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_assert_page_state", _state_ok()):

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
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_assert_page_state", _state_ok()):

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
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_assert_page_state", _state_ok()):

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
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_assert_page_state", _state_ok()):

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

    @pytest.mark.asyncio
    async def test_attach_button_matches_igu_resource_2026_05_06_build(self, service, mock_wecom):
        """Regression for the 2026-05-06 WeCom build where the attach button
        resource ID drifted to ``igu``. Without this entry in selectors the
        flow falls back to the position heuristic which is far less reliable.
        """
        elements = [
            {
                "index": 7,
                "resourceId": "com.tencent.wework:id/igu",
                "bounds": "[644,1425][700,1481]",
                "clickable": True,
            },
        ]
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, elements))
        mock_wecom.adb.tap = AsyncMock()

        result = await service._tap_attach_button()

        assert result is True
        mock_wecom.adb.tap.assert_awaited_once_with(7)


class TestContactSharePreMessageTransactionality:
    """Regression for the 'said-but-no-card' incident.

    When the pre-share message has been delivered but a later UI step fails,
    the customer must NOT be left expecting a card that never arrives — we
    must send the recovery_message_on_failure_text instead.
    """

    @pytest.mark.asyncio
    async def test_recovery_sent_when_picker_fails_after_pre_message(self, service, mock_wecom):
        mock_wecom.send_message = AsyncMock(return_value=(True, None))

        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=False), \
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_assert_page_state", _state_ok()):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="苏南老师",
                send_message_before_share=True,
                pre_share_message_text="可以的小宝，这是名片",
                recovery_message_on_failure_text="抱歉系统稍后重发，请稍候",
            )
            result = await service._perform_ui_share(request)

        assert result is False
        # Two send_message calls: pre-share + recovery
        send_calls = mock_wecom.send_message.await_args_list
        sent_texts = [call.args[0] for call in send_calls]
        assert "可以的小宝，这是名片" in sent_texts
        assert "抱歉系统稍后重发，请稍候" in sent_texts

    @pytest.mark.asyncio
    async def test_no_recovery_when_pre_message_was_not_sent(self, service, mock_wecom):
        """If pre-message was disabled, do NOT send a recovery message —
        otherwise we'd surface a confusing 'something went wrong' message to a
        customer who never saw the lead-in.
        """
        mock_wecom.send_message = AsyncMock(return_value=(True, None))

        with patch.object(service, "_tap_attach_button", return_value=False):
            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="苏南老师",
                send_message_before_share=False,
                pre_share_message_text="",
                recovery_message_on_failure_text="抱歉系统稍后重发，请稍候",
            )
            result = await service._perform_ui_share(request)

        assert result is False
        mock_wecom.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_recovery_when_pre_message_send_returned_false(
        self, service, mock_wecom
    ):
        """If the pre-message itself failed to send, the customer never saw
        anything — no need for a recovery, just fail closed.
        """
        mock_wecom.send_message = AsyncMock(return_value=(False, "Send failed"))

        with patch.object(service, "_tap_attach_button", return_value=False):
            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="苏南老师",
                send_message_before_share=True,
                pre_share_message_text="可以的小宝，这是名片",
                recovery_message_on_failure_text="抱歉系统稍后重发，请稍候",
            )
            result = await service._perform_ui_share(request)

        assert result is False
        # Exactly one send (the failed pre-message) — recovery is suppressed.
        assert mock_wecom.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_no_recovery_when_recovery_text_empty(self, service, mock_wecom):
        mock_wecom.send_message = AsyncMock(return_value=(True, None))

        with patch.object(service, "_tap_attach_button", return_value=False):
            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="苏南老师",
                send_message_before_share=True,
                pre_share_message_text="可以的小宝，这是名片",
                recovery_message_on_failure_text="   ",
            )
            result = await service._perform_ui_share(request)

        assert result is False
        # Only the pre-share message went out; empty recovery text is honored.
        assert mock_wecom.send_message.await_count == 1


class TestContactSharePickerFallback:
    """Default picker uses CompositeContactFinder (search → scroll)."""

    @pytest.mark.asyncio
    async def test_default_finder_falls_back_to_scroll_when_search_misses(
        self, service, mock_wecom
    ):
        # Make UI calls for SearchContactFinder return nothing useful, but
        # ScrollContactFinder will see a matching row.
        elements_for_search = [
            {"index": 50, "className": "android.widget.EditText", "bounds": "[50,60][700,110]"},
        ]
        elements_for_scroll = [
            # Picker signature so ScrollContactFinder's context check passes
            {"index": 1, "resourceId": "com.tencent.wework:id/cth"},
            {"index": 99, "text": "苏南老师", "bounds": "[200,200][800,260]"},
        ]
        # The composite finder reuses adb.get_ui_state across many calls; we
        # simulate "search miss → scroll hit" by always returning the scroll
        # match — search will still miss because there's no input field row.
        async def get_ui_state(force=False):  # noqa: ARG001
            return (None, elements_for_search + elements_for_scroll)

        mock_wecom.adb.get_ui_state = AsyncMock(side_effect=get_ui_state)
        mock_wecom.adb.tap = AsyncMock()
        mock_wecom.adb.clear_text_field = AsyncMock()
        mock_wecom.adb.input_text = AsyncMock()
        mock_wecom.adb.wait = AsyncMock()

        ok = await service._select_contact_from_picker("苏南老师", device_serial="dev1")

        assert ok is True
        # Scroll finder taps by the row's index (99)
        assert any(call.args == (99,) for call in mock_wecom.adb.tap.await_args_list)


class TestPageStateAssertionRegression:
    """Regression for the 2026-05-06 22:58 fake-success.

    The share flow used to trust each step's "I tapped something matching"
    return value. With page-state validation in place, a missed transition
    must:
      1. Abort the flow (return False).
      2. NOT write to ``media_action_contact_shares`` (next image retries).
      3. Trigger the recovery message if pre-message was already sent.
      4. Dump the full UI tree to ``logs/contact_share_dump_*.json``.
    """

    @pytest.mark.asyncio
    async def test_attach_button_state_check_failure_aborts_and_does_not_record(
        self, service, mock_wecom, tmp_path, monkeypatch
    ):
        # Redirect dump dir into pytest tmp so the test stays clean.
        monkeypatch.chdir(tmp_path)
        mock_wecom.send_message = AsyncMock(return_value=(True, None))

        # The chat-screen UI returned by adb won't satisfy is_attach_panel_open,
        # so _assert_page_state("attach_panel", ...) will fail — exactly the
        # 22:58 scenario.
        chat_only = [
            {"index": 0, "className": "android.widget.EditText"},
            {"index": 1, "text": "聊天历史"},
        ]
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, chat_only))

        record_spy = MagicMock()

        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=True), \
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_record_share", record_spy):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="客户A",
                contact_name="苏南老师",
                send_message_before_share=True,
                pre_share_message_text="可以的小宝，这是名片",
                recovery_message_on_failure_text="抱歉系统稍后重发，请稍候",
            )
            result = await service._perform_ui_share(request)

        assert result is False
        record_spy.assert_not_called()
        sent_texts = [call.args[0] for call in mock_wecom.send_message.await_args_list]
        assert "可以的小宝，这是名片" in sent_texts
        assert "抱歉系统稍后重发，请稍候" in sent_texts

        dumps = list((tmp_path / "logs").glob("contact_share_dump_*_attach_button.json"))
        assert dumps, "expected a UI dump for the failed attach_button state check"

    @pytest.mark.asyncio
    async def test_share_contact_card_does_not_record_on_state_check_failure(
        self, service, mock_wecom, tmp_path, monkeypatch
    ):
        """End-to-end via ``share_contact_card`` — the public entry path
        must mirror _perform_ui_share's "no record on state-check failure"
        contract so future callers don't accidentally bypass it.
        """
        monkeypatch.chdir(tmp_path)
        mock_wecom.send_message = AsyncMock(return_value=(True, None))
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, [
            {"index": 0, "className": "android.widget.EditText"},
        ]))

        record_spy = MagicMock()
        with patch.object(service, "_tap_attach_button", return_value=True), \
             patch.object(service, "_open_contact_card_menu", return_value=True), \
             patch.object(service, "_select_contact_from_picker", return_value=True), \
             patch.object(service, "_confirm_send", return_value=True), \
             patch.object(service, "_record_share", record_spy):

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="客户A",
                contact_name="苏南老师",
            )
            result = await service.share_contact_card(request)

        assert result is False
        record_spy.assert_not_called()


class TestStrictMatchPreventsFakeSuccess:
    """The original substring matching let any node containing 'Send' /
    '名片' / '确定' satisfy the menu/confirm steps. Exact match must put
    a stop to that — these tests pin the new behaviour at the helper
    level so a future regression in ContactShareService is impossible
    without flipping the helper too.
    """

    def test_substring_default_still_matches(self):
        from wecom_automation.services.ui_search.ui_helpers import find_elements_by_keywords

        elements = [
            {"text": "我的名片夹", "index": 1},
            {"text": "Contact Card", "index": 2},
        ]
        substring_hits = find_elements_by_keywords(
            elements, text_patterns=("名片",)
        )
        assert len(substring_hits) == 1
        assert substring_hits[0]["text"] == "我的名片夹"

    def test_exact_mode_does_not_match_my_card_folder_substring(self):
        from wecom_automation.services.ui_search.ui_helpers import find_elements_by_keywords

        elements = [
            {"text": "我的名片夹", "index": 1},
            {"text": "Contact Card", "index": 2},
        ]
        exact_hits = find_elements_by_keywords(
            elements,
            text_patterns=("Contact Card", "名片"),
            text_match_mode="exact",
        )
        assert [e["text"] for e in exact_hits] == ["Contact Card"]

    def test_exact_mode_send_does_not_match_send_to_label(self):
        """The very label that caused 22:58: 'Send to:' on picker title."""
        from wecom_automation.services.ui_search.ui_helpers import find_elements_by_keywords

        elements = [
            {"text": "Send to:", "index": 1},
            {"text": "Sender", "index": 2},
        ]
        exact_hits = find_elements_by_keywords(
            elements,
            text_patterns=("Send", "SEND", "发送", "确定"),
            text_match_mode="exact",
        )
        assert exact_hits == []


class TestOpenContactCardMenuMissDiagnostics:
    """When both fast-path and slow-path miss the Contact Card item we
    now (a) log every node whose text/desc contains a Contact-Card-shaped
    keyword so we can extend selectors blind, and (b) dump the full UI
    tree to ``logs/contact_share_dump_*_contact_card_menu.json`` so a
    real device snapshot is preserved off-log.

    This is the regression for the 00:07 failure on 10AE9P1DTT002LE
    where attach_panel state-check passed (aij/aif fix worked) but
    Contact Card itself was still unfindable on page 1 *and* page 2,
    and we had no UI dump to debug it because the failure path
    short-circuited before ``_assert_page_state``.
    """

    @pytest.mark.asyncio
    async def test_miss_with_request_dumps_ui_and_logs_candidates(
        self, service, mock_wecom
    ):
        ui_after_swipe = (
            None,
            [
                {
                    "text": "我的名片夹",
                    "contentDescription": "",
                    "resourceId": "com.tencent.wework:id/aif",
                    "bounds": "[0,0][100,100]",
                },
                {
                    "text": "Personal Card",
                    "contentDescription": "",
                    "resourceId": "com.tencent.wework:id/aif",
                    "bounds": "[0,100][100,200]",
                },
            ],
        )
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=ui_after_swipe)

        with patch.object(service, "_tap_contact_card_menu", return_value=False), \
             patch.object(service, "_swipe_attach_grid", return_value=True), \
             patch.object(service, "_dump_full_ui_for_diagnosis") as mock_dump:

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="主管王",
            )
            result = await service._open_contact_card_menu(request=request)

        assert result is False
        mock_dump.assert_called_once()
        kwargs = mock_dump.call_args.kwargs
        assert kwargs["step"] == "contact_card_menu"
        assert kwargs["expected_state"] == "contact_card_visible"
        assert "after_swipe=True" in kwargs["reason"]
        assert kwargs["request"] is request

    @pytest.mark.asyncio
    async def test_miss_without_request_does_not_dump_but_still_safe(
        self, service, mock_wecom
    ):
        """Backward-compat: legacy callers that don't pass ``request``
        must not blow up — they just skip the dump.
        """
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, []))

        with patch.object(service, "_tap_contact_card_menu", return_value=False), \
             patch.object(service, "_swipe_attach_grid", return_value=True), \
             patch.object(service, "_dump_full_ui_for_diagnosis") as mock_dump:

            result = await service._open_contact_card_menu()

        assert result is False
        mock_dump.assert_not_called()

    @pytest.mark.asyncio
    async def test_miss_when_swipe_itself_fails_still_dumps(
        self, service, mock_wecom
    ):
        """If the swipe fails (no GridView found) we still want the
        UI dump — that's exactly the case where selector intel is most
        valuable, since *something* about the panel layout is foreign.
        """
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(None, []))

        with patch.object(service, "_tap_contact_card_menu", return_value=False), \
             patch.object(service, "_swipe_attach_grid", return_value=False), \
             patch.object(service, "_dump_full_ui_for_diagnosis") as mock_dump:

            request = ContactShareRequest(
                device_serial="dev1",
                customer_name="张三",
                contact_name="主管王",
            )
            result = await service._open_contact_card_menu(request=request)

        assert result is False
        mock_dump.assert_called_once()
        assert "after_swipe=False" in mock_dump.call_args.kwargs["reason"]


class TestSwipeAttachGridResolvesByPattern:
    """`_swipe_attach_grid` used to hardcode ``'ahe'`` as the GridView
    resource id. The 720x1612, 2026-05-06 build moved it to ``'aij'``,
    which is exactly why Contact Card on page 2 became unreachable —
    every share aborted right after the + button.

    These regressions lock the swipe path against future build drifts
    by walking the full ``ATTACH_GRID_RESOURCE_PATTERNS`` set.
    """

    @pytest.mark.asyncio
    async def test_swipes_legacy_ahe_grid(self, service, mock_wecom):
        mock_wecom.adb.get_ui_state = AsyncMock(
            return_value=(
                None,
                [
                    {
                        "resourceId": "com.tencent.wework:id/ahe",
                        "bounds": "[0,1000][720,1400]",
                    }
                ],
            )
        )
        mock_wecom.adb.swipe = AsyncMock()

        result = await service._swipe_attach_grid()

        assert result is True
        mock_wecom.adb.swipe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swipes_2026_05_06_aij_grid(self, service, mock_wecom):
        """The exact failure case from the contact_share_dump on
        device 10AE9P1DTT002LE: GridView is ``aij``, not ``ahe``.
        """
        mock_wecom.adb.get_ui_state = AsyncMock(
            return_value=(
                None,
                [
                    {
                        "resourceId": "com.tencent.wework:id/aij",
                        "bounds": "[0,1032][720,1442]",
                    }
                ],
            )
        )
        mock_wecom.adb.swipe = AsyncMock()

        result = await service._swipe_attach_grid()

        assert result is True
        mock_wecom.adb.swipe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_known_grid_id_present(
        self, service, mock_wecom
    ):
        mock_wecom.adb.get_ui_state = AsyncMock(
            return_value=(
                None,
                [
                    {
                        "resourceId": "com.tencent.wework:id/something_else",
                        "bounds": "[0,0][100,100]",
                    }
                ],
            )
        )
        mock_wecom.adb.swipe = AsyncMock()

        result = await service._swipe_attach_grid()

        assert result is False
        mock_wecom.adb.swipe.assert_not_awaited()


class TestSwipeAttachGridAvoidsEdgeGestureZone:
    """Regression for 12:43:09 dump on 10AE9P1DTT002LE: the prior
    swipe started 30px from the right edge and ended 30px from the
    left edge — both inside Android's system back-gesture zones
    (≈20–48dp). The OS swallowed the gesture, the GridView never
    paged, and Contact Card on page 2 stayed unreachable forever.

    These tests pin three properties of the new geometry:
    1. start_x is far enough from the right edge to clear the zone,
    2. end_x is far enough from the left edge to clear the zone,
    3. duration is long enough to read as a content scroll, not a
       back-fling.
    """

    @pytest.mark.asyncio
    async def test_swipe_starts_and_ends_outside_edge_gesture_zone(
        self, service, mock_wecom
    ):
        # Real bounds from the 720x1612 dump that exposed the bug.
        mock_wecom.adb.get_ui_state = AsyncMock(
            return_value=(
                None,
                [
                    {
                        "resourceId": "com.tencent.wework:id/aij",
                        "bounds": "[0,1134][720,1544]",
                    }
                ],
            )
        )
        mock_wecom.adb.swipe = AsyncMock()

        result = await service._swipe_attach_grid()

        assert result is True
        mock_wecom.adb.swipe.assert_awaited_once()
        args, kwargs = mock_wecom.adb.swipe.await_args
        start_x, _start_y, end_x, _end_y = args[0], args[1], args[2], args[3]

        # Both endpoints must be ≥ 100px from the screen edges so the
        # system gesture detector doesn't claim the swipe.
        assert 720 - start_x >= 100, f"start_x={start_x} too close to right edge"
        assert end_x >= 100, f"end_x={end_x} too close to left edge"
        # Distance must remain large enough to commit a page change.
        assert (start_x - end_x) >= 240, (
            f"swipe distance only {start_x - end_x}px — likely won't flip page"
        )
        # Duration must be slow enough to not be misread as a fling.
        assert kwargs.get("duration_ms", 0) >= 500, kwargs

    @pytest.mark.asyncio
    async def test_narrow_grid_shrinks_margin_to_preserve_swipe_distance(
        self, service, mock_wecom
    ):
        """If a freakishly narrow grid would leave <240px of swipe
        travel after the 100px margin, the implementation drops the
        margin instead of producing a no-op swipe. This protects the
        legacy 1080x*** case if anyone ever swaps in a smaller layout.
        """
        # Grid is 280px wide — applying full 100px margin both sides
        # would leave only 80px of travel.
        mock_wecom.adb.get_ui_state = AsyncMock(
            return_value=(
                None,
                [
                    {
                        "resourceId": "com.tencent.wework:id/aij",
                        "bounds": "[0,1000][280,1300]",
                    }
                ],
            )
        )
        mock_wecom.adb.swipe = AsyncMock()

        result = await service._swipe_attach_grid()

        assert result is True
        args, _ = mock_wecom.adb.swipe.await_args
        start_x, _, end_x, _ = args[0], args[1], args[2], args[3]
        # Swipe distance must remain at least the configured floor.
        assert (start_x - end_x) >= 240, (
            f"narrow-grid swipe distance only {start_x - end_x}px"
        )


class TestAssertPageStateContactPicker2026_05_07Build:
    """End-to-end regression for the 2026-05-07 contact-picker drift.

    On this WeCom build the picker title's resourceId moved to ``nle``
    and the list container moved to ``cwa``; the title text became
    ``Select Contact(s)`` (with a literal ``(s)`` suffix). The validator
    only knew the legacy ``nca``/``cth`` IDs and a fixed catalog of
    title strings, so every share that *did* reach the picker page
    aborted at the post-Contact-Card state assertion. Customers got the
    apology recovery message instead of the actual card.

    Captured from
    ``logs/contact_share_dump_20260507_134355_516273_contact_card_menu.json``.
    """

    @pytest.mark.asyncio
    async def test_assert_contact_picker_passes_for_nle_cwa_build(
        self, service, mock_wecom
    ):
        ui_tree_obj = object()
        elements = [
            {
                "className": "android.widget.TextView",
                "resourceId": "com.tencent.wework:id/nle",
                "text": "Select Contact(s)",
                "bounds": "[20,81][302,127]",
                "index": 4,
            },
            {
                "className": "android.widget.ListView",
                "resourceId": "com.tencent.wework:id/cwa",
                "bounds": "[0,152][720,1612]",
                "index": 7,
            },
            {"text": "Customer", "bounds": "[112,178][260,221]", "index": 10},
            {"text": "Company Contacts", "bounds": "[112,274][400,317]", "index": 13},
            {
                "text": "★ Starred Contact",
                "resourceId": "com.tencent.wework:id/gpa",
                "bounds": "[0,344][720,402]",
                "index": 15,
            },
            {
                "text": "Frequent Contacts",
                "resourceId": "com.tencent.wework:id/nef",
                "bounds": "[28,529][285,567]",
                "index": 19,
            },
        ]
        mock_wecom.adb.get_ui_state = AsyncMock(return_value=(ui_tree_obj, elements))

        request = ContactShareRequest(
            device_serial="10AE9P1DTT002LE",
            customer_name="B2604250558-(保底正常)",
            contact_name="孙德家",
            send_message_before_share=False,
            pre_share_message_text="",
        )

        with patch.object(service, "_dump_full_ui_for_diagnosis") as mock_dump, \
             patch(
                 "wecom_automation.services.contact_share.service._STATE_STABILIZATION_DELAY",
                 0,
             ):
            ok = await service._assert_page_state(
                "contact_picker",
                step="contact_card_menu",
                request=request,
            )

        assert ok is True, (
            "PageStateValidator must accept the 2026-05-07 build picker "
            "(nle title + cwa list + 'Select Contact(s)' label)"
        )
        mock_dump.assert_not_called()
