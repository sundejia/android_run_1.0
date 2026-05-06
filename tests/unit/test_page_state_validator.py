"""
Unit tests for PageStateValidator.

The validator is the safety net that prevents ContactShareService from
fake-succeeding on the wrong page (regression: 2026-05-06 22:58 incident).
Each predicate must be confident enough to recognize its own page AND
disjoint enough not to falsely match other share-flow states.
"""

from __future__ import annotations

import pytest

from wecom_automation.services.contact_share.page_state import PageStateValidator


def _elem(**fields):
    """Build a minimal UI element dict using the keys the validator inspects."""
    return dict(fields)


# ── Fixtures: one realistic element list per page state ───────────


@pytest.fixture
def attach_panel_elements() -> list[dict]:
    """Attach panel popped open over chat — GridView + ≥4 attach items."""
    return [
        _elem(resourceId="com.tencent.wework:id/ahe", index=0),
        _elem(resourceId="com.tencent.wework:id/aha", text="Image", index=1),
        _elem(resourceId="com.tencent.wework:id/aha", text="Camera", index=2),
        _elem(resourceId="com.tencent.wework:id/aha", text="Contact Card", index=3),
        _elem(resourceId="com.tencent.wework:id/aha", text="Favorites", index=4),
        # Chat input row stays in tree — must NOT confuse "chat_screen"
        _elem(className="android.widget.EditText", index=5),
    ]


@pytest.fixture
def attach_panel_no_grid_elements() -> list[dict]:
    """Attach panel where the GridView resourceId drifted but item IDs survived."""
    return [
        _elem(resourceId="com.tencent.wework:id/aha", text="Image", index=1),
        _elem(resourceId="com.tencent.wework:id/aha", text="Camera", index=2),
        _elem(resourceId="com.tencent.wework:id/aha", text="Contact Card", index=3),
        _elem(resourceId="com.tencent.wework:id/aha", text="Favorites", index=4),
        _elem(resourceId="com.tencent.wework:id/aha", text="Location", index=5),
    ]


@pytest.fixture
def contact_picker_elements() -> list[dict]:
    """Contact picker (Select Contact screen)."""
    return [
        _elem(resourceId="com.tencent.wework:id/nca", text="Select Contact", index=0),
        _elem(resourceId="com.tencent.wework:id/cth", index=1),
        _elem(text="孙德家", index=10),
        _elem(text="苏南老师", index=11),
    ]


@pytest.fixture
def confirm_send_dialog_elements() -> list[dict]:
    """Confirm-send dialog with both Send and Cancel buttons (Button class)."""
    return [
        _elem(className="android.widget.Button", text="Cancel", index=0),
        _elem(className="android.widget.Button", text="Send", index=1),
        _elem(text="Send '孙德家' to '客户A'?", index=2),
    ]


@pytest.fixture
def confirm_send_dialog_imageview_elements() -> list[dict]:
    """Some WeCom builds expose Send/Cancel as ImageView with dak/dah resourceIds."""
    return [
        _elem(resourceId="com.tencent.wework:id/dak", className="android.widget.ImageView", index=0),
        _elem(resourceId="com.tencent.wework:id/dah", className="android.widget.ImageView", index=1),
    ]


@pytest.fixture
def chat_screen_elements() -> list[dict]:
    """Plain chat screen — input field, no panel, no picker, no dialog."""
    return [
        _elem(className="android.widget.EditText", index=0, bounds="[50,1400][700,1500]"),
        _elem(text="客户A", index=1),
        _elem(text="历史消息节点", index=2),
    ]


# ── Positive recognition ─────────────────────────────────────────


class TestAttachPanelRecognition:
    def test_recognized_via_ahe_grid(self, attach_panel_elements):
        assert PageStateValidator.is_attach_panel_open(attach_panel_elements) is True

    def test_recognized_via_item_count_when_grid_id_drifted(self, attach_panel_no_grid_elements):
        assert PageStateValidator.is_attach_panel_open(attach_panel_no_grid_elements) is True

    def test_not_recognized_on_chat_screen(self, chat_screen_elements):
        assert PageStateValidator.is_attach_panel_open(chat_screen_elements) is False

    def test_empty_list_returns_false(self):
        assert PageStateValidator.is_attach_panel_open([]) is False


class TestContactPickerRecognition:
    def test_recognized_via_nca_title(self, contact_picker_elements):
        assert PageStateValidator.is_contact_picker_open(contact_picker_elements) is True

    def test_recognized_via_title_text_only(self):
        elements = [_elem(text="选择联系人", index=0)]
        assert PageStateValidator.is_contact_picker_open(elements) is True

    def test_not_recognized_on_attach_panel(self, attach_panel_elements):
        assert PageStateValidator.is_contact_picker_open(attach_panel_elements) is False

    def test_not_recognized_on_chat_screen(self, chat_screen_elements):
        assert PageStateValidator.is_contact_picker_open(chat_screen_elements) is False


