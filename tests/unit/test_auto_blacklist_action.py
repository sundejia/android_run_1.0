"""
Tests for AutoBlacklistAction.

TDD red phase: defines expected behavior for auto-blacklisting
when a customer sends an image or video.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from wecom_automation.services.media_actions.actions.auto_blacklist import (
    AutoBlacklistAction,
)
from wecom_automation.services.media_actions.interfaces import (
    ActionStatus,
    MediaEvent,
)
from wecom_automation.services.media_actions.media_review_decision import (
    MediaReviewDecision,
)


def _make_event(**overrides) -> MediaEvent:
    defaults = {
        "event_type": "customer_media_detected",
        "message_type": "image",
        "customer_id": 1,
        "customer_name": "张三",
        "channel": "@WeChat",
        "device_serial": "device001",
        "kefu_name": "客服A",
        "message_id": 100,
        "timestamp": datetime(2026, 4, 4, 12, 0, 0),
    }
    defaults.update(overrides)
    return MediaEvent(**defaults)


def _default_settings(enabled: bool = True, **overrides) -> dict:
    base = {
        "enabled": True,
        "auto_blacklist": {
            "enabled": enabled,
            "reason": "Customer sent media (auto)",
            "skip_if_already_blacklisted": True,
        },
    }
    base["auto_blacklist"].update(overrides)
    return base


class TestAutoBlacklistActionName:
    def test_action_name(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)
        assert action.action_name == "auto_blacklist"


class TestAutoBlacklistShouldExecute:
    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_image(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_execute_when_enabled_and_video(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="video")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_not_execute_when_disabled(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=False)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_global_disabled(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = {"enabled": False, "auto_blacklist": {"enabled": True}}

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_not_execute_when_already_blacklisted(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_already_blacklisted=True)

        assert await action.should_execute(event, settings) is False

    @pytest.mark.asyncio
    async def test_should_execute_even_if_already_blacklisted_when_skip_disabled(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings(enabled=True, skip_if_already_blacklisted=False)

        assert await action.should_execute(event, settings) is True

    @pytest.mark.asyncio
    async def test_should_not_execute_for_text_message(self):
        writer = MagicMock()
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="text")
        settings = _default_settings(enabled=True)

        assert await action.should_execute(event, settings) is False


class TestAutoBlacklistExecute:
    @pytest.mark.asyncio
    async def test_execute_adds_to_blacklist(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="image")
        settings = _default_settings()

        result = await action.execute(event, settings)

        writer.add_to_blacklist.assert_called_once_with(
            device_serial="device001",
            customer_name="张三",
            customer_channel="@WeChat",
            reason="Customer sent media (auto)",
            customer_db_id=1,
        )
        assert result.status == ActionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_with_video(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event(message_type="video")
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.SUCCESS
        writer.add_to_blacklist.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_failure_returns_error(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_execute_exception_returns_error(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(side_effect=RuntimeError("DB error"))
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event()
        settings = _default_settings()

        result = await action.execute(event, settings)

        assert result.status == ActionStatus.ERROR
        assert "DB error" in result.message

    @pytest.mark.asyncio
    async def test_execute_uses_custom_reason(self):
        writer = MagicMock()
        writer.add_to_blacklist = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer)

        event = _make_event()
        settings = _default_settings(reason="Sent inappropriate content")

        await action.execute(event, settings)

        call_kwargs = writer.add_to_blacklist.call_args
        assert call_kwargs[1]["reason"] == "Sent inappropriate content"


class TestAutoBlacklistReviewGate:
    """The gate keeps blacklist + group_invite aligned: only act on portrait media.

    These tests exercise the *legacy* gated mode, which now requires
    ``require_review_pass=True`` to opt back in. The default standalone
    behaviour (``require_review_pass=False``) is covered separately in
    ``TestAutoBlacklistRequireReviewPassDefault`` to ensure the rating
    pipeline is only consulted when explicitly opted into.
    """

    def _settings(self, *, gate_enabled: bool, skip_already: bool = True) -> dict:
        return {
            "enabled": True,
            "auto_blacklist": {
                "enabled": True,
                "reason": "auto",
                "skip_if_already_blacklisted": skip_already,
                "require_review_pass": True,
            },
            "review_gate": {"enabled": gate_enabled},
        }

    @pytest.mark.asyncio
    async def test_gate_off_portrait_true_executes(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=True,
            has_data=True,
            reason="ok",
            details={"is_portrait": True},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
            return_value=decision,
        ) as mock_eval:
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=False)) is True
            assert mock_eval.call_args.kwargs["gate_enabled"] is False

    @pytest.mark.asyncio
    async def test_gate_off_portrait_false_skips(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=False,
            has_data=True,
            reason="portrait_false",
            details={"is_portrait": False},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
            return_value=decision,
        ):
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=False)) is False

    @pytest.mark.asyncio
    async def test_gate_on_portrait_and_qualified_executes(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=True,
            has_data=True,
            reason="ok",
            details={"is_portrait": True, "decision": "合格"},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
            return_value=decision,
        ):
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=True)) is True

    @pytest.mark.asyncio
    async def test_gate_on_unqualified_skips(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=False,
            has_data=True,
            reason="decision_not_qualified",
            details={"is_portrait": True, "decision": "不合格"},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
            return_value=decision,
        ):
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=True)) is False

    @pytest.mark.asyncio
    async def test_missing_review_data_skips_with_warning(self, caplog):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        decision = MediaReviewDecision(
            gate_pass=False,
            has_data=False,
            reason="ai_review_status='pending'",
            details={"message_id": 100},
        )

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
            return_value=decision,
        ):
            import logging

            with caplog.at_level(
                logging.WARNING,
                logger="wecom_automation.services.media_actions.actions.auto_blacklist",
            ):
                assert await action.should_execute(_make_event(), self._settings(gate_enabled=True)) is False

        assert any("review data missing" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_already_blacklisted_short_circuits_before_gate(self):
        """If user is already blacklisted, we skip without calling evaluator."""
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=True)) is False
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_no_db_path_keeps_behaviour(self):
        """When db_path is omitted (legacy mode), gate is skipped entirely."""
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer)

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(), self._settings(gate_enabled=False)) is True
            mock_eval.assert_not_called()


class TestAutoBlacklistRequireReviewPassDefault:
    """Default mode (require_review_pass=False) — the user-facing semantics:
    customer-sent media → blacklist immediately, no rating-server dependency.

    This locks in the 2026-05-07 fix where the action would silently skip
    every customer because review data was missing while the deployment
    had never opted into the rating pipeline. See
    docs/04-bugs-and-fixes/resolved/2026-05-07-auto-blacklist-review-data-missing.md
    """

    @pytest.mark.asyncio
    async def test_default_blacklists_image_without_calling_evaluator(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        settings = _default_settings(enabled=True)
        # No require_review_pass key → defaults to False.
        assert "require_review_pass" not in settings["auto_blacklist"]

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(message_type="image"), settings) is True
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_blacklists_video_without_calling_evaluator(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        settings = _default_settings(enabled=True)

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(message_type="video"), settings) is True
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_blacklists_even_when_review_data_missing(self):
        """Regression for 2026-05-07: WARNING 'Skipping auto-blacklist: review
        data missing' silenced auto-blacklist for every deployment without
        review_gate. Defaulting require_review_pass=False makes that path
        unreachable unless the operator explicitly opts in.
        """
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        # Settings shape from a real production install before the fix:
        # gate_enabled=False, no require_review_pass override, no review row.
        settings = {
            "enabled": True,
            "auto_blacklist": {
                "enabled": True,
                "reason": "Customer sent media (auto)",
                "skip_if_already_blacklisted": True,
            },
            "review_gate": {"enabled": False},
        }

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(message_type="image"), settings) is True
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_explicit_false_skips_evaluator(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        settings = _default_settings(enabled=True, require_review_pass=False)

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(), settings) is True
            mock_eval.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_blocks_default_path_too(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=False)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        settings = _default_settings(enabled=False)

        assert await action.should_execute(_make_event(), settings) is False

    @pytest.mark.asyncio
    async def test_already_blacklisted_short_circuits_default_path(self):
        writer = MagicMock()
        writer.is_blacklisted_by_name = MagicMock(return_value=True)
        action = AutoBlacklistAction(blacklist_writer=writer, db_path="/db.sqlite")

        settings = _default_settings(enabled=True)

        with patch(
            "wecom_automation.services.media_actions.actions.auto_blacklist.evaluate_gate_pass",
        ) as mock_eval:
            assert await action.should_execute(_make_event(), settings) is False
            mock_eval.assert_not_called()
