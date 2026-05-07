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
def attach_panel_2026_05_06_build_elements() -> list[dict]:
    """Real attach-panel snapshot from 720x1612, 2026-05-06 build.

    GridView is ``aij`` (not legacy ``ahe``) and item labels use ``aif``
    (not legacy ``aha``). Captured verbatim from
    ``logs/contact_share_dump_*_attach_button.json`` after the page-state
    envelope correctly caught a missed transition. The plain chat input
    EditText stays in tree on this build too so chat_screen exclusion
    must work via the new aij/aif signature.
    """
    return [
        _elem(className="android.widget.EditText", resourceId="com.tencent.wework:id/ih6", index=37),
        _elem(className="android.widget.GridView", resourceId="com.tencent.wework:id/aij", index=41),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Image", index=43),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Camera", index=45),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Favorites", index=47),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Voice Call", index=49),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Red Packets", index=51),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Document", index=53),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Calendar", index=55),
        _elem(className="android.widget.TextView", resourceId="com.tencent.wework:id/aif", text="Quick Meeting", index=57),
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
def contact_picker_2026_05_07_build_elements() -> list[dict]:
    """Real contact-picker snapshot from 720x1612, 2026-05-07 build.

    Title resourceId is ``nle`` (not legacy ``nca``) and the list container
    is ``cwa`` (not legacy ``cth``). Title text is plural ``Select Contact(s)``
    rather than the singular forms previously matched.

    Captured verbatim from
    ``logs/contact_share_dump_20260507_134355_516273_contact_card_menu.json``
    where ``Contact Card`` was correctly tapped — the picker pushed onto
    the screen exactly as expected — but PageStateValidator returned
    ``unknown`` because every recognition signal still pointed at the
    legacy build's strings/resourceIds. The whole flow then aborted into
    the recovery message path even though the picker was right there.
    """
    return [
        _elem(
            className="android.widget.TextView",
            resourceId="com.tencent.wework:id/nle",
            text="Select Contact(s)",
            bounds="[20,81][302,127]",
            index=4,
        ),
        _elem(
            className="android.widget.ListView",
            resourceId="com.tencent.wework:id/cwa",
            bounds="[0,152][720,1612]",
            index=7,
        ),
        _elem(text="Customer", bounds="[112,178][260,221]", index=10),
        _elem(text="Company Contacts", bounds="[112,274][400,317]", index=13),
        _elem(
            text="★ Starred Contact",
            resourceId="com.tencent.wework:id/gpa",
            bounds="[0,344][720,402]",
            index=15,
        ),
        _elem(
            text="Frequent Contacts",
            resourceId="com.tencent.wework:id/nef",
            bounds="[28,529][285,567]",
            index=19,
        ),
        _elem(text="爱吃汉堡不加酱", bounds="[132,692][356,735]", index=22),
        _elem(text="B2305170741-[重复(保底正常)]", bounds="[132,887][443,930]", index=26),
    ]