class TestConfirmSendDialogRecognition:
    def test_recognized_via_button_class(self, confirm_send_dialog_elements):
        assert PageStateValidator.is_confirm_send_dialog_open(confirm_send_dialog_elements) is True

    def test_recognized_via_dak_dah_resource_ids(self, confirm_send_dialog_imageview_elements):
        assert (
            PageStateValidator.is_confirm_send_dialog_open(confirm_send_dialog_imageview_elements)
            is True
        )

    def test_send_alone_is_not_a_dialog(self):
        """A lone Send button (e.g. chat compose row) must not satisfy."""
        elements = [_elem(className="android.widget.Button", text="Send", index=0)]
        assert PageStateValidator.is_confirm_send_dialog_open(elements) is False

    def test_cancel_alone_is_not_a_dialog(self):
        elements = [_elem(className="android.widget.Button", text="Cancel", index=0)]
        assert PageStateValidator.is_confirm_send_dialog_open(elements) is False

    def test_send_to_label_does_not_match(self):
        """'Send to:' text on the picker title must NOT count as a Send button.

        Exact text matching is the whole point — the original substring
        match was the second half of 22:58's fake-success.
        """
        elements = [
            _elem(className="android.widget.Button", text="Send to:", index=0),
            _elem(className="android.widget.Button", text="Cancel", index=1),
        ]
        assert PageStateValidator.is_confirm_send_dialog_open(elements) is False


class TestChatScreenRecognition:
    def test_recognized_when_only_input_visible(self, chat_screen_elements):
        assert PageStateValidator.is_chat_screen(chat_screen_elements) is True

    def test_not_recognized_when_attach_panel_above(self, attach_panel_elements):
        """Chat input row is still in tree but attach_panel takes precedence."""
        assert PageStateValidator.is_chat_screen(attach_panel_elements) is False

    def test_not_recognized_on_picker(self, contact_picker_elements):
        assert PageStateValidator.is_chat_screen(contact_picker_elements) is False

    def test_not_recognized_on_confirm_dialog(self, confirm_send_dialog_elements):
        # Add an EditText to make the test stricter — even with input present,
        # confirm dialog must mask chat_screen recognition.
        with_input = confirm_send_dialog_elements + [
            _elem(className="android.widget.EditText", index=99)
        ]
        assert PageStateValidator.is_chat_screen(with_input) is False

    def test_no_input_field_means_not_chat(self):
        elements = [_elem(text="some label", index=0)]
        assert PageStateValidator.is_chat_screen(elements) is False


# ── State disjointness (the cross-product matrix) ────────────────


class TestStatesAreDisjoint:
    """No element list should be classified as more than one state.

    The validator uses chat_screen as a "fallback" so it deliberately
    excludes the other three; this matrix confirms the exclusion is in
    place for every page fixture above.
    """

    @pytest.mark.parametrize(
        "fixture_name,expected_state",
        [
            ("attach_panel_elements", "attach_panel"),
            ("contact_picker_elements", "contact_picker"),
            ("confirm_send_dialog_elements", "confirm_send_dialog"),
            ("chat_screen_elements", "chat_screen"),
        ],
    )
    def test_each_fixture_matches_exactly_one_state(
        self,
        fixture_name,
        expected_state,
        request,
    ):
        elements = request.getfixturevalue(fixture_name)
        states_matched = []
        if PageStateValidator.is_attach_panel_open(elements):
            states_matched.append("attach_panel")
        if PageStateValidator.is_contact_picker_open(elements):
            states_matched.append("contact_picker")
        if PageStateValidator.is_confirm_send_dialog_open(elements):
            states_matched.append("confirm_send_dialog")
        if PageStateValidator.is_chat_screen(elements):
            states_matched.append("chat_screen")
        assert states_matched == [expected_state], (
            f"{fixture_name} should match only {expected_state!r}, "
            f"got {states_matched!r}"
        )


class TestDescribeHelper:
    def test_describe_unknown_when_no_match(self):
        assert PageStateValidator.describe([]) == "unknown"
        assert PageStateValidator.describe([_elem(text="random", index=0)]) == "unknown"

    def test_describe_lists_attach_panel(self, attach_panel_elements):
        assert "attach_panel" in PageStateValidator.describe(attach_panel_elements)

    def test_describe_lists_picker(self, contact_picker_elements):
        assert "contact_picker" in PageStateValidator.describe(contact_picker_elements)