@pytest.fixture
def contact_picker_with_only_plural_title_text() -> list[dict]:
    """Picker page where neither ``nca``/``cth`` nor ``nle``/``cwa`` is present
    in any resourceId, so recognition has to fall back to the title text.

    The real-world picker title is ``Select Contact(s)`` with a literal
    ``(s)`` suffix. The legacy validator only matched a fixed catalog of
    exact strings (``Select Contact`` / ``Select a Contact`` / ``Select`` /
    ``选择联系人`` / ``选择联系人:``) and would silently miss this build.
    """
    return [
        _elem(text="Select Contact(s)", index=0),
        _elem(text="Customer", index=1),
        _elem(text="Company Contacts", index=2),
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
def confirm_send_dialog_2026_05_07_textview_elements() -> list[dict]:
    """2026-05-07 (720x1612) build: confirm dialog uses TextView + de2/de5.

    Captured live from the device with a real Contact Card flow ending at the
    'Send to:' confirmation modal. Neither Button-class detection nor the
    legacy dak/dah resource ids match — only de2 (Cancel) + de5 (Send) do.
    Recipient/title TextViews (de8/fu5) are kept to keep the fixture
    realistic so the predicate cannot accidentally pass on Send/Cancel
    text alone.
    """
    return [
        _elem(resourceId="com.tencent.wework:id/de8", className="android.widget.TextView", text="Send to:", index=0),
        _elem(resourceId="com.tencent.wework:id/fu5", className="android.widget.TextView", text="客户A", index=1),
        _elem(resourceId="com.tencent.wework:id/de2", className="android.widget.TextView", text="Cancel", index=2),
        _elem(resourceId="com.tencent.wework:id/de5", className="android.widget.TextView", text="Send", index=3),
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

    def test_recognized_on_2026_05_06_build_with_aij_aif(
        self, attach_panel_2026_05_06_build_elements
    ):
        """Regression for the 720x1612 2026-05-06 build whose attach-panel
        signature drifted to ``aij``/``aif``. Without recognising this
        the page-state envelope rejected a transition that *did* happen
        and the share aborted right after the + button.
        """
        assert (
            PageStateValidator.is_attach_panel_open(attach_panel_2026_05_06_build_elements)
            is True
        )

    def test_chat_screen_excludes_2026_05_06_attach_panel(
        self, attach_panel_2026_05_06_build_elements
    ):
        """The 2026-05-06 attach-panel snapshot still has the chat input
        EditText in tree. ``is_chat_screen`` must defer to attach_panel
        recognition just like it does for the legacy build.
        """
        assert (
            PageStateValidator.is_chat_screen(attach_panel_2026_05_06_build_elements)
            is False
        )

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

    def test_recognized_on_2026_05_07_build_with_nle_cwa(
        self, contact_picker_2026_05_07_build_elements
    ):
        """Regression for the 720x1612 2026-05-07 build whose contact-picker
        signature drifted to ``nle`` (title) / ``cwa`` (list). Without
        recognising this signature the page-state envelope rejected a
        transition that *did* happen — Contact Card was tapped, the picker
        was pushed, but the share aborted into the recovery message path.

        Captured from ``logs/contact_share_dump_20260507_134355_*``.
        """
        assert (
            PageStateValidator.is_contact_picker_open(
                contact_picker_2026_05_07_build_elements
            )
            is True
        )

    def test_recognized_via_select_contacts_plural_title_text(
        self, contact_picker_with_only_plural_title_text
    ):
        """The real picker title on the 2026-05-07 build is the plural
        form ``Select Contact(s)`` with a literal ``(s)`` suffix. The
        validator's text fallback must accept this even when the title /
        list resourceIds are unknown — otherwise we keep losing share
        flows the moment WeCom renames a single resourceId.
        """
        assert (
            PageStateValidator.is_contact_picker_open(
                contact_picker_with_only_plural_title_text
            )
            is True
        )

    def test_not_recognized_on_attach_panel(self, attach_panel_elements):
        assert PageStateValidator.is_contact_picker_open(attach_panel_elements) is False

    def test_not_recognized_on_chat_screen(self, chat_screen_elements):
        assert PageStateValidator.is_contact_picker_open(chat_screen_elements) is False

    def test_chat_screen_excludes_2026_05_07_picker(
        self, contact_picker_2026_05_07_build_elements
    ):
        """The new picker fixture lacks an EditText, so chat_screen must
        never claim it. Pin this to keep the disjointness invariant
        from drifting alongside the picker fix.
        """
        assert (
            PageStateValidator.is_chat_screen(contact_picker_2026_05_07_build_elements)
            is False
        )


class TestConfirmSendDialogRecognition:
    def test_recognized_via_button_class(self, confirm_send_dialog_elements):
        assert PageStateValidator.is_confirm_send_dialog_open(confirm_send_dialog_elements) is True

    def test_recognized_via_dak_dah_resource_ids(self, confirm_send_dialog_imageview_elements):
        assert (
            PageStateValidator.is_confirm_send_dialog_open(confirm_send_dialog_imageview_elements)
            is True
        )

    def test_recognized_via_de2_de5_textview_2026_05_07_build(
        self, confirm_send_dialog_2026_05_07_textview_elements
    ):
        """2026-05-07 build: TextView + de2/de5 must satisfy the predicate.

        Regression for the dry-run E2E where the dialog was clearly visible
        on screen (Cancel was tappable in the next step) but
        is_confirm_send_dialog_open() returned False because:
          * no Button-class element existed (TextView only)
          * dak/dah resource ids were absent (renamed to de5/de2)
        """
        assert (
            PageStateValidator.is_confirm_send_dialog_open(
                confirm_send_dialog_2026_05_07_textview_elements
            )
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
